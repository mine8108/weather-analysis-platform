"""按站点和实际时刻处理观测；缺测不会压缩时间轴。"""
from functools import wraps

import numpy as np
import pandas as pd


def station_frames(df):
    if df is None or df.empty or "timestamp" not in df:
        return
    groups = df.groupby("station_id", dropna=False, sort=False) if "station_id" in df else [(None, df)]
    for station, frame in groups:
        # 缺失站号不能与任何已知站点合并。
        if station is not None and pd.isna(station):
            continue
        frame = frame.copy()
        try:
            frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce", format="mixed")
            frame = frame.dropna(subset=["timestamp"]).sort_values("timestamp")
        except (ValueError, TypeError):
            continue
        if frame.empty or frame["timestamp"].duplicated().any():
            continue
        yield station, frame


def per_station(fn):
    @wraps(fn)
    def detect(df):
        warnings = []
        for station, frame in station_frames(df):
            for warning in fn(frame):
                if station is not None:
                    warning = dict(warning, detail=f"站点 {station}：{warning['detail']}")
                warnings.append(warning)
        return warnings
    return detect


def numeric_series(df, field):
    if field not in df:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    values = pd.to_numeric(df[field], errors="coerce").replace([np.inf, -np.inf], np.nan)
    return pd.Series(values.to_numpy(), index=pd.DatetimeIndex(df["timestamp"]), dtype=float)


def recent(series, hours):
    if series.empty:
        return series
    return series.loc[series.index > series.index.max() - pd.Timedelta(hours=hours)]


def hourly_totals(series, hours):
    """仅对完整逐小时累积值求滚动和；断档、重复和子小时资料不推定小时量。"""
    if series.empty or series.index.has_duplicates:
        return pd.Series(dtype=float)
    deltas = series.index.to_series().diff()
    if ((deltas.dropna() % pd.Timedelta(hours=1)) != pd.Timedelta(0)).any():
        return pd.Series(dtype=float)
    # 不能把 3 个日值当成 3 小时，reindex 保留真实缺口。
    if (series.index.max() - series.index.min()) / pd.Timedelta(hours=1) > 1_000_000:
        return pd.Series(dtype=float)
    grid = pd.date_range(series.index.min(), series.index.max(), freq="h")
    hourly = series.reindex(grid)
    return hourly.rolling(hours, min_periods=hours).sum()
