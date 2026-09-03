import os
import xml.etree.ElementTree as ET
import re
from datetime import datetime
# Use urllib3 to bypass the runner's local socket restrictions
import urllib3
from twilio.rest import Client

# Configure a pool manager that forces connection retries and ignores SSL errors
http = urllib3.PoolManager(cert_reqs='CERT_NONE', timeout=15.0, retries=3)

def get_nws_pressure(station_id):
    url = f"https://weather.gov{station_id}.xml"
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = http.request('GET', url, headers=headers)
        if response.status == 200:
            root = ET.fromstring(response.data)
            return float(root.find('pressure_mb').text)
        return None
    except Exception as e:
        print(f"NWS Connection Error ({station_id}): {e}")
        return None

def get_buoy_data(station_id):
    url = f"https://noaa.gov{station_id}.txt"
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = http.request('GET', url, headers=headers)
        if response.status == 200:
            lines = response.data.decode('utf-8').split('\n')
            data_lines = [l for l in lines if l.strip() and not l.startswith('#')]
            if not data_lines: return None
            
            latest_data = data_lines[0].split()
            wdir = int(latest_data[5])
            wspd_kts = round(float(latest_data[6]) * 1.94384, 1)
            gst_kts = round(float(latest_data[7]) * 1.94384, 1)
            return {"wdir": wdir, "wspd": wspd_kts, "gst": gst_kts}
        return None
    except Exception as e: 
        print(f"Buoy Parse Error: {e}")
        return None

def get_marine_layer_depth():
    current_date = datetime.utcnow().strftime('%Y-%m-%d')
    url = f"https://uwyo.edu{current_date}%2012:00:00&id=72493&type=TEXT:LIST"
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = http.request('GET', url, headers=headers)
        if response.status == 200:
            html = response.data.decode('utf-8')
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
        print(f"Sounding Connection Error: {e}")
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
    print(f"SFO Pressure Data Fetched: {sfo is not None}")
    print(f"SAC Pressure Data Fetched: {sac is not None}")
    print(f"Buoy Data Object Fetched: {buoy is not None}")
