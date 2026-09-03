import os
import xml.etree.ElementTree as ET
import urllib.request
import re
import ssl
import socket
from datetime import datetime
from twilio.rest import Client

# Force standard IPv4 mapping to accommodate NOAA server routing
orig_getaddrinfo = socket.getaddrinfo
def forced_ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    return orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = forced_ipv4_getaddrinfo

socket.setdefaulttimeout(15)
ssl_context = ssl._create_unverified_context()

def get_nws_pressure(station_id):
    url = f"https://weather.gov{station_id}.xml"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, context=ssl_context) as response:
            root = ET.fromstring(response.read())
            return float(root.find('pressure_mb').text)
    except Exception as e:
        print(f"NWS Connection Drop ({station_id}): {e}")
        return None

def get_buoy_data(station_id):
    url = f"https://noaa.gov{station_id}.txt"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, context=ssl_context) as response:
            lines = response.read().decode('utf-8').split('\n')
            data_lines = [l for l in lines if l.strip() and not l.startswith('#')]
            if not data_lines: return None
            
            latest_data = data_lines.split()
            wdir = int(latest_data)
            wspd_kts = round(float(latest_data) * 1.94384, 1)
            gst_kts = round(float(latest_data) * 1.94384, 1)
            return {"wdir": wdir, "wspd": wspd_kts, "gst": gst_kts}
    except Exception as e: 
        print(f"Buoy Parse Error: {e}")
        return None

def get_marine_layer_depth():
    # Set to current date formatting requirements
    current_date = datetime.utcnow().strftime('%Y-%m-%d')
    # MIGRATION FIX: Swapped to the live active endpoint
    url = f"https://weather.uwyo.edu/wsgi/sounding?datetime={current_date}%2012:00:00&id=72493&type=TEXT:LIST"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, context=ssl_context) as response:
            html = response.read().decode('utf-8')
            raw_data = re.findall(r'<PRE>(.*?)</PRE>', html, re.DOTALL)
            if not raw_data: return None
            lines = raw_data.strip().split('\n')[4:]
            last_temp = None
            for line in lines:
                parts = line.split()
                if len(parts) >= 3:
                    hght_m = float(parts)
                    temp_c = float(parts)
                    if last_temp is not None and temp_c > last_temp:
                        return round(hght_m * 3.28084)
                    last_temp = temp_c
            return None
    except Exception as e:
        print(f"Sounding Connection Drop: {e}")
        return None

account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
from_num = os.environ.get('TWILIO_FROM_NUMBER')
to_num = os.environ.get('TWILIO_TO_NUMBER')

sfo = get_nws_pressure("KSFO")
sac = get_nws_pressure("KSAC")
buoy = get_buoy_data("46012")
fog_depth = get_marine_layer_depth()

if sfo and sac and buoy:
    sfo_to_sac = round(sfo - sac, 2)
    wdir, wspd, gst = buoy["wdir"], buoy["wspd"], buoy["gst"]
    
    gradient_trigger = sfo_to_sac >= 3.0
    wind_trigger = wspd >= 17.0 and (280 <= wdir <= 330)
    fog_trigger = fog_depth is None or fog_depth < 2000
    
    if gradient_trigger and wind_trigger and fog_trigger:
        depth_str = f"{fog_depth}ft" if fog_depth else "Unknown"
        msg = f"🚨 WADDELL GO TIME!\nGradient: +{sfo_to_sac}mb\nBuoy 46012: {wspd}kts @ {wdir}° (Gusts: {gst}kts)\nFog Layer: {depth_str}"
        client = Client(account_sid, auth_token)
        client.messages.create(body=msg, from_=from_num, to=to_num)
        print("Conditions met. Twilio SMS alert sent.")
    else:
        print(f"Holding. Grad: +{sfo_to_sac}mb, Buoy: {wspd}kts at {wdir} degrees, Marine Layer: {fog_depth}ft.")
else:
    print("Data compilation failed. Checking metrics manually:")
    print(f"SFO: {sfo}, SAC: {sac}, Buoy Data Object: {buoy}")
