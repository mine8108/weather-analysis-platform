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
                 nc_path: Optional[str] = None, nc_bytes: Optional[bytes] = None,
                 df=None):
        self.prefer = (prefer or "csv").lower()
        self.csv_path = csv_path
        self.nc_path = nc_path
        self.nc_bytes = nc_bytes  # 网页端上传的 NetCDF 原始字节
        self.df = df  # 网页端上传的 DataFrame，优先于 csv_path

    def available(self) -> bool:
        return (self.df is not None or self.nc_bytes is not None
                or bool(self._resolve_csv_path()) or bool(self._resolve_nc_path()))

    def _resolve_csv_path(self) -> Optional[str]:
        if self.csv_path:
            return self.csv_path
        try:
            import streamlit as st
            return st.secrets.get("CLIMATE_LOCAL_CSV") or None
        except Exception:
            return None

    def _resolve_nc_path(self) -> Optional[str]:
        if self.nc_path:
            return self.nc_path
        try:
            import streamlit as st
            return st.secrets.get("CLIMATE_LOCAL_NC") or None
        except Exception:
            return None

    def _should_use_nc(self) -> bool:
        """有上传 nc 字节，或偏好 nc，或无 CSV 源但有 nc 源。"""
        if self.nc_bytes is not None:
            return True
        has_csv = self.df is not None or bool(self._resolve_csv_path())
        has_nc = bool(self._resolve_nc_path())
        if not has_nc:
            return False
        if self.prefer in ("nc", "netcdf"):
            return True
        return not has_csv

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
        # NetCDF 优先分支（上传字节 / 偏好 nc / 仅有 nc 源）
        if self._should_use_nc():
            try:
                return self._fetch_from_nc(lat, lon, month)
            except ClimateFileError:
                raise
            except _NcDependencyMissing as e:
                if _has_streamlit():
                    import streamlit as st
                    st.warning(str(e))
                # 依赖缺失时若还有 CSV 源，继续往下走 CSV；否则返回空
                if self.nc_bytes is not None or not (
                        self.df is not None or self._resolve_csv_path()):
                    return None, None
            except Exception as e:
                if _has_streamlit():
                    import streamlit as st
                    st.warning(f"NetCDF 气候态读取失败: {e}")
                if self.nc_bytes is not None:
                    return None, None
        # CSV / DataFrame 分支
        try:
            table = self._load_table()
        except ClimateFileError:
            raise
        except Exception as e:
            if _has_streamlit():
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
            if _has_streamlit():
                import streamlit as st
                st.warning(f"本地气候态匹配失败: {e}")
            return None, None

    def _fetch_from_nc(self, lat, lon, month):
        """打开 NetCDF（路径或上传字节），自适应探测变量与维度后取点。"""
        ds = _open_nc_dataset(nc_bytes=self.nc_bytes, nc_path=self._resolve_nc_path())
        try:
            return _read_nc_climate(ds, lat, lon, month)
        finally:
            try:
                ds.close()
            except Exception:
                pass


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
# NetCDF 自适应读取（M2）—— 无固定 schema，靠候选名+维度探测
# ---------------------------------------------------------------------------
class _NcDependencyMissing(Exception):
    """xarray/引擎未安装。触发温和降级而非崩溃。"""


# 变量候选（小写；精确优先，其后按“变量名含候选且候选长度>=3”宽松匹配）
# 顺序敏感：t_max/t_min 先于 t_mean 认领，避免裸词误抢
_NC_VARS = [
    ("t_max", ["tmax", "t2m_max", "tasmax", "tmp_max", "temperature_max",
               "tx", "mx2t", "air_temperature_max"]),
    ("t_min", ["tmin", "t2m_min", "tasmin", "tmp_min", "temperature_min",
               "tn", "mn2t", "air_temperature_min"]),
    ("t_mean", ["t2m", "t2", "tas", "tmean", "t_mean", "tmp", "temp",
                "temperature", "air_temperature", "air", "tavg"]),
    ("precip", ["tp", "pr", "precip", "precipitation", "prcp", "rain",
                "total_precipitation", "pre", "rr", "ppt"]),
    ("wind_max_mean", ["wind_speed_max", "fg10", "wind_gust", "gust", "si10",
                       "wind_speed", "sfcwind", "wind", "w10", "fx", "ws"]),
]
_NC_LAT = ["lat", "latitude", "y", "nav_lat", "xlat", "g0_lat_1"]
_NC_LON = ["lon", "longitude", "x", "nav_lon", "xlong", "g0_lon_2"]
_NC_TIME = ["time", "month", "valid_time", "t", "date"]


def _open_nc_dataset(nc_bytes=None, nc_path=None):
    """打开 NetCDF。统一策略：先物化为 ASCII 临时文件再读。

    原因（Windows 实测）：
    - netCDF4 C 库不支持内存流（BytesIO），且对含非 ASCII 字符的路径
      （如中文/OneDrive 目录）会报 PermissionError/Errno 13；
    - 落盘到系统临时目录（ASCII 路径）后两个问题同时消除。
    """
    try:
        import xarray as xr
    except Exception:
        raise _NcDependencyMissing(
            "NetCDF 支持需要 xarray+netCDF4/h5netcdf，未安装。"
            "请 pip install xarray netCDF4，或改用 CSV 气候态文件。")

    import shutil
    import tempfile

    if nc_bytes is None and not (nc_path and os.path.exists(nc_path)):
        raise ClimateFileError("未找到 NetCDF 源（nc_bytes/nc_path 均为空）")

    def _is_ascii(s: str) -> bool:
        try:
            s.encode("ascii")
            return True
        except UnicodeEncodeError:
            return False

    tmp_file = None
    open_path = nc_path
    try:
        if nc_bytes is not None:
            fd, tmp_file = tempfile.mkstemp(suffix=".nc", prefix="wb_climate_")
            with os.fdopen(fd, "wb") as f:
                f.write(nc_bytes)
            open_path = tmp_file
        elif not _is_ascii(nc_path):
            fd, tmp_file = tempfile.mkstemp(suffix=".nc", prefix="wb_climate_")
            os.close(fd)
            shutil.copyfile(nc_path, tmp_file)
            open_path = tmp_file

        last_err = None
        for eng in ("netcdf4", "h5netcdf", "scipy", None):
            try:
                ds = (xr.open_dataset(open_path, engine=eng) if eng
                      else xr.open_dataset(open_path))
                # 立即载入内存并关闭文件句柄，便于清理临时文件
                ds = ds.load()
                ds.close()
                return ds
            except (ImportError, ModuleNotFoundError) as e:
                last_err = e
                continue
            except Exception as e:
                last_err = e
                continue
        raise ClimateFileError(f"NetCDF 无法解析（netcdf4/h5netcdf/scipy 引擎均失败）: {last_err}")
    finally:
        if tmp_file:
            try:
                os.remove(tmp_file)
            except OSError:
                pass


def _pick_name(candidates, available, used):
    """在 available 名字里为一组候选选一个：精确匹配优先，其次宽松包含。"""
    avail_lower = {str(a).lower(): a for a in available}
    for cand in candidates:
        if cand in avail_lower and avail_lower[cand] not in used:
            return avail_lower[cand]
    for cand in candidates:
        if len(cand) < 3:
            continue
        for al, orig in avail_lower.items():
            if cand in al and orig not in used:
                return orig
    return None


def _find_coord(da, candidates):
    names = list(da.dims) + [c for c in da.coords]
    lower = {str(n).lower(): n for n in names}
    for cand in candidates:
        if cand in lower:
            return lower[cand]
    for cand in candidates:
        for ln, orig in lower.items():
            if cand in ln:
                return orig
    return None


def _to_celsius_if_needed(da):
    """开尔文→摄氏：优先 units 属性，其次数值启发式（中位数>150 判 K）。"""
    units = str(da.attrs.get("units", "")).lower()
    if units in ("k", "kelvin"):
        return da - 273.15
    if units in ("degc", "c", "celsius", "deg_c", "℃", "degrees_celsius"):
        return da
    try:
        import numpy as np
        med = float(np.nanmedian(da.values))
        if med > 150:
            return da - 273.15
    except Exception:
        pass
    return da


def _scale_precip_if_needed(da):
    """降水单位 m→mm：仅当 units 明确为米时换算。"""
    units = str(da.attrs.get("units", "")).lower()
    if units in ("m", "metre", "meter", "metres", "meters"):
        return da * 1000.0
    return da


def _read_nc_climate(ds, lat, lon, month):
    import numpy as np
    import pandas as pd

    var_map = {}
    used = []
    for target, cands in _NC_VARS:
        name = _pick_name(cands, list(ds.data_vars), used)
        if name is not None:
            var_map[target] = name
            used.append(name)

    if "t_mean" not in var_map and "t_max" not in var_map and "precip" not in var_map:
        raise ClimateFileError(
            f"NetCDF 中未识别到气温/降水变量。文件变量: {list(ds.data_vars)}。"
            "请确认包含气温或降水，或改用 CSV。")

    # 经度约定对齐（0-360 vs -180-180）
    q_lon = lon
    any_var = ds[next(iter(var_map.values()))]
    lonname = _find_coord(any_var, _NC_LON)
    if lonname is not None:
        try:
            lon_vals = ds[lonname].values
            if float(np.nanmax(lon_vals)) > 180 and q_lon < 0:
                q_lon = q_lon + 360.0
        except Exception:
            pass

    def _point_series(varname):
        da = ds[varname]
        la = _find_coord(da, _NC_LAT)
        lo = _find_coord(da, _NC_LON)
        sel = {}
        if la:
            sel[la] = lat
        if lo:
            sel[lo] = q_lon
        if sel:
            try:
                da = da.sel(**sel, method="nearest")
            except Exception:
                da = da.sel(**sel)
        # 压掉残余非时间维
        tname = _find_coord(da, _NC_TIME)
        for d in list(da.dims):
            if d != tname:
                try:
                    da = da.isel({d: 0})
                except Exception:
                    pass
        return da, tname

    def _month_values(varname):
        """返回 (该月数值序列 ndarray, 年份序列 or None)。"""
        da, tname = _point_series(varname)
        vals = np.atleast_1d(np.asarray(da.values, dtype="float64"))
        if tname is None:
            return vals, None
        try:
            coord = ds[tname].values
        except Exception:
            coord = None
        if coord is None or len(coord) != len(vals):
            return vals, None
        # 时间坐标判定顺序：先查整数 1-12 月份维（pd.to_datetime 会把整数
        # 误当纳秒时间戳解析成 1970 年，必须先拦截），再尝试 datetime
        arr = np.atleast_1d(np.asarray(coord))
        years = None
        if np.issubdtype(arr.dtype, np.number) and 1 <= arr.min() and arr.max() <= 12:
            months = arr.astype(int)
        else:
            try:
                idx = pd.to_datetime(coord)
                months = idx.month.values
                years = idx.year.values
            except Exception:
                return vals, None
        mask = months == month
        if not mask.any():
            return np.array([]), None
        return vals[mask], (years[mask] if years is not None else None)

    def _mean_of(target, kelvin=False, precip=False):
        name = var_map.get(target)
        if name is None:
            return None
        da_full = ds[name]
        if kelvin:
            da_full = _to_celsius_if_needed(da_full)
        if precip:
            da_full = _scale_precip_if_needed(da_full)
        ds[name] = da_full  # 就地替换便于下游 _month_values 复用
        v, _ = _month_values(name)
        v = v[~np.isnan(v)] if v.size else v
        return float(np.mean(v)) if v.size else None

    stats = ClimateStats(
        lat=float(lat), lon=float(lon), month=int(month),
        t_mean=_mean_of("t_mean", kelvin=True),
        t_max=_mean_of("t_max", kelvin=True),
        t_min=_mean_of("t_min", kelvin=True),
        precip=_mean_of("precip", precip=True),
        wind_max_mean=_mean_of("wind_max_mean"),
        base_period=str(ds.attrs.get("base_period",
                        ds.attrs.get("title", "NetCDF 文件"))) or "NetCDF 文件",
        source="localfile-nc",
        raw={"variables": var_map},
    )

    def _extreme(target, kind):
        name = var_map.get(target)
        if name is None:
            return {"value": None, "year": None}
        v, years = _month_values(name)
        if v.size == 0:
            return {"value": None, "year": None}
        m = ~np.isnan(v)
        v2 = v[m]
        if v2.size == 0:
            return {"value": None, "year": None}
        i = int(np.argmax(v2) if kind == "max" else np.argmin(v2))
        yr = None
        if years is not None:
            yv = years[m]
            if i < len(yv):
                yr = int(yv[i])
        return {"value": float(v2[i]), "year": yr}

    ext = ClimateExtreme(
        t_max_record=_extreme("t_max", "max"),
        t_min_record=_extreme("t_min", "min"),
        precip_max_record=_extreme("precip", "max"),
        wind_max_record=_extreme("wind_max_mean", "max"),
    )
    return stats, ext


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
