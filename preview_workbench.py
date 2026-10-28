"""Isolated local design fixture. Run explicitly; production app never imports it.

No account impersonation, Supabase, weather API or AI calls are performed here.
"""
from unittest.mock import patch

import numpy as np
import pandas as pd
import streamlit as st

from modules import theme_aether
from modules.ui.shell import entry_identity, inject_workbench_style, page_heading, render_brand
from modules.ui.weather_component import render_weather
from modules.ui.navigation import render_navigation, queue_navigation
from modules.weather_view_model import build_cards, city_id
from modules.city_landmarks import landmark_catalog
from modules.forecast_context import make_intent, queue_intent, consume_intent, commit_success
from tools.workbench_fixtures import forecast_frame, air_quality, current_weather, image_and_report

st.set_page_config(page_title="气象分析工作台 · 本地预览", layout="wide", initial_sidebar_state="collapsed")
st.session_state.setdefault("dark_mode", False)
theme_aether.inject_theme()
inject_workbench_style()

CITIES = [
    {"zh": "廊坊", "lat": 39.96, "lon": 116.79}, {"zh": "北京", "lat": 39.90, "lon": 116.40},
    {"zh": "南昌", "lat": 28.68, "lon": 115.86}, {"zh": "上海", "lat": 31.23, "lon": 121.47},
    {"zh": "广州", "lat": 23.13, "lon": 113.26}, {"zh": "成都", "lat": 30.67, "lon": 104.06},
]
WEATHER = {city_id(c): {"code": code, "temp": temp, "t_max": high, "t_min": low,
    "wind": wind, "humidity": humidity, "is_day": 1, "valid_at": "2026-10-26 14:00", "timezone": "Asia/Shanghai"}
    for c, code, temp, high, low, wind, humidity in zip(CITIES, [2, 0, 61, 3, 2, 45], [10, 12, 22, 20, 27, 18],
        [17, 18, 24, 22, 30, 21], [7, 6, 18, 17, 23, 15], [4, 3, 2, 4, 2, 1], [80, 45, 86, 70, 70, 77])}
AQI = {city_id(c): {"aqi": aqi} for c, aqi in zip(CITIES, [45, 38, 42, 35, 39, 52])}
st.session_state.setdefault("_weather_expanded", True)
if not st.session_state.get("_preview_initialized"):
    intent = make_intent(CITIES[0], 7)
    queue_intent(st.session_state, intent)
    consume_intent(st.session_state)
    commit_success(st.session_state, intent, forecast_frame()[0])
    st.session_state["wall_cities"] = CITIES
    st.session_state["df"] = forecast_frame()[0]
    st.session_state["df"].loc[2, "humidity"] = np.nan
    st.session_state["df"].loc[3, "temperature"] += 9
    st.session_state["source"] = "合成示例数据 · 仅供界面测试"
    st.session_state["import_step"] = 2
    st.session_state["_preview_initialized"] = True


def weather(route):
    session, entry = entry_identity(route)
    sample = st.session_state.get("_preview_weather_sample", "六城正常")
    cities = CITIES[:{"无关注城市": 0, "单城": 1, "两城": 2}.get(sample, 6)]
    weather_values = {key: dict(value) for key, value in WEATHER.items()}
    landmark_group = st.session_state.get("_preview_landmark_group", "当前六城")
    if landmark_group != "当前六城":
        groups = {"全部 41 城": (0, 41), "北方与东北": (0, 9), "华东": (9, 20), "中南与港澳": (20, 31), "西部": (31, 41)}
        start, end = groups[landmark_group]
        cities = [{"zh": item["city"], "lat": item["lat"], "lon": item["lon"]} for item in landmark_catalog()[start:end]]
        weather_values = {city_id(c): {"code": 2, "temp": 24, "t_max": 28, "t_min": 20,
                          "wind": 2.8, "humidity": 65, "is_day": 1,
                          "valid_at": "2026-10-26 14:00", "timezone": "Asia/Shanghai"} for c in cities}
    if sample == "部分缺失":
        weather_values.pop(city_id(cities[0]), None)
    elif sample == "未知天气码":
        weather_values[city_id(cities[0])]["code"] = 999
    elif sample == "夜间":
        for value in weather_values.values():
            value["is_day"] = 0
    elif sample == "上次成功数据":
        weather_values[city_id(cities[0])]["stale"] = True
    cards = build_cards(cities, weather_values, AQI, active_city=(st.session_state.get("fc_result_context") or {}).get("city_id"))
    event = render_weather(cards, expanded=st.session_state["_weather_expanded"], session_id=session, entry_id=entry, dark=st.session_state.dark_mode, demo=True)
    if event and event["event_id"] != st.session_state.get("_preview_event"):
        st.session_state["_preview_event"] = event["event_id"]
        if event["type"] == "toggle":
            st.session_state["_weather_expanded"] = not st.session_state["_weather_expanded"]
            st.rerun()
        elif event["type"] == "confirm":
            city = event["city"]
            queue_intent(st.session_state, make_intent(city, event["days"], source_route=route))
            st.session_state["_weather_expanded"] = False
            queue_navigation(2)
            st.rerun()
        elif event["type"] == "refresh":
            st.toast("预览保留固定示例，未调用天气服务。")
        elif event["type"] == "manage":
            st.session_state["_preview_manage"] = not st.session_state.get("_preview_manage", False)
            st.rerun()
    if st.session_state.get("_preview_manage"):
        st.info("这是独立设计预览，可在下方检查项切换地标城市组；正式界面继续使用你的关注列表。")


def forecast():
    from modules import nwp_forecast as nwp
    def preview_fetch(*args, **kwargs):
        if st.session_state.get("_preview_forecast_delay"):
            import time
            time.sleep(3)
        if st.session_state.get("_preview_forecast_failure"):
            return None, "离线预览模拟失败，未请求天气接口。"
        return forecast_frame(*args, **kwargs)
    weather("forecast")
    with st.container(key="workbench_content"), patch.multiple(nwp,
            fetch_gfs_forecast=preview_fetch, fetch_air_quality=air_quality, _fetch_gfs_current=current_weather,
            _render_forecast_verification=lambda: st.info("此离线预览不运行实况取数。生产页保留会话观测、历史接口及上传验证入口。")):
        nwp.render_forecast_tab()


def analysis():
    from modules.visualizer import render_visualization_tab
    weather("visualization")
    with st.container(key="workbench_content"):
        render_visualization_tab(st.session_state.get("df"), st.session_state.get("source", ""))


def _adopt_preview(df, source="", **kwargs):
    from modules.dataset import prepare_import
    ds = prepare_import(df, source=source)
    st.session_state["df"] = ds.df
    st.session_state["source"] = ds.source
    return ds


def import_preview():
    from modules.views.import_data import render_import_page
    from modules.ui.navigation import navigate
    from modules import data_loader
    weather("import")
    with st.container(key="workbench_content"), patch.object(data_loader, "fetch_open_meteo", lambda *a, **kw: forecast_frame()), \
         patch.object(data_loader, "fetch_open_meteo_air_quality", lambda *a, **kw: (None, "离线预览不连接远程服务")):
        render_import_page(lambda name, fn, *args, **kwargs: fn(*args, **kwargs), _adopt_preview, navigate,
                           lambda: st.dataframe(st.session_state.get("df"), width="stretch"))


def reader_preview():
    from modules.chart_reader import render_chart_reader_tab
    from modules.ai_narrative import build_report_meta
    from modules.ai_report_model import input_fingerprint
    if not st.session_state.get("_preview_ai_loaded"):
        fixture = image_and_report()
        if fixture:
            inputs, frozen, model = fixture
            st.session_state.update(chart_reader_images=inputs, chart_reader_report_images=frozen,
                chart_reader_result=model, chart_reader_text=model["raw_response"],
                chart_reader_meta=build_report_meta("人工示例解读 · 未调用 AI 服务"),
                chart_reader_input_fingerprint=input_fingerprint(inputs), _preview_ai_loaded=True)
    weather("chart-reader")
    with st.container(key="workbench_content"), patch("modules.ai_narrative.resolve_vision_config", lambda: None):
        render_chart_reader_tab()
        if st.button("切换到生成前布局" if st.session_state.get("chart_reader_text") else "恢复示例结果", key="_preview_ai_toggle"):
            if st.session_state.get("chart_reader_text"):
                st.session_state["_preview_saved_ai_text"] = st.session_state.pop("chart_reader_text")
            else:
                st.session_state["chart_reader_text"] = st.session_state.get("_preview_saved_ai_text", "")
            st.rerun()


def report_preview():
    from modules.reporter import render_export_tab
    from modules.ui.data_context import render_data_context
    weather("report")
    with st.container(key="workbench_content"):
        render_export_tab(st.session_state.get("df"), [], 0, st.session_state.get("source", ""))


def decoder_preview():
    weather("decoder")
    with st.container(key="workbench_content"):
        from modules.codec import render_codec_tab
        render_codec_tab()


render_brand(preview=True)
page, route = render_navigation([import_preview, analysis, forecast, reader_preview, report_preview, decoder_preview])
page.run()
with st.expander("本地预览检查项", expanded=False):
    st.toggle("深色主题", key="_preview_dark", value=st.session_state.dark_mode,
              on_change=lambda: st.session_state.update(dark_mode=st.session_state["_preview_dark"]))
    st.selectbox("天气样例", ["六城正常", "无关注城市", "单城", "两城", "部分缺失", "未知天气码", "夜间", "上次成功数据"], key="_preview_weather_sample")
    st.selectbox("地标预览城市", ["当前六城", "全部 41 城", "北方与东北", "华东", "中南与港澳", "西部"], key="_preview_landmark_group")
    st.toggle("模拟预报加载失败", key="_preview_forecast_failure")
    st.toggle("模拟预报延迟（3 秒）", key="_preview_forecast_delay")
    st.caption("这里使用固定合成数据和人工示例解读，未连接账号、天气服务或 AI 服务。")
    st.caption(f"页面进入标识 {st.session_state.get('_workbench_entry', '')[:8]} · 普通控件重绘不应改变")
