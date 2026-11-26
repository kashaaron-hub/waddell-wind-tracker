import sys
import subprocess
import os

# --- AUTOMATIC DEPENDENCY INSTALLER ---
# This ensures that no matter where GitHub runs this, it automatically resolves imports.
try:
    import requests
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "--quiet"])
    import requests

from datetime import datetime

# --- CONFIGURATION ---
TELEGRAM_BOT_TOKEN = '8665523487:AAHpUrzXi_t6RRFOQmA4MObRlcWhwSKQEfc'
TELEGRAM_CHAT_ID = '8895086306'
# We hardcode your Synoptic token here directly to ensure GitHub actions can always access it!
SYNOPTIC_API_TOKEN = '078a674e8fd24cc29e33d74f89ab66ba'  

def send_telegram_alert(message_text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message_text,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Telegram alert error: {e}")
        return False

def get_nws_obs_history(station_id, limit=3):
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
    if not SYNOPTIC_API_TOKEN:
        print(f"⚠️ Synoptic API token missing. Skipping station check for {station_id}.")
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
    url = f"https://www.ndbc.noaa.gov/data/realtime2/{station_id}.txt"
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; WaddellMonitorPro/2.0)'}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        lines = response.text.split('\n')
        data_lines = [l for l in lines if l.strip() and not l.startswith('#')]
        history = []
        for line in data_lines[:hours * 6]:
            tokens = line.split()
            if len(tokens) > 7:
                wdir = int(tokens[5]) if tokens[5] != 'MM' else None
                wspd = round(float(tokens[6]) * 1.94384, 1) if tokens[6] != 'MM' else None
                gst = round(float(tokens[7]) * 1.94384, 1) if tokens[7] != 'MM' else None
                history.append({"wdir": wdir, "wspd": wspd, "gst": gst})
        return history
    except Exception as e:
        print(f"Buoy history error: {e}")
        return []

def evaluate_waddell_rules():
    print("🧭 Initiating Waddell Creek Advanced Predictive Analysis...")
    current_month = datetime.now().month
    if 3 <= current_month <= 5:
        season, mode = "SPRING (Frontal / Synoptic Mode)", "spring"
    elif 6 <= current_month <= 8:
        season, mode = "SUMMER (Pure Thermal Mode)", "summer"
    elif 9 <= current_month <= 10:
        season, mode = "FALL (Clearing / Offshore Mode)", "fall"
    else:
        season, mode = "WINTER (Storm Mode - Manual Review Only)", "winter"
    print(f"📅 Season Mode: {season}")

    sfo_obs = get_nws_obs_history("KSFO", limit=3)
    sac_obs = get_nws_obs_history("KSAC", limit=3)
    lvk_obs = get_nws_obs_history("KLVK", limit=3)
    haf_obs = get_nws_obs_history("KHAF", limit=3)

    sfo_cur = sfo_obs[0]['pressure'] if sfo_obs else None
    sac_cur = sac_obs[0]['pressure'] if sac_obs else None
    inland_temp_sac = sac_obs[0]['temp_f'] if sac_obs else None
    coast_temp_haf = haf_obs[0]['temp_f'] if haf_obs else None

    buoy_data = get_buoy_history("46012", hours=3)
    buoy_cur = buoy_data[0] if buoy_data else None

    eddy_warning = False
    eddy_data = get_synoptic_latest("SCXC1") or get_synoptic_latest("KWVI")
    if eddy_data:
        eddy_wdir = eddy_data.get('wind_direction')
        eddy_wspd = eddy_data.get('wind_speed')
        eddy_wspd_mph = round(eddy_wspd * 2.23694, 1) if eddy_wspd else 0
        if eddy_wdir and (130 <= eddy_wdir <= 220) and eddy_wspd_mph >= 8.0:
            eddy_warning = True

    inversion_status, inversion_boost = "Unknown", False
    skyline_data = get_synoptic_latest("SLIC1")
    if skyline_data and coast_temp_haf:
        sky_temp_c = skyline_data.get('air_temp')
        if sky_temp_c is not None:
            sky_temp_f = round((sky_temp_c * 9/5) + 32, 1)
            temp_difference = sky_temp_f - coast_temp_haf
            if temp_difference >= 10.0:
                inversion_status, inversion_boost = f"Strong Inversion (+{round(temp_difference,1)}°F)", True
            else:
                inversion_status = f"Mixed/Weak Inversion (+{round(temp_difference,1)}°F)"

    rapid_build, sudden_drop = False, False
    if len(sfo_obs) >= 2 and len(sac_obs) >= 2:
        grad_now = sfo_obs[0]['pressure'] - sac_obs[0]['pressure']
        grad_1hr = sfo_obs[1]['pressure'] - sac_obs[1]['pressure']
        grad_change = round(grad_now - grad_1hr, 2)
        if len(buoy_data) >= 6:
            wind_now = buoy_data[0]['wspd']
            wind_1hr = buoy_data[6]['wspd']
            wind_change = round(wind_now - wind_1hr, 1)
            local_hour = datetime.now().hour - 8
            if 11 <= local_hour <= 13 and grad_change >= 0.6 and wind_change >= 4.0:
                rapid_build = True
            if local_hour >= 15 and wind_change <= -5.0:
                sudden_drop = True

    inland_heat_ok = True
    if mode == "summer" and inland_temp_sac and coast_temp_haf:
        if inland_temp_sac < 78.0 or (inland_temp_sac - coast_temp_haf) < 18.0:
            inland_heat_ok = False

    if sfo_cur is not None and sac_cur is not None and buoy_cur:
        sfo_to_sac = round(sfo_cur - sac_cur, 2)
        wdir, wspd = buoy_cur['wdir'], buoy_cur['wspd']
        min_gradient = 2.8 if mode == "summer" else 3.0

        gradient_trigger = sfo_to_sac >= min_gradient
        wind_trigger = wspd >= 17.0 and (280 <= wdir <= 330)
        is_green = gradient_trigger and wind_trigger and inland_heat_ok and not sudden_drop

        if is_green and eddy_warning and wspd < 20.0:
            is_green = False
            status_label = "🟡 YELLOW (Alert Downgraded due to Monterey Bay Eddy Southerly Reversal)"
        elif is_green:
            status_label = f"🟢 GREEN (Go Time! Confidence: {'HIGH' if inversion_boost else 'STANDARD'})"
        elif rapid_build:
            status_label = "... ORANGE PRE-ALERT (Rapid midday gradient build detected!)"
        else:
            status_label = "🔴 RED / HOLDING (Conditions not fully aligned)"

        print(f"Final Assessment: {status_label}")

        if is_green:
            msg = f"🚨 *WADDELL GO TIME!*\n*Status*: {status_label}\n*Wind*: {wspd} kts @ {wdir}°\n*SFO-SAC*: +{sfo_to_sac} mb\n*Inversion*: {inversion_status}"
            send_telegram_alert(msg)
    else:
        print("❌ Diagnostics error: Unable to retrieve essential datasets.")

if __name__ == '__main__':
    evaluate_waddell_rules()
