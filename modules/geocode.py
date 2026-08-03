"""地理编码模块：城市名 ↔ 经纬度双向解析。

- forward_geocode(name)：正向地理编码（城市名 → 候选列表）。
  数据源 Open-Meteo Geocoding API（实测支持中文、重名返回多候选、未匹配返回空）。
- reverse_geocode(lat, lon)：反向地理编码（经纬度 → 城市中文名）。
  数据源 BigDataCloud（实测返回 307 重定向，requests 默认跟随；
  city 字段可能带"市"后缀或为空，按 city → locality → principalSubdivision 回退清洗）。
- 两个函数均带 st.cache_data 缓存（1 小时），失败返回空列表/None 由调用方降级。
"""

import re

import streamlit as st

from utils import retry_with_backoff

_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
_REVERSE_URL = "https://api.bigdatacloud.net/data/reverse-geocode-client"


# ============================================================
# 一、正向：城市名 → 候选列表（重名歧义返回多候选）
# ============================================================
@st.cache_data(ttl=3600, show_spinner=False)
@retry_with_backoff(max_retries=2, base_delay=1, backoff_factor=2, max_delay=8)
def _geocode_search_raw(name: str) -> list:
    """调用 Open-Meteo Geocoding。失败契约见 retry_with_backoff：
    返回降级缓存或 (None, msg)，由缓存层校验并转译为异常。"""
    import requests
    resp = requests.get(
        _GEOCODING_URL,
        params={"name": name, "count": 10, "language": "zh", "format": "json"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("results") or []


@st.cache_data(ttl=3600, show_spinner=False)
def forward_geocode(name: str) -> list[dict]:
    """城市名 → 候选列表，每项含 name/admin1/country/latitude/longitude/feature_code。

    非空校验：retry 层失败返回的 (None, msg) 在此转译为异常，
    避免失败结果被 cache_data 缓存 10 分钟（项目验证纪律，见 _fetch_batch）。
    """
    name = (name or "").strip()
    if not name:
        return []
    rows = _geocode_search_raw(name)
    if not isinstance(rows, list):
        raise RuntimeError(f"地理编码服务失败: {rows}")
    out = []
    for r in rows:
        lat, lon = r.get("latitude"), r.get("longitude")
        if lat is None or lon is None:
            continue
        out.append({
            "name": r.get("name", name),
            "admin1": r.get("admin1", ""),
            "country": r.get("country", ""),
            "lat": float(lat),
            "lon": float(lon),
            "feature_code": r.get("feature_code", ""),
        })
    return out


def format_candidate(c: dict) -> str:
    """候选显示文案：城市名（省份/国家），用于 selectbox 歧义选择。"""
    parts = [c["name"]]
    if c.get("admin1"):
        parts.append(c["admin1"])
    if c.get("country"):
        parts.append(c["country"])
    return " · ".join(parts)


# ============================================================
# 二、反向：经纬度 → 城市中文名（BigDataCloud）
# ============================================================
def _clean_city_name(raw: str | None) -> str:
    """清洗城市名：去"市/区"等行政后缀，避免卡片上出现「北京市」这种冗余。"""
    if not raw:
        return ""
    s = str(raw).strip()
    for suf in ("市", "区", "县", "盟", "旗"):
        if s.endswith(suf) and len(s) > len(suf):
            return s[: -len(suf)]
    return s


@st.cache_data(ttl=3600, show_spinner=False)
@retry_with_backoff(max_retries=2, base_delay=1, backoff_factor=2, max_delay=8)
def reverse_geocode(lat: float, lon: float) -> str:
    """经纬度 → 城市中文名；失败返回 ""（调用方降级为「经纬度 (lat, lon)」）。

    回退链：city → locality → principalSubdivision（乡村/边缘区域 city 可能为空）。
    """
    import requests
    try:
        resp = requests.get(
            _REVERSE_URL,
            params={"latitude": float(lat), "longitude": float(lon),
                    "localityLanguage": "zh"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return ""  # 失败统一返回空串，调用方降级为「经纬度 (lat, lon)」
    if not isinstance(data, dict):
        return ""
    for key in ("city", "locality", "principalSubdivision"):
        name = _clean_city_name(data.get(key))
        if name:
            return name
    return ""


def parse_lat_lon(text: str):
    """解析 '39.9,116.4' 或 '39.9，116.4' 格式的经纬度输入。

    返回 (lat, lon) 或 None（不匹配）。匹配规则：两个数字，逗号/空格分隔，
    纬度范围 [-90, 90]，经度范围 [-180, 180]。
    """
    text = (text or "").strip().replace("，", ",").replace(" ", ",")
    parts = [p for p in re.split(r"[,\s]+", text) if p]
    if len(parts) != 2:
        return None
    try:
        lat, lon = float(parts[0]), float(parts[1])
    except ValueError:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon
