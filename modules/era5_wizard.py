"""
再分析数据处理向导（ERA5 · M0 知识库 + M1 勾选器 + M2 模板引擎）

目的：在天气分析平台的「再分析数据处理」板块内引导用户按需选择 ERA5
产品/变量/区域/时间，由模板引擎生成完整可运行的 Python 下载与处理脚本。
用户复制到本地执行后，产出与 ClimateStats schema 对齐的气候态宽表 CSV，
可回传平台板块直接消费，实现 "真 ERA5 气候态" 闭环。

一期（M0-M2）纯模板拼接，保证生成代码 100% 可靠；
二期（M3）预留 LLM 分析代码生成接口（见 build_era5_script 尾部）。

设计约束：
- 参数层（产品/变量/气压层/区域）全部硬编码，模板只读字典，
  LLM 永不接触参数层（防变量名自由发挥导致"跑通但数据错"）。
- 生成脚本绑定新 CDS 平台端点与 cdsapi 认证方式。
- 体积预估护栏：大请求警告，推荐月均值产品。
"""
from __future__ import annotations

from typing import Optional

try:  # 既可作为模块（app 内 from modules...）也可作为脚本直接运行
    from .nc_probe_common import (
        DIM_LAT, DIM_LON, DIM_TIME, VAR_SPECS, WIZARD_VARS,
        aliases_for, probe_var, open_nc_safe, clim_rows_block,
    )
    from .llm_client import (
        build_analysis_prompt, generate_analysis_code,
        LlmUnavailable, LlmCallError,
    )
    from .llm_validator import validate_safe_for_scene
except ImportError:  # 直接 `python modules/era5_wizard.py` 运行
    from nc_probe_common import (
        DIM_LAT, DIM_LON, DIM_TIME, VAR_SPECS, WIZARD_VARS,
        aliases_for, probe_var, open_nc_safe, clim_rows_block,
    )
    from llm_client import (
        build_analysis_prompt, generate_analysis_code,
        LlmUnavailable, LlmCallError,
    )
    from llm_validator import validate_safe_for_scene

# ============================================================
# M0 知识库：ERA5 产品 / 变量 / 气压层 / 区域 / 体积系数
# ============================================================

# 产品类型定义。group: single=单层, pressure=气压层, land=地表
ERA5_PRODUCTS = {
    "single_hourly": {
        "dataset": "reanalysis-era5-single-levels",
        "name": "ERA5 单层再分析（逐小时）",
        "desc": "近地面变量，0.25°（约 28 km），1940 至今",
        "group": "single",
        "time_res": "hourly",
        "req_type": "reanalysis",
    },
    "pressure_hourly": {
        "dataset": "reanalysis-era5-pressure-levels",
        "name": "ERA5 气压层再分析（逐小时）",
        "desc": "高空变量，37 层（1000-1 hPa），0.25°",
        "group": "pressure",
        "time_res": "hourly",
        "req_type": "reanalysis",
    },
    "single_monthly": {
        "dataset": "reanalysis-era5-single-levels-monthly-means",
        "name": "ERA5 单层月均值",
        "desc": "月平均再分析，气候态统计首选，体积约为逐小时的 1/700",
        "group": "single",
        "time_res": "monthly",
        "req_type": "monthly_averaged_reanalysis",
    },
    "pressure_monthly": {
        "dataset": "reanalysis-era5-pressure-levels-monthly-means",
        "name": "ERA5 气压层月均值",
        "desc": "高空月平均再分析，气候态首选",
        "group": "pressure",
        "time_res": "monthly",
        "req_type": "monthly_averaged_reanalysis",
    },
    "land_hourly": {
        "dataset": "reanalysis-era5-land",
        "name": "ERA5-Land 地表再分析（逐小时）",
        "desc": "陆面 0.1°（约 9 km），1950 至今，仅陆地",
        "group": "land",
        "time_res": "hourly",
        "req_type": None,  # era5-land 无 product_type 参数
    },
}

# 变量目录（CDS 官方命名）。每组: key -> (中文名, 单位, 备注)
_SINGLE_VARS = {
    "2m_temperature": ("2m 气温", "℃", "K→℃ 自动换算"),
    "2m_dewpoint_temperature": ("2m 露点温度", "℃", "K→℃ 自动换算"),
    "2m_relative_humidity": ("2m 相对湿度", "%", ""),
    "surface_pressure": ("地表气压", "hPa", "Pa→hPa 自动换算"),
    "mean_sea_level_pressure": ("海平面气压", "hPa", "Pa→hPa 自动换算"),
    "total_precipitation": ("总降水量", "mm", "m→mm 自动换算，累计值"),
    "10m_u_component_of_wind": ("10m U 风分量", "m/s", ""),
    "10m_v_component_of_wind": ("10m V 风分量", "m/s", ""),
    "10m_wind_speed": ("10m 风速（由 U/V 合成）", "m/s", "自动包含 U/V 两分量"),
    "100m_u_component_of_wind": ("100m U 风分量", "m/s", ""),
    "100m_v_component_of_wind": ("100m V 风分量", "m/s", ""),
    "total_cloud_cover": ("总云量", "%", ""),
    "surface_solar_radiation_downwards": ("地表向下太阳辐射", "J/m²", ""),
    "skin_temperature": ("地表皮肤温度", "℃", "K→℃ 自动换算"),
    "snow_depth": ("雪深", "m", ""),
}

_PRESSURE_VARS = {
    "temperature": ("温度", "℃", "K→℃ 自动换算"),
    "geopotential": ("位势高度", "gpm", "m²/s²→gpm 自动换算"),
    "relative_humidity": ("相对湿度", "%", ""),
    "specific_humidity": ("比湿", "kg/kg", ""),
    "u_component_of_wind": ("U 风分量", "m/s", ""),
    "v_component_of_wind": ("V 风分量", "m/s", ""),
    "wind_speed": ("风速（由 U/V 合成）", "m/s", "自动包含 U/V 两分量"),
    "vertical_velocity": ("垂直速度", "Pa/s", ""),
    "potential_vorticity": ("位涡", "K·m²/(kg·s)", ""),
}

_LAND_VARS = {
    "2m_temperature": ("2m 气温", "℃", "K→℃ 自动换算"),
    "2m_dewpoint_temperature": ("2m 露点温度", "℃", "K→℃ 自动换算"),
    "2m_relative_humidity": ("2m 相对湿度", "%", ""),
    "surface_pressure": ("地表气压", "hPa", "Pa→hPa 自动换算"),
    "total_precipitation": ("总降水量", "mm", "m→mm 自动换算，累计值"),
    "10m_u_component_of_wind": ("10m U 风分量", "m/s", ""),
    "10m_v_component_of_wind": ("10m V 风分量", "m/s", ""),
    "10m_wind_speed": ("10m 风速（由 U/V 合成）", "m/s", "自动包含 U/V 两分量"),
    "skin_temperature": ("地表皮肤温度", "℃", "K→℃ 自动换算"),
    "snow_depth": ("雪深", "m", ""),
    "surface_latent_heat_flux": ("地表潜热通量", "J/m²", ""),
    "surface_sensible_heat_flux": ("地表感热通量", "J/m²", ""),
    "volumetric_soil_water_layer_1": ("0-7cm 土壤体积含水量", "m³/m³", ""),
    "evaporation": ("蒸散量", "mm", "m→mm 自动换算"),
    "runoff": ("径流", "mm", "m→mm 自动换算"),
}

_VARS_BY_GROUP = {"single": _SINGLE_VARS, "pressure": _PRESSURE_VARS, "land": _LAND_VARS}

# 虚拟"合成风速" -> (U 变量, V 变量, 合成后变量名)
_WIND_SYNTH = {
    "10m_wind_speed": ("10m_u_component_of_wind", "10m_v_component_of_wind", "10m_wind_speed"),
    "wind_speed": ("u_component_of_wind", "v_component_of_wind", "wind_speed"),
}

# 单位换算规则（变量名 -> xarray 表达式右侧，含前导空格）
_UNIT_CONV = {
    "2m_temperature": " - 273.15",
    "2m_dewpoint_temperature": " - 273.15",
    "skin_temperature": " - 273.15",
    "temperature": " - 273.15",
    "surface_pressure": " / 100.0",
    "mean_sea_level_pressure": " / 100.0",
    "total_precipitation": " * 1000.0",
    "evaporation": " * 1000.0",
    "runoff": " * 1000.0",
    "geopotential": " / 9.80665",
}

# 气压层（ERA5 官方 37 层，hPa）
PRESSURE_LEVELS_HPA = [1000, 975, 950, 925, 900, 875, 850, 825, 800, 775, 750,
                       700, 650, 600, 550, 500, 450, 400, 350, 300, 250, 225,
                       200, 175, 150, 125, 100, 70, 50, 30, 20, 10, 7, 5, 3, 2, 1]

QUICK_LEVEL_SETS = {
    "850 hPa（低空）": [850],
    "700 hPa（中低空）": [700],
    "500 hPa（中高空）": [500],
    "300 hPa（高空）": [300],
    "200 hPa（急流层）": [200],
    "100 hPa（平流层底）": [100],
}

# 区域预设（CDS area 顺序：北, 西, 南, 东）
REGION_PRESETS = {
    "中国（含南海）": (53.5, 73.5, 15.0, 135.0),
    "中国大陆": (53.5, 73.5, 18.0, 135.0),
    "京津冀": (42.5, 113.0, 36.0, 120.0),
    "全球": (90.0, -180.0, -90.0, 180.0),
}

# 体积估算系数（GB / 变量 / 月 / 全球，逐小时产品；量级估算，用于护栏）
_VOL_PER_VAR_GB = {"single": 2.0, "pressure": 2.6, "land": 12.0}
_MONTHLY_MULT = 0.015        # 月均值产品约为逐小时同体积的 1.5%
_GLOBAL_DEG2 = 360.0 * 180.0


def expand_real_variables(variables: list[str]) -> list[str]:
    """展开虚拟风速为真实 U/V 分量，其余变量原样返回。"""
    out = []
    for v in variables:
        if v in _WIND_SYNTH:
            u, vv, _ = _WIND_SYNTH[v]
            if u not in out:
                out.append(u)
            if vv not in out:
                out.append(vv)
        else:
            out.append(v)
    return out


def estimate_size_gb(product: str, variables: list[str], pressure_levels: list[int],
                      year_start: int, year_end: int, months: list[int],
                      area: Optional[tuple]) -> float:
    """粗估下载体积（GB）。用于护栏与提示，精度不保证。"""
    info = ERA5_PRODUCTS[product]
    group = info["group"]
    real_vars = len(expand_real_variables(variables))
    n_years = max(0, year_end - year_start + 1)
    months_total = n_years * max(1, len(months))
    if area is None:
        area_frac = 1.0
    else:
        n, w, s, e = area
        area_frac = max(0.0, (n - s) * (e - w)) / _GLOBAL_DEG2
    per_var = _VOL_PER_VAR_GB[group]
    if group == "pressure":
        per_var *= max(1, len(pressure_levels))
    mult = 1.0 if info["time_res"] == "hourly" else _MONTHLY_MULT
    return real_vars * per_var * months_total * area_frac * mult


def _ts() -> str:
    import datetime
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


# ============================================================
# M2 模板引擎：按参数拼装完整脚本（纯字符串，无外部依赖）
# ============================================================

def build_era5_script(*, product: str, variables: list[str],
                      pressure_levels: Optional[list[int]] = None,
                      area: Optional[tuple] = None,
                      year_start: int, year_end: int,
                      months: Optional[list[int]] = None,
                      hourly_times: str = "all24",
                      time_res: str = "clim",
                      daily_stats: Optional[list[str]] = None,
                      output_climate_csv: bool = True,
                      climate_months: Optional[list[int]] = None,
                      center_lat: float = 39.9, center_lon: float = 116.4,
                      out_prefix: str = "era5_download") -> str:
    """生成完整可运行的 ERA5 下载与处理脚本（字符串）。

    一期为纯模板拼接；二期 M3 将在此函数尾部追加 LLM 分析代码片段，
    接口不变（多传一个 analysis_prompt 参数即可）。
    """
    info = ERA5_PRODUCTS[product]
    dataset = info["dataset"]
    group = info["group"]
    is_pressure = group == "pressure"
    is_monthly = info["time_res"] == "monthly"
    is_land = group == "land"

    months = months or list(range(1, 13))
    climate_months = climate_months or months
    pressure_levels = pressure_levels or [500, 850]
    daily_stats = daily_stats or ["mean"]
    real_vars = expand_real_variables(variables)

    years = list(range(year_start, year_end + 1))
    if is_monthly:
        time_list = ["00:00"]
    elif hourly_times == "4daily":
        time_list = ["00:00", "06:00", "12:00", "18:00"]
    else:
        time_list = [f"{h:02d}:00" for h in range(24)]

    # ---- 请求参数字典 ----
    def _list_block(values, indent="    "):
        lines = []
        for i, v in enumerate(values):
            comma = "," if i < len(values) - 1 else ""
            lines.append(f'{indent}        "{v}"{comma}')
        return "\n".join(lines)

    req_lines = []
    if not is_land:
        req_lines.append(f'    "product_type": "{info["req_type"]}",')
    req_lines.append("    \"variable\": [")
    req_lines.append(_list_block(real_vars))
    req_lines.append("    ],")
    if is_pressure:
        req_lines.append("    \"pressure_level\": [")
        req_lines.append(_list_block([str(p) for p in pressure_levels]))
        req_lines.append("    ],")
    req_lines.append("    \"year\": [")
    req_lines.append(_list_block([str(y) for y in years]))
    req_lines.append("    ],")
    req_lines.append("    \"month\": [")
    req_lines.append(_list_block([f"{m:02d}" for m in months]))
    req_lines.append("    ],")
    if is_monthly:
        req_lines.append('    "time": ["00:00"],')
    else:
        req_lines.append("    \"time\": [")
        req_lines.append(_list_block(time_list))
        req_lines.append("    ],")
    req_lines.append('    "data_format": "netcdf",')
    req_lines.append('    "download_format": "unarchived",')
    if area is not None:
        n, w, s, e = area
        req_lines.append(f"    \"area\": [{n:g}, {w:g}, {s:g}, {e:g}],")
    req_lines.append("}")
    request_block = "\n".join(req_lines)

    # ---- 单位换算行 ----
    conv_lines = []
    for v in real_vars:
        if v in _UNIT_CONV:
            conv_lines.append(f'ds["{v}"] = ds["{v}"]{_UNIT_CONV[v]}')
    conv_block = "\n".join(conv_lines)

    # ---- 风速合成行 ----
    synth_lines = []
    for v in variables:
        if v in _WIND_SYNTH:
            u, vv, out = _WIND_SYNTH[v]
            synth_lines.append(
                f'ds["{out}"] = np.sqrt(ds["{u}"] ** 2 + ds["{vv}"] ** 2)'
            )
    synth_block = "\n".join(synth_lines)

    # ---- 字段可用性 ----
    has_t = "2m_temperature" in real_vars or "temperature" in real_vars
    has_precip = "total_precipitation" in real_vars
    has_wind = any(v in real_vars or v in variables for v in
                   ("10m_wind_speed", "wind_speed", "10m_u_component_of_wind",
                    "u_component_of_wind", "10m_v_component_of_wind",
                    "v_component_of_wind"))

    # 宽表每行取值表达式（单一真相源 clim_rows_block，两模式 schema 一致）
    fields = []
    if has_t:
        tname = "2m_temperature" if "2m_temperature" in real_vars else "temperature"
        fields.append((tname, "t_mean"))
    if has_precip:
        fields.append(("total_precipitation", "precip"))
    if has_wind:
        wname = "10m_wind_speed" if "10m_wind_speed" in variables else (
            "wind_speed" if "wind_speed" in variables else "")
        if wname:
            fields.append((wname, "wind_max_mean"))
    rows_block = clim_rows_block(
        fields, climate_months, know_period=True,
        base_period=f"{year_start}-{year_end}", indent=4,  # 块落在 if output_climate_csv 体内
    )

    # ---- 时间处理段 ----
    if time_res == "raw":
        time_block = "# 保持原始时次\nDS_OUT = ds\n"
    elif time_res == "daily":
        stat_lines = [f'_d_{s} = ds.resample(time="1D").{s}()' for s in daily_stats]
        time_block = (
            "# 日聚合（可选统计：mean/max/min）\n"
            + "\n".join(stat_lines)
            + "\nDS_OUT = xr.merge([x for x in ("
            + ", ".join(f"_d_{s}" for s in daily_stats)
            + ") if x is not None])\n"
        )
    else:  # clim
        time_block = (
            "# 气候态：先月均（逐小时产品），再跨年同月平均\n"
            "ds_month = ds.resample(time=\"1MS\").mean()\n"
            "CLIM = ds_month.groupby(\"time.month\").mean(\"time\")\n"
            "DS_OUT = CLIM\n"
        )

    # ---- 变量中文说明 ----
    var_defs = _VARS_BY_GROUP[group]
    var_desc = "、".join(f"{var_defs[v][0]}({v})" for v in variables if v in var_defs)
    area_desc = "全球" if area is None else f"北{area[0]:g}° 西{area[1]:g}° 南{area[2]:g}° 东{area[3]:g}°"
    time_desc = "原始时次" if time_res == "raw" else (
        "日聚合 " + "/".join(daily_stats) if time_res == "daily" else "气候态月统计")

    script = f'''# -*- coding: utf-8 -*-
# ============================================================
# ERA5 数据下载与处理脚本（由天气分析平台 ERA5 向导生成）
# 生成时间: {_ts()}
# 产品: {info["name"]}
# 变量: {var_desc}
# 区域: {area_desc}
# 时间: {year_start}-{year_end} 年，{len(months)} 个月份，{'逐小时' if not is_monthly else '月度'}采样
# 处理: {time_desc}
# ------------------------------------------------------------
# 用法:
#   1. 注册 CDS 免费账号: https://cds.climate.copernicus.eu
#      （首次使用每个数据集需在网页端勾选接受许可条款）
#   2. 创建 API key，写入本机 ~/.cdsapirc（一行 url 一行 key）:
#        url: https://cds.climate.copernicus.eu/api
#        key: <UID>:<API_KEY>
#      key 获取: CDS 网页右上角用户菜单 -> API key
#   3. 安装依赖（任一 Python 3.9+ 环境）:
#        pip install cdsapi xarray netCDF4 pandas numpy
#   4. 运行: python {out_prefix}.py
# 说明: CDS 为排队下载制，大请求等待 30 分钟~数小时属正常现象。
#       首次下载失败多为条款未接受或 key 未生效，登录网页重试即可。
#       宽表中 t_max/t_min 当前取月均值（日极值统计为二期能力）。
# ============================================================
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ---- 0. 认证检查 ----
_rc = Path.home() / ".cdsapirc"
if not _rc.exists():
    print("[!] 未找到 ~/.cdsapirc，请先创建并填入 CDS API key：")
    print("    url: https://cds.climate.copernicus.eu/api")
    print("    key: <你的UID>:<你的API_KEY>")
    sys.exit(1)

# ---- 1. 下载 ----
import cdsapi

REQUEST = {{
{request_block}

TARGET = "{out_prefix}_download.nc"
print(f"[1/3] 请求 CDS 数据集 {dataset}，排队+下载可能需要较长时间...")
client = cdsapi.Client()
try:
    client.retrieve("{dataset}", REQUEST, TARGET)
except Exception as e:
    print(f"[!] 下载失败: {{e}}")
    print("    常见原因: 数据集许可条款未接受 / key 错误 / 参数不合法")
    sys.exit(1)

# ---- 2. 读取与单位换算 ----
import os
import numpy as np
import xarray as xr

ds = xr.open_dataset(TARGET)
{conv_block}
{synth_block}

# ---- 3. 时间处理 ----
output_climate_csv = {str(output_climate_csv)}
{time_block}

    # ---- 4. 输出 ----
if output_climate_csv:
    import pandas as pd
    LAT, LON = {center_lat:g}, {center_lon:g}
    rows = []
    # 注意：rows_block 已含各月循环体（clim_rows_block 按月份展开），勿再包 for m
{rows_block}
    df = pd.DataFrame(rows)
    out_csv = "{out_prefix}_climate_stats.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"[OK] 气候态宽表已输出: {{out_csv}}")
    print("     将该 CSV 上传到平台「再分析数据处理」板块即可直接使用")
# ---- 5. 结果摘要（P2.3 回传提示）----
print("\\n" + "=" * 60)
print("[摘要] ERA5 下载处理完成")
print(f"       产品: {info['name']}")
print(f"       变量: {var_desc}")
print(f"       范围: {area_desc} · {year_start}-{year_end} · {time_desc}")
print(f"       产物:")
print(f"         NetCDF 处理结果: {{os.path.abspath('{out_prefix}' + '_processed.nc')}}")
print(f"         气候态宽表 CSV: {{os.path.abspath(out_csv)}}")
print(f"         宽表行数: {{len(df)}}（{len(climate_months) if climate_months else 0} 个月份）")
print(f"       平台回传: 将 {{os.path.basename(out_csv)}} 上传到「再分析数据处理」板块即可直接使用")
print("=" * 60)

DS_OUT.to_netcdf("{out_prefix}_processed.nc")
print("[3/3] 完成。处理结果已保存为 {out_prefix}_processed.nc")
'''
    return script


# ============================================================
# M1 勾选器 UI（延迟 import streamlit，保证纯函数可测）
# ============================================================

def render_era5_wizard_download():
    """下载模式：勾选参数生成 ERA5 下载脚本。"""
    import streamlit as st

    st.write("---")
    with st.expander("⬇️ 下载模式 · ERA5 下载/处理代码生成", expanded=False):
        st.caption(
            "选择 ERA5 产品与参数，生成完整 Python 脚本，复制到本地执行，"
            "结果（气候态宽表 CSV）可直接回传本板块使用。"
            "需要免费的 CDS 账号，注册与配置方法见生成脚本头部说明。"
        )

        c1, c2 = st.columns([3, 2])
        with c1:
            prod_key = st.radio(
                "产品类型",
                list(ERA5_PRODUCTS.keys()),
                format_func=lambda k: ERA5_PRODUCTS[k]["name"],
                horizontal=True, key="wiz_product",
            )
            info = ERA5_PRODUCTS[prod_key]
            st.caption(f"数据集 `{info['dataset']}` · {info['desc']}")
        with c2:
            group = info["group"]
            var_defs = _VARS_BY_GROUP[group]
            default_vars = [v for v in
                            ("2m_temperature", "total_precipitation", "10m_wind_speed")
                            if v in var_defs]
            variables = st.multiselect(
                "变量（多选）", list(var_defs.keys()),
                default=default_vars,
                format_func=lambda k: var_defs[k][0],
                key="wiz_vars",
            )

        pressure_levels = []
        if group == "pressure":
            pc1, pc2 = st.columns(2)
            with pc1:
                quick = st.selectbox(
                    "常用层快捷选择", ["自定义..."] + list(QUICK_LEVEL_SETS.keys()),
                    index=1, key="wiz_quick",  # 默认 500 hPa
                )
                if quick != "自定义...":
                    pressure_levels = list(QUICK_LEVEL_SETS[quick])
            with pc2:
                if quick == "自定义...":
                    pressure_levels = st.multiselect(
                        "气压层（hPa）", PRESSURE_LEVELS_HPA,
                        default=[850, 500], key="wiz_levels",
                    )

        # 区域
        rc1, rc2, rc3 = st.columns(3)
        with rc1:
            region_mode = st.radio(
                "区域", ["目标点小区域", "中国（含南海）", "全球", "自定义"],
                index=0, key="wiz_region_mode",
            )
        area = None
        center_lat = float(st.session_state.get("climate_lat", 39.9))
        center_lon = float(st.session_state.get("climate_lon", 116.4))
        if region_mode == "目标点小区域":
            with rc2:
                center_lat = st.number_input("中心纬度", -90.0, 90.0,
                                             center_lat, 0.1, key="wiz_center_lat")
            with rc3:
                center_lon = st.number_input("中心经度", -180.0, 180.0,
                                             center_lon, 0.1, key="wiz_center_lon")
            area = (min(center_lat + 0.25, 90.0), max(center_lon - 0.25, -180.0),
                    max(center_lat - 0.25, -90.0), min(center_lon + 0.25, 180.0))
            st.caption(
                f"以目标点为中心 0.5°×0.5° 小区域（北{area[0]:.2f} 西{area[1]:.2f} "
                f"南{area[2]:.2f} 东{area[3]:.2f}），宽表取中心格点值"
            )
        elif region_mode == "自定义":
            n0, w0, s0, e0 = 53.5, 73.5, 18.0, 135.0
            with rc2:
                n0 = st.number_input("北界 °N", -90.0, 90.0, n0, key="wiz_n")
                s0 = st.number_input("南界 °N", -90.0, 90.0, s0, key="wiz_s")
            with rc3:
                w0 = st.number_input("西界 °E", -180.0, 180.0, w0, key="wiz_w")
                e0 = st.number_input("东界 °E", -180.0, 180.0, e0, key="wiz_e")
            if n0 > s0 and w0 != e0:
                area = (n0, w0, s0, e0)
            center_lat, center_lon = (n0 + s0) / 2, (w0 + e0) / 2
        else:
            area = REGION_PRESETS[region_mode]
            center_lat, center_lon = (area[0] + area[2]) / 2, (area[1] + area[3]) / 2
            st.caption(f"区域 {region_mode}；宽表取区域中心格点值，跨度大时建议改用目标点小区域")

        # 时间范围
        tc1, tc2, tc3 = st.columns(3)
        with tc1:
            year_start = st.number_input(
                "起始年", 1940, 2026, 1991, key="wiz_y0",
                help="ERA5 从 1940 年起；ERA5-Land 从 1950 年起",
            )
        with tc2:
            year_end = st.number_input(
                "结束年", 1940, 2026, 2020, key="wiz_y1",
                help="气候态标准窗口 1991-2020",
            )
        with tc3:
            months = st.multiselect(
                "月份（多选）", list(range(1, 13)),
                default=list(range(1, 13)),
                format_func=lambda m: f"{m}月", key="wiz_months",
            )

        # 时间采样与处理粒度
        hourly_times, daily_stats, climate_months = "all24", ["mean"], None
        if info["time_res"] == "monthly":
            time_res, climate_months = "clim", months
            st.caption("月均值产品：直接按月统计，无需时间采样。")
        else:
            ht1, tr1, tr2 = st.columns(3)
            with ht1:
                hourly_times = st.radio(
                    "时间采样", ["all24", "4daily"],
                    format_func=lambda t: {"all24": "全部 24 时次",
                                            "4daily": "每日 4 次 (00/06/12/18)"}[t],
                    key="wiz_htimes",
                )
            with tr1:
                time_res = st.radio(
                    "处理粒度", ["clim", "daily", "raw"],
                    format_func=lambda t: {"clim": "气候态月统计",
                                            "daily": "日聚合",
                                            "raw": "原始时次"}[t],
                    index=0, key="wiz_tres",
                )
            with tr2:
                if time_res == "daily":
                    daily_stats = st.multiselect(
                        "日统计量", ["mean", "max", "min"], default=["mean"],
                        key="wiz_dstats",
                    ) or ["mean"]
                elif time_res == "clim":
                    climate_months = st.multiselect(
                        "气候态统计月份", list(range(1, 13)),
                        default=list(range(1, 13)),
                        format_func=lambda m: f"{m}月", key="wiz_cmonths",
                    ) or list(range(1, 13))

        oc1, oc2 = st.columns(2)
        with oc1:
            output_climate_csv = st.checkbox(
                "生成气候态宽表 CSV（可直接上传本板块）", value=True,
                key="wiz_ocsv",
            )
        with oc2:
            out_prefix = st.text_input("输出文件前缀", "era5_china", key="wiz_prefix")

        if variables:
            gb = estimate_size_gb(prod_key, variables, pressure_levels,
                                  int(year_start), int(year_end), months, area)
            st.caption(f"估算下载体积 ≈ **{gb:.1f} GB**（量级参考，实际以 CDS 为准）")
            if gb > 5:
                st.warning(
                    f"体积较大（{gb:.0f} GB），排队时间可能数小时。"
                    "若仅需气候态统计，建议改用「ERA5 单层月均值」产品（体积缩小约 98%）。"
                )

        if st.button("生成 ERA5 脚本", key="wiz_gen"):
            if not variables:
                st.error("请至少选择一个变量")
            elif year_start > year_end:
                st.error("起始年不能大于结束年")
            elif not months:
                st.error("请至少选择一个月份")
            else:
                script = build_era5_script(
                    product=prod_key, variables=variables,
                    pressure_levels=pressure_levels, area=area,
                    year_start=int(year_start), year_end=int(year_end),
                    months=months,
                    hourly_times=hourly_times,
                    time_res=time_res,
                    daily_stats=daily_stats,
                    output_climate_csv=output_climate_csv,
                    climate_months=climate_months if climate_months else months,
                    center_lat=float(center_lat), center_lon=float(center_lon),
                    out_prefix=out_prefix,
                )
                st.code(script, language="python")
                st.download_button(
                    "下载脚本 (.py)", script,
                    file_name=f"{out_prefix}.py", mime="text/x-python",
                    key="wiz_dl",
                )

        with st.expander("CDS 账号与 .cdsapirc 配置说明"):
            st.markdown(
                "1. 打开 [CDS 注册页](https://cds.climate.copernicus.eu) 免费注册\n"
                "2. 登录后在用户菜单找到 **API key**（UID 与 Key 两串字符）\n"
                "3. 在本机用户目录创建 `.cdsapirc` 文件："
            )
            st.code("url: https://cds.climate.copernicus.eu/api\nkey: <UID>:<API_KEY>")
            st.markdown(
                "4. 首次使用某数据集时，需在 CDS 网页端进入该数据集页面，"
                "勾选接受许可条款后再运行脚本\n"
                "5. 下载为排队制，等待时间与请求体积相关，属正常现象"
            )


# ============================================================
# 处理模式（P0+P1）：文件探测 + 处理代码生成 + 下载对照单
# ============================================================

# 变量别名表 / 维度候选名 / 变量指派 已统一到 nc_probe_common（单一真相源）。

# 处理场景定义
PROCESS_SCENES = {
    "inspect": {"name": "文件信息探查", "desc": "打印变量/单位/维度/统计摘要，快速确认数据"},
    "clim_stats": {"name": "气候态月统计", "desc": "月均值跨年同月平均，输出气候态宽表 CSV（可回传平台）"},
    "daily": {"name": "日聚合统计", "desc": "逐小时聚合为日值（均值/最大/最小），输出 CSV"},
    "extreme": {"name": "极值统计", "desc": "各变量历史最大/最小值及出现时间，输出统计表"},
}


def probe_netcdf_file(data) -> dict:
    """探测 NetCDF 文件（bytes 或路径），返回结构化信息（平台侧 P1-4）。

    数据不落盘存储：bytes 物化到系统临时目录，函数返回后由调用方清理。
    返回: {"ok": bool, "error": str, "variables": [...], "time_dim", "n_time",
           "n_lat", "n_lon", "n_grid", "shape"}
    """
    import os

    try:
        if isinstance(data, (bytes, bytearray)):
            ds, path, size_kb = open_nc_safe(data)
        else:
            p = str(data)
            if not os.path.exists(p):
                return {"ok": False, "error": f"文件不存在: {p}"}
            if not p.lower().endswith((".nc", ".nc4", ".cdf")):
                return {"ok": False, "error": f"文件扩展名不是 .nc（收到 {os.path.basename(p)}），"
                                              "请在 CDS 下载时选择 NetCDF 格式"}
            ds, path, size_kb = open_nc_safe(p)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"NetCDF 读取失败: {e}"}

    try:
        # 变量清单 + 规范名映射（单一真相源 probe_var）
        variables = []
        for name in ds.data_vars:
            da = ds[name]
            spec = probe_var(name)
            variables.append({
                "orig": str(name),
                "units": str(da.attrs.get("units", "") or ""),
                "dims": list(da.dims),
                "norm": spec["era5"] if spec else None,
            })

        # 时间维与水平格点（共享维度候选）
        time_dim, n_time, n_lat, n_lon = None, 0, 0, 0
        for d in ds.dims:
            dl = d.lower()
            if dl in DIM_TIME and time_dim is None:
                time_dim = d
                n_time = int(ds.sizes[d])
            elif dl in DIM_LAT:
                n_lat = int(ds.sizes[d])
            elif dl in DIM_LON:
                n_lon = int(ds.sizes[d])

        return {
            "ok": True,
            "file": os.path.basename(path) if isinstance(data, str) else "upload.nc",
            "size_kb": size_kb,
            "variables": variables,
            "time_dim": time_dim, "n_time": n_time,
            "n_lat": n_lat, "n_lon": n_lon,
            "n_grid": n_lat * n_lon,
            "shape": f"{n_lat}x{n_lon}x{n_time}",
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"NetCDF 读取失败: {e}"}


def _process_scene_block(scene: str, norm_vars: list[str],
                         scene_opts: Optional[dict], out_prefix: str) -> str:
    """按场景生成处理段代码（P0-1 读取层模板化，变量名来自探测/映射）。"""
    opts = scene_opts or {}

    if scene == "inspect":
        return f'''# ---- 统计摘要 ----
print("\\n[摘要] 各变量统计（换算后，非 NaN）：")
for norm, actual in ACTUAL.items():
    if not actual or actual not in ds:
        print(f"  {{norm}}: 未找到对应变量，跳过")
        continue
    s = ds[actual].values
    s = s[np.isfinite(s)]
    print(f"  {{norm}} ({{actual}}): min={{s.min():.3f}} max={{s.max():.3f}} mean={{s.mean():.3f}} n={{s.size}}")
print("\\n[完成] 信息探查结束。")
'''
    if scene == "clim_stats":
        months = opts.get("months", list(range(1, 13)))
        fields = []
        for n in norm_vars:
            spec = next((s for s in VAR_SPECS if s["era5"] == n), None)
            if spec and spec["field"]:
                fields.append((n, spec["field"]))
        rows_block = clim_rows_block(fields, months, know_period=False, indent=0)  # 块落在脚本顶层
        return f'''# ---- 气候态月统计（跨年同月平均） ----
ds_month = ds.resample(time="1MS").mean()
CLIM = ds_month.groupby("time.month").mean("time")
# 按规范名重命名，便于统一取值（ds_month 供宽表极值列使用，须同步重命名）
for norm, actual in ACTUAL.items():
    if actual and actual in ds_month:
        ds_month = ds_month.rename({{actual: norm}})
    if actual and actual in CLIM:
        CLIM = CLIM.rename({{actual: norm}})

# 中心格点取水平维均值，作为区域代表点
_lat = [d for d in ("latitude", "lat", "y", "nav_lat", "xlat", "g0_lat_1") if d in ds.dims]
_lon = [d for d in ("longitude", "lon", "x", "nav_lon", "xlong", "g0_lon_2") if d in ds.dims]
LAT = float(ds[_lat[0]].mean()) if _lat else 0.0
LON = float(ds[_lon[0]].mean()) if _lon else 0.0

rows = []
# 注意：rows_block 已含各月循环体（clim_rows_block 按月份展开），勿再包 for m
{rows_block}
df = pd.DataFrame(rows)
out_csv = "{out_prefix}_climate_stats.csv"
df.to_csv(out_csv, index=False, encoding="utf-8-sig")
print(f"[OK] 气候态宽表已输出: {{out_csv}}（上传平台「再分析数据处理」板块即可使用）")
'''
    if scene == "daily":
        stats = opts.get("daily_stats", ["mean"])
        stat_lines = [f'_d_{s} = ds.resample(time="1D").{s}()' for s in stats]
        merge_expr = "xr.merge([x for x in (" + ", ".join(f"_d_{s}" for s in stats) + ") if x is not None])"
        return f'''# ---- 日聚合（{"/".join(stats)}） ----
{chr(10).join(stat_lines)}
DS_DAILY = {merge_expr}
for norm, actual in ACTUAL.items():
    if actual and actual in DS_DAILY:
        DS_DAILY = DS_DAILY.rename({{actual: norm}})

df = DS_DAILY.to_dataframe().reset_index()
out_csv = "{out_prefix}_daily.csv"
df.to_csv(out_csv, index=False, encoding="utf-8-sig")
print(f"[OK] 日聚合结果已输出: {{out_csv}}（共 {{len(df)}} 行）")
'''
    # extreme
    return f'''# ---- 极值统计（各变量最大/最小值） ----
results = []
for norm, actual in ACTUAL.items():
    if not actual or actual not in ds:
        continue
    da = ds[actual]
    results.append({{
        "变量": norm, "单位": str(ds[actual].attrs.get("units", "?")),
        "最大值": float(da.max().values), "最小值": float(da.min().values),
        "时次数": int(da.size),
    }})
df = pd.DataFrame(results)
out_csv = "{out_prefix}_extreme.csv"
df.to_csv(out_csv, index=False, encoding="utf-8-sig")
print(df.to_string(index=False))
print(f"[OK] 极值统计已输出: {{out_csv}}")
'''


def build_process_script(*, scene: str = "inspect",
                         expected_vars: Optional[list[str]] = None,
                         file_mode: str = "paste",
                         detected: Optional[dict] = None,
                         path_hint: str = "",
                         glob_pattern: str = "",
                         scene_opts: Optional[dict] = None,
                         out_prefix: str = "era5_process",
                         analysis_prompt: str = "",
                         llm_body: str = "") -> str:
    """生成处理模式脚本（P0+P1+P2 batch glob + M3 LLM 场景体）。

    scene: 见 PROCESS_SCENES。
    file_mode: "paste"=本地路径 | "upload"=平台已探测
               | "batch"=批量 glob 匹配（多文件循环处理）。
    detected: probe_netcdf_file 的结果（upload 模式）。
    glob_pattern: batch 模式下的 glob 表达式（如 "C:\\era5\\*.nc"）。
    analysis_prompt: 用户分析需求文本（M3 LLM 模式上下文；为空=纯模板模式）。
    llm_body: LLM 生成的处理段代码（须已通过 llm_validator 校验）。非空时
        覆盖模板场景体；analysis_prompt 非空但 llm_body 为空 → 模板回退。
        LLM 只写处理段，不接触变量名/单位（硬约束：先模板后 LLM）。
    """
    expected_vars = expected_vars or ["2m_temperature"]
    scene_opts = scene_opts or {}

    # 规范名 -> 文件实际变量名
    if file_mode == "upload" and detected and detected.get("ok"):
        by_norm = {v["norm"]: v["orig"] for v in detected.get("variables", []) if v.get("norm")}
        bind_lines = []
        for n in expected_vars:
            bind_lines.append(f'    "{n}": {by_norm.get(n, n)!r},')
        bind_code = "ACTUAL = {\n" + "\n".join(bind_lines) + "\n}"
    else:
        # 运行时映射：候选名探测
        fn_lines = []
        for n, cands in aliases_for(expected_vars).items():
            fn = "_find_" + n.replace("10m_", "w10_").replace("2m_", "s2_").replace("-", "_")
            fn_lines.append(
                f'def {fn}(ds):\n'
                f'    for c in {cands}:\n'
                f'        if c in ds.data_vars:\n'
                f'            return c\n'
                f'    return None')
        bind_lines = []
        for n in expected_vars:
            fn = "_find_" + n.replace("10m_", "w10_").replace("2m_", "s2_").replace("-", "_")
            bind_lines.append(f'    "{n}": {fn}(ds),')
        bind_code = "\n".join(fn_lines) + "\n\nACTUAL = {\n" + "\n".join(bind_lines) + "\n}"

    scene_body = _process_scene_block(scene, expected_vars, scene_opts, out_prefix)
    if llm_body and llm_body.strip():
        scene_body = (
            "# ---- LLM 生成处理段（已通过 llm_validator 校验）----\n"
            + llm_body.strip()
        )

    # 换算段（运行时，按 ACTUAL 映射）
    conv_runtime = []
    for n in expected_vars:
        if n in _UNIT_CONV:
            conv_runtime.append(
                f'if ACTUAL["{n}"] and ACTUAL["{n}"] in ds:\n'
                f'    ds[ACTUAL["{n}"]] = ds[ACTUAL["{n}"]]{_UNIT_CONV[n]}')
    conv_runtime_block = "\n".join(conv_runtime)

    scene_name = PROCESS_SCENES.get(scene, {}).get("name", scene)
    scene_desc = PROCESS_SCENES.get(scene, {}).get("desc", "")
    dep_block = (
        'for _m, _hint in (("xarray", "pip install xarray"),\n'
        '                  ("netCDF4", "pip install netCDF4"),\n'
        '                  ("pandas", "pip install pandas"),\n'
        '                  ("numpy", "pip install numpy")):\n'
        '    try:\n'
        '        __import__(_m)\n'
        '    except ImportError:\n'
        '        print(f"[!] 缺少依赖 {_m}，请执行: {_hint}")\n'
        '        sys.exit(1)'
    )

    path_line = path_hint or r"C:\path\to\your\downloaded\file.nc"
    probe_known = ""
    if file_mode == "upload" and detected and detected.get("ok"):
        var_lines = "".join(
            f'#   {v["orig"]} | units={v["units"]} | dims={v["dims"]} | norm={v["norm"]}\n'
            for v in detected.get("variables", []))
        probe_known = "# 平台探测到的变量：\n" + var_lines

    # ---- 批量 glob 模式（P2.1）----
    if file_mode == "batch":
        import textwrap
        glob_pattern = glob_pattern or r"C:\era5\*.nc"
        # scene_body 内嵌缩进到 _process_one 函数体内（4 空格）
        indented_scene = textwrap.indent(scene_body, "    ")
        indented_conv = textwrap.indent(conv_runtime_block, "    ") if conv_runtime_block else ""

        batch_header = (
            '# 批量 glob 模式：按模式匹配多文件，逐个处理\n'
            f'PATTERN = r"{glob_pattern}"\n'
            '\n'
            '# ---- glob 展开与去重 ----\n'
            '_raw = glob.glob(PATTERN)\n'
            '_matched = sorted(set(os.path.abspath(f) for f in _raw))\n'
            'if not _matched:\n'
            '    print(f"[!] 未匹配到文件：{PATTERN}")\n'
            '    print("    请确认路径模式正确（如 C:\\\\era5\\\\*.nc）且文件存在")\n'
            '    sys.exit(1)\n'
            f'print(f"[匹配] 模式 {{PATTERN}}，共 {{len(_matched)}} 个文件（已去重排序）")\n'
            'for _m in _matched:\n'
            '    print(f"       {_m}")\n'
            '\n'
            '_results = {"ok": 0, "missing_vars": 0, "error": 0, "total": len(_matched), "files": []}\n'
            f'out_prefix = "{out_prefix}"  # 批量模式：输出目录/文件前缀（M3 LLM 契约）\n'
            '\n'
            'def _process_one(fpath, fname, idx):\n'
            '    """处理单个文件，返回 True/False。非 ASCII 路径自动复制临时目录。"""\n'
            '    _fp = fpath\n'
            '    try:\n'
            '        _fp.encode("ascii")\n'
            '    except UnicodeEncodeError:\n'
            '        _tmp = tempfile.mkdtemp(prefix="era5_proc_")\n'
            '        _tmp_path = os.path.join(_tmp, os.path.basename(_fp))\n'
            '        shutil.copyfile(_fp, _tmp_path)\n'
            '        print(f"[路径] 检测到非 ASCII 路径，已复制到: {_tmp_path}")\n'
            '        _fp = _tmp_path\n'
            '\n'
            '    ds = xr.open_dataset(_fp)\n'
            '    print(f"\\n{\'=\'*60}")\n'
            '    print(f"[处理] idx={idx:03d} 文件: {fname}")\n'
            '    print("      变量清单（原名 | 单位 | 维度）:")\n'
            '    for _v in ds.data_vars:\n'
            '        print(f"      {_v} | {ds[_v].attrs.get(\'units\', \'?\')} | {list(ds[_v].dims)}")\n'
            f'{probe_known}\n'
            '\n'
            '    # 期望变量绑定\n'
            f'{textwrap.indent(bind_code, "    ")}\n'
            '\n'
            '    # 缺失校验（仅警告，不中断批处理）\n'
            '    _missing = [n for n, a in ACTUAL.items() if not a or a not in ds]\n'
            '    if _missing:\n'
            '        print(f"[警告] idx={idx:03d} 缺少期望变量: {_missing}")\n'
            '        print(f"       文件实际变量: {list(ds.data_vars)}")\n'
            '        return False  # 记录缺失但不终止\n'
            '\n'
            '    # 时间维/格点信息\n'
            '    _time_dims = [d for d in ds.dims '
            'if d.lower() in ("time", "valid_time", "t", "date", "month")]\n'
            '    if _time_dims:\n'
            '        print(f"[探测] 时间维: {_time_dims[0]}，共 {ds.sizes[_time_dims[0]]} 个时次")\n'
            '\n'
            '    # ---- 单位换算 ----\n'
            f'{indented_conv}\n'
            '\n'
            '    # ---- 处理段 ----\n'
            f'{indented_scene}\n'
            '\n'
            '    print(f"[完成] idx={idx:03d} 文件处理完毕")\n'
            '    return True\n'
            '\n'
            'import shutil\n'
            'import tempfile\n'
            'for _idx, _fp in enumerate(_matched):\n'
            '    _res_dir = f"{out_prefix}_batch{_idx:03d}"\n'
            '    os.makedirs(_res_dir, exist_ok=True)\n'
            '    _old_dir = os.getcwd()\n'
            '    try:\n'
            '        os.chdir(_res_dir)\n'
            '        _ok = _process_one(_fp, os.path.basename(_fp), _idx)\n'
            '    except Exception as _e:\n'
            '        print(f"[错误] idx={_idx:03d} 文件处理异常: {_e}")\n'
            '        _ok = False\n'
            '    finally:\n'
            '        os.chdir(_old_dir)\n'
            '    _status = "ok" if _ok else ("missing_vars" if _ok is False else "error")\n'
            '    _results[_status] += 1\n'
            '    _results["files"].append({"idx": _idx, "file": _fp, "ok": _ok})\n'
            '\n'
            '# ---- 批量摘要（P2.3 回传提示）----\n'
            'print("\\n" + "=" * 60)\n'
            'print("[摘要] 批量处理完成")\n'
            'print(f"       总文件: {_results[\'total\']}")\n'
            'print(f"       成功: {_results[\'ok\']}  缺变量跳过: {_results[\'missing_vars\']}  异常: {_results[\'error\']}")\n'
            'print("       各文件结果：")\n'
            'for _f in _results["files"]:\n'
            '    _tag = "OK" if _f["ok"] else "FAIL"\n'
            '    print(f"       [{_tag}] batch{_f[\'idx\']:03d}  <- {_f[\'file\']}")\n'
            'print("\\n如需将结果回传平台，请将各 batchNNN/ 目录下的 CSV/统计文件上传即可。")'
        )

        script = f'''# -*- coding: utf-8 -*-
# ============================================================
# ERA5 批量处理脚本（平台「再分析数据处理」· 批量 glob 模式生成）
# 生成时间: {_ts()}
# 场景: {scene_name}（{scene_desc}）
# 期望变量: {expected_vars}
# Glob 模式: {glob_pattern}
# ------------------------------------------------------------
# 用法:
#   1. 修改 PATTERN 为你的文件匹配模式（如 C:\\era5\\*.nc）
#   2. 确保已安装: pip install xarray netCDF4 pandas numpy
#   3. 运行: python {out_prefix}.py
# 说明: 脚本展开 glob 模式 → 去重排序 → 逐个文件处理 → 每文件输出到独立子目录。
#       批量模式下缺失变量仅警告不终止；异常文件跳过继续处理。
# ============================================================
import glob
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ---- 依赖自检 ----
{dep_block}

import numpy as np
import pandas as pd
import xarray as xr

# ---- 文件匹配与批量处理 ----
{batch_header}
'''
        return script

    script = f'''# -*- coding: utf-8 -*-
# ============================================================
# ERA5 数据处理脚本（平台「再分析数据处理」· 处理模式生成）
# 生成时间: {_ts()}
# 场景: {scene_name}（{scene_desc}）
# 期望变量: {expected_vars}
# 文件来源: {'平台已探测' if file_mode == "upload" else '本地路径，运行时自动映射变量名'}
# ------------------------------------------------------------
# 用法:
#   1. 将 FILE_PATH 改为你的 ERA5 文件路径（在 CDS 网页下载的 .nc 文件）
#   2. 确保已安装: pip install xarray netCDF4 pandas numpy
#   3. 运行: python {out_prefix}.py
# 说明: 脚本自动探测文件内容并校验期望变量；路径含中文时自动复制到临时目录。
# ============================================================
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ---- 依赖自检（P1-6）----
{dep_block}

import numpy as np
import pandas as pd
import xarray as xr

# ---- 文件路径（P0-3 双防线）----
FILE_PATH = r"{path_line}"   # ← 把这里改成你的文件路径（r 开头防止转义）

if not os.path.exists(FILE_PATH):
    print(f"[!] 文件不存在: {{FILE_PATH}}")
    print("    请检查路径是否正确（可右键文件 → 属性 → 复制完整路径）")
    sys.exit(1)
try:
    FILE_PATH.encode("ascii")
except UnicodeEncodeError:
    import shutil
    import tempfile
    _tmp = tempfile.mkdtemp(prefix="era5_proc_")
    _tmp_path = os.path.join(_tmp, os.path.basename(FILE_PATH))
    shutil.copyfile(FILE_PATH, _tmp_path)
    print(f"[路径] 检测到非 ASCII 路径（中文/空格），已复制到临时目录: {{_tmp_path}}")
    FILE_PATH = _tmp_path

# ---- 文件探测段（P0-2）----
ds = xr.open_dataset(FILE_PATH)
print(f"[探测] 文件: {{os.path.basename(FILE_PATH)}}")
print("      变量清单（原名 | 单位 | 维度）:")
for _v in ds.data_vars:
    print(f"      {{_v}} | {{ds[_v].attrs.get('units', '?')}} | {{list(ds[_v].dims)}}")
{probe_known}

# 期望变量绑定
{bind_code}

# 校验：期望变量是否都能在文件中找到
_missing = [n for n, a in ACTUAL.items() if not a or a not in ds]
if _missing:
    print(f"[!] 文件中缺少期望变量: {{_missing}}")
    print(f"    文件实际变量: {{list(ds.data_vars)}}")
    print("    请检查下载时选择的产品类型是否匹配（如气压层产品没有 2m 气温）")
    sys.exit(1)

# 时间维/格点信息
_time_dims = [d for d in ds.dims if d.lower() in ("time", "valid_time", "t", "date", "month")]
if _time_dims:
    print(f"[探测] 时间维: {{_time_dims[0]}}，共 {{ds.sizes[_time_dims[0]]}} 个时次")
_geo = 1
for _d in ds.dims:
    if _d.lower() in ("latitude", "lat", "y", "nav_lat", "xlat", "g0_lat_1", "longitude", "lon", "x", "nav_lon", "xlong", "g0_lon_2"):
        _geo *= ds.sizes[_d]
print(f"[探测] 水平格点数: {{_geo}}")

# ---- 单位换算（按规范名）----
{conv_runtime_block}

# ---- 处理段（读取层模板化，变量名来自探测）----
out_prefix = "{out_prefix}"  # M3 LLM 契约：处理段可用的输出前缀
{scene_body}

# ---- 结果摘要（P2.3 回传提示）----
print("\\n" + "=" * 60)
print("[摘要] 处理完成")
print(f"       场景: {scene_name}")
print(f"       文件: {{os.path.basename(FILE_PATH)}}")
print(f"       期望变量: {expected_vars}")
print(f"       产物: {{os.getcwd()}} 目录下")
print("       平台回传: 将结果文件上传到「再分析数据处理」板块即可直接使用")
print("=" * 60)
'''
    return script


def build_cds_web_checklist(*, product: str, variables: list[str],
                            pressure_levels: Optional[list[int]] = None,
                            area: Optional[tuple] = None,
                            year_start: int, year_end: int,
                            months: Optional[list[int]] = None,
                            hourly_times: str = "all24") -> str:
    """生成「去 CDS 网页照着填」的下载对照单（P1-5）。"""
    info = ERA5_PRODUCTS[product]
    months = months or list(range(1, 13))
    var_defs = _VARS_BY_GROUP[info["group"]]
    var_sel = "、".join(f"{var_defs[v][0]}（{v}）" for v in variables if v in var_defs) or "（未选）"
    years_str = f"{year_start}–{year_end}"
    months_str = "、".join(f"{m:02d}" for m in months)
    if info["time_res"] == "monthly":
        time_str = "（月均值产品无需选时间）"
    elif hourly_times == "4daily":
        time_str = "00:00、06:00、12:00、18:00"
    else:
        time_str = "00:00 至 23:00（全部 24 个时次）"
    area_str = "全球（不填 Area）" if area is None else (
        f"北 {area[0]:g} / 西 {area[1]:g} / 南 {area[2]:g} / 东 {area[3]:g}")
    plev_str = "、".join(str(p) for p in (pressure_levels or [])) or "（单层产品无需填）"
    req_type = info["req_type"] or "（era5-land 无此项）"

    return f"""# CDS 网页下载对照单（由平台生成）

**数据集**: `{info["dataset"]}`
**产品**: {info["name"]}

## 操作步骤
1. 打开 https://cds.climate.copernicus.eu 并登录
2. 搜索数据集 `{info["dataset"]}`，进入数据集页面
3. 首次使用：在页面下方勾选**接受许可条款**（Accept licence）
4. 在 **Download data** 表单中按下表填写：
5. 填写后点击 **Submit form** → 等待排队处理 → 处理完成后邮件通知 → 下载 `.nc` 文件

## 表单填写对照表

| 表单字段 | 填写值 |
|----------|--------|
| Product type | {req_type} |
| Variable | {var_sel} |
| Pressure level | {plev_str} |
| Year | {years_str} |
| Month | {months_str} |
| Time | {time_str} |
| Area | {area_str} |
| Data format | **NetCDF**（不要选 GRIB，Windows 本地处理兼容性差） |

## 注意事项
- 排队时间 30 分钟~数小时属正常，期间无需操作
- 下载完成后建议将文件放入英文路径的文件夹（如 `C:\\era5`），避免中文路径问题
- 若需再次使用，可直接在本页重新生成对照单
"""


def render_era5_wizard():
    """「再分析数据处理」向导入口：下载模式 / 处理模式。"""
    import streamlit as st

    st.write("---")
    st.write("### 🛰️ 再分析数据处理 · ERA5 向导")
    mode = st.radio(
        "向导模式",
        ["download", "process"],
        format_func=lambda m: {"download": "下载模式（生成 CDS 下载脚本）",
                               "process": "处理模式（生成本地数据处理脚本）"}[m],
        horizontal=True, key="wiz_mode",
    )
    if mode == "download":
        render_era5_wizard_download()
        return

    # ---- 处理模式 ----
    with st.expander("🔬 处理模式 · 生成本地数据处理脚本", expanded=False):
        st.caption(
            "针对已在 CDS 网页下载的 ERA5 文件（.nc），生成读取+处理脚本。"
            "可上传文件由平台自动探测（用后即弃，不存储），或提供本地路径由脚本运行时自动映射变量。"
        )
        src = st.radio(
            "文件来源", ["upload", "paste", "batch"],
            format_func=lambda s: {"upload": "上传文件（平台探测，推荐）",
                                   "paste": "本地路径（脚本运行时自动映射）",
                                   "batch": "批量 glob 匹配（多文件循环处理）"}[s],
            horizontal=True, key="proc_src",
        )
        detected = None
        batch_pattern = ""
        if src == "upload":
            up = st.file_uploader("上传 ERA5 NetCDF 文件 (.nc)", type=["nc", "nc4", "cdf"],
                                  key="proc_up")
            if up is not None:
                detected = probe_netcdf_file(up.getvalue())
                if detected.get("ok"):
                    vlines = "\n".join(
                        f"- `{v['orig']}` | 单位 {v['units'] or '?'} | 维度 {v['dims']}"
                        + (f" → 规范名 `{v['norm']}`" if v.get("norm") else "（未识别）")
                        for v in detected["variables"])
                    st.success(
                        f"探测成功：{detected['file']}（{detected['size_kb']} KB）"
                        f" | 结构 {detected['shape']} | 时次 {detected['n_time']}"
                    )
                    st.markdown(vlines)
                else:
                    st.error(detected.get("error"))
        elif src == "batch":
            batch_pattern = st.text_input(
                "Glob 模式（如 C:\\era5\\*.nc）",
                value=r"C:\era5\*.nc",
                key="proc_batch_glob",
                help="支持 * ? [...] 通配符；运行时去重排序；无匹配时报错",
            )
            st.caption(
                "脚本展开模式 → 文件列表去重排序 → 逐个处理 → 每文件输出到独立子目录。"
                "批量模式下缺变量仅警告不终止。"
            )

        label = {**{k: v[0] for k, v in _SINGLE_VARS.items()},
                 **{k: v[0] for k, v in _PRESSURE_VARS.items()},
                 **{k: v[0] for k, v in _LAND_VARS.items()}}
        all_vars = WIZARD_VARS
        default_vars = [v for v in ("2m_temperature", "total_precipitation") if v in all_vars]
        expected_vars = st.multiselect(
            "期望变量（生成的脚本会校验这些变量存在）", all_vars,
            default=default_vars,
            format_func=lambda k: label.get(k, k), key="proc_vars",
        )
        if src == "upload" and detected and detected.get("ok"):
            avail = [v["norm"] for v in detected["variables"] if v.get("norm")]
            unknown = [v for v in expected_vars if v not in avail]
            if unknown:
                st.warning(f"以下期望变量未在文件中识别到（可能产品类型不匹配）：{unknown}")
                st.caption(f"文件中识别到的规范变量：{avail or '无'}")

        scene = st.radio(
            "分析场景", list(PROCESS_SCENES.keys()),
            format_func=lambda k: PROCESS_SCENES[k]["name"],
            horizontal=True, key="proc_scene",
        )
        st.caption(PROCESS_SCENES[scene]["desc"])
        scene_opts = {}
        if scene == "clim_stats":
            scene_opts["months"] = st.multiselect(
                "统计月份", list(range(1, 13)), default=list(range(1, 13)),
                format_func=lambda m: f"{m}月", key="proc_months") or list(range(1, 13))
        elif scene == "daily":
            scene_opts["daily_stats"] = st.multiselect(
                "日统计量", ["mean", "max", "min"], default=["mean"],
                key="proc_dstats") or ["mean"]

        oc1, oc2 = st.columns(2)
        with oc1:
            out_prefix = st.text_input("输出文件前缀", "era5_process", key="proc_prefix")
        with oc2:
            llm_prompt = st.text_area(
                "自定义分析需求（可选 · AI 生成处理段）",
                placeholder="留空=按预设场景模板生成；填写后由 AI 生成处理段，例如：计算每年 6-8 月平均气温并输出 CSV",
                key="proc_llm", height=68,
            )
        if llm_prompt.strip():
            st.caption(
                "AI 模式：骨架（文件读取/变量映射/单位换算）仍由平台模板生成，"
                "AI 只编写处理段代码，生成后经安全校验（模块白名单+禁止调用），未通过自动回退模板。"
            )

        if st.button("生成处理脚本", key="proc_gen"):
            if not expected_vars:
                st.error("请至少选择一个期望变量")
            elif src == "batch" and not batch_pattern.strip():
                st.error("请填写 glob 匹配模式")
            else:
                llm_body, llm_note = "", ""
                if llm_prompt.strip():
                    with st.spinner("AI 正在生成处理段代码…"):
                        ctx = {
                            "scene": scene,
                            "scene_name": PROCESS_SCENES.get(scene, {}).get("name", scene),
                            "expected_vars": expected_vars, "detected": detected,
                            "scene_opts": scene_opts, "out_prefix": out_prefix,
                        }
                        try:
                            prompt = build_analysis_prompt(ctx, llm_prompt.strip())
                            code = generate_analysis_code(prompt)
                            verdict = validate_safe_for_scene(code, scene)
                            if not verdict["ok"]:
                                st.error("AI 生成的代码未通过安全校验，已回退预设模板：")
                                for e in verdict["errors"]:
                                    st.error(f"- {e}")
                                llm_note = "（AI 代码未通过校验，回退模板）"
                            else:
                                llm_body = code
                                st.success(f"AI 生成成功（{len(code)} 字符），已通过安全校验")
                                for w in verdict["warnings"]:
                                    st.warning(f"- {w}")
                        except LlmUnavailable as e:
                            st.error(f"{e}；已回退预设模板。")
                            llm_note = "（未配置 LLM，回退模板）"
                        except LlmCallError as e:
                            st.error(f"AI 生成失败：{e}；已回退预设模板。")
                            llm_note = "（LLM 调用失败，回退模板）"
                script = build_process_script(
                    scene=scene, expected_vars=expected_vars,
                    file_mode=src, detected=detected,
                    glob_pattern=batch_pattern,
                    scene_opts=scene_opts, out_prefix=out_prefix,
                    analysis_prompt=llm_prompt or "",
                    llm_body=llm_body,
                )
                st.code(script, language="python")
                st.caption(f"来源: {'AI 生成' if llm_body else '预设模板'}{llm_note}")
                st.download_button(
                    "下载脚本 (.py)", script,
                    file_name=f"{out_prefix}.py", mime="text/x-python",
                    key="proc_dl",
                )


if __name__ == "__main__":
    # 纯函数自检：各产品生成一次脚本并打印体积预估
    for pk in ERA5_PRODUCTS:
        vd = _VARS_BY_GROUP[ERA5_PRODUCTS[pk]["group"]]
        vars_sel = [list(vd.keys())[0]]
        for cand in ("10m_wind_speed", "wind_speed"):
            if cand in vd:
                vars_sel.append(cand)
                break
        gb = estimate_size_gb(pk, vars_sel, [850, 500], 1991, 2020, list(range(1, 13)),
                              (53.5, 73.5, 18.0, 135.0))
        script = build_era5_script(
            product=pk, variables=vars_sel,
            pressure_levels=[850, 500], area=(53.5, 73.5, 18.0, 135.0),
            year_start=1991, year_end=2020, months=list(range(1, 13)),
            time_res="clim", output_climate_csv=True,
        )
        assert ERA5_PRODUCTS[pk]["dataset"] in script
        print(f"[{pk}] 体积≈{gb:.2f} GB | 脚本 {len(script)} 字符 | 断言通过")

    # 处理模式自检：四场景生成脚本 + 对照单
    import ast
    for sc in PROCESS_SCENES:
        s = build_process_script(
            scene=sc, expected_vars=["2m_temperature", "total_precipitation"],
            file_mode="paste", scene_opts={"months": [1, 7], "daily_stats": ["mean", "max"]},
            out_prefix=f"proc_{sc}",
        )
        ast.parse(s)
        assert "FILE_PATH" in s and "依赖自检" in s
        print(f"[{sc}] 处理脚本 {len(s)} 字符 | 语法合法 | 断言通过")
    cl = build_cds_web_checklist(
        product="single_monthly", variables=["2m_temperature"],
        area=(53.5, 73.5, 18.0, 135.0), year_start=1991, year_end=2020,
        months=list(range(1, 13)),
    )
    assert "NetCDF" in cl and "reanalysis-era5-single-levels-monthly-means" in cl
    print(f"[checklist] 下载对照单 {len(cl)} 字符 | 断言通过")
    print("自检完成")
