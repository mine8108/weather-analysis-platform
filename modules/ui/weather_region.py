"""Global weather data and management adapter, rendered under module navigation."""
import streamlit as st

from modules.city_prefs import load_cities, save_cities, save_show_wall
from modules.forecast_context import make_intent, queue_intent
from modules.ui.navigation import navigate
from modules.ui.shell import entry_identity
from modules.ui.weather_component import render_weather
from modules.weather_view_model import build_cards, city_id
from modules import weather_wall as wall


def _remove(identity):
    st.session_state["wall_cities"] = [c for c in st.session_state.get("wall_cities", []) if city_id(c) != identity]
    save_cities(st.session_state["wall_cities"])


def _show_weather():
    st.session_state["_wall_show"] = True
    st.session_state["wall_show_toggle"] = True
    save_show_wall(True)


def render_management():
    with st.container(border=True, key="weather_management"):
        left, right = st.columns([5, 1])
        left.markdown("**管理关注城市**")
        if right.button("完成", key="weather_manage_close", width="stretch"):
            st.session_state["_weather_manage"] = False
            st.rerun()
        st.caption(f"最多关注 {wall.MAX_CITIES} 个城市。可搜索城市名或直接输入纬度、经度。")
        search, add, locate = st.columns([5, 1, 1])
        search.text_input("城市名或经纬度", key="wall_query", placeholder="北京 / 39.9,116.4", label_visibility="collapsed")
        add.button("添加", key="wall_resolve", icon=":material/add:", width="stretch", on_click=wall._resolve_query)
        if locate.button("定位", key="wall_locate", icon=":material/my_location:", width="stretch"):
            st.session_state["_weather_locate"] = True
            st.session_state["_weather_locate_clear"] = True
            st.session_state["_geo_consumed"] = False
        # Mount geolocation only following an explicit user action.
        if st.session_state.get("_weather_locate"):
            clear = st.session_state.pop("_weather_locate_clear", False)
            location = wall.geo_locator(clear=clear, key="wall_geo")
            if location and not clear:
                wall._consume_geo(location)
                st.session_state["_weather_locate"] = False
                st.rerun()
        candidates = st.session_state.get("_resolve_candidates") or []
        if candidates:
            st.selectbox("选择具体地点", candidates, index=None, key="wall_candidate_pick",
                         format_func=wall.format_candidate, on_change=wall._on_pick_candidate)
        for city in st.session_state.get("wall_cities", []):
            text_col, remove_col = st.columns([6, 1])
            text_col.write(f"{city['zh']} · {city['lat']:.2f}, {city['lon']:.2f}")
            remove_col.button("移除", key=f"ww_del_{city_id(city)}", on_click=_remove, args=(city_id(city),), width="stretch")


def render_weather_region(route):
    session, entry = entry_identity(route)
    if not st.session_state.get("_wall_show", True):
        st.button("显示城市天气", key="weather_show", icon=":material/partly_cloudy_day:", on_click=_show_weather)
        return
    if "wall_cities" not in st.session_state:
        normalized = [c for c in (wall._normalize_city(c) for c in (load_cities() or [])) if c]
        seen = set()
        cities = []
        for city in normalized:
            identity = city_id(city)
            if identity not in seen:
                cities.append(city); seen.add(identity)
        st.session_state["wall_cities"] = cities[:wall.MAX_CITIES]
    cities = st.session_state["wall_cities"]
    st.session_state.setdefault("_weather_expanded", False)
    wx = wall.fetch_wall_weather(cities, identity_keys=True)
    aq = wall.fetch_wall_aqi(cities, identity_keys=True)
    result = st.session_state.get("fc_result_context") or {}
    cards = build_cards(cities, wx, aq, active_city=result.get("city_id"))
    event = render_weather(cards, expanded=st.session_state["_weather_expanded"], session_id=session,
                           entry_id=entry, dark=st.session_state.get("dark_mode", False))
    if event and event["event_id"] != st.session_state.get("_weather_last_event"):
        st.session_state["_weather_last_event"] = event["event_id"]
        kind = event["type"]
        if kind == "toggle":
            st.session_state["_weather_expanded"] = not st.session_state["_weather_expanded"]
        elif kind == "manage":
            st.session_state["_weather_manage"] = True
        elif kind == "refresh":
            wall.refresh_weather()
        elif kind == "confirm":
            city = event["city"]
            city["zh"] = city["name"]
            intent = make_intent(city, event["days"], source_route=route,
                                 source_filters={"date_range": str(st.session_state.get("_filter_date_range") or "")})
            queue_intent(st.session_state, intent)
            st.session_state["_weather_expanded"] = False
            navigate(2)
        st.rerun()
    notice = st.session_state.pop("_wall_notice", None)
    if notice:
        st.warning(notice)
    if cities and (not wx or any(c["stale"] for c in cards)):
        st.caption("天气服务暂未更新，已保留上次可用数据；可点击刷新重试。")
    if st.session_state.get("_weather_manage"):
        render_management()
