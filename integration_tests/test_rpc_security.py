"""Supabase RPC 安全契约的集成测试。

默认跳过；只有显式提供 `SUPABASE_TEST_*` 环境变量时才连接真实项目。
建议在**独立的 staging 项目**上运行，不要指向生产库。
"""

import concurrent.futures
import hashlib
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from helpers import new_user_client, unique_name

MAX_WORKERS = 6


def _quota_state(client, uid):
    used = int(client.rpc(
        "get_storage_usage", {"p_user_id": uid}).execute().data or 0)
    quota = int(client.rpc(
        "get_storage_quota", {"p_user_id": uid}).execute().data or 0)
    return used, quota


def test_save_dataset_concurrent_quota(cfg, user_session):
    """SEC-01：并发 save_dataset 不得突破服务端存储配额。

    旧实现先统计后加锁，并发请求都用加锁前的旧用量通过校验；修复后
    总写入字节数应 <= 测试用户的剩余配额。
    """
    client, uid = user_session
    used, quota = _quota_state(client, uid)
    remaining = quota - used
    if remaining < 512 * 1024:
        pytest.skip("测试用户剩余配额不足 512KB，无法构造并发场景")

    # 每个请求约占剩余配额 1/2，6 个并发总量约为配额的 3 倍；
    # 修复前会明显超过 remaining，修复后最多写满 remaining。
    chunk = max(64 * 1024, remaining // 2)
    payload = "x" * chunk
    names = [unique_name("itest-quota") for _ in range(MAX_WORKERS)]

    def _worker(name):
        worker_client, _ = new_user_client(cfg)
        try:
            res = worker_client.rpc("save_dataset", {
                "p_dataset_id": None,
                "p_name": name,
                "p_csv": payload,
            }).execute()
            return name, res.data
        finally:
            try:
                worker_client.auth.sign_out()
            except Exception:
                pass

    results = []
    with concurrent.futures.ThreadPoolExecutor(
            max_workers=MAX_WORKERS) as pool:
        for item in pool.map(_worker, names):
            results.append(item)

    ok_ids = []
    ok_bytes = 0
    try:
        for name, data in results:
            if isinstance(data, dict) and data.get("ok"):
                ok_ids.append(data.get("id"))
                ok_bytes += len(payload.encode("utf-8")) + len(
                    name.encode("utf-8"))
        assert ok_bytes <= remaining, (
            "并发写入超过剩余配额：total=%d remaining=%d（SEC-01 回归）"
            % (ok_bytes, remaining)
        )
    finally:
        for dataset_id in ok_ids:
            if not dataset_id:
                continue
            try:
                client.table("datasets").delete().eq(
                    "id", dataset_id).eq("user_id", uid).execute()
            except Exception:
                pass


def test_outbound_quota_concurrency(cfg, user_session, admin_client):
    """SEC-02：并发 begin_outbound_call 只能放行配额内的次数。

    需要 SUPABASE_TEST_SERVICE_KEY 修改测试用户的每日配额。
    """
    client, uid = user_session
    day = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    limit = 3
    admin_client.table("profiles").update({
        "outbound_calls_per_day": limit,
    }).eq("user_id", uid).execute()
    admin_client.table("outbound_usage").delete().eq(
        "user_id", uid).eq("day", day).execute()

    def _worker(_):
        worker_client, _ = new_user_client(cfg)
        try:
            data = worker_client.rpc("begin_outbound_call", {}).execute().data
            return bool(isinstance(data, dict) and data.get("allowed"))
        finally:
            try:
                worker_client.auth.sign_out()
            except Exception:
                pass

    try:
        with concurrent.futures.ThreadPoolExecutor(
                max_workers=10) as pool:
            allowed = sum(pool.map(_worker, range(10)))
        assert allowed == limit, (
            "并发出站配额放行 %d 次，期望 %d 次（SEC-02 回归）"
            % (allowed, limit)
        )
    finally:
        try:
            admin_client.table("profiles").update({
                "outbound_calls_per_day": 200,
            }).eq("user_id", uid).execute()
            admin_client.table("outbound_usage").delete().eq(
                "user_id", uid).eq("day", day).execute()
        except Exception:
            pass


def test_invite_functions_require_service_role(cfg, user_session):
    """SEC-08：验码/认领不再对 anon / authenticated 开放。"""
    from supabase import create_client

    code_hash = hashlib.sha256(uuid.uuid4().hex.encode("utf-8")).hexdigest()

    anon = create_client(cfg["url"], cfg["anon"])
    with pytest.raises(Exception):
        anon.rpc("claim_invite_code", {"p_code": code_hash}).execute()
    with pytest.raises(Exception):
        anon.rpc("is_invite_code_valid", {"p_code": code_hash}).execute()

    client, _ = user_session
    with pytest.raises(Exception):
        client.rpc("claim_invite_code", {"p_code": code_hash}).execute()

    # 可选：有 service key 时，同一调用必须可执行并返回 false（随机码不存在）
    if cfg.get("service"):
        admin = create_client(cfg["url"], cfg["service"])
        data = admin.rpc("claim_invite_code", {"p_code": code_hash}).execute().data
        assert data is False
