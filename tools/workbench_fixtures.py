"""Offline, visibly labelled fixtures. Never imported by the production entry point."""
import json
from pathlib import Path

import numpy as np
import pandas as pd


def forecast_frame(lat=39.9, lon=116.4, days=7, model="gfs_seamless", **kwargs):
    h = np.arange(24 * days)
    temp = 22 + 4*np.sin(2*np.pi*(h-8)/24) + 1.5*np.sin(h/18)
    rain = np.where((h > 42) & (h < 66), np.maximum(0, 1.1*np.sin((h-42)/7)), 0)
    frame = pd.DataFrame({"timestamp": pd.date_range("2026-10-26", periods=len(h), freq="h"),
        "temperature": temp, "apparent_temperature": temp-1.2, "humidity": 65-12*np.sin(h/5),
        "wind_speed": 2.8+1.3*np.sin(h/7), "wind_direction": (190+70*np.sin(h/12)) % 360,
        "precipitation": rain, "precipitation_probability": np.where(rain > 0, 65., 10.),
        "weather_code": np.where(rain > 0, 61, 2), "station_id": "SYNTHETIC",
        "pressure": 1014+5*np.cos(h/14), "visibility": 12., "cloud_cover": 5.,
        "pm25": 18+7*np.sin(h/15), "pm10": 32+9*np.sin(h/15), "so2": 8., "nox": 14.})
    return frame, None


def air_quality(lat, lon, days=7):
    frame, _ = forecast_frame(lat, lon, days)
    return pd.DataFrame({"timestamp": frame["timestamp"], "aqi": 42+12*np.sin(np.arange(len(frame))/10),
                         "level": "优", "primary": "PM2.5"}), None, None


def current_weather(lat, lon, model="gfs_seamless"):
    return {"temperature": 24., "apparent_temperature": 23., "humidity": 42., "wind_speed": 3.2,
            "weather_code": 2, "is_day": 1, "valid_at": "2026-10-26T14:00"}


def image_and_report():
    from modules.chart_reader import process_image
    from modules.ai_report_model import SECTION_TITLES, decode_report, freeze_images
    image = Path(__file__).resolve().parents[1] / "docs/design/workbench-20261026/evidence/fixtures/synthetic-pressure.png"
    if not image.exists():
        return None
    inputs = [process_image(image.read_bytes(), "合成气压场_仅供界面测试.png")]
    frozen = freeze_images(inputs)
    raw = json.dumps({"schema_version": 1,
        "findings": [
            {"id": "F1", "text": "图左侧有 L 标记，周围可见闭合等值线。", "kind": "visible", "evidence_ids": ["E1"], "limitation_ids": ["L1"]},
            {"id": "F2", "text": "按图示气压单位，可将左侧区域描述为低值中心；真实天气影响仍需时次与区域信息。", "kind": "conditional", "evidence_ids": ["E1", "E2"], "limitation_ids": ["L1"]}],
        "evidence": [
            {"id": "E1", "image_id": "img_1", "location": "图左侧中部", "feature": "蓝色 L 标记与周围多圈闭合等值线。"},
            {"id": "E2", "image_id": "img_1", "location": "图上方标题", "feature": "标题标注合成气压场，单位为 hPa。"}],
        "limitations": [{"id": "L1", "missing": "图中未提供真实区域和有效时间。", "impact": "单图不能判断系统移动，也不能据此作出实际天气预报。", "next_input": "同一区域多时次资料及图像说明。"}],
        "sections": [{"title": title, "body": body} for title, body in zip(SECTION_TITLES, [
            "一张合成气压场图片，仅供布局与引用交互测试。", "标题显示气压单位 hPa，坐标为示例坐标。",
            "左侧闭合低值区与右侧高值区相邻。", "仅描述图面标注，不将合成数值作为实况。",
            "单图无法判断演变。", "这是一份人工编写的示例解读，未调用 AI 服务，不可用于天气决策。"])]}, ensure_ascii=False)
    return inputs, frozen, decode_report(raw, frozen)
