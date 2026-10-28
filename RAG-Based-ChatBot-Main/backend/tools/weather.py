"""
DocuChat AI - Production Weather Tool
Integrates with Open-Meteo's official geocoding and forecast APIs (free, no API key required).
Provides live current weather, today's high/low, hourly forecasts, rain probability,
wind speed, humidity, and actionable outdoor recommendations.
"""

import re
import json
import logging
import contextvars
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
import httpx
from pydantic import BaseModel, Field
from langchain_core.tools import tool

logger = logging.getLogger("weather_tool")

# ContextVar to capture structured weather payload for the current request execution
active_weather_data: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar("active_weather_data", default=None)

# Popular location coordinates and aliases for fast, reliable disambiguation
POPULAR_LOCATIONS = {
    "goa": {"name": "Goa", "country": "India", "latitude": 15.49574, "longitude": 73.82624, "admin1": "Goa"},
    "panjim": {"name": "Panjim", "country": "India", "latitude": 15.49574, "longitude": 73.82624, "admin1": "Goa"},
    "panaji": {"name": "Panaji", "country": "India", "latitude": 15.49574, "longitude": 73.82624, "admin1": "Goa"},
    "bengaluru": {"name": "Bengaluru", "country": "India", "latitude": 12.97194, "longitude": 77.59369, "admin1": "Karnataka"},
    "bangalore": {"name": "Bengaluru", "country": "India", "latitude": 12.97194, "longitude": 77.59369, "admin1": "Karnataka"},
    "hyderabad": {"name": "Hyderabad", "country": "India", "latitude": 17.38405, "longitude": 78.45636, "admin1": "Telangana"},
    "chennai": {"name": "Chennai", "country": "India", "latitude": 13.08784, "longitude": 80.27847, "admin1": "Tamil Nadu"},
    "mumbai": {"name": "Mumbai", "country": "India", "latitude": 19.07283, "longitude": 72.88261, "admin1": "Maharashtra"},
    "delhi": {"name": "Delhi", "country": "India", "latitude": 28.65195, "longitude": 77.23149, "admin1": "Delhi"},
    "kolkata": {"name": "Kolkata", "country": "India", "latitude": 22.5697, "longitude": 88.3697, "admin1": "West Bengal"},
    "pune": {"name": "Pune", "country": "India", "latitude": 18.5204, "longitude": 73.8567, "admin1": "Maharashtra"},
    "kashmir": {"name": "Srinagar", "country": "India", "latitude": 34.0837, "longitude": 74.7973, "admin1": "Jammu and Kashmir"},
    "srinagar": {"name": "Srinagar", "country": "India", "latitude": 34.0837, "longitude": 74.7973, "admin1": "Jammu and Kashmir"},
    "jaipur": {"name": "Jaipur", "country": "India", "latitude": 26.9124, "longitude": 75.7873, "admin1": "Rajasthan"},
    "london": {"name": "London", "country": "United Kingdom", "latitude": 51.50853, "longitude": -0.12574, "admin1": "England"},
    "new york": {"name": "New York", "country": "United States", "latitude": 40.7128, "longitude": -74.0060, "admin1": "New York"},
    "san francisco": {"name": "San Francisco", "country": "United States", "latitude": 37.7749, "longitude": -122.4194, "admin1": "California"},
    "tokyo": {"name": "Tokyo", "country": "Japan", "latitude": 35.6895, "longitude": 139.69171, "admin1": "Tokyo"},
    "paris": {"name": "Paris", "country": "France", "latitude": 48.8534, "longitude": 2.3488, "admin1": "Île-de-France"},
    "dubai": {"name": "Dubai", "country": "United Arab Emirates", "latitude": 25.2048, "longitude": 55.2708, "admin1": "Dubai"},
    "singapore": {"name": "Singapore", "country": "Singapore", "latitude": 1.3521, "longitude": 103.8198, "admin1": "Singapore"},
    "sydney": {"name": "Sydney", "country": "Australia", "latitude": -33.8688, "longitude": 151.2093, "admin1": "New South Wales"},
    "bali": {"name": "Denpasar", "country": "Indonesia", "latitude": -8.6500, "longitude": 115.2167, "admin1": "Bali"},
}

WMO_WEATHER_CODES = {
    0: ("Clear skies", "clear"),
    1: ("Mainly clear", "partly_cloudy"),
    2: ("Partly cloudy", "partly_cloudy"),
    3: ("Overcast", "cloudy"),
    45: ("Fog", "fog"),
    48: ("Depositing rime fog", "fog"),
    51: ("Light drizzle", "rain"),
    53: ("Moderate drizzle", "rain"),
    55: ("Dense drizzle", "rain"),
    56: ("Light freezing drizzle", "snow"),
    57: ("Dense freezing drizzle", "snow"),
    61: ("Slight rain", "rain"),
    63: ("Moderate rain", "rain"),
    65: ("Heavy rain", "rain"),
    66: ("Light freezing rain", "snow"),
    67: ("Heavy freezing rain", "snow"),
    71: ("Slight snowfall", "snow"),
    73: ("Moderate snowfall", "snow"),
    75: ("Heavy snowfall", "snow"),
    77: ("Snow grains", "snow"),
    80: ("Slight rain showers", "rain"),
    81: ("Moderate rain showers", "rain"),
    82: ("Violent rain showers", "rain"),
    85: ("Slight snow showers", "snow"),
    86: ("Heavy snow showers", "snow"),
    95: ("Thunderstorm", "thunderstorm"),
    96: ("Thunderstorm with slight hail", "thunderstorm"),
    99: ("Thunderstorm with heavy hail", "thunderstorm"),
}


def extract_location_from_query(query: str) -> Optional[str]:
    """
    Extracts target location name from natural language weather queries.
    Handles:
    - 'What is the weather today in Goa?' -> 'Goa'
    - 'Will it rain in Bengaluru tomorrow?' -> 'Bengaluru'
    - 'What is the current temperature in Hyderabad?' -> 'Hyderabad'
    - 'Give me a 5-day weather forecast for Chennai.' -> 'Chennai'
    - 'Should I carry an umbrella in Goa tonight?' -> 'Goa'
    - 'Delhi weather forecast' -> 'Delhi'
    - 'London weather' -> 'London'
    """
    if not query:
        return None
    q = query.strip()

    # 1. First check if any known city from POPULAR_LOCATIONS is mentioned
    q_words = [re.sub(r"[^\w]", "", w.lower()) for w in q.split()]
    for city_key in POPULAR_LOCATIONS.keys():
        if city_key in q_words:
            return POPULAR_LOCATIONS[city_key]["name"]
        if " " in city_key and city_key in q.lower():
            return POPULAR_LOCATIONS[city_key]["name"]

    # 2. Match prepositional patterns: 'in <City>', 'for <City>', 'at <City>'
    prep_matches = re.findall(r"\b(?:in|for|at|around)\s+([A-Za-z\s]+?)(?:\s+(?:today|tomorrow|tonight|this\s+week|right\s+now|currently)|\?|\.|$)", q, re.I)
    if prep_matches:
        candidate = prep_matches[0].strip()
        candidate = re.sub(r"\b(today|tomorrow|tonight|now|the\s+morning|the\s+evening)\b", "", candidate, flags=re.I).strip()
        if candidate and len(candidate.split()) <= 3:
            return candidate

    # 3. Match '<City> weather' or '<City> forecast' or '<City> temperature'
    city_first = re.findall(r"^([A-Za-z\s]+?)\s+(?:weather|forecast|temperature|rain)", q, re.I)
    if city_first:
        candidate = city_first[0].strip()
        candidate = re.sub(r"^(what\s+is|give\s+me|tell\s+me)\s+", "", candidate, flags=re.I).strip()
        if candidate and len(candidate.split()) <= 3:
            return candidate

    # 4. Fallback: match after 'weather of <City>'
    of_matches = re.findall(r"\b(?:weather|temperature|forecast)\s+of\s+([A-Za-z\s]+?)(?:\s+(?:today|tomorrow)|\?|\.|$)", q, re.I)
    if of_matches:
        return of_matches[0].strip()

    return None



class WeatherInput(BaseModel):
    location: str = Field(..., min_length=2, max_length=100, description="City, region, or country to get weather for (e.g. 'Goa', 'Bengaluru', 'London')")
    days: int = Field(1, ge=1, le=7, description="Number of forecast days (1 for today, up to 7)")
    unit: str = Field("celsius", description="Temperature unit ('celsius' or 'fahrenheit')")


async def geocode_location(location: str, client: Optional[httpx.AsyncClient] = None) -> Optional[Dict[str, Any]]:
    """
    Resolves location string to geographical coordinates and metadata.
    Uses popularity fallback dictionary for rapid zero-latency lookup,
    falling back to Open-Meteo's official geocoding service.
    """
    clean_loc = location.strip().lower()
    clean_loc = re.sub(r"^(in|for|at)\s+", "", clean_loc).strip()
    clean_loc = re.sub(r"[?.!]+$", "", clean_loc).strip()

    # 1. Check popular locations map
    if clean_loc in POPULAR_LOCATIONS:
        return POPULAR_LOCATIONS[clean_loc]

    # Also check if any popular location keyword is contained
    for key, data in POPULAR_LOCATIONS.items():
        if key in clean_loc.split():
            return data

    # 2. Query Open-Meteo Geocoding API
    geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={clean_loc}&count=5&language=en&format=json"
    should_close = False
    if client is None:
        client = httpx.AsyncClient(timeout=8.0)
        should_close = True

    try:
        resp = await client.get(geo_url)
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("results", [])
            if results:
                # Prioritize India if India mentioned or if exact name matches
                top = results[0]
                return {
                    "name": top.get("name"),
                    "country": top.get("country", ""),
                    "admin1": top.get("admin1", ""),
                    "latitude": top.get("latitude"),
                    "longitude": top.get("longitude"),
                    "timezone": top.get("timezone", "auto")
                }
    except Exception as e:
        logger.warning(f"Geocoding error for '{location}': {e}")
    finally:
        if should_close:
            await client.aclose()

    return None


def format_wmo_code(code: int) -> Tuple[str, str]:
    """Returns (Condition string, condition category icon key)."""
    return WMO_WEATHER_CODES.get(code, ("Partly cloudy", "partly_cloudy"))


def describe_feels_like(temp: float, apparent: float, humidity: int) -> str:
    """Provides natural descriptive feels-like text matching reference design."""
    diff = apparent - temp
    if apparent >= 32 and humidity >= 70:
        return "Feels warm and humid"
    elif apparent >= 35:
        return "Feels hot and humid"
    elif apparent >= 28 and diff > 2:
        return "Feels warm"
    elif apparent <= 10:
        return "Feels cold and brisk"
    elif apparent <= 18:
        return "Feels cool and comfortable"
    else:
        return f"Feels like {round(apparent)}°C"


def generate_weather_advice(condition: str, rain_chance: int, max_temp: float, min_temp: float) -> List[Dict[str, str]]:
    """
    Generates sensible, grounded recommendations based strictly on forecast metrics:
    - Beach/Outdoor visit
    - Rain/Umbrella
    - What to wear
    """
    advice = []

    # 1. Beach visit / Outdoor activity
    if max_temp >= 28:
        advice.append({
            "category": "Beach visit",
            "icon": "🏖",
            "text": "The weather is warm, so evenings are more comfortable for outdoor visits."
        })
    elif max_temp >= 20:
        advice.append({
            "category": "Outdoor visit",
            "icon": "🚶",
            "text": "Pleasant temperatures make it great for daytime outdoor activities."
        })
    else:
        advice.append({
            "category": "Outdoor visit",
            "icon": "🧥",
            "text": "Cool temperatures; dress warmly if heading out for extended periods."
        })

    # 2. Rain / Umbrella advice
    if rain_chance >= 50:
        advice.append({
            "category": "Rain",
            "icon": "🌧",
            "text": f"High chance of rain ({rain_chance}%). It is recommended to carry an umbrella or rain gear."
        })
    elif rain_chance >= 25:
        advice.append({
            "category": "Rain",
            "icon": "🌧",
            "text": f"A passing shower is possible ({rain_chance}% chance). Keep a light umbrella handy."
        })
    else:
        advice.append({
            "category": "Rain",
            "icon": "🌧",
            "text": f"Rain is unlikely today ({rain_chance}% chance). Skies are expected to remain mostly dry."
        })

    # 3. What to wear
    if max_temp >= 27:
        advice.append({
            "category": "What to wear",
            "icon": "👕",
            "text": "Light cotton clothes; stay hydrated during the daytime."
        })
    elif max_temp >= 18:
        advice.append({
            "category": "What to wear",
            "icon": "👔",
            "text": "Comfortable casual wear with light layering for the evening."
        })
    else:
        advice.append({
            "category": "What to wear",
            "icon": "🧥",
            "text": "Warm clothing, jacket, or sweater recommended."
        })

    return advice


async def fetch_weather_data(location_info: Dict[str, Any], days: int = 1, unit: str = "celsius") -> Optional[Dict[str, Any]]:
    """
    Fetches real forecast and current observation from Open-Meteo.
    """
    lat = location_info["latitude"]
    lon = location_info["longitude"]
    temp_unit_param = "&temperature_unit=fahrenheit" if unit.lower() == "fahrenheit" else ""

    forecast_url = (
        f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
        f"&current=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m"
        f"&hourly=temperature_2m,relative_humidity_2m,precipitation_probability,weather_code"
        f"&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
        f"&timezone=auto{temp_unit_param}"
    )

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(forecast_url)
        if resp.status_code != 200:
            logger.error(f"Open-Meteo API returned status {resp.status_code}: {resp.text}")
            return None
        return resp.json()


def parse_weather_payload(loc: Dict[str, Any], raw_data: Dict[str, Any], unit: str = "celsius") -> Dict[str, Any]:
    """
    Normalizes Open-Meteo response into a structured, validated card model.
    """
    current = raw_data.get("current", {})
    daily = raw_data.get("daily", {})
    hourly = raw_data.get("hourly", {})

    temp_unit_symbol = "°F" if unit.lower() == "fahrenheit" else "°C"
    cur_temp = current.get("temperature_2m")
    apparent_temp = current.get("apparent_temperature", cur_temp)
    humidity = current.get("relative_humidity_2m", 0)
    wind_speed = current.get("wind_speed_10m", 0)
    wmo_code = current.get("weather_code", 0)
    condition_text, condition_category = format_wmo_code(wmo_code)

    today_high = daily.get("temperature_2m_max", [cur_temp])[0]
    today_low = daily.get("temperature_2m_min", [cur_temp])[0]
    rain_chance = daily.get("precipitation_probability_max", [0])[0] or 0

    # Calculate tonight temperature range from hourly data (hours 20:00 to 04:00)
    tonight_str = f"{round(today_low)}{temp_unit_symbol}"
    hourly_times = hourly.get("time", [])
    hourly_temps = hourly.get("temperature_2m", [])
    hourly_codes = hourly.get("weather_code", [])
    hourly_rain = hourly.get("precipitation_probability", [])

    night_temps = []
    for t_str, t_val in zip(hourly_times[:36], hourly_temps[:36]):
        try:
            hour = int(t_str.split("T")[1].split(":")[0])
            if hour >= 20 or hour <= 4:
                night_temps.append(t_val)
        except Exception:
            pass

    if night_temps:
        min_n = round(min(night_temps))
        max_n = round(max(night_temps))
        if min_n == max_n:
            tonight_str = f"{min_n}{temp_unit_symbol}"
        else:
            tonight_str = f"{min_n}–{max_n}{temp_unit_symbol}"

    # Extract 6-hour hourly forecast starting from current hour
    current_time_str = current.get("time", "")
    hourly_forecast = []
    cur_hour = 0
    try:
        cur_hour = int(current_time_str.split("T")[1].split(":")[0])
    except Exception:
        cur_hour = datetime.now().hour

    for i in range(len(hourly_times)):
        try:
            h_time_str = hourly_times[i]
            h_hour = int(h_time_str.split("T")[1].split(":")[0])
            if i >= cur_hour and len(hourly_forecast) < 6:
                display_hour = f"{h_hour % 12 or 12} {'AM' if h_hour < 12 else 'PM'}"
                h_code = hourly_codes[i] if i < len(hourly_codes) else 0
                h_cond, _ = format_wmo_code(h_code)
                hourly_forecast.append({
                    "time": display_hour,
                    "temp": f"{round(hourly_temps[i])}{temp_unit_symbol}",
                    "condition": h_cond,
                    "rain_chance": f"{hourly_rain[i]}%" if i < len(hourly_rain) else "0%"
                })
        except Exception:
            pass

    # Format timestamp
    display_time = "Live"
    try:
        if current_time_str:
            dt = datetime.fromisoformat(current_time_str)
            display_time = dt.strftime("%I:%M %p").lstrip("0")
    except Exception:
        display_time = "Live"

    city_name = loc.get("name", "Unknown")
    country_name = loc.get("country", "")
    location_label = f"{city_name}, {country_name}".strip(", ")
    feels_desc = describe_feels_like(cur_temp, apparent_temp, humidity)
    advice_items = generate_weather_advice(condition_text, rain_chance, today_high, today_low)

    payload = {
        "location": location_label,
        "city": city_name,
        "country": country_name,
        "admin1": loc.get("admin1", ""),
        "current_temp": round(cur_temp),
        "current_temp_display": f"{round(cur_temp)}{temp_unit_symbol}",
        "condition": condition_text,
        "condition_category": condition_category,
        "weather_code": wmo_code,
        "feels_like": round(apparent_temp),
        "feels_like_desc": feels_desc,
        "humidity": humidity,
        "humidity_display": f"{humidity}%",
        "wind_speed": wind_speed,
        "wind_speed_display": f"{wind_speed} km/h",
        "today_high": round(today_high),
        "today_high_display": f"{round(today_high)}{temp_unit_symbol}",
        "today_low": round(today_low),
        "today_low_display": f"{round(today_low)}{temp_unit_symbol}",
        "rain_chance": rain_chance,
        "rain_chance_desc": f"{rain_chance}% daytime",
        "tonight_temp": tonight_str,
        "hourly_forecast": hourly_forecast,
        "last_updated": display_time,
        "source": f"Live weather data and forecast for {city_name}.",
        "advice": advice_items,
        "type": "weather"
    }

    return payload


async def get_weather_forecast_async(location: str, days: int = 1, unit: str = "celsius") -> Dict[str, Any]:
    """
    Executes geocoding + weather lookup safely and returns structured card payload
    together with formatted text suitable for LLM grounding.
    """
    loc = await geocode_location(location)
    if not loc:
        return {
            "error": f"Could not find geographic location for '{location}'. Please check spelling or specify city and country.",
            "status": "error"
        }

    raw_data = await fetch_weather_data(loc, days=days, unit=unit)
    if not raw_data:
        return {
            "error": f"Weather service temporarily unavailable for '{location}'. Please try again in a few moments.",
            "status": "error"
        }

    payload = parse_weather_payload(loc, raw_data, unit=unit)
    active_weather_data.set(payload)

    # Build concise textual summary for LLM grounding
    text_summary = (
        f"Location: {payload['location']}\n"
        f"Current: {payload['current_temp_display']}, {payload['condition']}. {payload['feels_like_desc']}.\n"
        f"Humidity: {payload['humidity_display']}, Wind Speed: {payload['wind_speed_display']}.\n"
        f"Today's High: {payload['today_high_display']}, Today's Low: {payload['today_low_display']}.\n"
        f"Rain Chance: {payload['rain_chance_desc']}.\n"
        f"Tonight Forecast: {payload['tonight_temp']}.\n"
        f"Source: {payload['source']}\n"
    )

    return {
        "status": "success",
        "weather": payload,
        "summary": text_summary
    }


@tool("weather", args_schema=WeatherInput)
async def weather_tool(location: str, days: int = 1, unit: str = "celsius") -> str:
    """
    Fetches real-time weather, temperature, forecasts, precipitation probability,
    humidity, wind speed, and outdoor recommendations for any city or location worldwide.
    """
    result = await get_weather_forecast_async(location=location, days=days, unit=unit)
    if result.get("status") == "success":
        return result.get("summary", "")
    return result.get("error", "Weather data unavailable.")
