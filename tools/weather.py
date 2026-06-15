#!/usr/bin/env python3
"""
Weather CLI — location auto-detected from Home Assistant (person.vineet)
Uses Open-Meteo (free, no API key)

Usage:
  weather.py              — current + today
  weather.py today        — today's hourly
  weather.py week         — 7-day forecast
  weather.py now          — current conditions only
"""
import sys, os, json, urllib.request, urllib.parse

HA_URL    = "http://localhost:8123"
HA_TOKEN  = open(os.path.expanduser("~/.config/homeassistant/token")).read().strip()

WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Icy fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Light showers", 81: "Showers", 82: "Heavy showers",
    85: "Snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm w/ hail", 99: "Thunderstorm w/ heavy hail",
}

WMO_EMOJI = {
    0: "☀️", 1: "🌤", 2: "⛅", 3: "☁️",
    45: "🌫", 48: "🌫",
    51: "🌦", 53: "🌦", 55: "🌧",
    61: "🌧", 63: "🌧", 65: "🌧",
    71: "🌨", 73: "❄️", 75: "❄️", 77: "❄️",
    80: "🌦", 81: "🌧", 82: "⛈",
    85: "🌨", 86: "🌨",
    95: "⛈", 96: "⛈", 99: "⛈",
}

def ha_get(path):
    req = urllib.request.Request(
        HA_URL + path,
        headers={"Authorization": f"Bearer {HA_TOKEN}"}
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())

def get_location():
    data  = ha_get("/api/states/person.vineet")
    attrs = data.get("attributes", {})
    lat   = attrs.get("latitude")
    lon   = attrs.get("longitude")
    state = data.get("state", "unknown")
    if not lat or not lon:
        raise RuntimeError("No location from HA — enable location tracking on iPhone")
    return float(lat), float(lon), state

def reverse_geocode(lat, lon):
    url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json"
    req = urllib.request.Request(url, headers={"User-Agent": "VineetPiBot/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            d = json.loads(r.read())
        addr = d.get("address", {})
        city = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("county", "")
        state = addr.get("state", "")
        return f"{city}, {state}".strip(", ")
    except:
        return f"{lat:.2f}, {lon:.2f}"

def fetch_weather(lat, lon):
    params = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m,wind_direction_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max",
        "hourly": "temperature_2m,precipitation_probability,weather_code",
        "timezone": "auto",
        "forecast_days": 7,
    })
    url = f"https://api.open-meteo.com/v1/forecast?{params}"
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read())

def wind_dir(deg):
    dirs = ["N","NE","E","SE","S","SW","W","NW"]
    return dirs[round(deg / 45) % 8]

def cmd_now(lat, lon, location_name, ha_state):
    w = fetch_weather(lat, lon)
    c = w["current"]
    code  = c.get("weather_code", 0)
    emoji = WMO_EMOJI.get(code, "🌡")
    desc  = WMO_CODES.get(code, "Unknown")
    temp  = c.get("temperature_2m", "?")
    feels = c.get("apparent_temperature", "?")
    humid = c.get("relative_humidity_2m", "?")
    wind  = c.get("wind_speed_10m", "?")
    wdir  = wind_dir(c.get("wind_direction_10m", 0))
    rain  = c.get("precipitation", 0)

    status = "🏠 home" if ha_state == "home" else f"📍 {ha_state}"
    print(f"\n{emoji}  {desc}")
    print(f"📍 {location_name} ({status})")
    print(f"🌡  {temp}°C  (feels like {feels}°C)")
    print(f"💧 Humidity: {humid}%")
    print(f"💨 Wind: {wind} km/h {wdir}")
    if rain:
        print(f"🌧 Precipitation: {rain} mm")

def cmd_today(lat, lon, location_name, ha_state):
    cmd_now(lat, lon, location_name, ha_state)
    w = fetch_weather(lat, lon)
    hourly = w["hourly"]
    times  = hourly["time"]
    temps  = hourly["temperature_2m"]
    probs  = hourly["precipitation_probability"]
    codes  = hourly["weather_code"]

    from datetime import date
    today = date.today().isoformat()
    print(f"\n── Today's hourly ──")
    for i, t in enumerate(times):
        if not t.startswith(today): continue
        hour  = t[11:16]
        emoji = WMO_EMOJI.get(codes[i], "🌡")
        print(f"  {hour}  {emoji} {temps[i]}°C  🌧{probs[i]}%")

def cmd_week(lat, lon, location_name, ha_state):
    cmd_now(lat, lon, location_name, ha_state)
    w = fetch_weather(lat, lon)
    d = w["daily"]
    print(f"\n── 7-day forecast ──")
    for i in range(len(d["time"])):
        from datetime import date, datetime
        dt    = datetime.strptime(d["time"][i], "%Y-%m-%d")
        label = "Today    " if d["time"][i] == date.today().isoformat() else dt.strftime("%a %d %b  ")
        code  = d["weather_code"][i]
        emoji = WMO_EMOJI.get(code, "🌡")
        desc  = WMO_CODES.get(code, "")
        hi    = d["temperature_2m_max"][i]
        lo    = d["temperature_2m_min"][i]
        rain  = d["precipitation_sum"][i]
        prob  = d["precipitation_probability_max"][i]
        print(f"  {label}  {emoji} {desc:<20} ↑{hi}° ↓{lo}°  🌧{prob}% ({rain}mm)")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "today"
    try:
        lat, lon, ha_state = get_location()
        location_name = reverse_geocode(lat, lon)
    except Exception as e:
        print(f"Error getting location: {e}"); sys.exit(1)

    if cmd == "now":
        cmd_now(lat, lon, location_name, ha_state)
    elif cmd == "week":
        cmd_week(lat, lon, location_name, ha_state)
    else:
        cmd_today(lat, lon, location_name, ha_state)
