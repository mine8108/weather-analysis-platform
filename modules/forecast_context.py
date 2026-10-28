"""One request identity and one successful result identity for every forecast view."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pandas as pd
import numpy as np

from modules.weather_view_model import city_id


def make_intent(city, days=7, *, model="gfs_seamless", source_route="forecast", source_filters=None):
    identity = city_id(city)
    if type(days) is not int or not 1 <= days <= 16:
        raise ValueError("预报时段须为 1 至 16 天")
    if model not in {"gfs_seamless", None}:
        raise ValueError("未知预报模式")
    return {"request_id": uuid4().hex, "city_id": identity,
            "city": {"id": identity, "name": str(city.get("zh") or city.get("name") or "选定地点")[:40],
                     "lat": float(city["lat"]), "lon": float(city["lon"])},
            "days": days, "model": model, "source_route": source_route,
            "source_filters": dict(source_filters or {}),
            "requested_at": datetime.now(timezone.utc).isoformat()}


def queue_intent(state, intent):
    if state.get("_forecast_consumed") == intent["request_id"]:
        return False
    state["_forecast_intent"] = intent
    state["_forecast_status"] = {"state": "queued", "request_id": intent["request_id"], "city": intent["city"]}


def consume_intent(state):
    intent = state.pop("_forecast_intent", None)
    if not intent or state.get("_forecast_consumed") == intent["request_id"]:
        return None
    state["_forecast_consumed"] = intent["request_id"]
    state["_forecast_status"] = {"state": "loading", "request_id": intent["request_id"], "city": intent["city"]}
    return intent


def commit_success(state, intent, frame):
    from utils import df_fingerprint
    current = state.get("_forecast_consumed")
    if current and current != intent["request_id"]:
        raise ValueError("已有更新的请求，忽略过期结果")
    if frame is None or frame.empty or "timestamp" not in frame:
        raise ValueError("预报返回为空，原有结果已保留")
    timestamps = pd.to_datetime(frame["timestamp"], errors="coerce")
    if timestamps.isna().any() or not timestamps.is_monotonic_increasing or timestamps.duplicated().any():
        raise ValueError("预报时间轴无效，原有结果已保留")
    if not any(c in frame and np.isfinite(pd.to_numeric(frame[c], errors="coerce")).any()
               for c in ("temperature", "precipitation", "wind_speed")):
        raise ValueError("预报缺少有效要素，原有结果已保留")
    context = {**intent, "coverage_start": timestamps.min().isoformat(), "coverage_end": timestamps.max().isoformat(),
               "data_fingerprint": df_fingerprint(frame), "received_at": datetime.now(timezone.utc).isoformat(),
               "source": "Open-Meteo / GFS" if intent["model"] else "Open-Meteo / 自动混合",
               "timezone": "Asia/Shanghai",
               "units": {"temperature": "°C", "precipitation": "mm", "wind_speed": "m/s"},
               "provider_metadata": dict(frame.attrs.get("weather_metadata") or {}), "data": frame}
    previous = state.get("fc_result_context")
    if previous:
        state["_forecast_previous_result"] = previous
        history = list(state.get("_forecast_history", []))
        history.append({k: v for k, v in previous.items() if k != "data"})
        state["_forecast_history"] = history[-5:]
    state.update(fc_result_context=context, fc_df=frame, nwp_forecast_for_analysis=frame,
                 fc_lat=intent["city"]["lat"], fc_lon=intent["city"]["lon"], fc_analysis=None,
                 life_indices=None, nwp_air_quality_for_analysis=None)
    state["_forecast_status"] = {"state": "success", "request_id": intent["request_id"], "city": intent["city"]}
    return context


def fail_request(state, intent, message):
    # Never change the successful city, dataframe or derived values on failure.
    current = state.get("_forecast_consumed")
    if current and current != intent["request_id"]:
        return
    state["_forecast_status"] = {"state": "failed", "request_id": intent["request_id"],
                                 "city": intent["city"], "message": str(message)[:300]}


def restore_previous(state):
    previous = state.get("_forecast_previous_result")
    if not previous:
        return False
    state["_forecast_previous_result"] = state.get("fc_result_context")
    state.update(fc_result_context=previous, fc_df=previous["data"], nwp_forecast_for_analysis=previous["data"],
                 fc_lat=previous["city"]["lat"], fc_lon=previous["city"]["lon"], fc_analysis=None,
                 life_indices=None, nwp_air_quality_for_analysis=None)
    state["_forecast_status"] = {"state": "success", "request_id": previous["request_id"], "city": previous["city"]}
    return True
