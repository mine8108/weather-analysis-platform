"""Supabase RPC 集成测试的公共夹具。

这些测试需要真实的 Supabase 项目，**只在显式提供测试环境变量时运行**，
默认 `pytest tests` 不会收集本目录。绝不把生产项目的 service_role key
写进 CI 或提交到仓库。

必需环境变量：
- SUPABASE_TEST_URL
- SUPABASE_TEST_ANON_KEY
- SUPABASE_TEST_EMAIL
- SUPABASE_TEST_PASSWORD

可选：
- SUPABASE_TEST_SERVICE_KEY（只有出站配额/邀请码服务端路径的用例需要）
"""

import os

import pytest

from helpers import new_user_client  # noqa: F401  (re-export 给测试文件)

REQUIRED_ENV = (
    "SUPABASE_TEST_URL",
    "SUPABASE_TEST_ANON_KEY",
    "SUPABASE_TEST_EMAIL",
    "SUPABASE_TEST_PASSWORD",
)


def _missing_env():
    return [name for name in REQUIRED_ENV if not os.environ.get(name)]
@pytest.fixture(scope="session")
def cfg():
    missing = _missing_env()
    if missing:
        pytest.skip("缺少集成测试环境变量: %s" % ", ".join(missing))
    return {
        "url": os.environ["SUPABASE_TEST_URL"],
        "anon": os.environ["SUPABASE_TEST_ANON_KEY"],
        "email": os.environ["SUPABASE_TEST_EMAIL"],
        "password": os.environ["SUPABASE_TEST_PASSWORD"],
        "service": os.environ.get("SUPABASE_TEST_SERVICE_KEY", ""),
    }


@pytest.fixture()
def user_session(cfg):
    client, uid = new_user_client(cfg)
    try:
        yield client, uid
    finally:
        try:
            client.auth.sign_out()
        except Exception:
            pass


@pytest.fixture()
def admin_client(cfg):
    if not cfg.get("service"):
        pytest.skip("未提供 SUPABASE_TEST_SERVICE_KEY，跳过服务端路径用例")
    from supabase import create_client

    return create_client(cfg["url"], cfg["service"])


def unique_name(prefix="itest"):
    return "%s-%s" % (prefix, uuid.uuid4().hex[:12])
