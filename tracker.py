pythonimport os
import xml.etree.ElementTree as ET
import urllib.request
import re
from datetime import datetime
from twilio.rest import Client

def get_nws_pressure(station_id):
    url = f"https://weather.gov{station_id}.xml"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        root = ET.fromstring(urllib.request.urlopen(req, timeout=10).read())
        return float(root.find('pressure_mb').text)
    except Exception: return None

def get_buoy_data(station_id):
    url = f"https://noaa.gov{station_id}.txt"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        lines = urllib.request.urlopen(req, timeout=10).read().decode('utf-8').split('\n')
        latest_data = lines[2].split()
        wdir = int(latest_data[5])
        wspd_kts = round(float(latest_data[6]) * 1.94384, 1)
        gst_kts = round(float(latest_data[7]) * 1.94384, 1)
        return {"wdir": wdir, "wspd": wspd_kts, "gst": gst_kts}
    except Exception: return None

def get_marine_layer_depth():
    today = datetime.utcnow().strftime('%Y%m%d')
    url = f"https://uwyo.edu{today}12&TO={today}12&STNM=72493"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        html = urllib.request.urlopen(req, timeout=15).read().decode('utf-8')
        raw_data = re.findall(r'<PRE>(.*?)</PRE>', html, re.DOTALL)[0]
        lines = raw_data.strip().split('\n')[4:]
        last_temp = None
        for line in lines:
            parts = line.split()
            if len(parts) >= 3:
                hght_m, temp_c = float(parts[1]), float(parts[2])
                if last_temp is not None and temp_c > last_temp:
                    return round(hght_m * 3.28084)
                last_temp = temp_c
        return None
    except Exception: return None

# Fetch environment variables from GitHub Secrets
account_sid = os.environ.get('TWILIO_ACCOUNT_SID')
auth_token = os.environ.get('TWILIO_AUTH_TOKEN')
from_num = os.environ.get('TWILIO_FROM_NUMBER')
to_num = os.environ.get('TWILIO_TO_NUMBER')

# Run Analysis
sfo, sac = get_nws_pressure("KSFO"), get_nws_pressure("KSAC")
buoy = get_buoy_data("46012")
fog_depth = get_marine_layer_depth()

if sfo and sac and buoy:
    sfo_to_sac = round(sfo - sac, 2)
    wdir, wspd, gst = buoy["wdir"], buoy["wspd"], buoy["gst"]
    
    # Conditions: Gradient >= 3.0mb, Buoy Wind >= 17kts, NW Angle (280-330°), Fog < 2000ft
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
        print(f"Holding. Grad: +{sfo_to_sac}mb, Buoy: {wspd}kts at {wdir}°
