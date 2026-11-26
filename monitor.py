import os
import json
import requests
from datetime import datetime

# --- CONFIGURATION (Zero-cost, unlimited Telegram alerts) ---
TELEGRAM_BOT_TOKEN = '8665523487:AAHpUrzXi_t6RRFOQmA4MObRlcWhwSKQEfc'
TELEGRAM_CHAT_ID = '8895086306'
SYNOPTIC_API_TOKEN = '078a674e8fd24cc29e33d74f89ab66ba'

STATE_FILE = "waddell_state.json"

def load_state():
    """Loads the alert state to ensure only one alert of each type fires per day."""
    today_str = datetime.now().strftime('%Y-%m-%d')
    default_state = {
        "date": today_str,
        "stage1_fired": False,
        "stage2_fired": False,
        "stage2b_fired": False
    }
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                state = json.load(f)
            if state.get("date") == today_str:
                return state
        except Exception as e:
            print(f"Error reading state: {e}")
    return default_state

def save_state(state):
    """Saves the current alert state to a local JSON file."""
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"Error writing state: {e}")

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
        print(f"❌ Telegram API Error: {response.status_code} - {response.text}")
        return False
    except Exception as e:
        print(f"❌ Failed to send Telegram message: {e}")
        return False

def get_nws_obs_history(station_id, limit=3):
    url = f"https://api.weather.gov/stations/{station_id}/observations"
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; WaddellMonitorPro/3.0)'}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        features = response.json().get('properties', {}).get('periods', []) or response.json().get('features', [])

        obs_list = []
        for feat in features[:limit]:
            props = feat.get('properties', {})
            pres_pa = props.get('barometricPressure', {}).get('value')
            temp_c = props.get('temperature', {}).get('value')
            dew_c = props.get('dewpoint', {}).get('value')
            timestamp_str = props.get('timestamp')

            pres_mb = round(pres_pa / 100, 2) if pres_pa else None
            temp_f = round((temp_c * 9/5) + 32, 1) if temp_c is not None else None
            dew_f = round((dew_c * 9/5) + 32, 1) if dew_c is not None else None
            obs_list.append({"time": timestamp_str, "pressure": pres_mb, "temp_f": temp_f, "dewpoint_f": dew_f})
        return obs_list
    except Exception as e:
        print(f"Failed fetching historical NWS data for {station_id}: {e}")
        return []

def get_synoptic_latest(station_id):
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
                latest['elevation'] = data['STATION'][0].get('ELEV_DEM') or data['STATION'][0].get('ELEVATION')
                return latest
        return None
    except Exception as e:
        print(f"Synoptic API error on {station_id}: {e}")
        return None

def get_high_elevation_fallback():
    """Queries Synoptic Data within a 15-mile radius of Waddell for a backup high elevation sensor above 1,800 ft."""
    if not SYNOPTIC_API_TOKEN:
        return None
    url = f"https://api.synopticdata.com/v2/stations/latest?radius=37.0913,-122.2797,15&token={SYNOPTIC_API_TOKEN}"
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            data = response.json()
            stations = data.get('STATION', [])
            high_stations = []
            for st in stations:
                elev_m = st.get('ELEV_DEM') or st.get('ELEVATION') or 0
                elev_ft = elev_m * 3.28084
                if elev_ft > 1800:
                    obs = st.get('OBSERVATIONS', {})
                    air_temp_c = obs.get('air_temp_value_1') or obs.get('air_temp')
                    if air_temp_c and len(air_temp_c) > 0:
                        high_stations.append({
                            "stid": st.get('STID'),
                            "elevation_ft": elev_ft,
                            "temp_c": air_temp_c[0].get('value')
                        })
            if high_stations:
                high_stations.sort(key=lambda x: x['elevation_ft'], reverse=True)
                return high_stations[0]
        return None
    except Exception as e:
        print(f"Radius search fail-safe error: {e}")
        return None

def get_buoy_history(station_id, hours=3):
    url = f"https://www.ndbc.noaa.gov/data/realtime2/{station_id}.txt"
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (compatible; WaddellMonitorPro/3.0)'}
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
        return [h for h in history if h.get("wdir") is not None]
    except Exception as e:
        print(f"Buoy history error: {e}")
        return []

def run_stateful_pipeline():
    print("░▒▓ Stateful Waddell Creek Multi-Stage Predictive Analysis ▓▒░")

    state = load_state()
    now = datetime.now()
    local_hour = now.hour - 8  # PST Approximation
    if local_hour < 0:
        local_hour += 24
    local_minute = now.minute

    month = now.month
    day = now.day
    is_spring = (month == 2 and day >= 22) or (3 <= month <= 5)
    is_summer = (6 <= month <= 8)

    if is_spring:
        season = "SPRING (Extended: Feb 22 - May 31)"
        mode = "spring"
    elif is_summer:
        season = "SUMMER (June 1 - August 31)"
        mode = "summer"
    elif 9 <= month <= 10:
        season = "FALL (September 1 - October 31)"
        mode = "fall"
    else:
        season = "WINTER (November 1 - February 21)"
        mode = "winter"

    print(f"📅 Season Mode: {season} | Current Local Time: {local_hour:02d}:{local_minute:02d} PST")

    # 1. FETCH TELEMETRY
    sfo_obs = get_nws_obs_history("KSFO", limit=3)
    sac_obs = get_nws_obs_history("KSAC", limit=3)
    haf_obs = get_nws_obs_history("KHAF", limit=3)

    pg_latest = get_synoptic_latest("458PG")

    sfo_cur = sfo_obs[0]['pressure'] if sfo_obs else None
    sac_cur = sac_obs[0]['pressure'] if sac_obs else None
    inland_temp_sac = sac_obs[0]['temp_f'] if sac_obs else None

    if pg_latest and pg_latest.get('air_temp') is not None:
        coast_temp_haf = round((pg_latest['air_temp'] * 9/5) + 32, 1)
        if pg_latest.get('dew_point_temperature') is not None:
            coast_dewpoint_haf = round((pg_latest['dew_point_temperature'] * 9/5) + 32, 1)
        else:
            coast_dewpoint_haf = haf_obs[0]['dewpoint_f'] if haf_obs else None
    else:
        coast_temp_haf = haf_obs[0]['temp_f'] if haf_obs else None
        coast_dewpoint_haf = haf_obs[0]['dewpoint_f'] if haf_obs else None

    buoy_data = get_buoy_history("46012", hours=3)
    buoy_cur = buoy_data[0] if buoy_data else None

    # Eddy Check (KWVI, SCXC1, and backup harbor eddy F2595)
    eddy_warning = False
    eddy_data = get_synoptic_latest("SCXC1") or get_synoptic_latest("KWVI") or get_synoptic_latest("F2595")
    if eddy_data:
        eddy_wdir = eddy_data.get('wind_direction')
        eddy_wspd = eddy_data.get('wind_speed')
        eddy_wspd_mph = round(eddy_wspd * 2.23694, 1) if eddy_wspd else 0
        if eddy_wdir and (130 <= eddy_wdir <= 220) and eddy_wspd_mph >= 8.0:
            eddy_warning = True
            print(f"⚠️ Monterey Bay Eddy Active: {eddy_wspd_mph} mph @ {eddy_wdir}°")

    # STAGE 1: STANDBY RULES
    if (is_spring or is_summer) and (8 <= local_hour <= 10):
        if not state["stage1_fired"]:
            print("🔍 Evaluating Stage 1: Morning Standby Rules...")
            sfo_sac_grad = (sfo_cur - sac_cur) if (sfo_cur and sac_cur) else 0
            acv_data = get_synoptic_latest("KACV")
            mry_data = get_synoptic_latest("KMRY")
            acv_mry_grad = (acv_data.get('barometric_pressure', 0) - mry_data.get('barometric_pressure', 0)) if (acv_data and mry_data) else 0
            if acv_mry_grad > 100:
                acv_mry_grad = acv_mry_grad / 100
            preload_ok = (sfo_sac_grad >= 1.5) or (acv_mry_grad >= 2.5)

            heating_ok = True
            if is_summer and inland_temp_sac is not None:
                if local_hour == 8 and inland_temp_sac < 64.0:
                    heating_ok = False
                elif local_hour >= 9 and inland_temp_sac < 68.0:
                    heating_ok = False

            buoy_aligned = False
            if buoy_cur:
                b_wdir = buoy_cur['wdir']
                b_wspd = buoy_cur['wspd']
                if b_wdir and b_wspd:
                    buoy_aligned = (280 <= b_wdir <= 335) and (b_wspd >= 10.0)

            no_eddy_block = not eddy_warning
            no_storm_block = True
            if buoy_cur and buoy_cur.get('gst') and buoy_cur.get('wspd'):
                if (buoy_cur['gst'] - buoy_cur['wspd']) > 9.0:
                    no_storm_block = False

            inversion_ok = True
            fog_block = False

            ridge_data = get_synoptic_latest("BNDC1")
            ridge_temp_f = None

            if ridge_data and ridge_data.get('air_temp') is not None:
                ridge_temp_f = (ridge_data['air_temp'] * 9/5) + 32
                print(f"⛰️ Inversion Temp from Primary Station (BNDC1): {round(ridge_temp_f,1)}°F")
            else:
                print("⚠️ BNDC1 is offline. Running 15-mile high-elevation radius query...")
                fallback_st = get_high_elevation_fallback()
                if fallback_st:
                    ridge_temp_f = (fallback_st['temp_c'] * 9/5) + 32
                    print(f"⛰️ Fallback Inversion Temp loaded from {fallback_st['stid']} ({round(fallback_st['elevation_ft'])} ft): {round(ridge_temp_f,1)}°F")

            if ridge_temp_f is not None and coast_temp_haf is not None:
                inversion_val = ridge_temp_f - coast_temp_haf
                if inversion_val <= 0:
                    print(f"❌ Mixed layer detected (Ridge: {round(ridge_temp_f,1)}°F vs Coast: {round(coast_temp_haf,1)}°F). Blocking alert.")
                    inversion_ok = False
                if coast_dewpoint_haf is not None:
                    temp_dew_spread = coast_temp_haf - coast_dewpoint_haf
                    if temp_dew_spread <= 1.5 and inversion_val < 4.0:
                        print(f"❌ Extreme Fog Lock active (Spread: {round(temp_dew_spread,1)}°F, Inversion: {round(inversion_val,1)}°F). Blocking alert.")
                        fog_block = True

            if preload_ok and heating_ok and buoy_aligned and no_eddy_block and no_storm_block and inversion_ok and not fog_block:
                standby_msg = (
                    f"🏎️ *Waddell Standby Alert (Stage 1)*\n"
                    f"Early pressure preload is locked (+{round(sfo_sac_grad,1)} mb) and buoy flow has clocked NW ({buoy_cur['wspd']} kts).\n"
                    f"Inversion profiles are solid. Pack your gear—likely Go Time later!"
                )
                if send_telegram_alert(standby_msg):
                    state["stage1_fired"] = True
                    save_state(state)
            else:
                print("Stage 1 conditions not met yet or blocked by inversion/fog profiles.")

    # STAGE 2: GO TIME
    elif 11 <= local_hour <= 18:
        if not state["stage2_fired"]:
            print("🔍 Evaluating Stage 2: Go Time Rules...")
            if sfo_cur is not None and sac_cur is not None and buoy_cur:
                sfo_to_sac = round(sfo_cur - sac_cur, 2)
                wdir = buoy_cur['wdir']
                wspd = buoy_cur['wspd']
                gust = buoy_cur['gst']

                min_gradient = 2.8 if mode in ["spring", "summer"] else 3.0
                gradient_trigger = sfo_to_sac >= min_gradient
                wind_speed_ok = wspd >= 14.5

                if mode == "winter":
                    wind_dir_ok = (280 <= wdir <= 345)
                    gust_spread = (gust - wspd) if (gust and wspd) else 0
                    gust_ok = gust_spread <= 8.7
                else:
                    wind_dir_ok = (280 <= wdir <= 330)
                    gust_ok = True

                inland_heat_ok = True
                if mode == "summer" and inland_temp_sac and coast_temp_haf:
                    if inland_temp_sac < 78.0 or (inland_temp_sac - coast_temp_haf) < 18.0:
                        inland_heat_ok = False

                if gradient_trigger and wind_speed_ok and wind_dir_ok and gust_ok and inland_heat_ok and not eddy_warning:
                    go_msg = (
                        f"🚨 *Waddell GO TIME! (Stage 2 Confirmed)*\n"
                        f"Conditions held and beach wind is hitting targets.\n"
                        f"*Wind*: {wspd} kts @ {wdir}°\n"
                        f"*SFO-SAC Gradient*: +{sfo_to_sac} mb\n"
                        f"Load up and head out!"
                    )
                    if send_telegram_alert(go_msg):
                        state["stage2_fired"] = True
                        save_state(state)

        # STAGE 2b: STANDBY DOWNGRADE
        if local_hour == 11 and local_minute >= 30:
            if state["stage1_fired"] and not state["stage2_fired"] and not state["stage2b_fired"]:
                print("📉 Evaluating Stage 2b: Standby Downgrade...")
                downgrade_msg = (
                    f"🟡 *Waddell Update (Stage 2b)*\n"
                    f"Morning setup has stalled out (Eddy / Fog / Weak Gradient). Hold off for now!"
                )
                if send_telegram_alert(downgrade_msg):
                    state["stage2b_fired"] = True
                    save_state(state)

if __name__ == '__main__':
    run_stateful_pipeline()
