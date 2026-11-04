"""Calendar-day and forward hourly forecast windows in Beijing time."""
from __future__ import annotations

import pandas as pd


def beijing_time(value):
    """Return a naive Beijing timestamp; naive input already denotes Beijing time."""
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        raise ValueError("预报请求时间无效")
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert("Asia/Shanghai").tz_localize(None)
    return stamp


def beijing_times(values):
    """Open-Meteo's naive times are local; timezone-aware times are converted."""
    timestamps = pd.to_datetime(values, errors="coerce")
    if isinstance(timestamps.dtype, pd.DatetimeTZDtype):
        timestamps = timestamps.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    return timestamps


def calendar_forecast(frame, as_of, days):
    """Keep the selected natural days starting on the request's Beijing date."""
    if frame is None or frame.empty or "timestamp" not in frame:
        raise ValueError("预报返回为空，原有结果已保留")
    start = beijing_time(as_of).normalize()
    times = beijing_times(frame["timestamp"])
    selected = frame.loc[(times >= start) & (times < start + pd.Timedelta(days=days))].copy()
    selected["timestamp"] = times.loc[selected.index]
    return selected


def future_hourly_forecast(frame, as_of, hours=72):
    """Select hourly valid times in [request time, request time + hours).

    The API reports instantaneous values on whole hours and precipitation for
    the preceding hour.  Coverage counts distinct expected whole-hour stamps.
    """
    request_time = beijing_time(as_of)
    first = request_time.ceil("h")
    end = request_time + pd.Timedelta(hours=hours)
    expected = pd.date_range(first, periods=hours, freq="h")
    times = beijing_times(frame["timestamp"])
    selected = frame.loc[(times >= request_time) & (times < end)].copy()
    selected["timestamp"] = times.loc[selected.index]
    selected_times = beijing_times(selected["timestamp"])
    complete = pd.DatetimeIndex(selected_times).equals(expected)
    return selected, {"requested_at": request_time, "first": first,
                      "last": expected[-1], "expected": hours,
                      "present": int(selected_times.nunique()), "complete": complete}
