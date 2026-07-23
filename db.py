"""数据持久化模块：把每个用户的数据集存到 Supabase，按 user_id 隔离。

表结构见 supabase/schema.sql。所有读写都带 `.eq("user_id", ...)` 条件，
配合数据库 RLS 策略，即使客户端越权也读不到他人数据。
"""

import io

import pandas as pd
import streamlit as st

from auth import get_supabase


def _user_id() -> str | None:
    user = st.session_state.get("auth_user")
    return user["id"] if user else None


def save_dataset(df: pd.DataFrame, name: str, dataset_id: str | None = None) -> bool:
    """保存/更新一个数据集。df 序列化为 CSV 文本存入 csv_text 字段。"""
    uid = _user_id()
    if uid is None or df is None or df.empty:
        return False
    sb = get_supabase()
    if sb is None:
        return False

    csv_text = df.to_csv(index=False)
    payload = {"user_id": uid, "name": name, "csv_text": csv_text}

    try:
        if dataset_id:
            sb.table("datasets").update(payload).eq(
                "id", dataset_id
            ).eq("user_id", uid).execute()
        else:
            sb.table("datasets").insert(payload).execute()
        return True
    except Exception as e:
        st.error(f"保存失败：{str(e)[:200]}")
        return False


def list_datasets():
    """返回当前用户的数据集元信息列表（不含 csv_text）。"""
    uid = _user_id()
    if uid is None:
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
    except Exception:
        return []


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
        st.error(f"载入失败：{str(e)[:200]}")
    return None, None


def load_latest_dataset():
    """登录后自动载入用户最近一次保存的数据集。"""
    datasets = list_datasets()
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
        return True
    except Exception:
        return False
