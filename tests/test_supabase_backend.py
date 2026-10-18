"""Supabase 后端加固契约测试（批次 1：S1-S4）。

覆盖四块：

1. `modules.supabase_backend.selfcheck_problems` 的判定逻辑；
2. `modules.gfs_cache` 的读写契约（updated_at 过滤、put_gfs_cache RPC）；
3. `nwp_forecast` 确实改走了新 RPC，而不是继续直写表；
4. `schema.sql` 与 `db.save_error_message` 的静态契约。

无 pytest 时可直接运行（`python -B tests/test_supabase_backend.py`）。
"""
import os
import sys
import logging
import types
from unittest import mock

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from modules import gfs_cache  # noqa: E402
from modules import supabase_backend as backend  # noqa: E402
import auth  # noqa: E402
import db  # noqa: E402
from modules import nwp_forecast  # noqa: E402


def _read(rel):
    import io
    with io.open(os.path.join(_APP_DIR, rel), encoding="utf-8") as handle:
        return handle.read()


# ============================================================
# 假客户端：记录调用链，不联网
# ============================================================
class _Resp:
    def __init__(self, data):
        self.data = data


class _FakeChain:
    def __init__(self, client):
        self._c = client

    def select(self, columns):
        self._c.calls.append(("select", columns))
        return self

    def eq(self, column, value):
        self._c.calls.append(("eq", column, value))
        return self

    def gte(self, column, value):
        self._c.calls.append(("gte", column, value))
        return self

    def execute(self):
        self._c.calls.append(("execute",))
        return _Resp(self._c.data)


class _FakeClient:
    def __init__(self, data=None):
        self.data = data
        self.calls = []

    def table(self, name):
        self.calls.append(("table", name))
        return _FakeChain(self)

    def rpc(self, name, params=None):
        self.calls.append((name, params))
        return _FakeChain(self)


# ============================================================
# 一、安全自检判定
# ============================================================
def _healthy_report():
    return {
        "rls": {table: True for table in backend.RLS_TABLES},
        "functions": {
            "save_dataset": {"anon": False, "authenticated": True},
            "put_gfs_cache": {"anon": False, "authenticated": False,
                              "service_role": True},
            "security_selfcheck": {"anon": False, "authenticated": False},
            "release_invite_code": {"anon": False, "authenticated": False},
        },
        "table_privileges": {
            "datasets.authenticated.INSERT": False,
            "datasets.authenticated.UPDATE": False,
            "profiles.authenticated.UPDATE": False,
            "vision_usage.authenticated.INSERT": False,
            "vision_usage.authenticated.UPDATE": False,
            "vision_usage.authenticated.DELETE": False,
            "gfs_cache.authenticated.SELECT": False,
            "gfs_cache.authenticated.INSERT": False,
            "gfs_cache.authenticated.UPDATE": False,
            "gfs_cache.authenticated.DELETE": False,
            "admin_audit_log.authenticated.SELECT": False,
            "admin_audit_log.authenticated.INSERT": False,
            "admin_audit_log.authenticated.UPDATE": False,
            "admin_audit_log.authenticated.DELETE": False,
            "schema_version.authenticated.SELECT": False,
            "schema_version.authenticated.INSERT": False,
            "schema_version.authenticated.UPDATE": False,
            "schema_version.authenticated.DELETE": False,
        },
    }


def test_selfcheck_passes_on_expected_report():
    assert backend.selfcheck_problems(_healthy_report()) == []


def test_selfcheck_detects_disabled_rls():
    report = _healthy_report()
    report["rls"]["datasets"] = False
    problems = backend.selfcheck_problems(report)
    assert any("datasets" in p and "RLS" in p for p in problems), problems


def test_selfcheck_detects_anon_execute_grant():
    report = _healthy_report()
    report["functions"]["save_dataset"]["anon"] = True
    problems = backend.selfcheck_problems(report)
    assert any("save_dataset" in p and "anon" in p for p in problems), problems


def test_selfcheck_detects_function_grant_problems():
    for name in ("put_gfs_cache", "security_selfcheck"):
        report = _healthy_report()
        report["functions"][name]["authenticated"] = True
        problems = backend.selfcheck_problems(report)
        assert any(name in p for p in problems), (name, problems)

    report = _healthy_report()
    report["functions"]["put_gfs_cache"]["service_role"] = False
    problems = backend.selfcheck_problems(report)
    assert any("put_gfs_cache" in p and "service_role" in p for p in problems), problems


def test_selfcheck_detects_table_write_privilege():
    for key, table, priv in (
        ("gfs_cache.authenticated.INSERT", "gfs_cache", "INSERT"),
        ("gfs_cache.authenticated.SELECT", "gfs_cache", "SELECT"),
        ("admin_audit_log.authenticated.INSERT", "admin_audit_log", "INSERT"),
    ):
        report = _healthy_report()
        report["table_privileges"][key] = True
        problems = backend.selfcheck_problems(report)
        assert any(table in p and priv in p for p in problems), (key, problems)


def test_selfcheck_rejects_non_dict_report():
    assert backend.selfcheck_problems(None) != []


def test_is_session_error_recognizes_expired_tokens():
    for text in ("JWT expired", "invalid JWT", "PGRST301",
                 "refresh token not found", "401 Unauthorized"):
        assert auth.is_session_error(Exception(text)), text
    assert not auth.is_session_error(Exception("network timeout"))


# ============================================================
# 二、GFS 缓存读写契约
# ============================================================
def test_write_params_matches_rpc_arguments():
    params = gfs_cache.write_params(
        "gfs_fc_cache_v3_39.9042_116.4074_d7_blend",
        39.9042, 116.4074, 7, "blend",
        [{"timestamp": "2026-10-18T00:00"}],
    )
    assert params["p_key"] == "gfs_fc_cache_v3_39.9042_116.4074_d7_blend"
    assert params["p_lat"] == 39.9042
    assert params["p_lon"] == 116.4074
    assert params["p_days"] == 7
    assert params["p_model"] == "blend"
    assert params["p_data"] == [{"timestamp": "2026-10-18T00:00"}]


def test_read_from_uses_exact_key_rpc():
    client = _FakeClient([{"timestamp": "2026-10-18T00:00"}])
    key = "gfs_fc_cache_v3_1.0000_2.0000_d7_blend"
    rows = gfs_cache.read_from(client, key)
    assert rows == [{"timestamp": "2026-10-18T00:00"}]
    assert client.calls[0] == ("get_gfs_cache", {"p_key": key})
    assert client.calls[1] == ("execute",)


def test_read_from_returns_none_on_miss():
    assert gfs_cache.read_from(_FakeClient([]), "k") is None


def test_save_to_uses_put_gfs_cache_rpc():
    client = _FakeClient(True)
    ok = gfs_cache.save_to(
        client, "gfs_fc_cache_v3_1.0000_2.0000_d7_blend",
        1.0, 2.0, 7, "blend", [{"timestamp": "2026-10-18T00:00"}],
    )
    assert ok is True
    name, params = client.calls[0]
    assert name == "put_gfs_cache"
    assert params["p_days"] == 7
    assert params["p_model"] == "blend"


def test_save_to_treats_false_response_as_failure():
    assert gfs_cache.save_to(
        _FakeClient(False), "k", 1.0, 2.0, 7, "blend", [{"timestamp": "x"}]
    ) is False


# ============================================================
# 三、nwp_forecast 接线
# ============================================================
def _fake_streamlit_secrets():
    return types.SimpleNamespace(
        secrets={"SUPABASE_URL": "https://example.com", "SUPABASE_ANON_KEY": "anon"}
    )


def test_nwp_cache_write_uses_rpc():
    import pandas as pd

    df = pd.DataFrame({"timestamp": ["2026-10-18T00:00"], "temperature": [20.0]})
    client = _FakeClient(True)
    key = "gfs_fc_cache_v3_1.0000_2.0000_d7_blend"
    with mock.patch.object(nwp_forecast, "st", _fake_streamlit_secrets()), \
            mock.patch("utils.st", _fake_streamlit_secrets()), \
            mock.patch("auth.get_supabase_admin", return_value=client), \
            mock.patch("auth.get_supabase",
                       side_effect=AssertionError("写入不得使用登录用户客户端")):
        nwp_forecast._save_gfs_to_cache(key, 1.0, 2.0, 7, "blend", df)
    assert client.calls, "缓存写入没有发出任何请求"
    assert client.calls[0][0] == "put_gfs_cache", client.calls


def test_nwp_cache_read_uses_rpc():
    client = _FakeClient([
        {"timestamp": "2026-10-18T00:00", "temperature": 20.0}
    ])
    key = "gfs_fc_cache_v3_1.0000_2.0000_d7_blend"
    with mock.patch.object(nwp_forecast, "st", _fake_streamlit_secrets()), \
            mock.patch("utils.st", _fake_streamlit_secrets()), \
            mock.patch("auth.get_supabase", return_value=client):
        df = nwp_forecast._load_gfs_from_cache(key)
    assert df is not None and len(df) == 1
    assert ("get_gfs_cache", {"p_key": key}) in client.calls


def test_list_users_paginates_until_short_page():
    class _Admin:
        def __init__(self):
            self.calls = []

        def list_users(self, page=None, per_page=None):
            self.calls.append((page, per_page))
            if page == 1:
                return [
                    types.SimpleNamespace(
                        id="u%d" % i, email="u%d@example.com" % i, created_at=""
                    )
                    for i in range(100)
                ]
            return [types.SimpleNamespace(
                id="last", email="last@example.com", created_at="")]

    class _Auth:
        def __init__(self):
            self.admin = _Admin()

    class _Client:
        def __init__(self):
            self.auth = _Auth()

    client = _Client()
    users = auth._list_users(client)
    assert len(users) == 101
    assert client.auth.admin.calls == [(1, 100), (2, 100)]


def test_scalar_rpc_logs_failure_and_returns_default():
    class _Client:
        def rpc(self, name, params=None):
            raise RuntimeError("storage down")

    class _Handler(logging.Handler):
        def __init__(self):
            super().__init__()
            self.records = []

        def emit(self, record):
            self.records.append(record)

    handler = _Handler()
    old_level = db._LOG.level
    db._LOG.addHandler(handler)
    db._LOG.setLevel(logging.WARNING)
    try:
        db.get_storage_usage_bytes.clear()
        with mock.patch.object(db, "get_supabase", return_value=_Client()):
            assert db.get_storage_usage_bytes("uid-1") == 0
    finally:
        db._LOG.removeHandler(handler)
        db._LOG.setLevel(old_level)
    assert any("get_storage_usage" in r.getMessage() for r in handler.records)


def test_gfs_cache_key_rounds_coordinates():
    a = nwp_forecast._gfs_forecast_cache_key(39.941, 116.851, 7, "gfs_seamless")
    b = nwp_forecast._gfs_forecast_cache_key(39.94, 116.85, 7, "gfs_seamless")
    assert a == b
    assert "39.9400_116.8500" in a


def test_invite_code_is_128_bit():
    code = auth._gen_code()
    assert len(code) == 32
    assert all(ch in "0123456789ABCDEF" for ch in code)
    assert auth._hash_invite_code(code) == auth._hash_invite_code(code.lower())


# ============================================================
# 四、schema.sql 与错误文案
# ============================================================
def test_schema_defines_cache_rpc_and_updated_at():
    sql = _read("sql/schema.sql")
    for needle in (
        "add column if not exists updated_at",
        "gfs_cache_updated_idx",
        "create or replace function public.put_gfs_cache",
        "create or replace function public.get_gfs_cache",
        "revoke select on public.gfs_cache",
        "revoke insert, update, delete on public.gfs_cache",
        "create or replace function public.security_selfcheck",
        "grant execute on function public.security_selfcheck() to service_role",
        "revoke execute on function public.security_selfcheck() from public, anon, authenticated;",
        "revoke execute on function public.save_dataset(uuid, text, text) from public, anon;",
        "revoke execute on function public.consume_invite_code(text, uuid) from public, anon;",
        "from public, anon, authenticated;",
        "to service_role;",
        "datasets_name_len_check",
        "insert into public.profiles (user_id) values (v_uid)",
        "select id from auth.users",
        "expires_at timestamptz not null",
        "revoked_at timestamptz",
        "revoked_at is null",
        "expires_at is null or expires_at > now()",
        "schema_version",
        "admin_audit_log",
        "revoke all on public.admin_audit_log",
        "profiles_role_check",
        "gfs_cache_lat_check",
        "vision_usage_total_check",
    ):
        assert needle in sql, needle
    # save_dataset 与 begin_vision_call 两处都要先补行再锁
    assert sql.count("insert into public.profiles (user_id) values (v_uid)") >= 2
    # 验码、认领、核销三条路径都要过滤作废与过期
    assert sql.count("revoked_at is null") >= 3
    assert sql.count("expires_at is null or expires_at > now()") >= 3


def test_schema_counts_dataset_name_against_quota():
    sql = _read("sql/schema.sql")
    assert "octet_length(p_name)" in sql
    assert "char_length(p_name) > 200" in sql
    assert "数据集数量已达上限" in sql


def test_save_error_message_maps_new_codes():
    assert "配额" in db.save_error_message("配额不足")
    assert "名称" in db.save_error_message("名称过长")
    assert "数量" in db.save_error_message("数据集数量已达上限")
    assert "保存失败" in db.save_error_message("未知错误")


def test_admin_selfcheck_reads_rpc():
    class _Client:
        def __init__(self, data):
            self.data = data
            self.calls = []

        def rpc(self, name, params=None):
            self.calls.append(name)
            return types.SimpleNamespace(execute=lambda: _Resp(self.data))

    client = _Client({"rls": {"datasets": True}})
    assert auth._run_security_selfcheck(client)["rls"]["datasets"] is True
    assert client.calls == ["security_selfcheck"]


def test_admin_selfcheck_returns_none_on_error():
    class _Boom:
        def rpc(self, name, params=None):
            raise RuntimeError("function does not exist")

    assert auth._run_security_selfcheck(_Boom()) is None


def test_admin_audit_writes_log():
    class _Client:
        def __init__(self):
            self.calls = []

        def table(self, name):
            self.calls.append(("table", name))
            return self

        def insert(self, payload):
            self.calls.append(("insert", payload))
            return self

        def execute(self):
            self.calls.append(("execute",))
            return types.SimpleNamespace(data=[])

    client = _Client()
    auth._audit_admin(client, "quota.storage.update", "uid-1", {"mb": 20})
    assert client.calls[0] == ("table", "admin_audit_log")
    assert client.calls[1][0] == "insert"
    assert client.calls[1][1]["action"] == "quota.storage.update"
    assert client.calls[1][1]["target_user"] == "uid-1"


if __name__ == "__main__":
    import traceback

    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception:
                failed += 1
                print(f"[FAIL] {name}")
                traceback.print_exc()
            else:
                print(f"[PASS] {name}")
    print(f"\n{'FAILED' if failed else 'ALL PASSED'} ({failed} failures)")
    sys.exit(1 if failed else 0)
