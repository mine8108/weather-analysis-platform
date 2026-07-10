"""
气象数据交互分析平台 - 配置模块
包含：国家预警标准阈值、字段映射、风力等级表、防御指南文本、配色方案
"""

# ============================================================
# 一、字段映射：常见气象数据列名 → 标准字段名
# ============================================================
FIELD_ALIASES = {
    # ---- 时间戳 (扩展) ----
    "时间": "timestamp",
    "日期": "timestamp",
    "时刻": "timestamp",
    "datetime": "timestamp",
    "date": "timestamp",
    "time": "timestamp",
    "valid_time": "timestamp",
    "观测时间": "timestamp",
    "观测时次": "timestamp",
    "记录时间": "timestamp",
    "采集时间": "timestamp",
    "数据时间": "timestamp",
    "资料时间": "timestamp",
    "年月日": "timestamp",
    "TIMESTAMP": "timestamp",
    "obs_time": "timestamp",
    "record_time": "timestamp",
    "t": "timestamp",
    "温度": "temperature",
    "气温": "temperature",
    "temp": "temperature",
    "温度(℃)": "temperature",
    "temperature": "temperature",
    "t2m": "temperature",
    "2m_temperature": "temperature",
    "t": "temperature",
    "气压": "pressure",
    "本站气压": "pressure",
    "海平面气压": "pressure",
    "pressure": "pressure",
    "pres": "pressure",
    "sp": "pressure",
    "surface_pressure": "pressure",
    "msl": "pressure",
    "mean_sea_level_pressure": "pressure",
    "湿度": "humidity",
    "相对湿度": "humidity",
    "rh": "humidity",
    "humidity": "humidity",
    "r": "humidity",
    "relative_humidity": "humidity",
    "比湿": "specific_humidity",
    "specific_humidity": "specific_humidity",
    "q": "specific_humidity",
    "露点温度": "dewpoint",
    "露点": "dewpoint",
    "dewpoint_temperature": "dewpoint",
    "dewpoint": "dewpoint",
    "d2m": "dewpoint",
    "2m_dewpoint_temperature": "dewpoint",
    "风速": "wind_speed",
    "wind_speed": "wind_speed",
    "ws": "wind_speed",
    "10m_wind_speed": "wind_speed",
    "si10": "wind_speed",
    "风向": "wind_direction",
    "wind_direction": "wind_direction",
    "wd": "wind_direction",
    "10m_wind_direction": "wind_direction",
    "纬向风": "wind_u",
    "u_component_of_wind": "wind_u",
    "u10": "wind_u",
    "10m_u_component_of_wind": "wind_u",
    "u": "wind_u",
    "经向风": "wind_v",
    "v_component_of_wind": "wind_v",
    "v10": "wind_v",
    "10m_v_component_of_wind": "wind_v",
    "v": "wind_v",
    "云量": "cloud_cover",
    "总云量": "cloud_cover",
    "cloud": "cloud_cover",
    "cloud_cover": "cloud_cover",
    "tcc": "cloud_cover",
    "total_cloud_cover": "cloud_cover",
    "能见度": "visibility",
    "visibility": "visibility",
    "vis": "visibility",
    "天气现象": "weather_code",
    "天气码": "weather_code",
    "weather": "weather_code",
    "weather_code": "weather_code",
    "降水量": "precipitation",
    "降雨量": "precipitation",
    "雨量": "precipitation",
    "precipitation": "precipitation",
    "precip": "precipitation",
    "tp": "precipitation",
    "total_precipitation": "precipitation",
    "位势高度": "geopotential",
    "位势": "geopotential",
    "geopotential": "geopotential",
    "z": "geopotential",
    "地表温度": "skin_temperature",
    "skin_temperature": "skin_temperature",
    "skt": "skin_temperature",
    "垂直速度": "vertical_velocity",
    "vertical_velocity": "vertical_velocity",
    "w": "vertical_velocity",
    "雪深": "snow_depth",
    "snow_depth": "snow_depth",
    "sd": "snow_depth",
    "站点": "station_id",
    "站号": "station_id",
    "station": "station_id",
    "station_id": "station_id",
    "经度": "longitude",
    "纬度": "latitude",
    "lon": "longitude",
    "lat": "latitude",
    "longitude": "longitude",
    "latitude": "latitude",
    # ---- 英文列名（Excel/METAR 常用） ----
    "windSpeed": "wind_speed",
    "wind_speed": "wind_speed",
    "windDirection": "wind_direction",
    "wind_direction": "wind_direction",
    "meanWindSpeed": "mean_wind_speed",
    "mean_wind_speed": "mean_wind_speed",
    "temperature": "temperature",
    "humidity": "humidity",
    "pressure": "pressure",
    "precipitation": "precipitation",
    "cloud_cover": "cloud_cover",
    "visibility": "visibility",
    "weather_code": "weather_code",
    "station_id": "station_id",
    "Unnamed: 0": "timestamp",  # pandas 读取无标题列时的默认名
    "unnamed": "timestamp",
    "timestamp": "timestamp",
    "time": "timestamp",
    "date": "timestamp",
    "datetime": "timestamp",
    "obs_time": "timestamp",
    "record_time": "timestamp",
    "t": "timestamp",
    "TIMESTAMP": "timestamp",
    # 补充时间相关列
    "观测时间": "timestamp",
    "观测时次": "timestamp",
    "记录时间": "timestamp",
    "采集时间": "timestamp",
    "数据时间": "timestamp",
    "资料时间": "timestamp",
    "年月日": "timestamp",
    "时刻": "timestamp",
    "时间": "timestamp",
    "日期": "timestamp",

    # ---- 大气污染物 ----
    "二氧化硫": "so2",
    "so2": "so2",
    "SO2": "so2",
    "硫氧化物": "so2",
    "氮氧化物": "nox",
    "nox": "nox",
    "NOx": "nox",
    "NOX": "nox",
    "总悬浮颗粒物": "tsp",
    "tsp": "tsp",
    "TSP": "tsp",
    "pm2.5": "pm25",
    "PM2.5": "pm25",
    "pm2_5": "pm25",
    "PM2_5": "pm25",
    "细颗粒物": "pm25",
    "pm10": "pm10",
    "PM10": "pm10",
    "pm_10": "pm10",
    "PM_10": "pm10",
    "可吸入颗粒物": "pm10",
}

STANDARD_FIELDS = [
    "timestamp", "temperature", "pressure", "humidity",
    "wind_speed", "wind_direction", "cloud_cover", "visibility",
    "weather_code", "precipitation", "station_id", "longitude", "latitude",
    "so2", "nox", "tsp", "pm25", "pm10",
]

REQUIRED_FIELDS = ["timestamp"]

# 各字段的有效范围
FIELD_RANGES = {
    "temperature": (-50, 55),
    "pressure": (500, 1100),
    "humidity": (0, 100),
    "wind_speed": (0, 75),
    "wind_direction": (0, 360),
    "cloud_cover": (0, 10),
    "visibility": (0, 100),
    "precipitation": (0, 500),
    # 大气污染物
    "so2": (0, 500),       # SO₂ μg/m³
    "nox": (0, 500),       # NOx μg/m³
    "tsp": (0, 1000),      # TSP μg/m³
    "pm25": (0, 500),      # PM2.5 μg/m³
    "pm10": (0, 1000),     # PM10 μg/m³
}

# ============================================================
# 二、国家预警标准阈值（气象灾害预警信号发布与传播办法·第16号令）
# ============================================================

# --- 高温预警 ---
HIGH_TEMP_WARNING = {
    "黄色": {"condition": "连续3天日最高气温≥35℃", "temp": 35, "days": 3, "level": "Ⅲ级", "icon": "[晴]"},
    "橙色": {"condition": "24h内最高气温≥37℃", "temp": 37, "hours": 24, "level": "Ⅱ级", "icon": "[火]"},
    "红色": {"condition": "24h内最高气温≥40℃", "temp": 40, "hours": 24, "level": "Ⅰ级", "icon": "[红]"},
}

# --- 寒潮预警 ---
COLD_WAVE_WARNING = {
    "蓝色": {
        "level": "Ⅳ级", "icon": "[蓝]",
        "temp_drop": 8, "min_temp": 4, "hours": 48, "wind_level": 5,
        "condition": "48h降温≥8℃且最低气温≤4℃"
    },
    "黄色": {
        "level": "Ⅲ级", "icon": "[黄]",
        "temp_drop": 10, "min_temp": 4, "hours": 24, "wind_level": 6,
        "condition": "24h降温≥10℃且最低气温≤4℃"
    },
    "橙色": {
        "level": "Ⅱ级", "icon": "[橙]",
        "temp_drop": 12, "min_temp": 0, "hours": 24, "wind_level": 6,
        "condition": "24h降温≥12℃且最低气温≤0℃"
    },
    "红色": {
        "level": "Ⅰ级", "icon": "[红]",
        "temp_drop": 16, "min_temp": 0, "hours": 24, "wind_level": 6,
        "condition": "24h降温≥16℃且最低气温≤0℃"
    },
}

# --- 大风预警 ---
GALE_WARNING = {
    "蓝色": {
        "level": "Ⅳ级", "icon": "[蓝]",
        "avg_wind": 10.8, "gust": None, "hours": 24,
        "condition": "24h内平均风力≥6级(10.8m/s)或阵风≥7级"
    },
    "黄色": {
        "level": "Ⅲ级", "icon": "[黄]",
        "avg_wind": 17.2, "gust": None, "hours": 12,
        "condition": "12h内平均风力≥8级(17.2m/s)或阵风≥9级"
    },
    "橙色": {
        "level": "Ⅱ级", "icon": "[橙]",
        "avg_wind": 24.5, "gust": None, "hours": 6,
        "condition": "6h内平均风力≥10级(24.5m/s)或阵风≥11级"
    },
    "红色": {
        "level": "Ⅰ级", "icon": "[红]",
        "avg_wind": 32.7, "gust": None, "hours": 6,
        "condition": "6h内平均风力≥12级(32.7m/s)或阵风≥13级"
    },
}

# --- 大雾预警 ---
FOG_WARNING = {
    "黄色": {"level": "Ⅲ级", "icon": "[黄]", "visibility": 500, "hours": 12,
              "condition": "能见度<500m"},
    "橙色": {"level": "Ⅱ级", "icon": "[橙]", "visibility": 200, "hours": 6,
              "condition": "能见度<200m"},
    "红色": {"level": "Ⅰ级", "icon": "[红]", "visibility": 50, "hours": 2,
              "condition": "能见度<50m"},
}

# --- 暴雨预警 ---
RAINSTORM_WARNING = {
    "蓝色": {"level": "Ⅳ级", "icon": "[蓝]", "rain": 50, "hours": 12,
              "condition": "12h降雨量≥50mm"},
    "黄色": {"level": "Ⅲ级", "icon": "[黄]", "rain": 50, "hours": 6,
              "condition": "6h降雨量≥50mm"},
    "橙色": {"level": "Ⅱ级", "icon": "[橙]", "rain": 50, "hours": 3,
              "condition": "3h降雨量≥50mm"},
    "红色": {"level": "Ⅰ级", "icon": "[红]", "rain": 100, "hours": 3,
              "condition": "3h降雨量≥100mm"},
}

# --- 霜冻预警 ---
FROST_WARNING = {
    "蓝色": {"level": "Ⅳ级", "icon": "[蓝]", "ground_temp": 0, "hours": 48,
              "condition": "48h内地面最低温度≤0℃"},
    "黄色": {"level": "Ⅲ级", "icon": "[黄]", "ground_temp": -3, "hours": 24,
              "condition": "24h内地面最低温度≤-3℃"},
    "橙色": {"level": "Ⅱ级", "icon": "[橙]", "ground_temp": -5, "hours": 24,
              "condition": "24h内地面最低温度≤-5℃"},
}

# --- 雷电预警 ---
THUNDER_WARNING = {
    "黄色": {"level": "Ⅲ级", "icon": "[雷电]", "condition": "6h内可能发生雷电活动"},
    "橙色": {"level": "Ⅱ级", "icon": "[雷电]", "condition": "2h内发生雷电可能性很大"},
    "红色": {"level": "Ⅰ级", "icon": "[雷电]", "condition": "2h内发生雷电可能性非常大"},
}

# --- 霾预警 ---
HAZE_WARNING = {
    "黄色": {"level": "Ⅲ级", "icon": "[黄]", "visibility": 3000, "hours": 12,
              "condition": "能见度<3000m（霾）"},
    "橙色": {"level": "Ⅱ级", "icon": "[橙]", "visibility": 2000, "hours": 6,
              "condition": "能见度<2000m（霾）"},
}

# ============================================================
# 三、蒲福风力等级表
# ============================================================
BEAUFORT_SCALE = {
    0: {"name": "无风", "speed_range": (0, 0.2)},
    1: {"name": "软风", "speed_range": (0.3, 1.5)},
    2: {"name": "轻风", "speed_range": (1.6, 3.3)},
    3: {"name": "微风", "speed_range": (3.4, 5.4)},
    4: {"name": "和风", "speed_range": (5.5, 7.9)},
    5: {"name": "清风", "speed_range": (8.0, 10.7)},
    6: {"name": "强风", "speed_range": (10.8, 13.8)},
    7: {"name": "劲风", "speed_range": (13.9, 17.1)},
    8: {"name": "大风", "speed_range": (17.2, 20.7)},
    9: {"name": "烈风", "speed_range": (20.8, 24.4)},
    10: {"name": "狂风", "speed_range": (24.5, 28.4)},
    11: {"name": "暴风", "speed_range": (28.5, 32.6)},
    12: {"name": "台风/飓风", "speed_range": (32.7, 999)},
}

WIND_DIRECTIONS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                   "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def get_beaufort_level(speed_ms):
    """根据风速(m/s)返回蒲福风级"""
    for level, info in sorted(BEAUFORT_SCALE.items()):
        lo, hi = info["speed_range"]
        if lo <= speed_ms <= hi:
            return level, info["name"]
    return 12, "台风/飓风"


def get_wind_direction_name(deg):
    """将风向角度转为16方位名"""
    idx = int((deg + 11.25) / 22.5) % 16
    return WIND_DIRECTIONS[idx]


def get_dominant_wind_direction(deg_series):
    """计算频率主导风向（与 get_wind_direction_name 同分区，与玫瑰图一致）。
    返回 (主导方向名, 频率, 次数)。"""
    if deg_series is None or len(deg_series) == 0:
        return None, 0, 0
    counts = {}
    for d in deg_series:
        d_name = get_wind_direction_name(d)
        counts[d_name] = counts.get(d_name, 0) + 1
    n = len(deg_series)
    dominant = max(counts, key=counts.get)
    freq = counts[dominant] / n
    return dominant, freq, counts[dominant]


# ============================================================
# 四、防御指南文本库（公众出行 + 农业生产）
# ============================================================

# 公众出行建议
PUBLIC_ADVICE = {
    "高温": {
        "黄色": "午后尽量减少户外活动；对老弱病幼人群提供防暑降温指导；高温作业人员需采取防护措施。",
        "橙色": "尽量避免高温时段户外活动；缩短高温作业连续工作时间；注意用电安全，防范电力负载过大引发火灾。",
        "红色": "停止户外露天作业（特殊行业除外）；对老弱病幼人群采取保护措施；特别注意防火。",
    },
    "寒潮": {
        "蓝色": "注意添衣保暖；对热带作物采取防护措施；做好防风准备。",
        "黄色": "注意添衣保暖，照顾好老弱病人；牲畜家禽及农作物采取防寒措施；做好防风工作。",
        "橙色": "注意防寒保暖；农业、水产业、畜牧业采取防霜冻冰冻等防寒措施；做好防风工作。",
        "红色": "注意防寒保暖；农业水产业畜牧业积极采取防霜冻冰冻措施；做好防风工作。",
    },
    "大风": {
        "蓝色": "关好门窗，加固搭建物；行人少骑自行车，勿在广告牌等下方逗留；注意森林防火。",
        "黄色": "停止户外高空危险作业；危房人员转移至避风场所；加固港口设施。",
        "橙色": "中小学校及单位停课停业；人员减少外出；切断危险电源；机场铁路高速公路采取措施保障安全。",
        "红色": "人员尽可能留在室内；不要随意外出；机场铁路高速公路采取交通安全管制措施。",
    },
    "大雾": {
        "黄色": "机场、高速公路加强交通管理；驾驶人员注意雾的变化，小心驾驶；户外活动注意安全。",
        "橙色": "驾驶人员严格控制车速；机场高速公路轮渡加强调度指挥；减少户外活动。",
        "红色": "适时采取交通安全管制（机场停飞、高速封闭、轮渡停航）；不要进行户外活动。",
    },
    "暴雨": {
        "蓝色": "检查城市农田排水系统；驾驶人员注意道路积水；学校幼儿园保证学生安全。",
        "黄色": "交通管制强降雨路段；切断低洼地带危险电源；转移危房居民。",
        "橙色": "切断有危险的室外电源，暂停户外作业；处于危险地带的单位停课停业；防范山洪滑坡泥石流。",
        "红色": "停止集会、停课、停业（特殊行业除外）；做好山洪滑坡泥石流等灾害防御和抢险。",
    },
    "雷电": {
        "黄色": "密切关注天气，尽量避免户外活动。",
        "橙色": "留在室内并关好门窗；户外人员躲入有防雷设施的建筑物或汽车内；勿在树下塔吊下避雨。",
        "红色": "躲入有防雷设施的建筑物内；切勿接触天线水管金属门窗等；密切注意预警发布。",
    },
    "霜冻": {
        "蓝色": "对农作物蔬菜花卉采取防护措施；关注霜冻预警信息。",
        "黄色": "对农作物采取田间灌溉等防霜冻措施；对蔬菜花卉采取覆盖喷洒防冻液等措施。",
        "橙色": "对农作物蔬菜花卉瓜果林业育种采取积极应对措施，尽量减少损失。",
    },
}

# 农业生产建议
AGRI_ADVICE = {
    "高温": {
        "黄色": "及时灌溉降温，保持土壤湿度；设施农业注意通风降温；禽畜舍加强通风和遮阳。",
        "橙色": "增加灌溉频次；大棚覆盖遮阳网；禽畜采取喷淋降温措施；暂停白天施药和施肥。",
        "红色": "全面启动抗旱灌溉设备；设施农业强制通风降温；禽畜舍喷淋+风扇降温；停止一切田间作业。",
    },
    "寒潮": {
        "蓝色": "设施农业检查棚膜完整性；果园采取熏烟防霜；禽畜舍关闭门窗。",
        "黄色": "大棚加盖保温被；果园树干涂白；禽畜舍增加保温层；热带作物覆盖防寒。",
        "橙色": "设施农业启动加温设备；果园全面熏烟防霜；水产养殖加深水位；不耐寒畜禽转入暖棚。",
        "红色": "设施农业全力保温增温；全面防护农林作物；水产养殖应急增温；暂停一切室外农事活动。",
    },
    "大风": {
        "蓝色": "加固大棚压膜线；收起晾晒物；检查禽畜舍牢固性。",
        "黄色": "停止喷药和灌溉作业；加固设施农业骨架；收起室外农具。",
        "橙色": "全面检查加固农业设施；大棚采取防风加固措施；暂停一切高空农事作业。",
        "红色": "设施农业全面加固；人员撤离农业设施；暂停所有户外农事活动。",
    },
    "大雾": {
        "黄色": "推迟露天施药作业；设施农业注意调控温湿度；注意运输安全。",
        "橙色": "停止露天施药；设施农业减少通风；推迟采收和运输。",
        "红色": "暂停一切田间作业；设施农业密闭管理；停止农产品运输。",
    },
    "暴雨": {
        "蓝色": "清沟排水；检查农田排水系统；设施农业检查排水沟。",
        "黄色": "疏通田间排水沟渠；加固大棚基础；鱼塘检查防逃设施。",
        "橙色": "全力疏通排水系统；设施农业加固防涝；鱼塘设置防逃网；暂停施肥和施药。",
        "红色": "紧急排水排涝；设施农业全力防护；水产养殖应急防逃；暂停一切农事活动。",
    },
    "霜冻": {
        "蓝色": "对蔬菜花卉覆盖薄膜或无纺布；果园准备熏烟材料；冬小麦镇压保墒。",
        "黄色": "蔬菜大棚加盖草帘；果园夜间熏烟防霜；喜温作物提前收获；灌溉提高地温。",
        "橙色": "全面覆盖保护蔬菜花卉；果园集中熏烟；大棚加温；已成熟作物紧急抢收。",
    },
}


# ============================================================
# 五、配色方案
# ============================================================
COLORS = {
    "primary": "#1f77b4",
    "secondary": "#ff7f0e",
    "success": "#2ca02c",
    "danger": "#d62728",
    "warning": "#ffbb00",
    "info": "#17becf",
    "purple": "#9467bd",
    "pink": "#e377c2",
    # 预警颜色
    "warn_blue": "#0066cc",
    "warn_yellow": "#f5a623",
    "warn_orange": "#f26522",
    "warn_red": "#d0021b",
    # 图表色系
    "temp_color": "#e74c3c",
    "pres_color": "#27ae60",
    "humid_color": "#3498db",
    "wind_color": "#f39c12",
    "vis_color": "#9b59b6",
    "rain_color": "#2980b9",
    # 大气污染物色系
    "so2_color": "#d4a017",    # SO₂ 硫磺黄
    "nox_color": "#c0504d",    # NOx 铁锈红棕
    "tsp_color": "#8b7355",    # TSP 灰棕
    "pm25_color": "#5b7a9e",   # PM2.5 灰蓝
    "pm10_color": "#6b5b7a",   # PM10 灰紫
}

# 预警级别样式
WARN_STYLES = {
    "蓝色": {"color": "#0066cc", "bg": "#e6f0ff", "text_color": "white"},
    "黄色": {"color": "#f5a623", "bg": "#fff8e6", "text_color": "#333"},
    "橙色": {"color": "#f26522", "bg": "#fff0e6", "text_color": "white"},
    "红色": {"color": "#d0021b", "bg": "#ffe6e6", "text_color": "white"},
}

# ============================================================
# 六、Streamlit 页面配置
# ============================================================
PAGE_CONFIG = {
    "page_title": "气象数据交互分析平台",
    "page_icon": "W",
    "layout": "wide",
    "initial_sidebar_state": "expanded",
}

# ============================================================
# 七、天气现象编码表（WMO 部分常见码）
# ============================================================
WMO_WEATHER_CODES = {
    0: "晴/无重要天气",
    1: "云量减少",
    2: "云量无变化",
    3: "云量增加",
    4: "烟/霾",
    5: "霾",
    10: "轻雾",
    11: "浅雾/碎雾",
    12: "连续薄雾",
    20: "毛毛雨（间歇/轻微）",
    21: "毛毛雨（连续/轻微）",
    50: "间歇性小雨",
    51: "连续性小雨",
    60: "间歇性中雨",
    61: "连续性中雨",
    70: "间歇性小雪",
    71: "连续性小雪",
    80: "阵雨",
    81: "中阵雨",
    82: "强阵雨",
    85: "小阵雪",
    86: "中或强阵雪",
    95: "雷暴（小或中）",
    96: "雷暴伴有冰雹（小或中）",
    97: "强雷暴",
    99: "强雷暴伴有冰雹",
}


# ============================================================
# 八、全局调试模式与单图崩溃防护
# ============================================================
def get_debug_mode():
    """返回当前调试模式 (从 streamlit session_state 读取，外部调用时默认 False)。"""
    try:
        import streamlit as st
        return st.session_state.get("debug_mode", False)
    except Exception:
        return False


def safe_chart(fig, section_label, *, use_container_width=True, key=None):
    """受保护的图表渲染：正常模式显式错误报告，异常时捕获并显示分层次、通俗化的错误摘要。

    参数：
      fig: plotly Figure 对象
      section_label: 图表区块名称（如 "温度时序图"），用于错误报告中定位
    """
    import streamlit as st
    import traceback

    try:
        kwargs = {"use_container_width": use_container_width}
        if key:
            kwargs["key"] = key
        st.plotly_chart(fig, **kwargs)
    except Exception as e:
        debug = get_debug_mode()
        err_type = type(e).__name__

        # 通俗化错误摘要：从 Python 异常类型映射到中文描述
        _FRIENDLY_MAP = {
            "ValueError": "参数值越界",
            "TypeError": "类型不匹配",
            "KeyError": "缺少必要字段",
            "IndexError": "数组下标越界",
            "AttributeError": "对象属性缺失",
            "RuntimeError": "运行时异常",
        }
        cause = _FRIENDLY_MAP.get(err_type, f"未知错误 ({err_type})")

        if debug:
            # 调试模式：折叠显示完整 traceback 供排查
            st.warning(f"[图表 {cause}] 「{section_label}」渲染失败，详细信息如下。")
            st.code(traceback.format_exc(), language="python")
        else:
            # 普通模式：一行可读摘要
            st.error(
                f"[图表 {cause}] 「{section_label}」渲染失败，"
                f"可在侧边栏开启「调试模式」查看详情。"
            )


# ============================================================
# 九、常见错误中文翻译表（供 safe_chart 之外独立使用）
# ============================================================
ERROR_TRANSLATIONS = {
    "ValueError": "参数值越界",
    "TypeError": "类型不匹配",
    "KeyError": "缺少必要字段",
    "IndexError": "数组下标越界",
    "AttributeError": "对象属性缺失",
    "RuntimeError": "运行时异常",
    "ConnectionError": "网络连接失败",
    "TimeoutError": "请求超时",
    "OSError": "文件系统错误",
    "FileNotFoundError": "文件未找到",
    "PermissionError": "无权限访问",
    "MemoryError": "内存不足",
}
