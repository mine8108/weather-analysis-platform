"""
NetCDF 探测单一真相源（Single Source of Truth）

背景：ERA5 向导（era5_wizard）与平台消费端（climate_source）曾经各自维护一份
变量别名表、维度候选名、安全打开逻辑，两份手工表会漂移——向导认得、平台认不出，
或反之。本模块把这三样与气候态行生成逻辑收口到一处，两模块只 import，不再各写。

内容：
- DIM_LAT / DIM_LON / DIM_TIME：维度候选名（合并两模块，含常用命名）。
- VAR_SPECS：变量规格列表，字段：
    field : 气候态宽表列名（消费层，如 t_mean）；None 表示向导可识别但不直接落列。
    era5  : ERA5 规范变量名（向导层可选/规范显示，可空）。
    cands : 候选原名（合并向导+平台两份去重）。
    prio  : 匹配优先级（数值小先认领；t_max>t_min>t_mean 防裸词误抢）。
- open_nc_safe(src)：安全打开（bytes/非 ASCII 路径→ASCII 临时副本，多引擎回退）。
- probe_var(name)：单变量名→规格（向导探测 norm 显示）。
- assign_vars(available)：可用变量名→{field: actual}（平台消费，顺序敏感去重）。
- clim_rows_block(fields, months, know_period, base_period)：气候态宽表行代码（两模式共用）。

注意：本模块不 import streamlit / 顶层不 import xarray（xarray 仅在 open_nc_safe 内惰性 import），
保证纯函数可测、生成端无需依赖。
"""
from __future__ import annotations

import os
import shutil
import tempfile


# ---------------------------------------------------------------------------
# 维度候选名（合并 era5_wizard._DIM_* 与 climate_source._NC_*）
# ---------------------------------------------------------------------------
DIM_LAT = ["latitude", "lat", "y", "nav_lat", "xlat", "g0_lat_1"]
DIM_LON = ["longitude", "lon", "x", "nav_lon", "xlong", "g0_lon_2"]
DIM_TIME = ["time", "valid_time", "t", "date", "month"]


# ---------------------------------------------------------------------------
# 变量规格：单一真相源（合并向导 _PROBE_ALIASES 与平台 _NC_VARS）
# ---------------------------------------------------------------------------
# 消费层字段（带 field）按 prio 排序在前，保证 assign_vars 顺序敏感认领。
VAR_SPECS = [
    # —— 消费层：极值/均值（顺序敏感，t_max 先于 t_mean 防误抢）——
    {"field": "t_max", "era5": None, "prio": 0,
     "cands": ["tmax", "t2m_max", "tasmax", "tmp_max", "temperature_max",
               "tx", "mx2t", "air_temperature_max"]},
    {"field": "t_min", "era5": None, "prio": 1,
     "cands": ["tmin", "t2m_min", "tasmin", "tmp_min", "temperature_min",
               "tn", "mn2t", "air_temperature_min"]},
    {"field": "t_mean", "era5": "2m_temperature", "prio": 2,
     "cands": ["2m_temperature", "t2m", "tas", "tmean", "t_mean", "tmp", "temp",
               "temperature", "air_temperature", "air", "tavg", "temperature_2m", "t2"]},
    {"field": "t_mean", "era5": "temperature", "prio": 2,
     "cands": ["temperature", "t"]},
    {"field": "precip", "era5": "total_precipitation", "prio": 3,
     "cands": ["total_precipitation", "tp", "pr", "precip", "precipitation",
               "prcp", "rain", "pre", "rr", "ppt"]},
    {"field": "wind_max_mean", "era5": "10m_wind_speed", "prio": 4,
     "cands": ["10m_wind_speed", "ws10", "windspeed", "sfcwind", "w10"]},
    {"field": "wind_max_mean", "era5": "wind_speed", "prio": 4,
     "cands": ["wind_speed", "wind", "si10", "fg10", "gust", "wind_gust",
               "wind_speed_max", "fx", "ws"]},
    # —— 向导层：可识别但不直接落气候态列的变量（field=None）——
    {"field": None, "era5": "2m_dewpoint_temperature", "prio": 9,
     "cands": ["2m_dewpoint_temperature", "d2m", "dewpoint", "td"]},
    {"field": None, "era5": "2m_relative_humidity", "prio": 9,
     "cands": ["2m_relative_humidity", "r2m", "rh"]},
    {"field": None, "era5": "surface_pressure", "prio": 9,
     "cands": ["surface_pressure", "sp"]},
    {"field": None, "era5": "mean_sea_level_pressure", "prio": 9,
     "cands": ["mean_sea_level_pressure", "msl"]},
    {"field": None, "era5": "10m_u_component_of_wind", "prio": 9,
     "cands": ["10m_u_component_of_wind", "u10"]},
    {"field": None, "era5": "10m_v_component_of_wind", "prio": 9,
     "cands": ["10m_v_component_of_wind", "v10"]},
    {"field": None, "era5": "skin_temperature", "prio": 9,
     "cands": ["skin_temperature", "skt"]},
    {"field": None, "era5": "geopotential", "prio": 9,
     "cands": ["geopotential", "z"]},
    {"field": None, "era5": "relative_humidity", "prio": 9,
     "cands": ["relative_humidity", "r"]},
    {"field": None, "era5": "specific_humidity", "prio": 9,
     "cands": ["specific_humidity", "q"]},
    {"field": None, "era5": "u_component_of_wind", "prio": 9,
     "cands": ["u_component_of_wind", "u"]},
    {"field": None, "era5": "v_component_of_wind", "prio": 9,
     "cands": ["v_component_of_wind", "v"]},
    {"field": None, "era5": "vertical_velocity", "prio": 9,
     "cands": ["vertical_velocity", "w"]},
]

# 向导可选变量（有 era5 名的规格）
WIZARD_VARS = [s["era5"] for s in VAR_SPECS if s["era5"]]

# 向导别名表（派生，等价于旧 _PROBE_ALIASES）
WIZARD_ALIASES = {s["era5"]: s["cands"] for s in VAR_SPECS if s["era5"]}


def aliases_for(expected_vars) -> dict:
    """向导生成脚本时用：仅保留期望变量相关别名（控制生成代码体积）。"""
    return {n: WIZARD_ALIASES[n] for n in expected_vars if n in WIZARD_ALIASES}


def probe_var(name):
    """单变量名 → 规格（精确、大小写不敏感）。向导探测 norm 显示用。"""
    n = str(name).lower()
    for s in VAR_SPECS:
        if any(c.lower() == n for c in s["cands"]):
            return s
    return None


def assign_vars(available):
    """可用变量名 → {field: 实际名}。顺序敏感、去重（优先级高者先认领，
    且同 field 只认领一次）。复刻旧 climate_source._pick_name 的语义。"""
    avail_lower = {str(a).lower(): a for a in available}
    assigned, used = {}, set()
    specs = sorted(VAR_SPECS, key=lambda s: s["prio"])
    # 精确优先
    for s in specs:
        f = s["field"]
        if f is None or f in assigned:
            continue
        for c in s["cands"]:
            if c in avail_lower and avail_lower[c] not in used:
                assigned[f] = avail_lower[c]
                used.add(avail_lower[c])
                break
    # 其次模糊子串（候选长度 >= 3）
    for s in specs:
        f = s["field"]
        if f is None or f in assigned:
            continue
        for c in s["cands"]:
            if len(c) < 3:
                continue
            for al, orig in avail_lower.items():
                if c in al and orig not in used:
                    assigned[f] = orig
                    used.add(orig)
                    break
            if f in assigned:
                break
    return assigned


def open_nc_safe(src):
    """安全打开 NetCDF。src: bytes 或路径。

    返回 (loaded_dataset, resolved_path, size_kb)。
    - bytes / 非 ASCII 路径 → 复制到 ASCII 临时文件（实测规避 Windows 下
      netCDF4 C 库 Errno 13 PermissionError）。
    - 多引擎回退：netcdf4 → h5netcdf → scipy → 默认。
    - 立即载入内存并关闭文件句柄，便于清理临时文件。
    异常：缺依赖 ImportError；缺文件 FileNotFoundError；扩展名/空文件 ValueError；
    解析失败 RuntimeError。
    """
    is_bytes = isinstance(src, (bytes, bytearray))
    tmp_file = None
    path = None
    try:
        if is_bytes:
            fd, tmp_file = tempfile.mkstemp(suffix=".nc", prefix="wb_nc_")
            with os.fdopen(fd, "wb") as f:
                f.write(src)
            path = tmp_file
        else:
            path = str(src)
            if not os.path.exists(path):
                raise FileNotFoundError(path)
            if not path.lower().endswith((".nc", ".nc4", ".cdf")):
                raise ValueError(
                    f"文件扩展名不是 .nc（收到 {os.path.basename(path)}），"
                    "请在 CDS 下载时选择 NetCDF 格式")
            try:
                path.encode("ascii")
            except UnicodeEncodeError:
                fd, tmp_file = tempfile.mkstemp(suffix=".nc", prefix="wb_nc_")
                os.close(fd)
                shutil.copyfile(path, tmp_file)
                path = tmp_file
        if os.path.getsize(path) == 0:
            raise ValueError("文件大小为 0，可能下载未完成（请勿上传 .crdownload 半成品）")

        import xarray as xr
        last_err = None
        for eng in ("netcdf4", "h5netcdf", "scipy", None):
            try:
                ds = (xr.open_dataset(path, engine=eng) if eng
                      else xr.open_dataset(path))
                ds = ds.load()
                ds.close()
                return ds, path, int(os.path.getsize(path) // 1024)
            except (ImportError, ModuleNotFoundError) as e:
                raise
            except Exception as e:  # noqa: BLE001
                last_err = e
                continue
        raise RuntimeError(f"NetCDF 无法解析（netcdf4/h5netcdf/scipy 引擎均失败）: {last_err}")
    finally:
        if tmp_file:
            try:
                os.remove(tmp_file)
            except OSError:
                pass


# 极值列映射：norm → [(值列, 年份列, agg), ...]
# 语义：基于逐月均值网格 ds_month（保留年份维），取该月跨年极值 + 出现年份。
# 对月均值产品输入自然退化为"该月唯一值 + 年份"；无该月数据时保持 None。
_EXTREME_COLS = {
    "2m_temperature": [("t_max_val", "t_max_year", "max"), ("t_min_val", "t_min_year", "min")],
    "temperature": [("t_max_val", "t_max_year", "max"), ("t_min_val", "t_min_year", "min")],
    "total_precipitation": [("precip_max", "precip_max_year", "max")],
    "10m_wind_speed": [("wind_max", "wind_max_year", "max")],
    "wind_speed": [("wind_max", "wind_max_year", "max")],
}


def clim_rows_block(fields, months=None, know_period=False, base_period="", indent=4):
    """生成气候态宽表行填充代码（下载/处理两模式共用，输出 schema 完全一致）。

    fields: [(era5_norm, app_field), ...] 参与统计的变量；
    months: 统计月份列表；
    know_period: 是否知道年份范围（下载模式 True → base_period 填实值）；
    base_period: 已知时填入如 '1991-2020'，否则空串；
    indent: 块所在上下文的基础缩进（下载模式 4 = if output_climate_csv 体内；处理模式 0 = 脚本顶层）。
    产物恒为 17 列。均值列基于 CLIM（跨年同月平均），extreme 列
    （t_max_val/t_max_year/...）基于 ds_month（逐月均值网格，保留年份维），
    取该月跨年极值 + 出现年份；无该月数据时保持 None。
    注意：返回块【已按月份展开并含 rows.append(row)】，调用方直接拼在
    rows = [] 之后即可，【禁止再包 for m 循环】（曾致月份翻倍的双重循环 bug）。
    """
    sp = " " * indent
    sp2 = " " * (indent + 4)
    months = months or list(range(1, 13))
    rows = []
    for m in months:
        fills = []
        for norm, field in fields:
            fills.append(
                f'{sp}_v = pt["{norm}"]\n'
                f'{sp}if "pressure_level" in _v.dims:\n'
                f'{sp}    _v = _v.isel(pressure_level=0)\n'
                f'{sp}row["{field}"] = float(_v.mean().values) if "{norm}" in pt else None  # 区域均值'
            )
            if norm == "2m_temperature":
                fills.append(f'{sp}row["t_max"] = row["t_mean"]  # 月均最高温近似（日级月均待 M3）')
                fills.append(f'{sp}row["t_min"] = row["t_mean"]')
        # ---- 极值列：该月跨年极值 + 出现年份（基于 ds_month，保留年份维）----
        ext_lines = [f'{sp}# 极值列：该月跨年极值 + 出现年份（基于 ds_month 逐月网格）']
        ext_lines.append(f'{sp}_m = ds_month.where(ds_month.time.dt.month == {m}, drop=True)')
        for norm, _field in fields:
            ext = _EXTREME_COLS.get(norm)
            if not ext:
                continue
            ext_lines.append(
                f'{sp}_e = _m["{norm}"].mean(dim=[d for d in _m["{norm}"].dims if d != "time"])'
            )
            ext_lines.append(f'{sp}if _e.size:')
            for vcol, ycol, agg in ext:
                ext_lines.append(f'{sp2}row["{vcol}"] = float(_e.{agg}().values)')
                # np.arg{agg} 取扁平索引（xarray 无参 argmax 将废弃）；_e.data 与 _e 同序
                ext_lines.append(f'{sp2}row["{ycol}"] = int(_e.time.dt.year[int(np.arg{agg}(_e.data))].values)')
        fills.extend(ext_lines)
        body = "\n".join(fills) if fills else f"{sp}pass"
        rows.append(
            f"{sp}pt = CLIM.sel(month={m})\n"
            f'{sp}row = {{"lat": round(LAT, 2), "lon": round(LON, 2), "month": {m},\n'
            f'{sp}       "t_mean": None, "t_max": None, "t_min": None,\n'
            f'{sp}       "precip": None, "wind_max_mean": None,\n'
            f'{sp}       "base_period": "{base_period}",\n'
            f'{sp}       "t_max_val": None, "t_max_year": None, "t_min_val": None, "t_min_year": None,\n'
            f'{sp}       "precip_max": None, "precip_max_year": None, "wind_max": None, "wind_max_year": None}}\n'
            f"{body}\n"
            f"{sp}rows.append(row)"
        )
    return "\n".join(rows)
