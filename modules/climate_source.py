"""
气候态数据源抽象层（地基层 M1）

统一接口：所有后端实现 ClimateSource，对外只暴露
fetch_climate_normal(lat, lon, month) -> (ClimateStats | None, ClimateExtreme | None)。

M1 交付：LocalFileSource（本地 CSV，零依赖）+ OpenMeteoSource（修复后的兜底，近似）。
M3 将在此追加 Era5NoaaSource / NoaaSource（API 权威源），工厂已预留降级链。
"""
from __future__ import annotations

import calendar
import math
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# 标准输出 schema：所有后端在返回前归一化到这里，应用层只认这套字段
# ---------------------------------------------------------------------------
@dataclass
class ClimateStats:
    """气候态统计 —— 所有后端的统一输出格式"""
    station_id: str = ""
    lat: float = 0.0
    lon: float = 0.0
    month: int = 1
    t_mean: Optional[float] = None
    t_max: Optional[float] = None
    t_min: Optional[float] = None
    precip: Optional[float] = None
    wind_max_mean: Optional[float] = None
    base_period: str = ""
    source: str = ""
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """兼容现有展示/距平代码的中文键（climate_ref.py render 与 compute_anomalies）"""
        return {
            "月均气温": self.t_mean,
            "月均最高气温": self.t_max,
            "月均最低气温": self.t_min,
            "月总降水量": self.precip,
            "最大风速均值": self.wind_max_mean,
            "数据年份范围": self.base_period,
        }


@dataclass
class ClimateExtreme:
    """历史同期极值（value/year 任一可空）"""
    t_max_record: dict = field(default_factory=lambda: {"value": None, "year": None})
    t_min_record: dict = field(default_factory=lambda: {"value": None, "year": None})
    precip_max_record: dict = field(default_factory=lambda: {"value": None, "year": None})
    wind_max_record: dict = field(default_factory=lambda: {"value": None, "year": None})

    def to_dict(self) -> dict:
        return {
            "历史最高气温": self.t_max_record,
            "历史最低气温": self.t_min_record,
            "历史最大日降水": self.precip_max_record,
            "历史最大风速": self.wind_max_record,
        }


class ClimateSourceUnavailable(Exception):
    """后端配置存在但运行不可用（如密钥缺失）。UI 捕获后温和提示并降级。"""


class ClimateFileError(Exception):
    """本地气候态文件格式错误（缺失必填列等）。"""


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# 抽象基类
# ---------------------------------------------------------------------------
class ClimateSource(ABC):
    name: str = "base"

    @abstractmethod
    def fetch_climate_normal(self, lat: float, lon: float, month: int
                             ) -> tuple[Optional[ClimateStats], Optional[ClimateExtreme]]:
        """成功返回 (stats, extreme)；无数据返回 (None, None)。
        禁止抛出未捕获异常——缺失/错误应转为 (None, None) 并由调用方提示。"""
        ...

    def available(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# 方案1：本地文件（M1 仅实现 CSV；NetCDF 在 M2 追加）
# ---------------------------------------------------------------------------
_WIDE_REQUIRED = ["lat", "lon", "month", "t_mean", "t_max", "t_min", "precip", "wind_max_mean"]
_WIDE_OPTIONAL_EXTREME = {
    "t_max_val": ("t_max_record", "value"),
    "t_max_year": ("t_max_record", "year"),
    "t_min_val": ("t_min_record", "value"),
    "t_min_year": ("t_min_record", "year"),
    "precip_max": ("precip_max_record", "value"),
    "precip_max_year": ("precip_max_record", "year"),
    "wind_max": ("wind_max_record", "value"),
    "wind_max_year": ("wind_max_record", "year"),
}
_LONG_TIME_COLS = ["t_mean", "t_max", "t_min", "precip", "wind_speed_max"]


class LocalFileSource(ClimateSource):
    name = "localfile"

    def __init__(self, prefer: str = "csv", csv_path: Optional[str] = None,
                 nc_path: Optional[str] = None, df: Optional["__pd.DataFrame"] = None):
        self.prefer = prefer
        self.csv_path = csv_path
        self.nc_path = nc_path
        self.df = df  # 网页端上传的 DataFrame，优先于 csv_path

    def available(self) -> bool:
        return self.df is not None or bool(self.csv_path)

    def _resolve_csv_path(self) -> Optional[str]:
        if self.csv_path:
            return self.csv_path
        try:
            import streamlit as st
            return st.secrets.get("CLIMATE_LOCAL_CSV") or None
        except Exception:
            return None

    def _load_table(self):
        """返回宽表 DataFrame，带 session_state 缓存（仅针对路径模式）。"""
        if self.df is not None:
            return self._to_wide(self.df)
        path = self._resolve_csv_path()
        if not path or not os.path.exists(path):
            return None
        cache = st.session_state.get("_climate_csv_cache") if _has_streamlit() else None
        if cache and cache[0] == path and cache[1] == os.path.getmtime(path):
            return cache[2]
        df = _read_csv_robust(path)
        wide = self._to_wide(df)
        if _has_streamlit():
            st.session_state["_climate_csv_cache"] = (path, os.path.getmtime(path), wide)
        return wide

    def _to_wide(self, df):
        """宽表直接校验；长表（含 timestamp）按站点+月聚合为宽表。"""
        import pandas as pd
        cols = list(df.columns)
        if all(c in cols for c in _WIDE_REQUIRED):
            return df
        # 长表兼容：timestamp + 时间序列列
        if "timestamp" in cols and set(_LONG_TIME_COLS).issubset(cols):
            d = df.copy()
            d["timestamp"] = pd.to_datetime(d["timestamp"], errors="coerce")
            d["month"] = d["timestamp"].dt.month
            d["wind_max_mean"] = d.get("wind_speed_max", d.get("wind_max_mean"))
            grp = d.groupby(["station_id", "lat", "lon", "month"], as_index=False).agg(
                t_mean=("t_mean", "mean"),
                t_max=("t_max", "mean"),
                t_min=("t_min", "mean"),
                precip=("precip", "sum"),
                wind_max_mean=("wind_max_mean", "mean"),
            )
            return grp
        missing = [c for c in _WIDE_REQUIRED if c not in cols]
        raise ClimateFileError(
            f"气候态 CSV 缺失必填列：{missing}。必填：{_WIDE_REQUIRED}；"
            f"或提供含 timestamp 的长表（列含 {_LONG_TIME_COLS}）。"
        )

    def _lookup(self, lat, lon, month, table):
        sub = table[table["month"] == month]
        if sub.empty:
            return None, None
        # 1) 坐标精确匹配（2 位小数）
        glat, glon = round(lat, 2), round(lon, 2)
        exact = sub[(sub["lat"].round(2) == glat) & (sub["lon"].round(2) == glon)]
        if not exact.empty:
            return self._row_to_stats(exact.iloc[0], month)
        # 2) 最近站 haversine
        max_r = 50.0
        try:
            import streamlit as st
            max_r = float(st.secrets.get("CLIMATE_MAX_RADIUS", 50))
        except Exception:
            pass
        best, best_d = None, float("inf")
        for _, row in sub.iterrows():
            try:
                d = _haversine_km(lat, lon, float(row["lat"]), float(row["lon"]))
            except (ValueError, TypeError):
                continue
            if d < best_d:
                best_d, best = d, row
        if best is None or best_d > max_r:
            return None, None
        return self._row_to_stats(best, month, dist_km=best_d)

    def _row_to_stats(self, row, month, dist_km=None):
        def _f(v):
            try:
                return None if pd_isna(v) else float(v)
            except (ValueError, TypeError):
                return None
        stats = ClimateStats(
            station_id=str(row.get("station_id", "") or ""),
            lat=float(row["lat"]), lon=float(row["lon"]), month=int(month),
            t_mean=_f(row.get("t_mean")), t_max=_f(row.get("t_max")),
            t_min=_f(row.get("t_min")), precip=_f(row.get("precip")),
            wind_max_mean=_f(row.get("wind_max_mean")),
            base_period=str(row.get("base_period", "本地文件") or "本地文件"),
            source="localfile",
        )
        ext = ClimateExtreme()
        for col, (target, field_name) in _WIDE_OPTIONAL_EXTREME.items():
            if col in row and not pd_isna(row[col]):
                val = int(row[col]) if field_name == "year" else _f(row[col])
                ext.__dict__[target][field_name] = val
        return stats, ext

    def fetch_climate_normal(self, lat, lon, month):
        try:
            table = self._load_table()
        except ClimateFileError:
            raise
        except Exception as e:
            import streamlit as st
            st.warning(f"本地气候态文件读取失败: {e}")
            return None, None
        if table is None:
            return None, None
        try:
            return self._lookup(lat, lon, month, table)
        except ClimateFileError:
            raise
        except Exception as e:
            import streamlit as st
            st.warning(f"本地气候态匹配失败: {e}")
            return None, None


def _has_streamlit() -> bool:
    try:
        import streamlit  # noqa: F401
        return True
    except Exception:
        return False


def _read_csv_robust(path: str):
    import pandas as pd
    last_err = None
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return pd.read_csv(path, encoding=enc)
        except (UnicodeDecodeError, LookupError) as e:
            last_err = e
            continue
    raise ClimateFileError(f"CSV 编码无法识别（已尝试 utf-8-sig/utf-8/gbk）: {last_err}")


def pd_isna(v) -> bool:
    try:
        import pandas as pd
        return bool(pd.isna(v))
    except Exception:
        return v is None or (isinstance(v, float) and math.isnan(v))


# ---------------------------------------------------------------------------
# 兜底：Open-Meteo（修复原 28 天 bug，标注为近似）
# ---------------------------------------------------------------------------
class OpenMeteoSource(ClimateSource):
    name = "openmeteo"

    def fetch_climate_normal(self, lat, lon, month):
        import datetime
        import pandas as pd
        import requests

        current_year = datetime.datetime.now().year
        years_range = range(current_year - 5, current_year)
        all_data = []
        for year in years_range:
            last_day = calendar.monthrange(year, month)[1]
            start = f"{year}-{month:02d}-01"
            end = f"{year}-{month:02d}-{last_day:02d}"  # 修复：取完整月份
            url = "https://archive-api.open-meteo.com/v1/archive"
            params = {
                "latitude": lat, "longitude": lon,
                "start_date": start, "end_date": end,
                "daily": [
                    "temperature_2m_max", "temperature_2m_min",
                    "temperature_2m_mean", "precipitation_sum",
                    "wind_speed_10m_max",
                ],
                "timezone": "Asia/Shanghai",
            }
            try:
                resp = requests.get(url, params=params, timeout=30)
                data = resp.json()
                if "daily" in data:
                    df = pd.DataFrame(data["daily"])
                    df["year"] = year
                    all_data.append(df)
            except Exception as e:
                import streamlit as st
                st.warning(f"气候态 {year} 年数据获取异常: {e}")
                continue

        if not all_data:
            return None, None

        combined = pd.concat(all_data, ignore_index=True)
        stats = ClimateStats(
            lat=lat, lon=lon, month=month,
            t_mean=_safe_mean(combined["temperature_2m_mean"]),
            t_max=_safe_mean(combined["temperature_2m_max"]),
            t_min=_safe_mean(combined["temperature_2m_min"]),
            precip=_safe_mean(combined["precipitation_sum"]) * 30,
            wind_max_mean=_safe_mean(combined["wind_speed_10m_max"]),
            base_period=f"{years_range[0]}-{years_range[-1]}",
            source="openmeteo",
        )

        def _extreme(col, func):
            s = combined[col].dropna()
            if s.empty:
                return {"value": None, "year": None}
            idx = s.idxmax() if func == "max" else s.idxmin()
            return {"value": float(s.iloc[s.index.get_loc(idx)]),
                    "year": int(combined.loc[idx, "year"])}

        ext = ClimateExtreme(
            t_max_record=_extreme("temperature_2m_max", "max"),
            t_min_record=_extreme("temperature_2m_min", "min"),
            precip_max_record=_extreme("precipitation_sum", "max"),
            wind_max_record=_extreme("wind_speed_10m_max", "max"),
        )
        return stats, ext


def _safe_mean(s):
    try:
        v = s.dropna().mean()
        return None if pd_isna(v) else float(v)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 工厂与后端解析
# ---------------------------------------------------------------------------
def _resolve_backend(explicit: Optional[str] = None) -> str:
    if explicit:
        return explicit.lower()
    try:
        import streamlit as st
        if "climate_backend" in st.session_state:
            return str(st.session_state["climate_backend"]).lower()
        return str(st.secrets.get("CLIMATE_BACKEND", "localfile")).lower()
    except Exception:
        return "localfile"


def get_climate_source(explicit: Optional[str] = None, local_df=None) -> ClimateSource:
    """工厂：localfile 优先；era5/noaa 在 M3 接入，当前降级 Open-Meteo 兜底。"""
    backend = _resolve_backend(explicit)
    if backend == "localfile":
        return LocalFileSource(df=local_df)
    # M3 将在此实例化 Era5NoaaSource / NoaaSource；本期所有未实现后端降级到 Open-Meteo
    return OpenMeteoSource()


def list_available_backends() -> list[str]:
    """M1 可用后端；M3 追加 era5noaa。"""
    return ["localfile", "openmeteo"]
