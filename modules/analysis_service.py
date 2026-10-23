"""UI 与报告共用的观测分析结果，缓存绑定数据、阈值及算法版本。"""
import json

import numpy as np
import pandas as pd

from modules import analyzer, data_quality
from utils import df_fingerprint

ANALYSIS_VERSION = "2026-10-23.1"
DETECTORS = (
    analyzer.check_high_temperature, analyzer.check_cold_wave, analyzer.check_gale,
    analyzer.check_fog, analyzer.check_rainstorm, analyzer.check_frost,
    analyzer.check_thunderstorm, analyzer.check_haze,
)


def analysis_key(df):
    return (ANALYSIS_VERSION, df_fingerprint(df),
            json.dumps(analyzer.current_thresholds(), sort_keys=True, ensure_ascii=False))


def analyze_observations(df):
    result = {"warnings": [], "score": 0.0, "notes": [], "status": "unavailable"}
    if df is None or df.empty:
        result["notes"] = ["没有可分析的观测数据。"]
        return result
    issues = (data_quality.range_check(df) + data_quality.temporal_consistency_check(df)
              + data_quality.completeness_check(df))
    result["score"] = data_quality.compute_quality_score(df, issues)
    result["notes"] = [i["field"] + "：" + i["detail"] for i in issues]
    required = {"temperature", "wind_speed", "precipitation", "visibility", "weather_code"}
    missing = required - set(df.columns)
    if missing:
        result["notes"].append("缺少检测字段：" + "、".join(sorted(missing)) + "；相应事件无法判定。")
    usable = any(pd.to_numeric(df[c], errors="coerce").replace([np.inf, -np.inf], np.nan).notna().any()
                 for c in required & set(df.columns))
    if "timestamp" not in df:
        result["notes"].append("没有有效时间轴，无法进行时段预警判定。")
        return result
    groups = df.groupby("station_id", dropna=False) if "station_id" in df else [(None, df)]
    valid_time = False
    for station, group in groups:
        label = f"站点 {station}" if station is not None else "观测"
        try:
            ts = pd.to_datetime(group["timestamp"], errors="coerce", format="mixed")
            if ts.isna().any() or ts.duplicated().any() or (station is not None and pd.isna(station)):
                result["notes"].append(label + "含无效时间、重复时刻或缺失站号，部分检测跳过。")
            valid_time |= ts.notna().any()
            steps = ts.dropna().sort_values().diff().dropna()
            if len(ts) < 24 or steps.empty or (steps != pd.Timedelta(hours=1)).any():
                result["notes"].append(label + "未覆盖完整连续逐小时资料；窗口不足的检测无法判定。")
        except (ValueError, TypeError):
            result["notes"].append(label + "时间格式不一致，无法判定。")
    for detector in DETECTORS:
        try:
            result["warnings"].extend(detector(df))
        except (ValueError, TypeError, KeyError) as exc:
            result["notes"].append(detector.__name__ + " 数据不满足检测要求：" + str(exc)[:160])
    result["status"] = ("partial" if result["notes"] else "complete") if usable and valid_time else "unavailable"
    return result


def ensure_analysis(state, df):
    key = analysis_key(df)
    if state.get("_warn_fp") != key or not state.get("_analysis_result"):
        result = analyze_observations(df)
        state["_analysis_result"] = result
        state["warnings_list"] = result["warnings"]
        state["quality_score"] = result["score"]
        state["_warn_fp"] = key
        state.pop("report_data", None)
        state.pop("_report_fp", None)
    return state["_analysis_result"]


def invalidate_analysis(state):
    for key in ("_warn_fp", "_analysis_result", "report_data", "_report_fp"):
        state.pop(key, None)
    state["warnings_list"] = []
    state["quality_score"] = 0.0
