"""数据持久化模块：把每个用户的数据集存到 Supabase，按 user_id 隔离。

表结构见 sql/schema.sql。所有读写都带 `.eq("user_id", ...)` 条件，
配合数据库 RLS 策略，即使客户端越权也读不到他人数据。
"""

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
    """保存/更新一个数据集。df 序列化为带 schema 版本的 CSV 文本。

    安全修复（P-12）：写入改经数据库函数 save_dataset（SECURITY DEFINER），
    配额校验由服务端强制执行，客户端无法绕过配额直插大 CSV。
    批次 2：序列化走 modules/dataset，读回时可识别版本并迁移。
    """
    uid = _user_id()
    if uid is None or df is None or df.empty:
        return False
    sb = get_supabase()
    if sb is None:
        return False

    from modules import dataset as dataset_contract
    csv_text = dataset_contract.to_text(df)

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


def list_datasets_result(uid: str):
    """返回 (列表, error|None)。后端故障与「没有数据集」不再共用 []。"""
    if not uid:
        return [], "未登录"
    sb = get_supabase()
    if sb is None:
        return [], "存储不可用"
    try:
        res = (
            sb.table("datasets")
            .select("id,name,created_at,updated_at")
            .eq("user_id", uid)
            .order("updated_at", desc=True)
            .execute()
        )
        return (res.data or []), None
    except Exception as exc:
        _LOG.warning("列出数据集失败", exc_info=True)
        if is_session_error(exc):
            expire_session()
        return [], "读取失败"


@st.cache_data(ttl=30, show_spinner=False)
def list_datasets(uid: str):
    """返回指定用户的数据集元信息列表（30 秒缓存，不含 csv_text）。"""
    return list_datasets_result(uid)[0]


def invalidate_dataset_cache() -> None:
    """保存/删除后清掉侧边栏缓存，下一次 rerun 重新拉取。"""
    get_storage_usage_bytes.clear()
    get_storage_quota_bytes.clear()
    list_datasets.clear()


def load_dataset_result(dataset_id: str):
    """按 id 载入数据集，返回 (Dataset|None, error|None)。

    与旧接口的区别：后端故障与「没有这条数据」不再共用同一个空值。
    调用方据此决定是提示用户还是静默跳过。
    """
    uid = _user_id()
    if uid is None:
        return None, "未登录"
    sb = get_supabase()
    if sb is None:
        return None, "存储不可用"
    try:
        res = (
            sb.table("datasets")
            .select("csv_text,name")
            .eq("id", dataset_id)
            .eq("user_id", uid)
            .execute()
        )
        if not res.data:
            return None, None
        row = res.data[0]
        from modules import dataset as dataset_contract
        return dataset_contract.from_text(row["csv_text"], source=row["name"]), None
    except Exception as e:
        _LOG.warning("载入数据集失败 dataset_id=%s", dataset_id, exc_info=True)
        if is_session_error(e):
            expire_session()
        return None, "读取失败"


def load_dataset(dataset_id: str):
    """按 id 载入数据集，返回 (DataFrame, name)。保留旧调用契约。"""
    loaded, error = load_dataset_result(dataset_id)
    if loaded is not None:
        return loaded.df, loaded.source
    if error == "读取失败":
        st.error("载入失败，请稍后重试。")
    return None, None


def load_latest_dataset():
    """登录后自动载入用户最近一次保存的数据集。

    后端故障时记录日志并放弃本次自动载入，不把故障伪装成「没有数据」。
    """
    uid = _user_id()
    if uid is None:
        return None, None
    datasets, error = list_datasets_result(uid)
    if error:
        _LOG.warning("自动载入跳过，数据集列表不可用：%s", error)
        return None, None
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


# ============================================================
# 出站请求配额（SEC-02，见 sql/schema.sql 第 9.4 节）
# 与读图配额同一约定：None 表示配额服务不可用（调用方放行并降级），
# dict 里 allowed=False 表示今日额度已用完（正常拒绝）。
# ============================================================

def begin_outbound_call():
    """原子地占用一次外部数据请求额度。

    未登录、会话里还没有 Supabase 客户端（测试/首屏）时返回 None，
    由调用方按「服务不可用」处理，避免在登录前或测试环境触发网络。
    """
    uid = _user_id()
    if uid is None or st.session_state.get("_sb_client") is None:
        return None
    sb = get_supabase()
    if sb is None:
        return None
    try:
        res = sb.rpc("begin_outbound_call", {}).execute()
        data = res.data if hasattr(res, "data") else res
        if isinstance(data, list):
            data = data[0] if data else None
        if isinstance(data, dict) and data.get("ok"):
            return data
        return None
    except Exception as exc:
        _LOG.warning("出站配额 RPC 失败", exc_info=True)
        if is_session_error(exc):
            expire_session()
        return None
