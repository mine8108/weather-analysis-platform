"""天气墙偏好持久化：城市列表 + 显示开关（刷新/重启后保留）。

双通道（与 theme_aether 主题持久化同构）：
- 未登录：本地文件 ``~/.weather_wall_cities.json``，结构
  ``{"cities": [...], "show_wall": bool}``（兼容旧版 list 结构）
- 已登录：``~/.weather_wall_cities.<uid>.json`` 与 Supabase
  ``user_metadata.cities``（JSON 字符串）+ ``show_wall``（"0"/"1"），登录时读回

安全修复（2026-10-18 审计）：
- SEC-05：城市名去掉控制字符并截断；HTML 转义在渲染层（weather_wall.card_html）
- SEC-06：本地文件按 uid 分区，避免 Streamlit Cloud 单容器多会话共享串读；
  ``save_show_wall`` 不再把共享文件里的城市列表写进当前用户的云端元数据
- SEC-35：坐标校验有限性、范围与类型，非法条目直接丢弃

云端写入使用当前会话的 ``auth.get_supabase()`` 客户端；调用前用
``utils.supabase_secrets_ready()`` 预检，避免缺密钥时 ``st.stop()``。
"""

import json
import math
import re
from pathlib import Path

import streamlit as st

from utils import supabase_secrets_ready

_PREF_FILE = Path.home() / ".weather_wall_cities.json"

_CITY_KEYS = ("zh", "en", "lat", "lon", "region", "capital")

_UID_SAFE_RE = re.compile(r"[^0-9A-Za-z_-]")


def _clean_text(value, limit=40):
    """去控制字符并截断；只用于展示字段，不做 HTML 转义。"""
    s = "".join(ch for ch in str(value or "") if ch.isprintable()).strip()
    return s[:limit]


def _current_uid() -> str:
    """当前登录用户 id；未登录、测试环境或运行时缺失时返回空串。"""
    try:
        user = st.session_state.get("auth_user") or {}
        return str(user.get("id") or "")
    except Exception:
        return ""


def _pref_file(uid=None) -> Path:
    """按 uid 分区的偏好文件；uid 为空时退回旧版共享路径（匿名/测试）。"""
    if uid is None:
        uid = _current_uid()
    uid = str(uid or "")
    if not uid:
        return _PREF_FILE
    safe = _UID_SAFE_RE.sub("", uid)[:64] or "user"
    return _PREF_FILE.parent / ("%s.%s.json" % (_PREF_FILE.stem, safe))


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
        if not (math.isfinite(lat) and math.isfinite(lon)
                and -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            continue
        zh = _clean_text(c.get("zh"))
        if not zh:
            continue
        out.append({
            "zh": zh,
            "en": _clean_text(c.get("en")),
            "lat": lat,
            "lon": lon,
            "region": _clean_text(c.get("region") or "自定义", 20) or "自定义",
            "capital": bool(c.get("capital", False)),
        })
    return out


# ============================================================
# 本地文件通道
# ============================================================
def _load_local(uid=None) -> dict:
    """读取本地偏好，返回 {"cities": [...], "show_wall": bool}。

    兼容旧版 list 结构（迁移为 show_wall=True）；文件缺失/损坏返回默认值。
    """
    default = {"cities": [], "show_wall": True}
    path = _pref_file(uid)
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
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


def _save_local(cities, show_wall: bool, uid=None) -> None:
    """原子写入本地偏好；失败只丢持久化，不影响本次会话。"""
    path = _pref_file(uid)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps({"cities": sanitize_cities(cities),
                           "show_wall": bool(show_wall)}, ensure_ascii=False)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    except Exception:
        pass


# ============================================================
# Supabase 云端通道
# ============================================================
def _cloud_available() -> bool:
    """只有已登录且当前会话已有客户端时才走云端。

    偏好保存是高频且非关键的路径。会话里没有客户端时（例如测试构造的登录态，
    或刚过期尚未重建），get_supabase(fatal=True) 会因网络/DNS 失败触发
    st.stop，把整页渲染打断；这里提前判定，缺客户端时只写本地。
    """
    return (supabase_secrets_ready()
            and bool(st.session_state.get("auth_user"))
            and st.session_state.get("_sb_client") is not None)


def _save_cloud(cities, show_wall: bool) -> None:
    """登录用户：user_metadata.cities + show_wall。失败静默。"""
    if not _cloud_available():
        return
    try:
        from auth import get_supabase

        sb = get_supabase()
        if sb is None:
            return
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
    """初始化读回当前用户的本地城市列表。"""
    return _load_local()["cities"]


def load_show_wall() -> bool:
    """初始化读回天气墙显示开关，默认 True（显示）。"""
    return _load_local()["show_wall"]


def save_show_wall(show: bool) -> None:
    """天气墙开关切换后调用：只持久化当前用户的列表，绝不复制共享文件内容。"""
    cities = st.session_state.get("wall_cities")
    if cities is None:
        cities = _load_local()["cities"]
    _save_local(cities, show)
    _save_cloud(cities, show)


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
