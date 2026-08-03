"""天气墙偏好持久化：城市列表 + 显示开关（刷新/重启后保留）。

双通道（与 theme_aether 主题持久化同构）：
- 未登录：本地文件 ~/.weather_wall_cities.json，结构 {"cities": [...], "show_wall": bool}
  （兼容旧版 list 结构：读到 list 时按 cities=旧列表、show_wall=True 迁移）
- 已登录：Supabase user_metadata.cities（JSON 字符串）+ show_wall（"0"/"1"），登录时读回

城市条目只保留 JSON 安全最小字段（zh/en/lat/lon/region/capital）。
所有云端写入用轻量 create_client（auth.get_supabase 会 st.stop() 中断页面，不可用于持久化）。
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


# ============================================================
# 本地文件通道
# ============================================================
def _load_local() -> dict:
    """读取本地偏好，返回 {"cities": [...], "show_wall": bool}。
    兼容旧版 list 结构（迁移为 show_wall=True）；文件缺失/损坏返回默认值。
    """
    default = {"cities": [], "show_wall": True}
    try:
        if _PREF_FILE.exists():
            data = json.loads(_PREF_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):  # 旧版结构迁移
                return {"cities": sanitize_cities(data), "show_wall": True}
            if isinstance(data, dict):
                return {
                    "cities": sanitize_cities(data.get("cities")),
                    "show_wall": bool(data.get("show_wall", True)),
                }
    except Exception:
        pass
    return default


def _save_local(cities, show_wall: bool) -> None:
    try:
        _PREF_FILE.write_text(
            json.dumps({"cities": sanitize_cities(cities),
                        "show_wall": bool(show_wall)}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass  # 写失败仅丢持久化，不影响本次会话


# ============================================================
# Supabase 云端通道
# ============================================================
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


def _save_cloud(cities, show_wall: bool) -> None:
    """登录用户：user_metadata.cities + show_wall。失败静默。"""
    if not _cloud_available():
        return
    sb = _supabase_client()
    if sb is None:
        return
    try:
        sb.auth.update_user({"data": {
            "cities": json.dumps(sanitize_cities(cities), ensure_ascii=False),
            "show_wall": "1" if show_wall else "0",
        }})
    except Exception:
        pass


# ============================================================
# 公开接口
# ============================================================
def save_cities(cities) -> None:
    """增删城市后调用：保留当前 show_wall 值，双通道持久化。"""
    cur = _load_local()
    _save_local(cities, cur["show_wall"])
    _save_cloud(cities, cur["show_wall"])


def load_cities() -> list:
    """初始化读回城市列表（云端值在登录时经 apply_cloud_prefs 注入会话）。"""
    return _load_local()["cities"]


def load_show_wall() -> bool:
    """初始化读回天气墙显示开关，默认 True（显示）。"""
    return _load_local()["show_wall"]


def save_show_wall(show: bool) -> None:
    """天气墙开关切换后调用：保留当前城市列表，双通道持久化。"""
    cur = _load_local()
    _save_local(cur["cities"], show)
    _save_cloud(cur["cities"], show)


def apply_cloud_prefs(cities_raw: str | None, show_wall_raw: str | None) -> None:
    """登录成功后由 auth.py 调用：云端城市列表与开关覆盖并同步本地文件。

    云端 cities 为 JSON 字符串（user_metadata.cities），show_wall 为 "0"/"1"。
    损坏的 JSON 静默忽略（保留本地值）。
    """
    try:
        cities = sanitize_cities(json.loads(cities_raw)) if cities_raw else []
    except (ValueError, TypeError):
        return
    show_wall = True
    if show_wall_raw is not None:
        show_wall = str(show_wall_raw) in ("1", "true", "True")
    _save_local(cities, show_wall)
