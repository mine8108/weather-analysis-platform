"""ERA5 数据获取引导：变量 catalogue、请求参数构建、脚本包交付。

catalogue 是选择器与脚本生成的唯一真相源。所有变量标识符均已对
``research/era5_variable_enums_2026-09-13.json``（CDS constraints 接口实测快照）
校验，``validate_catalogue`` 在测试中保证其持续一致。

本模块只依赖标准库与 streamlit；应用侧永不 import cdsapi / xarray / netCDF4，
以保证 Streamlit Cloud 部署不因缺少这些重依赖而失败，也避免服务器内存风险。
"""

from datetime import datetime

import streamlit as st

# 需要换算的量：key → 人类可读说明（同时用于生成的脚本与 UI 提示）
SCALES = {
    "K2C": "K → ℃（减 273.15）",
    "M2MM": "m → mm（乘 1000）",
    "PA2HPA": "Pa → hPa（除 100）",
    "FRAC2PCT": "0–1 → %（乘 100）",
    "GEOPOT2HEIGHT": "位势 → 位势高度（除 9.80665）",
    "UV2SPEEDDIR": "u/v 分量 → 风速与风向",
}

GROUP_ORDER = ("温度", "湿度", "风", "气压", "降水与蒸发", "云与辐射", "陆面", "大气层结")

# 产品键名保持既有文案，避免用户习惯断裂
ERA5_PRODUCTS = {
    "ERA5-Land (地表小时, 0.1°)": {
        "dataset": "reanalysis-era5-land",
        "url": "https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land",
        "type": "hourly",
        "product_type": None,
        "allow_day": True,
        "time_values": None,
        "resolution": "0.1° × 0.1°",
        "coverage": "1950 年至今（约滞后 2–3 个月）",
        "lag_months": 3,
        "field_limit": 12000,
        "notes": "陆面掩膜产品，海洋格点缺失；不提供相对湿度与云量。",
        "variables": {
            "2m_temperature": {"label": "2m 气温", "unit": "K", "group": "温度",
                               "scale": "K2C", "note": "距地面 2m 的空气温度"},
            "2m_dewpoint_temperature": {"label": "2m 露点温度", "unit": "K", "group": "湿度",
                                        "scale": "K2C", "note": "可与气温换算相对湿度"},
            "skin_temperature": {"label": "地表温度", "unit": "K", "group": "温度",
                                 "scale": "K2C", "note": "地表辐射温度"},
            "soil_temperature_level_1": {"label": "土壤温度（0–7cm）", "unit": "K", "group": "陆面",
                                         "scale": "K2C", "note": "表层土壤温度"},
            "total_precipitation": {"label": "总降水", "unit": "m", "group": "降水与蒸发",
                                    "scale": "M2MM", "note": "累计量，非速率"},
            "potential_evaporation": {"label": "潜在蒸发", "unit": "m", "group": "降水与蒸发",
                                      "scale": "M2MM", "note": "累计量，负值表示蒸发"},
            "10m_u_component_of_wind": {"label": "10m 纬向风 u", "unit": "m/s", "group": "风",
                                        "scale": "UV2SPEEDDIR", "note": "需与 v 分量合成风速风向"},
            "10m_v_component_of_wind": {"label": "10m 经向风 v", "unit": "m/s", "group": "风",
                                        "scale": "UV2SPEEDDIR", "note": "需与 u 分量合成风速风向"},
            "surface_pressure": {"label": "地面气压", "unit": "Pa", "group": "气压",
                                 "scale": "PA2HPA", "note": "站点气压常用"},
            "snow_depth": {"label": "雪深", "unit": "m", "group": "陆面",
                           "scale": None, "note": "瞬时值"},
            "volumetric_soil_water_layer_1": {"label": "土壤体积含水量（0–7cm）", "unit": "m³/m³",
                                              "group": "陆面", "scale": None, "note": "表层体积含水量"},
            "surface_net_solar_radiation": {"label": "地表净短波辐射", "unit": "J/m²", "group": "云与辐射",
                                            "scale": None, "note": "累计量"},
        },
        "unsupported": {
            "relative_humidity": {"label": "相对湿度",
                                  "reason": "ERA5-Land 不提供相对湿度，可用 2m 气温与 2m 露点温度换算",
                                  "switch_to": "ERA5 气压层 (0.25°)"},
            "total_cloud_cover": {"label": "总云量",
                                  "reason": "ERA5-Land 不提供云量",
                                  "switch_to": "ERA5 再分析单层 (0.25°)"},
        },
        "derivations": [
            {"kind": "uv_to_speed_dir", "u": "10m_u_component_of_wind",
             "v": "10m_v_component_of_wind",
             "output": ["wind_speed", "wind_direction"]},
        ],
    },
    "ERA5 再分析单层 (0.25°)": {
        "dataset": "reanalysis-era5-single-levels",
        "url": "https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels",
        "type": "hourly",
        "product_type": ["reanalysis"],
        "allow_day": True,
        "time_values": None,
        "resolution": "0.25° × 0.25°",
        "coverage": "1940 年至今（约滞后 2–3 个月）",
        "lag_months": 3,
        "field_limit": 120000,
        "notes": "全球覆盖（含海洋）；不提供相对湿度。",
        "variables": {
            "2m_temperature": {"label": "2m 气温", "unit": "K", "group": "温度",
                               "scale": "K2C", "note": "距地面 2m 的空气温度"},
            "2m_dewpoint_temperature": {"label": "2m 露点温度", "unit": "K", "group": "湿度",
                                        "scale": "K2C", "note": "可与气温换算相对湿度"},
            "skin_temperature": {"label": "地表温度", "unit": "K", "group": "温度",
                                 "scale": "K2C", "note": "地表辐射温度"},
            "mean_sea_level_pressure": {"label": "海平面气压", "unit": "Pa", "group": "气压",
                                        "scale": "PA2HPA", "note": "天气图常用"},
            "surface_pressure": {"label": "地面气压", "unit": "Pa", "group": "气压",
                                 "scale": "PA2HPA", "note": "站点气压常用"},
            "total_precipitation": {"label": "总降水", "unit": "m", "group": "降水与蒸发",
                                    "scale": "M2MM", "note": "累计量"},
            "snow_depth": {"label": "雪深", "unit": "m", "group": "陆面",
                           "scale": None, "note": "瞬时值"},
            "10m_u_component_of_wind": {"label": "10m 纬向风 u", "unit": "m/s", "group": "风",
                                        "scale": "UV2SPEEDDIR", "note": "需与 v 分量合成风速风向"},
            "10m_v_component_of_wind": {"label": "10m 经向风 v", "unit": "m/s", "group": "风",
                                        "scale": "UV2SPEEDDIR", "note": "需与 u 分量合成风速风向"},
            "total_cloud_cover": {"label": "总云量", "unit": "1", "group": "云与辐射",
                                  "scale": "FRAC2PCT", "note": "0–1 的比例"},
            "boundary_layer_height": {"label": "边界层高度", "unit": "m", "group": "大气层结",
                                      "scale": None, "note": "污染物扩散分析常用"},
            "surface_solar_radiation_downwards": {"label": "下行短波辐射", "unit": "J/m²",
                                                  "group": "云与辐射", "scale": None, "note": "累计量"},
        },
        "unsupported": {
            "relative_humidity": {"label": "相对湿度",
                                  "reason": "单层产品不提供相对湿度，仅气压层提供",
                                  "switch_to": "ERA5 气压层 (0.25°)"},
        },
        "derivations": [
            {"kind": "uv_to_speed_dir", "u": "10m_u_component_of_wind",
             "v": "10m_v_component_of_wind",
             "output": ["wind_speed", "wind_direction"]},
        ],
    },
    "ERA5 气压层 (0.25°)": {
        "dataset": "reanalysis-era5-pressure-levels",
        "url": "https://cds.climate.copernicus.eu/datasets/reanalysis-era5-pressure-levels",
        "type": "pressure",
        "product_type": ["reanalysis"],
        "allow_day": True,
        "time_values": None,
        "resolution": "0.25° × 0.25°",
        "coverage": "1940 年至今（约滞后 2–3 个月）",
        "lag_months": 3,
        "field_limit": 120000,
        "notes": "需选择气压层；相对湿度仅本产品提供。",
        "variables": {
            "geopotential": {"label": "位势", "unit": "m²/s²", "group": "大气层结",
                             "scale": "GEOPOT2HEIGHT", "note": "除 9.80665 得位势高度"},
            "temperature": {"label": "温度", "unit": "K", "group": "温度",
                            "scale": "K2C", "note": "等压面温度"},
            "u_component_of_wind": {"label": "纬向风 u", "unit": "m/s", "group": "风",
                                    "scale": "UV2SPEEDDIR", "note": "需与 v 分量合成风速风向"},
            "v_component_of_wind": {"label": "经向风 v", "unit": "m/s", "group": "风",
                                    "scale": "UV2SPEEDDIR", "note": "需与 u 分量合成风速风向"},
            "relative_humidity": {"label": "相对湿度", "unit": "%", "group": "湿度",
                                  "scale": None, "note": "等压面相对湿度"},
            "specific_humidity": {"label": "比湿", "unit": "kg/kg", "group": "湿度",
                                  "scale": None, "note": "水汽含量"},
            "vertical_velocity": {"label": "垂直速度", "unit": "Pa/s", "group": "大气层结",
                                  "scale": None, "note": "负值为上升运动"},
            "divergence": {"label": "散度", "unit": "1/s", "group": "大气层结",
                           "scale": None, "note": "高空辐散辐合"},
            "vorticity": {"label": "涡度", "unit": "1/s", "group": "大气层结",
                          "scale": None, "note": "相对涡度"},
            "potential_vorticity": {"label": "位涡", "unit": "K·m²/(kg·s)", "group": "大气层结",
                                    "scale": None, "note": "动力诊断常用"},
        },
        "unsupported": {
            "geopotential_height": {"label": "位势高度",
                                    "reason": "API 不提供位势高度，请改选位势并按 ÷9.80665 换算",
                                    "switch_to": None},
        },
        "derivations": [
            {"kind": "uv_to_speed_dir", "u": "u_component_of_wind",
             "v": "v_component_of_wind",
             "output": ["wind_speed", "wind_direction"]},
        ],
    },
    "ERA5-Land 月均值 (0.1°)": {
        "dataset": "reanalysis-era5-land-monthly-means",
        "url": "https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land-monthly-means",
        "type": "monthly",
        "product_type": ["monthly_averaged_reanalysis"],
        "allow_day": False,
        "time_values": ["00:00"],
        "resolution": "0.1° × 0.1°",
        "coverage": "1950 年至今（约滞后 2–3 个月）",
        "lag_months": 3,
        "field_limit": 100000,
        "notes": "月均值产品：不接受 day 键；product_type 取 monthly_averaged_reanalysis（月整体）。",
        "variables": {
            "2m_temperature": {"label": "2m 气温（月均）", "unit": "K", "group": "温度",
                               "scale": "K2C", "note": "月平均值"},
            "2m_dewpoint_temperature": {"label": "2m 露点温度（月均）", "unit": "K", "group": "湿度",
                                        "scale": "K2C", "note": "月平均值"},
            "skin_temperature": {"label": "地表温度（月均）", "unit": "K", "group": "温度",
                                 "scale": "K2C", "note": "月平均值"},
            "soil_temperature_level_1": {"label": "土壤温度（月均，0–7cm）", "unit": "K",
                                         "group": "陆面", "scale": "K2C", "note": "月平均值"},
            "total_precipitation": {"label": "总降水（月累计）", "unit": "m",
                                    "group": "降水与蒸发", "scale": "M2MM", "note": "月累计量"},
            "potential_evaporation": {"label": "潜在蒸发（月累计）", "unit": "m",
                                      "group": "降水与蒸发", "scale": "M2MM", "note": "月累计量"},
            "10m_u_component_of_wind": {"label": "10m 纬向风 u（月均）", "unit": "m/s",
                                        "group": "风", "scale": "UV2SPEEDDIR",
                                        "note": "需与 v 分量合成风速风向"},
            "10m_v_component_of_wind": {"label": "10m 经向风 v（月均）", "unit": "m/s",
                                        "group": "风", "scale": "UV2SPEEDDIR",
                                        "note": "需与 u 分量合成风速风向"},
            "surface_pressure": {"label": "地面气压（月均）", "unit": "Pa", "group": "气压",
                                 "scale": "PA2HPA", "note": "月平均值"},
            "snow_depth": {"label": "雪深（月均）", "unit": "m", "group": "陆面",
                           "scale": None, "note": "月平均值"},
            "volumetric_soil_water_layer_1": {"label": "土壤体积含水量（月均，0–7cm）",
                                              "unit": "m³/m³", "group": "陆面",
                                              "scale": None, "note": "月平均值"},
            "surface_net_solar_radiation": {"label": "地表净短波辐射（月均）", "unit": "J/m²",
                                            "group": "云与辐射", "scale": None, "note": "月平均值"},
        },
        "unsupported": {
            "relative_humidity": {"label": "相对湿度",
                                  "reason": "ERA5-Land 不提供相对湿度，可用 2m 气温与 2m 露点温度换算",
                                  "switch_to": "ERA5 气压层 (0.25°)"},
            "total_cloud_cover": {"label": "总云量",
                                  "reason": "ERA5-Land 不提供云量",
                                  "switch_to": "ERA5 再分析单层 (0.25°)"},
        },
        "derivations": [
            {"kind": "uv_to_speed_dir", "u": "10m_u_component_of_wind",
             "v": "10m_v_component_of_wind",
             "output": ["wind_speed", "wind_direction"]},
        ],
    },
}

# 常用组合预设：选中即填充「产品 + 变量」
PRESETS = {
    "站点气象常用（ERA5-Land）": {
        "product": "ERA5-Land (地表小时, 0.1°)",
        "variables": ["2m_temperature", "2m_dewpoint_temperature", "surface_pressure",
                      "10m_u_component_of_wind", "10m_v_component_of_wind"],
    },
    "降水与蒸发（ERA5-Land）": {
        "product": "ERA5-Land (地表小时, 0.1°)",
        "variables": ["total_precipitation", "potential_evaporation"],
    },
    "土壤与陆面（ERA5-Land）": {
        "product": "ERA5-Land (地表小时, 0.1°)",
        "variables": ["soil_temperature_level_1", "volumetric_soil_water_layer_1",
                      "snow_depth"],
    },
    "高空环流（气压层）": {
        "product": "ERA5 气压层 (0.25°)",
        "variables": ["geopotential", "temperature", "u_component_of_wind",
                      "v_component_of_wind", "specific_humidity"],
    },
    "云与辐射（单层）": {
        "product": "ERA5 再分析单层 (0.25°)",
        "variables": ["total_cloud_cover", "surface_solar_radiation_downwards",
                      "boundary_layer_height"],
    },
}


def validate_catalogue():
    """校验 catalogue 自身一致性，返回缺陷描述列表；空列表表示合法。"""
    problems = []
    for product, meta in ERA5_PRODUCTS.items():
        for field in ("dataset", "url", "type", "allow_day", "resolution",
                      "coverage", "field_limit", "variables"):
            if field not in meta:
                problems.append("%s: 缺少字段 %s" % (product, field))
        if meta["type"] not in ("hourly", "pressure", "monthly"):
            problems.append("%s: type 非法 %r" % (product, meta["type"]))
        if meta["type"] == "monthly" and meta["allow_day"]:
            problems.append("%s: 月均值产品不得允许 day" % product)
        if meta["type"] == "pressure" and not meta.get("derivations"):
            problems.append("%s: 气压层产品缺少 u/v 派生说明" % product)
        if not meta["variables"]:
            problems.append("%s: 变量表为空" % product)
        for name, info in meta["variables"].items():
            for field in ("label", "unit", "group", "scale", "note"):
                if field not in info:
                    problems.append("%s / %s: 缺少 %s" % (product, name, field))
            if info.get("group") not in GROUP_ORDER:
                problems.append("%s / %s: 分组 %r 不在 GROUP_ORDER 内"
                                % (product, name, info.get("group")))
            scale = info.get("scale")
            if scale is not None and scale not in SCALES:
                problems.append("%s / %s: 未知换算 %r" % (product, name, scale))
    for preset, spec in PRESETS.items():
        if spec["product"] not in ERA5_PRODUCTS:
            problems.append("预设 %s: 产品不存在" % preset)
            continue
        available = ERA5_PRODUCTS[spec["product"]]["variables"]
        for name in spec["variables"]:
            if name not in available:
                problems.append("预设 %s: 变量 %s 不在该产品中" % (preset, name))
    return problems


# 各数据集允许的键集（对 CDS process 定义实测所得，
# 见 research/era5_variable_enums_2026-09-13.json 的 allowed_keys）。
#
# 注意：必须按【数据集】而非产品类型分键。ERA5-Land 与 ERA5 单层同属小时数据，
# 但前者不接受 product_type、后者必须带，按类型分键会把两者混为一谈。
KEYS_ALLOWED_BY_DATASET = {
    "reanalysis-era5-land": (
        "area", "data_format", "day", "download_format", "month",
        "time", "variable", "year"),
    "reanalysis-era5-single-levels": (
        "area", "data_format", "day", "download_format", "month",
        "product_type", "time", "variable", "year"),
    "reanalysis-era5-pressure-levels": (
        "area", "data_format", "day", "download_format", "month",
        "pressure_level", "product_type", "time", "variable", "year"),
    "reanalysis-era5-land-monthly-means": (
        "area", "data_format", "download_format", "month",
        "product_type", "time", "variable", "year"),
}

# 当前有效的 37 个气压层（hPa），与快照一致
PRESSURE_LEVELS = ("1", "2", "3", "5", "7", "10", "20", "30", "50", "70", "100",
                   "125", "150", "175", "200", "225", "250", "300", "350", "400",
                   "450", "500", "550", "600", "650", "700", "750", "775", "800",
                   "825", "850", "875", "900", "925", "950", "975", "1000")

_ALL_DAYS = ["%02d" % d for d in range(1, 32)]
_ALL_HOURS = ["%02d:00" % h for h in range(24)]


def available_years():
    """可选年份：ERA5 约滞后 2–3 个月，当年数据不完整，故上限取去年。"""
    return list(range(1950, datetime.now().year))


def _days_of_months(months):
    """按月份取每月天数上限（2 月按 29 天，CDS 会忽略不存在的日期）。

    这是刻意的安全高估：请求里 day 固定为 01–31，估算用于提前预警而非精确计费。
    """
    lengths = {1: 31, 2: 29, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31,
               9: 30, 10: 31, 11: 30, 12: 31}
    return sum(lengths.get(int(m), 31) for m in months)


def build_payload(product, years, months, variables, pressure_levels=None, area=None):
    """按产品类型构建合法的 CDS 请求体。

    - 仅当产品声明了 product_type 时才写入该键（ERA5-Land 不接受它）。
    - 仅当 allow_day 为真时写入 day（月均值不接受它）。
    - 月均值等产品用自身声明的 time_values，否则取全部 24 个整点。
    - 坐标顺序为 [北, 西, 南, 东]，与 CDS 官网表单一致。
    """
    meta = ERA5_PRODUCTS[product]
    payload = {
        "variable": list(variables),
        "year": ["%04d" % int(y) for y in sorted(years)],
        "month": ["%02d" % int(m) for m in sorted(months)],
    }
    if meta.get("product_type"):
        payload["product_type"] = list(meta["product_type"])
    if meta.get("allow_day", True):
        payload["day"] = list(_ALL_DAYS)
    payload["time"] = list(meta.get("time_values") or _ALL_HOURS)
    if meta["type"] == "pressure":
        payload["pressure_level"] = [str(level) for level in (pressure_levels or [])]
    if area:
        north, west, south, east = area
        payload["area"] = [float(north), float(west), float(south), float(east)]
    payload["data_format"] = "netcdf"
    payload["download_format"] = "unarchived"
    return payload


def validate_payload(product, payload):
    """校验请求体：键集白名单、变量存在、气压层合法、无废弃关键字。"""
    meta = ERA5_PRODUCTS[product]
    problems = []
    allowed = set(KEYS_ALLOWED_BY_DATASET[meta["dataset"]])
    for key in payload:
        if key not in allowed:
            problems.append("%s: 该数据集不接受键 %r" % (product, key))
    for name in payload.get("variable", []):
        if name not in meta["variables"]:
            problems.append("%s: 变量 %r 不在本产品中" % (product, name))
    for level in payload.get("pressure_level", []):
        if str(level) not in PRESSURE_LEVELS:
            problems.append("%s: 气压层 %r 非法" % (product, level))
    if meta.get("allow_day") is False and "day" in payload:
        problems.append("%s: 月均值产品不接受 day" % product)
    if not meta.get("product_type") and "product_type" in payload:
        problems.append("%s: 该数据集不接受 product_type" % product)
    return problems


def estimate_field_count(product, years, months, variables,
                         pressure_levels=None):
    """估算请求规模（字段数），用于提交前与 CDS 数据集上限比对。

    字段数 = 变量数 × 年数 × Σ(各月天数) × 时次数 × 气压层数
    月均值产品的时次为 1 且不使用 day，故按「变量 × 年 × 月」计。
    """
    meta = ERA5_PRODUCTS[product]
    n_var = len(variables)
    n_year = len(years)
    n_month = len(months)
    if meta["type"] == "monthly":
        return n_var * n_year * n_month
    n_day = _days_of_months(months)
    n_hour = len(meta.get("time_values") or _ALL_HOURS)
    n_level = len(pressure_levels or []) if meta["type"] == "pressure" else 1
    return n_var * n_year * n_day * n_hour * n_level


def fields_over_limit(product, count):
    """字段数是否超出该数据集上限。"""
    return count > ERA5_PRODUCTS[product]["field_limit"]


# ============================================================
# 三、UI 渲染
# ============================================================

_HELP_GET_DATA = """
### 获取 ERA5 数据的完整流程

1. 访问 [Copernicus CDS](https://cds.climate.copernicus.eu/) 注册免费账号并登录。
2. **在目标数据集的下载页手工接受数据集许可**（页面底部 Terms of use 区块）。
   这一步无法用 API 代办，也是下载失败最常见的原因：未接受时请求会在提交阶段
   被拒，报 `Client has not agreed to the required terms and conditions`。
   已接受的许可列表可在个人资料页底部查看。
3. 在个人资料页生成 API Key，本地安装客户端：`pip install "cdsapi>=0.7.7"`。
4. 创建 `~/.cdsapirc`（内容见下载包中的 `.cdsapirc.example`）：

   ```
   url: https://cds.climate.copernicus.eu/api
   key: 你的API-Key
   ```

   **没有 UID 字段**。旧式 `uid:key` 凭证会让客户端走到已废弃的 LegacyClient
   分支而失败；地址也不要再用 `/api/v2` 或 `cds-beta`（均已停用）。
5. 在本页选好参数，下载 ZIP 脚本包，解压后**手动打开终端**执行脚本。
6. 脚本会排队等待 CDS 处理，完成后自动解包 NetCDF 并导出可直接导入本平台的 CSV。

### 需要预知的限制

- **队列**：请求提交后进入 CDS 队列，状态从 queued 变为 running 可能需要数十分钟到数小时。
- **字段数上限**（单请求，超限是排队而非报错）：ERA5-Land 小时 12000、
  ERA5-Land 月均值 100000、ERA5 单层与气压层各 120000。本页会在提交前估算并预警。
- **成本限额**：2025 年 4 月起 netCDF 请求另有成本限额，超限直接返回 403
  `cost limits exceeded`。
- **返回格式**：多变量或多文件请求**仍可能返回 ZIP**，脚本会自动解包。
- **时间维名**：新版 netCDF 的时间维可能是 `valid_time` 而非 `time`，脚本已兼容两者。
- **数据格式关键字**：`format` 已废弃，须用 `data_format` + `download_format`；
  缺省 `data_format` 会静默返回 GRIB 而不是 netCDF。
- **时效**：ERA5 约滞后 2–3 个月；近实时 ERA5T 数据可能被后续修订，相同请求也可能命中缓存。
"""


def label_for(product, name):
    """变量选择器显示文案：中文名（api_name，单位）。"""
    info = ERA5_PRODUCTS[product]["variables"][name]
    scale = SCALES.get(info.get("scale") or "", "")
    tail = "，%s" % scale if scale else ""
    return "%s（%s，%s%s）" % (info["label"], name, info["unit"], tail)


def _payload_preview(payload):
    """把请求体渲染为可照抄到 CDS 官网表单的纯文本。"""
    lines = []
    for key in ("variable", "product_type", "year", "month", "day", "time",
                "pressure_level", "area", "data_format", "download_format"):
        if key in payload:
            value = payload[key]
            if isinstance(value, list) and len(value) > 8:
                shown = "%s …（共 %d 项）" % (", ".join(str(v) for v in value[:8]),
                                             len(value))
            else:
                shown = ", ".join(str(v) for v in value) if isinstance(value, list) \
                    else str(value)
            lines.append("%-16s %s" % (key, shown))
    return "\n".join(lines)


def _reset_preset_marker():
    """预设切换时清掉「已应用」标记，避免与手动改动互相覆盖。"""
    st.session_state["_era5_preset_applied"] = None


def _apply_preset():
    """预设下拉的 on_change 回调：在本次 rerun 之前写入产品与各分组变量。"""
    name = st.session_state.get("era5_preset_pick")
    spec = PRESETS.get(name)
    if not spec:
        return
    product = spec["product"]
    st.session_state["era5_product"] = product
    wanted = set(spec["variables"])
    meta = ERA5_PRODUCTS[product]
    for group in GROUP_ORDER:
        names = [n for n, info in meta["variables"].items() if info["group"] == group]
        if not names:
            continue
        st.session_state["era5_pick_%s_%s" % (product, group)] = \
            [n for n in names if n in wanted]
    st.session_state["_era5_preset_applied"] = name


def _switch_product(target):
    """「切换到支持该变量的产品」按钮的回调。"""
    st.session_state["era5_product"] = target
    st.session_state["_era5_preset_applied"] = None


def render_era5_guide():
    """ERA5 CDS 数据获取引导（变量 catalogue + 参数配置 + 脚本包下载）。"""
    try:
        from modules.era5_script_pack import build_era5_zip
    except ImportError:  # 部署缺文件时降级，不影响页面其他功能区
        build_era5_zip = None

    st.caption("ERA5 数据由 Copernicus Climate Data Store (CDS) 提供。"
               "推荐在本页选好参数后下载脚本包，在自己电脑上运行（平台不接触你的 CDS 凭证）。")

    with st.expander("[说明] 如何获取 ERA5 数据", expanded=False):
        st.markdown(_HELP_GET_DATA)

    # ---- 常用组合预设 ----
    preset_names = ["不使用预设"] + list(PRESETS)
    st.selectbox("常用组合预设", preset_names, key="era5_preset_pick",
                 on_change=_apply_preset,
                 help="选择后自动切换产品并勾选该组合包含的变量；仍可手动增减")

    product = st.selectbox("数据产品", list(ERA5_PRODUCTS), key="era5_product",
                           on_change=_reset_preset_marker)
    meta = ERA5_PRODUCTS[product]

    # ---- 产品说明卡 ----
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("分辨率", meta["resolution"])
    c2.metric("字段数上限", "{:,}".format(meta["field_limit"]))
    c3.metric("时间范围", meta["coverage"])
    c4.metric("product_type",
              "、".join(meta.get("product_type") or ["不适用"]))
    st.caption(meta["notes"])
    st.link_button("[打开] 该数据集 CDS 页面", meta["url"])

    # ---- 时间范围 ----
    c5, c6 = st.columns(2)
    with c5:
        years = st.multiselect("年份", available_years(), default=[2024],
                               key="era5_years",
                               help="ERA5 约滞后 2–3 个月，当年数据不完整故不列出")
    with c6:
        months = st.multiselect("月份", list(range(1, 13)), default=[1],
                                format_func=lambda m: "%d 月" % m,
                                key="era5_months")

    # ---- 气压层（仅气压层产品）----
    pressure_levels = []
    if meta["type"] == "pressure":
        pressure_levels = st.multiselect(
            "气压层 (hPa)", list(PRESSURE_LEVELS), default=["500", "850"],
            key="era5_pressure_levels",
            help="共 37 个有效层次；位势高度需用位势换算（÷9.80665）")

    # ---- 变量选择（按分组）----
    # 分组多选是变量的唯一真相源：预设直接写入各分组键，用户取消勾选即刻生效。
    # 不设产品级汇总键，避免「汇总只增不减」导致取消勾选无效。
    st.write("**变量选择**")
    group_cols = st.columns(2)
    variables = []
    for idx, group in enumerate(GROUP_ORDER):
        names = [n for n, info in meta["variables"].items() if info["group"] == group]
        if not names:
            continue
        gkey = "era5_pick_%s_%s" % (product, group)
        if gkey not in st.session_state:
            # 首次进入该产品：每组默认勾选第一个变量，避免空选择
            st.session_state[gkey] = names[:1]
        else:
            # 防御：产品/预设变更后旧值可能不属于当前分组
            st.session_state[gkey] = [v for v in st.session_state[gkey] if v in names]
        with group_cols[idx % 2]:
            picked = st.multiselect(
                group, names, key=gkey,
                format_func=lambda n, p=product: label_for(p, n),
                help="显示格式：中文名（API 变量名，单位，换算）")
        variables.extend(picked)
    variables = list(dict.fromkeys(variables))

    # ---- 不支持变量（可见但不可选，并给出替代路径）----
    unsupported = meta.get("unsupported") or {}
    if unsupported:
        st.write("**本产品不提供的变量**")
        for name, info in unsupported.items():
            cols = st.columns([4, 1])
            with cols[0]:
                st.caption("`%s`（%s）：%s" % (name, info["label"], info["reason"]))
            with cols[1]:
                target = info.get("switch_to")
                if target and target in ERA5_PRODUCTS:
                    st.button("切换到该产品", key="era5_switch_%s_%s" % (product, name),
                              on_click=_switch_product, args=(target,))

    # ---- 区域 ----
    st.write("**区域范围**")
    a1, a2, a3, a4 = st.columns(4)
    with a1:
        north = st.number_input("北界 (N)", value=41.0, min_value=-90.0,
                                max_value=90.0, step=0.1, key="era5_n")
    with a2:
        west = st.number_input("西界 (W)", value=115.0, min_value=-180.0,
                               max_value=180.0, step=0.1, key="era5_w")
    with a3:
        south = st.number_input("南界 (S)", value=39.0, min_value=-90.0,
                                max_value=90.0, step=0.1, key="era5_s")
    with a4:
        east = st.number_input("东界 (E)", value=118.0, min_value=-180.0,
                               max_value=180.0, step=0.1, key="era5_e")

    # ---- 组包与规模预警 ----
    if not years or not months or not variables:
        st.info("请至少选择年份、月份与一个变量。")
        return
    if meta["type"] == "pressure" and not pressure_levels:
        st.warning("气压层产品需要至少选择一个气压层。")
        return

    payload = build_payload(product, years, months, variables, pressure_levels,
                            [north, west, south, east])
    problems = validate_payload(product, payload)
    if problems:
        st.error("参数校验未通过：" + "；".join(problems))
        return

    count = estimate_field_count(product, years, months, variables, pressure_levels)
    limit = meta["field_limit"]
    if fields_over_limit(product, count):
        st.error("请求规模约 {:,} 个字段，超过该数据集上限 {:,}。"
                 "请缩小区域、减少变量或缩短时段后再生成脚本包。".format(count, limit))
    else:
        st.caption("请求规模约 {:,} 个字段（上限 {:,}）。".format(count, limit))

    st.write("---")
    if build_era5_zip is None:
        st.warning("脚本包模块不可用，请改用下方「在 CDS 官网手动填表」的参数清单。")
    elif not fields_over_limit(product, count):
        st.download_button(
            "[下载] ERA5 下载脚本包 (.zip)",
            data=build_era5_zip(payload, meta["dataset"], product),
            file_name="era5_download_pack.zip",
            mime="application/zip",
            use_container_width=True,
            help="包含 era5_download.py、.cdsapirc.example、README.txt、依赖清单与一键运行脚本",
        )

    with st.expander("在 CDS 官网手动填表（不使用脚本包时）", expanded=False):
        st.caption("以下为本次选择的参数，可逐项照抄到 CDS 数据集下载页的表单中。")
        st.code(_payload_preview(payload), language="text")
