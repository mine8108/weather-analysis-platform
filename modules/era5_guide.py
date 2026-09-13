"""ERA5 数据获取引导：变量 catalogue、请求参数构建、脚本包交付。

catalogue 是选择器与脚本生成的唯一真相源。所有变量标识符均已对
``research/era5_variable_enums_2026-09-13.json``（CDS constraints 接口实测快照）
校验，``validate_catalogue`` 在测试中保证其持续一致。

本模块只依赖标准库与 streamlit；应用侧永不 import cdsapi / xarray / netCDF4，
以保证 Streamlit Cloud 部署不因缺少这些重依赖而失败，也避免服务器内存风险。
"""

from datetime import datetime

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
