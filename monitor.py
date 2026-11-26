import os
import requests
from datetime import datetime

# --- CONFIGURATION (Zero-cost, unlimited Telegram alerts) ---
TELEGRAM_BOT_TOKEN = '8665523487:AAHpUrzXi_t6RRFOQmA4MObRlcWhwSKQEfc'
TELEGRAM_CHAT_ID = '8895086306'
SYNOPTIC_API_TOKEN = '078a674e8fd24cc29e33d74f89ab66ba'  # Required for Mountain/Eddy sensors

def send_telegram_alert(message_text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message_text,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print("🎉 Alert notification sent successfully via Telegram!")
            return True
        else:
            print(f"❌ Telegram API Error: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        print(f"❌ Failed to send Telegram message: {e}")
        return False

def get_nws_obs_history(station_id, limit=3):
    """Gets hourly observation history for trend calculations from NWS."""
    url = f"https://api.weather.gov/stations/{station_id}/observations"
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; WaddellMonitorPro/2.0)'}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        features = response.json().get('properties', {}).get('periods', []) or response.json().get('features', [])
        
        obs_list = []
        for feat in features[:limit]:
            props = feat.get('properties', {})
            pres_pa = props.get('barometricPressure', {}).get('value')
            temp_c = props.get('temperature', {}).get('value')
            timestamp_str = props.get('timestamp')
            
            pres_mb = round(pres_pa / 100, 2) if pres_pa else None
            temp_f = round((temp_c * 9/5) + 32, 1) if temp_c is not None else None
            obs_list.append({"time": timestamp_str, "pressure": pres_mb, "temp_f": temp_f})
        return obs_list
    except Exception as e:
        print(f"Failed fetching historical NWS data for {station_id}: {e}")
        return []

def get_synoptic_latest(station_id):
    """Fetches the absolute latest observations from Synoptic Mesonet API."""
    if not SYNOPTIC_API_TOKEN:
        return None
    url = f"https://api.synopticdata.com/v2/stations/latest?stid={station_id}&token={SYNOPTIC_API_TOKEN}"
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            data = response.json()
            if data.get('STATION'):
                obs = data['STATION'][0].get('OBSERVATIONS', {})
                latest = {}
                for k, v in obs.items():
                    if v and len(v) > 0:
                        latest[k] = v[0].get('value')
                return latest
        return None
    except Exception as e:
        print(f"Synoptic API error on {station_id}: {e}")
        return None

def get_buoy_history(station_id, hours=3):
    """Fetches real-time buoy data and returns parsed rows."""
    url = f"https://www.ndbc.noaa.gov/data/realtime2/{station_id}.txt"
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; WaddellMonitorPro/2.0)'}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        lines = response.text.split('\n')
        data_lines = [l for l in lines if l.strip() and not l.startswith('#')]
        
        history = []
        for line in data_lines[:hours * 6]:  # buoy updates every 10 mins
            tokens = line.split()
            if len(tokens) > 7:
                wdir = int(tokens[5]) if tokens[5] != 'MM' else None
                wspd = round(float(tokens[6]) * 1.94384, 1) if tokens[6] != 'MM' else None
                gst = round(float(tokens[7]) * 1.94384, 1) if tokens[7] != 'MM' else None
                history.append({"wdir": wdir, "wspd": wspd, "gst": gst})
        return [h for h in history if h.get("wdir") is not None]
    except Exception as e:
        print(f"Buoy history error: {e}")
        return []

def run_pipeline():
    print("ᾟ1 Initiating Waddell Creek Advanced Predictive Analysis...")
    
    # Determine Season
    current_month = datetime.now().month
    if 3 <= current_month <= 5:
        season = "SPRING (Frontal / Synoptic NW Flow Mode)"
        mode = "spring"
    elif 6 <= current_month <= 8:
        season = "SUMMER (Pure Thermal Mode)"
        mode = "summer"
    elif 9 <= current_month <= 10:
        season = "FALL (Clearing / Offshore Mode)"
        mode = "fall"
    else:
        season = "WINTER (Active Winter Wind Monitoring Mode)"
        mode = "winter"
        
    print(f"Ὄ5 Season Mode: {season}")
    
    # Fetch NWS and Buoy Telemetry
    sfo_obs = get_nws_obs_history("KSFO", limit=3)
    sac_obs = get_nws_obs_history("KSAC", limit=3)
    haf_obs = get_nws_obs_history("KHAF", limit=3)
    
    sfo_cur = sfo_obs[0]['pressure'] if sfo_obs else None
    sac_cur = sac_obs[0]['pressure'] if sac_obs else None
    inland_temp_sac = sac_obs[0]['temp_f'] if sac_obs else None
    coast_temp_haf = haf_obs[0]['temp_f'] if haf_obs else None
    
    buoy_data = get_buoy_history("46012", hours=3)
    buoy_cur = buoy_data[0] if buoy_data else None
    
    # 1. Santa Cruz Eddy detection (SCXC1 / KWVI)
    eddy_warning = False
    eddy_data = get_synoptic_latest("SCXC1") or get_synoptic_latest("KWVI")
    if eddy_data:
        eddy_wdir = eddy_data.get('wind_direction')
        eddy_wspd = eddy_data.get('wind_speed')
        eddy_wspd_mph = round(eddy_wspd * 2.23694, 1) if eddy_wspd else 0
        if eddy_wdir and (130 <= eddy_wdir <= 220) and eddy_wspd_mph >= 8.0:
            eddy_warning = True
            print(f"⚠️ Santa Cruz Eddy detected: {eddy_wspd_mph} mph from {eddy_wdir}°!")
            
    # 2. Inversion Cap Proxy (SLIC1)
    skyline_data = get_synoptic_latest("SLIC1")
    inversion_status = "Unknown"
    inversion_boost = False
    if skyline_data and coast_temp_haf:
        sky_temp_c = skyline_data.get('air_temp')
        if sky_temp_c is not None:
            sky_temp_f = round((sky_temp_c * 9/5) + 32, 1)
            temp_difference = sky_temp_f - coast_temp_haf
            if temp_difference >= 10.0:
                inversion_status = f"Strong Inversion Cap Active (+{round(temp_difference,1)}°F Mountain Heat-Lock)"
                inversion_boost = True
            elif temp_difference < 0:
                inversion_status = "Mixed Out (Mountain is cooler than Beach)"
            else:
                inversion_status = f"Weak/Normal Inversion (+{round(temp_difference,1)}°F Gradient)"
                
    # 3. Trend Tracking & expanded 11:00 AM - 2:30 PM Pre-Alert window
    rapid_build = False
    sudden_drop = False
    if len(sfo_obs) >= 2 and len(sac_obs) >= 2:
        grad_now = sfo_obs[0]['pressure'] - sac_obs[0]['pressure']
        grad_1hr = sfo_obs[1]['pressure'] - sac_obs[1]['pressure']
        grad_change = round(grad_now - grad_1hr, 2)
        
        if len(buoy_data) >= 6:
            wind_now = buoy_data[0]['wspd']
            wind_1hr = buoy_data[6]['wspd']
            wind_change = round(wind_now - wind_1hr, 1)
            
            local_hour = datetime.now().hour - 8
            if (11 <= local_hour <= 14) or (local_hour == 14 and datetime.now().minute <= 30):
                if grad_change >= 0.6 and wind_change >= 4.0 and buoy_data[0]['wdir'] >= 270:
                    rapid_build = True
            if local_hour >= 15 and wind_change <= -5.0:
                sudden_drop = True
                
    # 4. Inland Thermal Temperature Spread (Summer Only)
    inland_heat_ok = True
    if mode == "summer":
        if inland_temp_sac and coast_temp_haf:
            sac_warmth_diff = inland_temp_sac - coast_temp_haf
            if inland_temp_sac < 78.0 or sac_warmth_diff < 18.0:
                inland_heat_ok = False
                print(f"⚠️ Pure Thermal block: Valley is only {inland_temp_sac}°F (Spread: {round(sac_warmth_diff,1)}°F)")
                
    # Evaluate Triggers
    if sfo_cur is not None and sac_cur is not None and buoy_cur:
        sfo_to_sac = round(sfo_cur - sac_cur, 2)
        wdir = buoy_cur['wdir']
        wspd = buoy_cur['wspd']
        gust = buoy_cur['gst']
        
        min_gradient = 2.8 if mode in ["spring", "summer"] else 3.0
        gradient_trigger = sfo_to_sac >= min_gradient
        
        # Lower wind speed trigger threshold to 14.5 knots
        wind_speed_ok = wspd >= 14.5
        
        if mode == "winter":
            # Winter direction ceiling capped to 345° with 10 mph (8.7 kts) gust spread cap
            wind_dir_ok = (280 <= wdir <= 345)
            gust_spread = gust - wspd if (gust is not None and wspd is not None) else 0
            gust_ok = gust_spread <= 8.7
        else:
            wind_dir_ok = (280 <= wdir <= 330)
            gust_ok = True
            
        wind_trigger = wind_speed_ok and wind_dir_ok and gust_ok
        is_green = gradient_trigger and wind_trigger and inland_heat_ok and not sudden_drop
        
        if is_green and eddy_warning and wspd < 20.0:
            is_green = False
            status_label = "🟡 YELLOW (Alert Downgraded due to Monterey Bay Eddy Southerly Reversal)"
        elif is_green:
            status_label = f"🟢 GREEN (Go Time! Confidence: {'HIGH' if inversion_boost else 'STANDARD'})"
        elif rapid_build:
            status_label = "🟠 ORANGE PRE-ALERT (Rapid midday gradient build detected! Get in the car!)"
        else:
            status_label = "🔴 RED / HOLDING (Conditions not fully aligned)"
            
        print("\n--- METEOROLOGICAL DIAGNOSTICS ---")
        print(f"Gradient (SFO-SAC): +{sfo_to_sac} mb (Target: >={min_gradient} mb)")
        print(f"Buoy 46012: {wspd} kts @ {wdir}° (Target: >=14.5 kts)")
        if mode == "winter" and gust:
            print(f"Winter Gust Spread: {round(gust - wspd, 1)} kts (Max Target: <=8.7 kts)")
        print(f"Inversion Cap Indicator: {inversion_status}")
        print(f"Active Eddy Warning: {eddy_warning}")
        print(f"Inland Thermal Heat OK: {inland_heat_ok}")
        print(f"Final Assessment: {status_label}")
        
        if is_green:
            msg = f"🚨 *WADDELL GO TIME!*\n*Status*: {status_label}\n*Wind*: {wspd} kts @ {wdir}°\n*SFO-SAC*: +{sfo_to_sac} mb\n*Inversion*: {inversion_status}"
            send_telegram_alert(msg)
        elif rapid_build:
            msg = f"🏎️ *RAPID BUILD DETECTED!*\n*Status*: {status_label}\n*Gradient Change*: +{grad_change} mb in 1hr\n*Wind Change*: +{wind_change} kts in 1hr\nGet ready to head out!"
            send_telegram_alert(msg)
    else:
        print("❌ Diagnostics error: Unable to retrieve essential datasets for validation.")

if __name__ == '__main__':
    run_pipeline()
