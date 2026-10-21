"""集成测试共用工具（普通模块，避免依赖 conftest 的特殊导入名）。"""

import uuid


def new_user_client(cfg):
    """创建一个已完成登录的独立客户端（每个线程各自登录，避免共享会话）。"""
    from supabase import create_client

    client = create_client(cfg["url"], cfg["anon"])
    resp = client.auth.sign_in_with_password(
        {"email": cfg["email"], "password": cfg["password"]}
    )
    return client, resp.user.id


def unique_name(prefix="itest"):
    return "%s-%s" % (prefix, uuid.uuid4().hex[:12])
