"""Bidirectional weather surface. No auth, private files or network calls in JS."""
from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st

_FRONTEND = Path(__file__).with_name("weather_frontend")


def asset_base() -> str:
    base = (st.get_option("server.baseUrlPath") or "").strip("/")
    # Relative URLs preserve hosted iframe prefixes such as Streamlit Cloud's /~/+/.
    return f"/{base}/app/static/weather" if base else "app/static/weather"


@lru_cache(maxsize=4)
def _component(base_path, revision):
    media = Path(st.__file__).parent / "static" / "static" / "media"
    font = next(media.glob("MaterialSymbols-Rounded*.woff2"), None)
    prefix = f"/{base_path}/" if base_path else ""
    font_url = f"{prefix}static/media/{font.name}" if font else ""
    css = (_FRONTEND / "weather.css").read_text(encoding="utf-8").replace("__MATERIAL_FONT_URL__", font_url)
    return st.components.v2.component(
        "workbench_weather", html='<section class="wc-root" aria-label="城市天气"></section>',
        css=css, js=(_FRONTEND / "weather.js").read_text(encoding="utf-8"),
        isolate_styles=True,
    )


def validate_event(value, cards):
    """Treat browser events as untrusted; resolve coordinates from server data."""
    if not isinstance(value, dict) or value.get("type") not in {"toggle", "manage", "refresh", "confirm"}:
        return None
    event_id = value.get("event_id")
    if not isinstance(event_id, str) or not 1 <= len(event_id) <= 80:
        return None
    event = {"type": value["type"], "event_id": event_id}
    if value["type"] == "confirm":
        days = value.get("days")
        city = next((c for c in cards if c["id"] == value.get("city_id")), None)
        if type(days) is not int or days not in (3, 7, 16) or city is None:
            return None
        event.update(city=dict(city), days=days)
    return event


def render_weather(cards, *, expanded, session_id, entry_id, dark=False, demo=False):
    revision = tuple((_FRONTEND / f).stat().st_mtime_ns for f in ("weather.css", "weather.js"))
    component = _component((st.get_option("server.baseUrlPath") or "").strip("/"), revision)
    result = component(
        data={"cards": cards, "expanded": expanded, "theme": "dark" if dark else "light",
              "session_id": session_id, "entry_id": entry_id, "asset_base": asset_base(),
              "today": datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(), "demo": demo},
        key="workbench_weather", on_event_change=lambda: None,
        width="stretch", height="content",
    )
    return validate_event(result.get("event"), cards)
