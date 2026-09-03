import os
import xml.etree.ElementTree as ET
import re
import socket
import ssl
from datetime import datetime
import urllib.request
from twilio.rest import Client

# Attempt to configure aggressive timeout thresholds to break runner freezes
socket.setdefaulttimeout(10)

def fetch_raw_data(url):
    """Fallback connection wrapper designed to force legacy SSL handshakes."""
    try:
        ctx = ssl._create_unverified_context()
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
        )
        with urllib.request.urlopen(req, context=ctx) as response:
            return response.read()
    except Exception as e:
        print(f"Gateway connection drop for URL [{url}]: {e}")
        return None

def get_nws_pressure(station_id):
    url = f"https://weather.gov{station_id}.xml"
    raw = fetch_raw_data(url)
    if not raw: return None
    try:
        root = ET.fromstring(raw)
        return float(root.find('pressure_mb').text)
    except Exception as e:
        print(f"XML Parsing Error for NWS {station_id}: {e}")
        return None

def get_buoy_data(station_id):
    url = f"https://noaa.gov{station_id}.txt"
    raw = fetch_raw_data(url)
    if not raw: return None
    try:
        lines = raw.decode('utf-8').split('\n')
        data_lines = [l for l in lines if l.strip() and not l.startswith('#')]
        if not data_lines: return None
        
        latest_data = data_lines[0].split()
        wdir = int(latest_data[5])
        wspd_kts = round(float(latest_data[6]) * 1.94384, 1)
        gst_kts = round(float(latest_data[7]) * 1.94384, 1)
        return {"wdir": wdir, "wspd": wspd_kts, "gst": gst_kts}
    except Exception as e: 
        print(f"Table Array Mapping Error for Buoy {station_id}: {e}")
        return None

def get_marine_layer_depth():
    current_date = datetime.utcnow().strftime('%Y-%m-%d')
    url = f"https://uwyo.edu{current_date}%2012:00:00&id=72493&type=TEXT:LIST"
    raw = fetch_raw_data(url)
    if not raw: return None
    try:
        html = raw.decode('utf-8')
        raw_data = re.findall(r'<PRE>(.*?)</PRE>', html, re.DOTALL)
        if not raw_data: return None
        lines = raw_data[0].strip().split('\n')[4:]
        last_temp = None
        for line in lines:
            parts = line.split()
            if len(parts) >= 3:
                hght_m = float(parts[1])
                temp_c = float(parts[2])
                if last_temp is not None and temp_c > last_temp:
                    return round(hght_m * 3.28084)
                last_temp = temp_c
        return None
    except Exception as e:
        print(f"Matrix Index Error for Sounding Data: {e}")
        return None

# Load runtime environment credentials
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
    print("--- CORE PIPELINE METRIC FAILURE BLOCKS ANALYSIS ---")
    print(f"SFO Station Online: {sfo is not None}")
    print(f"SAC Station Online: {sac is not None}")
    print(f"Buoy 46012 Stream Online: {buoy is not None}")
