"""GFS 二级缓存的读写契约。

缓存表在 Supabase 的 `gfs_cache`，写入只允许经 `put_gfs_cache` RPC（仅
`service_role` 可调）。这个模块不导入 streamlit，调用方负责鉴权、客户端生命
周期与 DataFrame 转换，因此可以在没有 UI 依赖的环境里直接测试。

时间戳用 `updated_at`。旧实现按 `created_at` 过滤，而 upsert 不会刷新
`created_at`，导致首次写入一小时后缓存对所有人永久失效。读写两端都改用
`updated_at`，由 RPC 在每次写入时刷新。
"""
import logging

LOG = logging.getLogger(__name__)

TABLE = "gfs_cache"


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


def read_from(client, cache_key):
    """按精确 key 读取未过期缓存，返回 records 列表；未命中或失败返回 None。

    S13：不再 select 整表，改为调用 ``get_gfs_cache(key)``，服务端按
    ``updated_at`` 判断 1 小时 TTL。登录用户因此无法枚举他人的缓存行。
    """
    if client is None:
        return None
    try:
        res = client.rpc("get_gfs_cache", {"p_key": cache_key}).execute()
        data = getattr(res, "data", None)
        if isinstance(data, dict):
            data = data.get("data_json")
        if isinstance(data, list):
            return data or None
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
