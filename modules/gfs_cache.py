"""GFS 二级缓存的读写契约。

缓存表在 Supabase 的 `gfs_cache`，写入只允许经 `put_gfs_cache` RPC（仅
`service_role` 可调）。这个模块不导入 streamlit，调用方负责鉴权、客户端生命
周期与 DataFrame 转换，因此可以在没有 UI 依赖的环境里直接测试。

时间戳用 `updated_at`。旧实现按 `created_at` 过滤，而 upsert 不会刷新
`created_at`，导致首次写入一小时后缓存对所有人永久失效。读写两端都改用
`updated_at`，由 RPC 在每次写入时刷新。
"""
import logging
from datetime import datetime, timedelta, timezone

LOG = logging.getLogger(__name__)

TABLE = "gfs_cache"
TTL_HOURS = 1


def write_params(cache_key, lat, lon, days, model, records):
    """组装 `put_gfs_cache` 的 RPC 参数，键名与 SQL 函数签名一一对应。"""
    return {
        "p_key": str(cache_key),
        "p_lat": float(lat),
        "p_lon": float(lon),
        "p_days": int(days),
        "p_model": model or "blend",
        "p_data": records,
    }


def read_from(client, cache_key, ttl_hours=TTL_HOURS, now=None):
    """按 key 读取未过期缓存，返回 records 列表；未命中或失败返回 None。

    只取 `data_json` 一列，避免把 `created_by` 等元数据一并传到客户端。
    """
    if client is None:
        return None
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=ttl_hours)).isoformat()
    try:
        res = (
            client.table(TABLE)
            .select("data_json")
            .eq("cache_key", cache_key)
            .gte("updated_at", cutoff)
            .execute()
        )
        data = getattr(res, "data", None)
        if data:
            row = data[0] or {}
            return row.get("data_json")
    except Exception:
        LOG.warning("读取 GFS 缓存失败 key=%s", cache_key, exc_info=True)
    return None


def save_to(client, cache_key, lat, lon, days, model, records):
    """经 RPC 写入缓存，返回是否被服务端接受。

    失败只记日志，不阻断主流程：缓存是优化层，实时请求已经成功返回。
    """
    if client is None:
        return False
    try:
        res = client.rpc(
            "put_gfs_cache",
            write_params(cache_key, lat, lon, days, model, records),
        ).execute()
        data = getattr(res, "data", True)
        if data is False:
            LOG.warning("GFS 缓存写入被服务端拒绝 key=%s", cache_key)
            return False
        return True
    except Exception:
        LOG.warning("写入 GFS 缓存失败 key=%s", cache_key, exc_info=True)
        return False
