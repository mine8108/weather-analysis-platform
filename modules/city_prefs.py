"""天气墙城市列表持久化：刷新/重启后保留用户添加的城市。

双通道（与 theme_aether 主题持久化同构）：
- 未登录：本地文件 ~/.weather_wall_cities.json
- 已登录：Supabase user_metadata.cities（JSON 字符串），登录时读回

存储内容只保留 JSON 安全的城市最小字段（zh/en/lat/lon/region/capital），
防止 session_state 里混入不可序列化对象导致写入失败。
"""

import json
from pathlib import Path

import streamlit as st

_PREF_FILE = Path.home() / ".weather_wall_cities.json"

_CITY_KEYS = ("zh", "en", "lat", "lon", "region", "capital")


def sanitize_cities(cities) -> list[dict]:
    """过滤为 JSON 安全的最小城市字段；非法条目丢弃。"""
    out = []
    for c in cities or []:
        if not isinstance(c, dict):
            continue
        try:
            lat, lon = float(c["lat"]), float(c["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        zh = str(c.get("zh", "")).strip()
        if not zh:
            continue
        out.append({
            "zh": zh,
            "en": str(c.get("en", "")),
            "lat": lat,
            "lon": lon,
            "region": str(c.get("region", "自定义")),
            "capital": bool(c.get("capital", False)),
        })
    return out


# ---- 本地文件通道 ----
def _load_local() -> list | None:
    try:
        if _PREF_FILE.exists():
            data = json.loads(_PREF_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return sanitize_cities(data)
    except Exception:
        pass
    return None


def _save_local(cities) -> None:
    try:
        _PREF_FILE.write_text(
            json.dumps(sanitize_cities(cities), ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass  # 写失败仅丢持久化，不影响本次会话


# ---- Supabase 云端通道 ----
def _cloud_available() -> bool:
    try:
        has_secrets = bool(str(st.secrets.get("SUPABASE_URL", "")).strip())
    except Exception:
        has_secrets = False
    return has_secrets and bool(st.session_state.get("auth_user"))


def _supabase_client():
    """轻量 Supabase 客户端（不调用 auth.get_supabase）。

    为什么不用 auth.get_supabase：它在缺密钥/DNS 失败时会 st.error + st.stop()
    （StopException 继承 BaseException，except Exception 抓不住），
    持久化这类「尽力而为」的写入不允许中断页面渲染。
    """
    try:
        from supabase import create_client
    except ImportError:
        return None
    try:
        url = str(st.secrets.get("SUPABASE_URL", "")).strip()
        key = str(st.secrets.get("SUPABASE_ANON_KEY", "")).strip()
    except Exception:
        return None
    if url.endswith("/rest/v1/"):
        url = url[:-9]
    elif url.endswith("/rest/v1"):
        url = url[:-8]
    url = url.rstrip("/")
    if url and not url.startswith(("http://", "https://")):
        url = "https://" + url
    if not url or not key:
        return None
    try:
        return create_client(url, key)
    except Exception:
        return None


def _save_cloud(cities) -> None:
    """登录用户：user_metadata.cities 存 JSON 字符串。失败静默。"""
    if not _cloud_available():
        return
    sb = _supabase_client()
    if sb is None:
        return
    try:
        sb.auth.update_user({"data": {
            "cities": json.dumps(sanitize_cities(cities), ensure_ascii=False),
        }})
    except Exception:
        pass


def save_cities(cities) -> None:
    """增删城市后调用：双通道持久化。"""
    _save_local(cities)
    _save_cloud(cities)


def load_cities() -> list:
    """初始化读回：本地文件（云端值在登录时经 apply_cloud_prefs 注入会话）。"""
    return _load_local() or []


def apply_cloud_cities(raw: str | None) -> None:
    """登录成功后由 auth.py 调用：云端城市列表覆盖并同步本地文件。"""
    if not raw:
        return
    try:
        cities = sanitize_cities(json.loads(raw))
    except (ValueError, TypeError):
        return
    if cities:
        _save_local(cities)
