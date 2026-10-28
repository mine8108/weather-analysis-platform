"""Weather presentation data, independent from Streamlit and network access."""
from __future__ import annotations

import hashlib
import math

from .city_landmarks import landmark_for_city


WEATHER_LABELS = {
    0: "晴", 1: "晴间多云", 2: "多云", 3: "阴",
    45: "雾", 48: "雾凇", 51: "毛毛雨", 53: "中等毛毛雨", 55: "强毛毛雨",
    56: "轻冻毛毛雨", 57: "强冻毛毛雨", 61: "小雨", 63: "中雨", 65: "大雨",
    66: "轻冻雨", 67: "强冻雨", 71: "小雪", 73: "中雪", 75: "大雪",
    77: "米雪", 80: "小阵雨", 81: "中阵雨", 82: "强阵雨", 85: "小阵雪",
    86: "强阵雪", 95: "雷雨", 96: "雷雨伴冰雹", 97: "强雷雨", 99: "强雷雨伴冰雹",
}


def number(value):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None


def city_id(city: dict) -> str:
    """Coordinate identity prevents collisions between same-named places."""
    lat, lon = number(city.get("lat")), number(city.get("lon"))
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("城市坐标无效")
    return hashlib.sha256(f"{lat:.5f},{lon:.5f}".encode()).hexdigest()[:16]


def weather_scene(code, is_day=1) -> str:
    value = number(code)
    code = int(value) if value is not None and value.is_integer() else None
    if code in {0, 1}:
        return "night" if is_day == 0 else ("partly-cloudy" if code == 1 else "sunny")
    if code == 2:
        return "cloudy"
    if code == 3:
        return "overcast"
    if code in {45, 48}:
        return "fog"
    if code in {71, 73, 75, 77, 85, 86}:
        return "snow"
    if code in {95, 96, 97, 99}:
        return "thunder"
    if code in {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82}:
        return "rain"
    return "overcast"


def format_value(value, suffix="", digits=0) -> str:
    n = number(value)
    return "—" if n is None else f"{n:.{digits}f}{suffix}"


def build_cards(cities, weather, air_quality=None, *, active_city=None):
    cards = []
    for city in cities:
        try:
            identity = city_id(city)
        except (ValueError, AttributeError):
            continue
        # The name lookup permits staged adoption of the existing weather fetcher.
        wx = (weather or {}).get(identity, (weather or {}).get(city.get("zh"))) or {}
        aq = (air_quality or {}).get(identity, (air_quality or {}).get(city.get("zh"))) or {}
        code_number = number(wx.get("code"))
        code = int(code_number) if code_number is not None and code_number.is_integer() else None
        loaded = bool(wx) and number(wx.get("temp")) is not None
        cards.append({
            "id": identity, "name": str(city.get("zh") or "未命名地点")[:40],
            "region": str(city.get("region") or "")[:30],
            "lat": float(city["lat"]), "lon": float(city["lon"]),
            "coordinates": f"{abs(float(city['lat'])):.2f}°{'N' if float(city['lat']) >= 0 else 'S'}  "
                           f"{abs(float(city['lon'])):.2f}°{'E' if float(city['lon']) >= 0 else 'W'}",
            "scene": weather_scene(code, wx.get("is_day", 1)),
            "is_day": wx.get("is_day", 1) != 0,
            "condition": WEATHER_LABELS.get(code, "天气未知") if loaded else "暂无天气数据",
            "temperature": format_value(wx.get("temp"), "°"),
            "high_low": f"{format_value(wx.get('t_max'), '°')} / {format_value(wx.get('t_min'), '°')}",
            "humidity": format_value(wx.get("humidity"), "%"),
            "wind": format_value(wx.get("wind"), " m/s", 1),
            "aqi": format_value(aq.get("aqi")), "aqi_level": str(aq.get("level") or ""),
            "valid_at": str(wx.get("valid_at") or ""),
            "timezone": str(wx.get("timezone") or ""),
            "fetched_at": str(wx.get("fetched_at") or ""),
            "aqi_stale": bool(aq.get("stale", False)),
            "stale": bool(wx.get("stale", False)), "loaded": loaded,
            "active": identity == active_city,
            "landmark": landmark_for_city(city),
        })
    return cards
