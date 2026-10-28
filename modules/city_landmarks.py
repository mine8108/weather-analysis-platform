"""Application-owned city artwork, matched by both city name and location."""
from __future__ import annotations

from functools import lru_cache
import json
import math
from pathlib import Path
import unicodedata

_CATALOG = Path(__file__).resolve().parents[1] / "assets" / "landmarks" / "catalog.json"
_MAX_DISTANCE_KM = 75.0


def _name_key(value) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    value = value.replace("臺", "台").replace("澳門", "澳门")
    if value.startswith("中国"):
        value = value[2:]
    for suffix in ("特别行政区", "特別行政區", "市"):
        if value.endswith(suffix):
            value = value[:-len(suffix)]
            break
    return "".join(c for c in value if c.isalnum())


@lru_cache(maxsize=1)
def landmark_catalog() -> tuple[dict, ...]:
    """Read trusted repository metadata; caller data never becomes an asset path."""
    return tuple(json.loads(_CATALOG.read_text(encoding="utf-8"))["cities"])


def landmark_for_city(city: dict) -> dict | None:
    if not isinstance(city, dict):
        return None
    try:
        lat, lon = float(city["lat"]), float(city["lon"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    names = {_name_key(city.get("zh")), _name_key(city.get("en")), _name_key(city.get("name"))} - {""}
    for item in landmark_catalog():
        if not names.intersection(_name_key(n) for n in (item["city"], *item["aliases"])):
            continue
        dlat = math.radians(lat - item["lat"])
        dlon = math.radians(lon - item["lon"])
        a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat)) * math.cos(math.radians(item["lat"])) * math.sin(dlon / 2) ** 2
        distance = 6371.0 * 2 * math.asin(min(1.0, math.sqrt(max(0.0, a))))
        if distance <= _MAX_DISTANCE_KM:
            return {"id": item["id"], "name": item["landmark"], "asset": item["asset"]}
    return None
