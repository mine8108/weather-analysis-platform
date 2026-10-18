"""数据持久化模块：把每个用户的数据集存到 Supabase，按 user_id 隔离。

表结构见 sql/schema.sql。所有读写都带 `.eq("user_id", ...)` 条件，
配合数据库 RLS 策略，即使客户端越权也读不到他人数据。
"""

import io
import logging

import pandas as pd
import streamlit as st

from auth import expire_session, get_supabase, is_session_error
from utils import safe_error_text

_LOG = logging.getLogger(__name__)


def _user_id() -> str | None:
    user = st.session_state.get("auth_user")
    return user["id"] if user else None


# ============================================================
# save_dataset 错误码到用户文案的映射（见 sql/schema.sql 第 8 节）
# 数据库函数只返回短错误码，文案留在应用层，便于测试与统一措辞。
# ============================================================
_SAVE_ERROR_TEXT = {
    "配额不足": (
        "❌ 存储配额不足，本次保存被拒绝。"
        "请删除部分数据集或联系管理员提升配额。"
    ),
    "名称过长": "❌ 数据集名称过长（上限 200 字符），本次保存被拒绝。",
    "数据集数量已达上限": (
        "❌ 数据集数量已达上限（200 个），请先删除不再需要的数据集。"
    ),
}


def save_error_message(error: str) -> str:
    """把 save_dataset 返回的错误码翻译成用户文案。"""
    code = str(error or "写入失败")
    return _SAVE_ERROR_TEXT.get(code, "保存失败：%s" % code)


def save_dataset(df: pd.DataFrame, name: str, dataset_id: str | None = None) -> bool:
    """保存/更新一个数据集。df 序列化为 CSV 文本存入 csv_text 字段。

    安全修复（P-12）：写入改经数据库函数 save_dataset（SECURITY DEFINER），
    配额校验由服务端强制执行，客户端无法绕过配额直插大 CSV。
    """
    uid = _user_id()
    if uid is None or df is None or df.empty:
        return False
    sb = get_supabase()
    if sb is None:
        return False

    csv_text = df.to_csv(index=False)

    # 配额校验与写入均由数据库函数 save_dataset 原子完成（服务端强制）
    try:
        res = sb.rpc(
            "save_dataset",
            {"p_dataset_id": dataset_id, "p_name": name, "p_csv": csv_text},
        ).execute()
        data = res.data if hasattr(res, "data") else res
        if isinstance(data, dict) and data.get("ok"):
            invalidate_dataset_cache()
            return True
        err = (data or {}).get("error", "写入失败") if isinstance(data, dict) else "写入失败"
        st.error(save_error_message(err))
        return False
    except Exception as e:
        _LOG.warning("保存数据集失败", exc_info=True)
        if is_session_error(e):
            expire_session()
        st.error(safe_error_text(e, "保存失败，请稍后重试。"))
        return False


def _scalar_rpc(name: str, default: int, uid: str | None = None) -> int:
    """调用返回单个整数的 RPC；未登录、客户端缺失或异常一律返回默认值。"""
    uid = uid or _user_id()
    if uid is None:
        return default
    sb = get_supabase()
    if sb is None:
        return default
    try:
        res = sb.rpc(name, {"p_user_id": uid}).execute()
        return int(res.data or default)
    except Exception as exc:
        _LOG.warning("存储 RPC %s 失败", name, exc_info=True)
        if is_session_error(exc):
            expire_session()
        return default


@st.cache_data(ttl=30, show_spinner=False)
def get_storage_usage_bytes(uid: str) -> int:
    """返回指定用户已用存储字节数（30 秒缓存，按 uid 隔离）。"""
    return _scalar_rpc("get_storage_usage", 0, uid)


@st.cache_data(ttl=30, show_spinner=False)
def get_storage_quota_bytes(uid: str) -> int:
    """返回指定用户的存储配额字节数（30 秒缓存，按 uid 隔离）。"""
    return _scalar_rpc("get_storage_quota", 10485760, uid)


@st.cache_data(ttl=30, show_spinner=False)
def list_datasets(uid: str):
    """返回指定用户的数据集元信息列表（30 秒缓存，不含 csv_text）。"""
    if not uid:
        return []
    sb = get_supabase()
    if sb is None:
        return []
    try:
        res = (
            sb.table("datasets")
            .select("id,name,created_at,updated_at")
            .eq("user_id", uid)
            .order("updated_at", desc=True)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        _LOG.warning("列出数据集失败", exc_info=True)
        if is_session_error(exc):
            expire_session()
        return []


def invalidate_dataset_cache() -> None:
    """保存/删除后清掉侧边栏缓存，下一次 rerun 重新拉取。"""
    get_storage_usage_bytes.clear()
    get_storage_quota_bytes.clear()
    list_datasets.clear()


def load_dataset(dataset_id: str):
    """按 id 载入数据集，返回 (DataFrame, name)。"""
    uid = _user_id()
    if uid is None:
        return None, None
    sb = get_supabase()
    if sb is None:
        return None, None
    try:
        res = (
            sb.table("datasets")
            .select("csv_text,name")
            .eq("id", dataset_id)
            .eq("user_id", uid)
            .execute()
        )
        if res.data:
            row = res.data[0]
            df = pd.read_csv(io.StringIO(row["csv_text"]))
            # 回复时间列类型
            if "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
            return df, row["name"]
    except Exception as e:
        _LOG.warning("载入数据集失败 dataset_id=%s", dataset_id, exc_info=True)
        if is_session_error(e):
            expire_session()
        st.error(safe_error_text(e, "载入失败，请稍后重试。"))
    return None, None


def load_latest_dataset():
    """登录后自动载入用户最近一次保存的数据集。"""
    uid = _user_id()
    if uid is None:
        return None, None
    datasets = list_datasets(uid)
    if datasets:
        return load_dataset(datasets[0]["id"])
    return None, None


def delete_dataset(dataset_id: str) -> bool:
    uid = _user_id()
    if uid is None:
        return False
    sb = get_supabase()
    if sb is None:
        return False
    try:
        sb.table("datasets").delete().eq("id", dataset_id).eq(
            "user_id", uid
        ).execute()
        invalidate_dataset_cache()
        return True
    except Exception as exc:
        _LOG.warning("删除数据集失败 dataset_id=%s", dataset_id, exc_info=True)
        if is_session_error(exc):
            expire_session()
        return False


# ============================================================
# 读图配额（服务端强制，见 sql/schema.sql 第 9 节）
# 三个函数都以 None 表示「配额服务不可用」，与「配额已用完」区分开：
# 前者是故障，后者是正常拒绝。调用方必须分别处置，不能把故障当成放行。
# ============================================================

def _vision_rpc(name, params=None):
    """调用读图配额 RPC，返回解析后的 dict；任何异常或非 ok 响应一律 None。"""
    uid = _user_id()
    sb = get_supabase()
    if uid is None or sb is None:
        return None
    try:
        res = sb.rpc(name, params or {}).execute()
        data = res.data if hasattr(res, "data") else res
        if isinstance(data, list):  # 某些版本会把单行结果包成列表
            data = data[0] if data else None
        if isinstance(data, dict) and data.get("ok"):
            return data
        return None
    except Exception as exc:
        _LOG.warning("读图配额 RPC %s 失败", name, exc_info=True)
        if is_session_error(exc):
            expire_session()
        return None


def get_vision_quota():
    """当前用户今日的读图配额状态（只读）。不可用时返回 None。"""
    return _vision_rpc("get_vision_quota")


def begin_vision_call():
    """原子地检查并占用一次读图次数。

    返回的 dict 里 ``allowed`` 为 False 表示今日配额已用完（正常拒绝），
    整个函数返回 None 才表示配额服务不可用。
    """
    return _vision_rpc("begin_vision_call")


def record_vision_usage(usage):
    """补记一次调用的实际用量，返回更新后的配额状态。

    成功与失败都要调用：服务商对失败的调用同样计费。
    """
    usage = usage or {}
    return _vision_rpc("record_vision_usage", {
        "p_prompt": int(usage.get("prompt") or 0),
        "p_completion": int(usage.get("completion") or 0),
        "p_reasoning": int(usage.get("reasoning") or 0),
        "p_total": int(usage.get("total") or 0),
    })
