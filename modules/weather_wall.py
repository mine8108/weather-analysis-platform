"""天气墙：封面页城市天气卡片墙（Aether / Skies & Weather）。

- 默认预置全国 34 个省级行政区的省会/首府/直辖市/特区城市（含中国香港、
  中国澳门、中国台湾台北），无需手动添加即可直接查看；另附主要地级市库供搜索添加。
- 数据：Open-Meteo 当前天气，多坐标合并为单次批量请求，10 分钟缓存 + 失败降级。
- 场景：WMO weather_code + is_day 映射七种动态场景（晴/多云/小雨/飘雪/雷阵雨/薄雾/晴夜），
  全部纯 CSS 动画（零 JS），天然免疫 Streamlit rerun 重置问题。
- 状态：st.session_state["wall_cities"] 驱动，render() 数据驱动重绘。
"""

import streamlit as st

from utils import retry_with_backoff

# ============================================================
# 一、城市库
# ============================================================
# capital=True 的 34 城为默认展示；region 用于封面分组标题。
CITY_LIBRARY = [
    # ---- 华北 ----
    {"zh": "北京", "en": "Beijing", "lat": 39.90, "lon": 116.41, "region": "华北", "capital": True},
    {"zh": "天津", "en": "Tianjin", "lat": 39.13, "lon": 117.20, "region": "华北", "capital": True},
    {"zh": "石家庄", "en": "Shijiazhuang", "lat": 38.04, "lon": 114.51, "region": "华北", "capital": True},
    {"zh": "太原", "en": "Taiyuan", "lat": 37.87, "lon": 112.55, "region": "华北", "capital": True},
    {"zh": "呼和浩特", "en": "Hohhot", "lat": 40.84, "lon": 111.75, "region": "华北", "capital": True},
    {"zh": "张家口", "en": "Zhangjiakou", "lat": 40.77, "lon": 114.89, "region": "华北", "capital": False},
    {"zh": "秦皇岛", "en": "Qinhuangdao", "lat": 39.94, "lon": 119.60, "region": "华北", "capital": False},
    # ---- 东北 ----
    {"zh": "沈阳", "en": "Shenyang", "lat": 41.80, "lon": 123.43, "region": "东北", "capital": True},
    {"zh": "长春", "en": "Changchun", "lat": 43.88, "lon": 125.32, "region": "东北", "capital": True},
    {"zh": "哈尔滨", "en": "Harbin", "lat": 45.80, "lon": 126.53, "region": "东北", "capital": True},
    {"zh": "大连", "en": "Dalian", "lat": 38.91, "lon": 121.61, "region": "东北", "capital": False},
    {"zh": "延吉", "en": "Yanji", "lat": 42.91, "lon": 129.51, "region": "东北", "capital": False},
    # ---- 华东 ----
    {"zh": "上海", "en": "Shanghai", "lat": 31.23, "lon": 121.47, "region": "华东", "capital": True},
    {"zh": "南京", "en": "Nanjing", "lat": 32.06, "lon": 118.80, "region": "华东", "capital": True},
    {"zh": "杭州", "en": "Hangzhou", "lat": 30.27, "lon": 120.16, "region": "华东", "capital": True},
    {"zh": "合肥", "en": "Hefei", "lat": 31.86, "lon": 117.28, "region": "华东", "capital": True},
    {"zh": "福州", "en": "Fuzhou", "lat": 26.08, "lon": 119.30, "region": "华东", "capital": True},
    {"zh": "南昌", "en": "Nanchang", "lat": 28.68, "lon": 115.86, "region": "华东", "capital": True},
    {"zh": "济南", "en": "Jinan", "lat": 36.65, "lon": 117.12, "region": "华东", "capital": True},
    {"zh": "台北", "en": "Taipei, Taiwan, China", "lat": 25.03, "lon": 121.57, "region": "华东", "capital": True},
    {"zh": "苏州", "en": "Suzhou", "lat": 31.30, "lon": 120.62, "region": "华东", "capital": False},
    {"zh": "无锡", "en": "Wuxi", "lat": 31.49, "lon": 120.31, "region": "华东", "capital": False},
    {"zh": "宁波", "en": "Ningbo", "lat": 29.87, "lon": 121.55, "region": "华东", "capital": False},
    {"zh": "温州", "en": "Wenzhou", "lat": 27.99, "lon": 120.70, "region": "华东", "capital": False},
    {"zh": "青岛", "en": "Qingdao", "lat": 36.07, "lon": 120.38, "region": "华东", "capital": False},
    {"zh": "烟台", "en": "Yantai", "lat": 37.46, "lon": 121.45, "region": "华东", "capital": False},
    {"zh": "厦门", "en": "Xiamen", "lat": 24.48, "lon": 118.09, "region": "华东", "capital": False},
    {"zh": "泉州", "en": "Quanzhou", "lat": 24.87, "lon": 118.68, "region": "华东", "capital": False},
    # ---- 华中 ----
    {"zh": "郑州", "en": "Zhengzhou", "lat": 34.75, "lon": 113.63, "region": "华中", "capital": True},
    {"zh": "武汉", "en": "Wuhan", "lat": 30.59, "lon": 114.31, "region": "华中", "capital": True},
    {"zh": "长沙", "en": "Changsha", "lat": 28.23, "lon": 112.94, "region": "华中", "capital": True},
    {"zh": "洛阳", "en": "Luoyang", "lat": 34.62, "lon": 112.45, "region": "华中", "capital": False},
    # ---- 华南 ----
    {"zh": "广州", "en": "Guangzhou", "lat": 23.13, "lon": 113.26, "region": "华南", "capital": True},
    {"zh": "南宁", "en": "Nanning", "lat": 22.82, "lon": 108.37, "region": "华南", "capital": True},
    {"zh": "海口", "en": "Haikou", "lat": 20.04, "lon": 110.20, "region": "华南", "capital": True},
    {"zh": "中国香港", "en": "Hong Kong, China", "lat": 22.32, "lon": 114.17, "region": "华南", "capital": True},
    {"zh": "中国澳门", "en": "Macao, China", "lat": 22.20, "lon": 113.55, "region": "华南", "capital": True},
    {"zh": "深圳", "en": "Shenzhen", "lat": 22.54, "lon": 114.06, "region": "华南", "capital": False},
    {"zh": "珠海", "en": "Zhuhai", "lat": 22.27, "lon": 113.58, "region": "华南", "capital": False},
    {"zh": "汕头", "en": "Shantou", "lat": 23.35, "lon": 116.68, "region": "华南", "capital": False},
    {"zh": "湛江", "en": "Zhanjiang", "lat": 21.27, "lon": 110.36, "region": "华南", "capital": False},
    {"zh": "三亚", "en": "Sanya", "lat": 18.25, "lon": 109.51, "region": "华南", "capital": False},
    {"zh": "桂林", "en": "Guilin", "lat": 25.27, "lon": 110.29, "region": "华南", "capital": False},
    # ---- 西南 ----
    {"zh": "重庆", "en": "Chongqing", "lat": 29.56, "lon": 106.55, "region": "西南", "capital": True},
    {"zh": "成都", "en": "Chengdu", "lat": 30.57, "lon": 104.07, "region": "西南", "capital": True},
    {"zh": "贵阳", "en": "Guiyang", "lat": 26.65, "lon": 106.63, "region": "西南", "capital": True},
    {"zh": "昆明", "en": "Kunming", "lat": 24.88, "lon": 102.83, "region": "西南", "capital": True},
    {"zh": "拉萨", "en": "Lhasa", "lat": 29.65, "lon": 91.14, "region": "西南", "capital": True},
    {"zh": "丽江", "en": "Lijiang", "lat": 26.86, "lon": 100.23, "region": "西南", "capital": False},
    {"zh": "大理", "en": "Dali", "lat": 25.61, "lon": 100.27, "region": "西南", "capital": False},
    # ---- 西北 ----
    {"zh": "西安", "en": "Xi'an", "lat": 34.34, "lon": 108.94, "region": "西北", "capital": True},
    {"zh": "兰州", "en": "Lanzhou", "lat": 36.06, "lon": 103.83, "region": "西北", "capital": True},
    {"zh": "西宁", "en": "Xining", "lat": 36.62, "lon": 101.78, "region": "西北", "capital": True},
    {"zh": "银川", "en": "Yinchuan", "lat": 38.49, "lon": 106.23, "region": "西北", "capital": True},
    {"zh": "乌鲁木齐", "en": "Urumqi", "lat": 43.83, "lon": 87.62, "region": "西北", "capital": True},
    {"zh": "喀什", "en": "Kashgar", "lat": 39.47, "lon": 75.99, "region": "西北", "capital": False},
    {"zh": "敦煌", "en": "Dunhuang", "lat": 40.14, "lon": 94.66, "region": "西北", "capital": False},
]

REGION_ORDER = ["华北", "东北", "华东", "华中", "华南", "西南", "西北"]

_BY_ZH = {c["zh"]: c for c in CITY_LIBRARY}


def capital_cities() -> list[dict]:
    """默认展示的 34 个省会级城市（按 CITY_LIBRARY 定义顺序）。"""
    return [c for c in CITY_LIBRARY if c["capital"]]


def city_by_zh(zh: str) -> dict | None:
    return _BY_ZH.get(zh)


# ============================================================
# 二、数据层：Open-Meteo 批量当前天气
# ============================================================
@retry_with_backoff(max_retries=2, base_delay=1, backoff_factor=2, max_delay=8)
def _fetch_batch_retry(lats: tuple, lons: tuple):
    """多坐标合并单次请求，带指数退避重试（429/瞬断）。

    注意 retry_with_backoff 的失败契约是「返回降级缓存或 (None, msg)」，
    并不会抛异常，因此外层 _fetch_batch 必须校验类型后再交给缓存层。
    """
    import requests
    resp = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": ",".join(f"{v:.2f}" for v in lats),
            "longitude": ",".join(f"{v:.2f}" for v in lons),
            "current": ("temperature_2m,relative_humidity_2m,apparent_temperature,"
                        "weather_code,wind_speed_10m,is_day"),
            "daily": "temperature_2m_max,temperature_2m_min",
            "timezone": "auto",
            "forecast_days": 1,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else [data]


@st.cache_data(ttl=600, show_spinner=False)
def _fetch_batch(lats: tuple, lons: tuple) -> list:
    """批量请求缓存层（10 分钟 TTL）。

    st.cache_data 只缓存正常返回、不缓存异常，因此这里把 retry 层的
    失败契约转译为 raise：避免一次瞬断的失败结果被缓存 10 分钟。
    retry 层自带的降级缓存（_api_cache_*）若为 list 则直接返回使用。
    """
    rows = _fetch_batch_retry(lats, lons)
    if not isinstance(rows, list):
        detail = rows[1] if isinstance(rows, tuple) and len(rows) > 1 else rows
        raise RuntimeError(f"Open-Meteo 批量请求失败: {detail}")
    return rows


def fetch_wall_weather(cities: list[dict]) -> dict:
    """返回 {城市中文名: 天气字典}；失败时降级到上次成功的会话缓存。"""
    if not cities:
        return {}
    try:
        rows = _fetch_batch(
            tuple(c["lat"] for c in cities),
            tuple(c["lon"] for c in cities),
        )
        out = {}
        for c, row in zip(cities, rows):
            cur = row.get("current", {}) or {}
            daily = row.get("daily", {}) or {}
            out[c["zh"]] = {
                "temp": cur.get("temperature_2m"),
                "humidity": cur.get("relative_humidity_2m"),
                "wind": cur.get("wind_speed_10m"),
                "code": cur.get("weather_code"),
                "is_day": cur.get("is_day", 1),
                "t_max": (daily.get("temperature_2m_max") or [None])[0],
                "t_min": (daily.get("temperature_2m_min") or [None])[0],
            }
        # 成功结果写入会话缓存，供后续请求失败时降级
        st.session_state["_wall_fallback"] = out
        return out
    except Exception:
        return st.session_state.get("_wall_fallback", {})


def refresh_weather() -> None:
    """手动刷新：清空批量缓存，下一次渲染重新请求。"""
    _fetch_batch.clear()


# ============================================================
# 三、WMO 天气码 → 七场景映射
# ============================================================
SCENE_META = {
    "sunny":   {"zh": "晴",   "en": "Sunny"},
    "cloudy":  {"zh": "多云", "en": "Cloudy"},
    "rain":    {"zh": "小雨", "en": "Rainy"},
    "snow":    {"zh": "飘雪", "en": "Snowy"},
    "thunder": {"zh": "雷阵雨", "en": "Thunderstorm"},
    "fog":     {"zh": "薄雾", "en": "Misty"},
    "night":   {"zh": "晴夜", "en": "Clear Night"},
}

_WMO_THUNDER = {95, 96, 99}
_WMO_SNOW = {71, 73, 75, 77, 85, 86}
_WMO_RAIN = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82}
_WMO_FOG = {45, 48}
_WMO_CLOUDY = {2, 3}
_WMO_CLEAR = {0, 1}


def map_scene(code, is_day=1) -> str:
    """WMO weather_code + is_day → 七场景 key。未知码兜底多云。"""
    try:
        code = int(code)
    except (TypeError, ValueError):
        return "cloudy"
    if code in _WMO_THUNDER:
        return "thunder"
    if code in _WMO_SNOW:
        return "snow"
    if code in _WMO_RAIN:
        return "rain"
    if code in _WMO_FOG:
        return "fog"
    if code in _WMO_CLOUDY:
        return "cloudy"
    if code in _WMO_CLEAR:
        return "night" if not is_day else "sunny"
    return "cloudy"


# ============================================================
# 四、场景 HTML 生成（纯 CSS 动画，元素相位由 seed 确定性错开）
# ============================================================
def _clouds(classes: tuple, seed: int) -> str:
    """云朵分区错相：不同水平带 + 负 animation-delay，避免多朵云堆叠在同一起点。"""
    return "".join(
        f'<div class="ww-cloud {cls}" style="animation-delay:-{(seed * 7 + i * 13) % 40}s"></div>'
        for i, cls in enumerate(classes)
    )


def _sky_html(scene: str, seed: int) -> str:
    """按场景生成天空装饰层元素。seed 取卡片序号，保证 rerun 后相位稳定不闪动。"""
    if scene == "sunny":
        return '<div class="ww-sun"></div>' + _clouds(("cl1", "cl2"), seed)
    if scene == "cloudy":
        return _clouds(("cl0", "cl1", "cl2"), seed)
    if scene == "rain":
        drops = "".join(
            f'<i style="left:{5 + k * 11}%;animation-delay:-{((seed + k * 3) % 10) * 0.09:.2f}s"></i>'
            for k in range(9)
        )
        return _clouds(("cl0",), seed) + f'<div class="ww-rain">{drops}</div>'
    if scene == "snow":
        flakes = "".join(
            f'<i style="left:{4 + k * 10}%;animation-delay:-{((seed + k * 5) % 12) * 0.3:.2f}s"></i>'
            for k in range(10)
        )
        return _clouds(("cl1",), seed) + f'<div class="ww-snow">{flakes}</div>'
    if scene == "thunder":
        return (_clouds(("cl0", "cl1"), seed)
                + '<div class="ww-bolt"></div><div class="ww-flash"></div>')
    if scene == "fog":
        bands = "".join(f'<i class="fb{k}"></i>' for k in range(3))
        return f'<div class="ww-fog">{bands}</div>'
    if scene == "night":
        stars = "".join(
            f'<i style="left:{(seed * 11 + k * 17) % 92 + 3}%;top:{(seed * 5 + k * 23) % 46 + 4}%;'
            f'animation-delay:-{((seed + k * 7) % 8) * 0.4:.1f}s"></i>'
            for k in range(12)
        )
        return f'<div class="ww-stars">{stars}</div><div class="ww-moon"></div>' + _clouds(("cl2",), seed)
    return ""


def _fmt(v, suffix="", digits=0) -> str:
    """数值格式化，None 显示为 —。"""
    if v is None:
        return "—"
    try:
        return f"{float(v):.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return "—"


def card_html(city: dict, wx: dict | None, scene: str, idx: int = 0) -> str:
    """生成单张城市卡片 HTML。wx 为 None（数据不可用）时显示占位。"""
    meta = SCENE_META.get(scene, SCENE_META["cloudy"])
    if wx:
        temp = _fmt(wx.get("temp"), "°")
        sub = (f"↑{_fmt(wx.get('t_max'), '°')} ↓{_fmt(wx.get('t_min'), '°')}"
               f"　💧{_fmt(wx.get('humidity'), '%')}　🌬{_fmt(wx.get('wind'), ' m/s', 1)}")
        cond = f"{meta['zh']} · {meta['en']}"
    else:
        temp, cond, sub = "—", "数据加载中", "Loading…"
    delay = min(idx, 12) * 0.06  # 入场淡入逐卡延迟，超过 12 张后不再递增
    return f"""
<div class="ww-card sc-{scene}" style="animation-delay:{delay:.2f}s">
  <div class="ww-sky">{_sky_html(scene, idx)}</div>
  <div class="ww-shade"></div>
  <div class="ww-city">{city['zh']}<span class="ww-en">{city['en']}</span></div>
  <div class="ww-temp">{temp}</div>
  <div class="ww-cond">{cond}</div>
  <div class="ww-sub">{sub}</div>
</div>"""


# ============================================================
# 五、天气墙 CSS（天空色随主题变量，动画纯 CSS）
# ============================================================
def wall_css() -> str:
    return """
<style>
/* ===== 卡片骨架 ===== */
.ww-card { position:relative; height:172px; border-radius:18px 22px 16px 24px;
           overflow:hidden; animation:ww-in .55s cubic-bezier(.22,.8,.36,1) both; }
@keyframes ww-in { from { opacity:0; transform:translateY(14px);} to { opacity:1; transform:none;} }
.ww-sky { position:absolute; inset:0; }
.sc-sunny   .ww-sky { background:var(--ww-sunny); }
.sc-cloudy  .ww-sky { background:var(--ww-cloudy); }
.sc-rain    .ww-sky { background:var(--ww-rain); }
.sc-snow    .ww-sky { background:var(--ww-snow); }
.sc-thunder .ww-sky { background:var(--ww-thunder); }
.sc-fog     .ww-sky { background:var(--ww-fog); }
.sc-night   .ww-sky { background:var(--ww-night); }
/* 底部深色渐变罩：保证亮色天空（雪/雾）上的白字可读 */
.ww-shade { position:absolute; inset:0;
            background:linear-gradient(180deg, rgba(18,26,52,0) 30%, rgba(18,26,52,0.42) 100%); }

/* ===== 信息层 ===== */
.ww-city { position:absolute; top:10px; left:12px; background:rgba(16,24,48,0.38);
           color:#fff; padding:3px 11px; border-radius:999px; font-size:.8rem; font-weight:600; }
.ww-city .ww-en { opacity:.78; font-weight:400; margin-left:5px; font-size:.68rem; }
.ww-temp { position:absolute; left:15px; bottom:48px; font-family:var(--font-temp);
           font-size:2.3rem; font-weight:800; color:#fff; line-height:1;
           text-shadow:0 2px 8px rgba(18,26,52,.4); }
.ww-cond { position:absolute; left:16px; bottom:30px; color:#f2f5fc; font-size:.78rem;
           font-weight:600; text-shadow:0 1px 4px rgba(18,26,52,.5); }
.ww-sub  { position:absolute; left:16px; bottom:9px; color:rgba(255,255,255,.9);
           font-size:.68rem; text-shadow:0 1px 3px rgba(18,26,52,.5); }

/* ===== 分组标题 ===== */
.ww-region { font-family:var(--font-display); font-size:1.02rem; font-weight:600;
             color:var(--text-secondary); margin:14px 0 6px 2px; letter-spacing:.04em; }

/* ===== 云：三个尺寸档（cl0/cl1/cl2 上中下分区），transform 位移动画 ===== */
.ww-cloud { position:absolute; background:#fff; border-radius:999px; opacity:.92;
            animation:ww-drift linear infinite; }
.ww-cloud::before, .ww-cloud::after { content:""; position:absolute; border-radius:50%; background:#fff; }
.ww-cloud.cl0 { width:52px; height:18px; top:16px; animation-duration:32s; }
.ww-cloud.cl0::before { width:24px; height:24px; top:-12px; left:8px; }
.ww-cloud.cl0::after  { width:15px; height:15px; top:-7px; right:8px; }
.ww-cloud.cl1 { width:38px; height:14px; top:48px; opacity:.85; animation-duration:46s; }
.ww-cloud.cl1::before { width:18px; height:18px; top:-9px; left:6px; }
.ww-cloud.cl1::after  { width:11px; height:11px; top:-5px; right:6px; }
.ww-cloud.cl2 { width:28px; height:11px; top:78px; opacity:.7; animation-duration:58s; }
.ww-cloud.cl2::before { width:13px; height:13px; top:-6px; left:5px; }
.ww-cloud.cl2::after  { width:8px; height:8px; top:-4px; right:5px; }
@keyframes ww-drift { from { transform:translateX(-80px);} to { transform:translateX(460px);} }

/* ===== 太阳 ===== */
.ww-sun { position:absolute; top:14px; right:16px; width:36px; height:36px; border-radius:50%;
          background:radial-gradient(circle at 35% 35%, #fff6d8, #ffd76e);
          box-shadow:0 0 22px 6px rgba(255,214,110,.55);
          animation:ww-sunpulse 5s ease-in-out infinite; }
@keyframes ww-sunpulse { 0%,100% { transform:scale(1);} 50% { transform:scale(1.07);} }

/* ===== 雨 ===== */
.ww-rain i { position:absolute; top:34px; width:2px; height:12px; border-radius:2px;
             background:linear-gradient(#cfe6fb, rgba(207,230,251,0));
             animation:ww-rainfall .9s linear infinite; }
@keyframes ww-rainfall { from { transform:translateY(-12px); opacity:0;}
                         25% { opacity:1;} to { transform:translateY(96px); opacity:0;} }

/* ===== 雪 ===== */
.ww-snow i { position:absolute; top:30px; width:5px; height:5px; border-radius:50%;
             background:#fff; opacity:.95; animation:ww-snowfall 3.6s linear infinite; }
@keyframes ww-snowfall { from { transform:translate(0,-10px); opacity:0;}
                         20% { opacity:1;} to { transform:translate(10px,110px); opacity:.1;} }

/* ===== 雷暴：闪电形 + 全屏微闪 ===== */
.ww-bolt { position:absolute; top:36px; left:52%; width:20px; height:42px; background:#ffe27a;
           clip-path:polygon(55% 0, 15% 55%, 42% 55%, 30% 100%, 85% 42%, 55% 42%);
           filter:drop-shadow(0 0 6px rgba(255,226,122,.8));
           animation:ww-boltflash 3.4s infinite; }
.ww-flash { position:absolute; inset:0; background:rgba(255,244,200,.28);
            animation:ww-boltflash 3.4s infinite; }
@keyframes ww-boltflash { 0%,86%,100% { opacity:0;} 88%,93% { opacity:1;} 90.5% { opacity:.15;} }

/* ===== 雾 ===== */
.ww-fog i { position:absolute; height:12px; width:130%; left:-15%; border-radius:12px;
            background:rgba(255,255,255,.32); filter:blur(4px);
            animation:ww-fogslide 11s ease-in-out infinite alternate; }
.ww-fog .fb0 { top:26px; animation-duration:11s; }
.ww-fog .fb1 { top:56px; animation-duration:15s; animation-delay:-5s; }
.ww-fog .fb2 { top:88px; animation-duration:19s; animation-delay:-9s; }
@keyframes ww-fogslide { from { transform:translateX(-30px);} to { transform:translateX(30px);} }

/* ===== 晴夜：月亮 + 星闪 ===== */
.ww-moon { position:absolute; top:12px; right:15px; width:34px; height:34px; border-radius:50%;
           background:radial-gradient(circle at 38% 35%, #fdf3cf, #ecd9a0);
           box-shadow:0 0 18px 5px rgba(245,230,184,.4); }
.ww-moon::before { content:""; position:absolute; width:7px; height:7px; border-radius:50%;
                   background:rgba(190,170,120,.55); top:8px; left:9px;
                   box-shadow:10px 9px 0 -1px rgba(190,170,120,.45); }
.ww-stars i { position:absolute; width:3px; height:3px; border-radius:50%; background:#fff;
              animation:ww-twinkle 2.8s ease-in-out infinite; }
@keyframes ww-twinkle { 0%,100% { opacity:.25; transform:scale(.8);}
                        50% { opacity:1; transform:scale(1.15);} }

/* ===== 卡片容器（Streamlit border 容器）：hover 上浮 + 删除按钮定位 ===== */
[data-testid="stVerticalBlockBorderWrapper"]:has(.ww-card) {
    position:relative; padding:0 !important; overflow:hidden; border:none !important;
    background:transparent !important; box-shadow:var(--shadow-md) !important;
    transition:transform var(--transition), box-shadow var(--transition);
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.ww-card):hover {
    transform:translateY(-4px); box-shadow:var(--shadow-lg) !important;
}
/* 删除按钮：贴卡片右上角，hover 卡片时显现 */
[data-testid="stVerticalBlockBorderWrapper"]:has(.ww-card) .stButton {
    position:absolute; top:8px; right:8px; z-index:6; width:auto;
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.ww-card) .stButton > button {
    width:26px !important; height:26px; min-height:26px; padding:0 !important;
    border-radius:50% !important; border:none !important; line-height:1;
    background:rgba(16,24,48,.45) !important; color:#fff !important; font-size:.8rem;
    opacity:0; transition:opacity var(--transition), background var(--transition);
}
[data-testid="stVerticalBlockBorderWrapper"]:has(.ww-card):hover .stButton > button { opacity:1; }
[data-testid="stVerticalBlockBorderWrapper"]:has(.ww-card) .stButton > button:hover {
    background:rgba(200,60,60,.85) !important; transform:none;
}
/* 卡片容器内 markdown 去掉默认间距 */
[data-testid="stVerticalBlockBorderWrapper"]:has(.ww-card) [data-testid="stMarkdownContainer"] { margin:0; }

/* ===== 减弱动态偏好：全部动画静止（无障碍） ===== */
@media (prefers-reduced-motion: reduce) {
    .ww-card, .ww-card * { animation:none !important; }
}
</style>
"""


# ============================================================
# 六、渲染入口
# ============================================================
def _on_add_city() -> None:
    """selectbox on_change 回调：把选中的城市加入展示列表并重置选择框。

    回调在脚本重跑前执行，此时修改 widget 的 session_state 值是合法时机
    （widget 实例化之后直接改会报错）。
    """
    sel = st.session_state.get("wall_add_city")
    if sel:
        shown = st.session_state.setdefault("wall_cities", [])
        if sel["zh"] not in shown:
            shown.append(sel["zh"])
            st.toast(f"已添加 {sel['zh']} · {sel['en']}", icon="➕")
        st.session_state["wall_add_city"] = None


def render_wall() -> None:
    """渲染天气墙：搜索添加 + 分组卡片网格。状态全部走 session_state。"""
    # 需求 1：初始化预置 34 个省会级城市，无需手动添加
    if "wall_cities" not in st.session_state:
        st.session_state["wall_cities"] = [c["zh"] for c in capital_cities()]
    shown_zh: list[str] = st.session_state["wall_cities"]

    st.markdown(wall_css(), unsafe_allow_html=True)

    # ---- 搜索添加（已展示城市不再出现在候选中） ----
    candidates = [c for c in CITY_LIBRARY if c["zh"] not in shown_zh]
    c_search, c_refresh = st.columns([5, 1])
    with c_search:
        st.selectbox(
            "添加城市",
            candidates,
            index=None,
            key="wall_add_city",
            format_func=lambda c: f"{c['zh']} · {c['en']}" if c else "",
            placeholder="🔍 搜索并添加城市（中 / 英文）…",
            label_visibility="collapsed",
            on_change=_on_add_city,
        )
    with c_refresh:
        if st.button("🔄 刷新", key="wall_refresh", help="重新拉取最新天气数据",
                     use_container_width=True):
            refresh_weather()
            st.toast("天气数据已刷新", icon="🔄")
            st.rerun()

    if not shown_zh:
        st.info("天气墙空空如也。在上方搜索框添加城市，或刷新页面恢复默认省会列表。")
        return

    cities = [c for z in shown_zh if (c := city_by_zh(z)) is not None]

    # ---- 拉取天气（批量一次请求；首次有 spinner，之后 10 分钟缓存） ----
    with st.spinner("正在获取实时天气…"):
        weather = fetch_wall_weather(cities)
    if not weather:
        st.warning("⚠️ 天气服务暂时不可用，展示缓存/占位数据，稍后点「刷新」重试。")

    # ---- 按区域分组渲染（桌面 3 列，移动端经全局媒体查询转单列） ----
    groups: dict[str, list[dict]] = {}
    for c in cities:
        groups.setdefault(c["region"], []).append(c)

    idx = 0
    for region in REGION_ORDER:
        cs = groups.pop(region, None)
        if not cs:
            continue
        st.markdown(f'<div class="ww-region">· {region} ·</div>', unsafe_allow_html=True)
        for row_start in range(0, len(cs), 3):
            cols = st.columns(3)
            for j, city in enumerate(cs[row_start:row_start + 3]):
                with cols[j]:
                    with st.container(border=True):
                        wx = weather.get(city["zh"])
                        scene = map_scene(wx["code"], wx["is_day"]) if wx else "cloudy"
                        st.markdown(card_html(city, wx, scene, idx),
                                    unsafe_allow_html=True)
                        if st.button("✕", key=f"ww_del_{city['zh']}",
                                     help=f"移除 {city['zh']}"):
                            st.session_state["wall_cities"].remove(city["zh"])
                            st.toast(f"已移除 {city['zh']}", icon="🗑️")
                            st.rerun()
                    idx += 1
    # 兜底：region 不在 REGION_ORDER 的城市（防御未来库扩展漏配）
    for region, cs in groups.items():
        st.markdown(f'<div class="ww-region">· {region} ·</div>', unsafe_allow_html=True)
        for row_start in range(0, len(cs), 3):
            cols = st.columns(3)
            for j, city in enumerate(cs[row_start:row_start + 3]):
                with cols[j]:
                    with st.container(border=True):
                        wx = weather.get(city["zh"])
                        scene = map_scene(wx["code"], wx["is_day"]) if wx else "cloudy"
                        st.markdown(card_html(city, wx, scene, idx),
                                    unsafe_allow_html=True)
                        if st.button("✕", key=f"ww_del_{city['zh']}",
                                     help=f"移除 {city['zh']}"):
                            st.session_state["wall_cities"].remove(city["zh"])
                            st.toast(f"已移除 {city['zh']}", icon="🗑️")
                            st.rerun()
                    idx += 1
