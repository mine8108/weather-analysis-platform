"""认证会话隔离回归测试（P0-1 / P0-2 / P1-1）。

用 AppTest.from_function 在真实 Streamlit 脚本上下文中运行，配合注入的假
supabase 模块，验证：

1. 客户端按会话持有：同一会话复用同一实例，不同会话互不相同（P0-1）。
2. 登出会调用 sb.auth.sign_out() 并清空本会话全部业务状态（P0-2）。
3. 邀请码注册走「原子认领 → 建号 → 核销」（P1-1）：
   - 认领失败时不建号；
   - 建号失败时释放认领；
   - 核销失败时删除刚建账号并释放认领。

无 pytest 时可直接运行本文件（`python tests/test_auth_session.py`）。
"""
import os
import sys
import types

import hashlib

# 让本文件既能被 pytest 收集，也能直接 `python tests/test_auth_session.py` 运行
_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

APP_SECRETS = {
    "SUPABASE_URL": "https://example.com",
    "SUPABASE_ANON_KEY": "anon-key",
    "SUPABASE_SERVICE_ROLE_KEY": "service-key",
}

# 记录所有被创建出来的假客户端，供跨会话隔离断言使用
CREATED = []


# ============================================================
# 假 supabase 模块
# ============================================================
class _FakeResp:
    def __init__(self, data):
        self.data = data


class _FakeRpc:
    def __init__(self, client, name, params):
        self._c, self._n, self._p = client, name, params

    def execute(self):
        self._c.calls.append(("rpc", self._n, dict(self._p)))
        if self._n == "claim_invite_code":
            return _FakeResp(self._c.claim_ok)
        if self._n == "consume_invite_code" and self._c.consume_error:
            raise RuntimeError(self._c.consume_error)
        return _FakeResp(True)


class _FakeAdmin:
    def __init__(self, client):
        self._c = client

    def create_user(self, payload):
        self._c.calls.append(("create_user", payload))
        if self._c.create_user_error:
            raise RuntimeError(self._c.create_user_error)
        return types.SimpleNamespace(user=types.SimpleNamespace(id="uid-1"))

    def delete_user(self, uid):
        self._c.calls.append(("delete_user", uid))


class _FakeAuth:
    def __init__(self, client):
        self._c = client
        self.admin = _FakeAdmin(client)

    def sign_out(self):
        self._c.calls.append(("sign_out",))

    def sign_in_with_password(self, creds):
        self._c.calls.append(("sign_in", creds))
        return types.SimpleNamespace(
            user=types.SimpleNamespace(id="uid-1", email=creds.get("email", ""))
        )

    def update_user(self, payload):
        self._c.calls.append(("update_user", payload))


class FakeClient:
    """最小可用的假客户端，记录全部调用。"""

    def __init__(self, *, claim_ok=True, create_user_error=None, consume_error=None):
        self.calls = []
        self.claim_ok = claim_ok
        self.create_user_error = create_user_error
        self.consume_error = consume_error
        self.auth = _FakeAuth(self)

    def rpc(self, name, params=None):
        return _FakeRpc(self, name, params or {})

    def names(self):
        return [c[0] for c in self.calls]


def _install_fake_supabase(defaults=None):
    """把假 supabase 模块装进 sys.modules；返回已创建客户端列表。"""
    defaults = defaults or {}
    mod = types.ModuleType("supabase")

    def create_client(url, key):
        client = FakeClient(**defaults)
        client.url, client.key = url, key
        CREATED.append(client)
        return client

    mod.create_client = create_client
    sys.modules["supabase"] = mod
    return mod


def _new_apptest(script):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_function(script, default_timeout=30)
    for k, v in APP_SECRETS.items():
        at.secrets[k] = v
    return at


# ============================================================
# 被测脚本（在 Streamlit 运行上下文中执行）
# ============================================================
def _script_client_identity():
    import streamlit as st

    import auth

    auth._dns_precheck = lambda host: None  # 避免测试依赖真实 DNS
    a = auth.get_supabase()
    b = auth.get_supabase()
    st.session_state["_t_same_instance"] = a is b
    st.session_state["_t_client_id"] = id(a)
    st.session_state["_t_url"] = a.url
    st.session_state["_t_key"] = a.key


def _script_sign_out():
    import streamlit as st

    import auth

    auth._dns_precheck = lambda host: None
    sb = auth.get_supabase()
    st.session_state["auth_user"] = {"id": "uid-1", "email": "a@b.c"}
    st.session_state["df"] = "some-data"
    st.session_state["api_df"] = "api-data"
    st.session_state["quality_score"] = 88.0
    auth.sign_out_user()
    st.session_state["_t_signed_out"] = ("sign_out" in sb.names())
    st.session_state["_t_cleared"] = not any(
        k in st.session_state
        for k in ("auth_user", "df", "api_df", "quality_score", "_sb_client")
    )
    st.session_state["_t_active_tab"] = st.session_state.get("active_tab")


def _script_register_claim_fails():
    import streamlit as st

    import auth

    if st.session_state.get("_t_done"):
        return
    st.session_state["_t_done"] = True
    auth._dns_precheck = lambda host: None
    auth.get_supabase()  # 触发假客户端创建（claim_ok=False）
    auth._register_with_invite(
        auth.get_supabase(), "new@user.com", "password1", "BADCODE"
    )


def _script_register_create_fails():
    import streamlit as st

    import auth

    if st.session_state.get("_t_done"):
        return
    st.session_state["_t_done"] = True
    auth._dns_precheck = lambda host: None
    auth._register_with_invite(
        auth.get_supabase(), "new@user.com", "password1", "GOODCODE"
    )


def _script_register_consume_fails():
    import streamlit as st

    import auth

    if st.session_state.get("_t_done"):
        return
    st.session_state["_t_done"] = True
    auth._dns_precheck = lambda host: None
    auth._register_with_invite(
        auth.get_supabase(), "new@user.com", "password1", "GOODCODE"
    )


# ============================================================
# 测试
# ============================================================
def test_client_is_per_session():
    """同一会话复用同一客户端实例；不同会话的客户端互不相同。"""
    CREATED.clear()
    _install_fake_supabase()
    at1 = _new_apptest(_script_client_identity).run()
    assert not at1.exception, f"脚本异常: {at1.exception}"
    assert at1.session_state["_t_same_instance"] is True, "同一会话应复用同一客户端"
    id1 = at1.session_state["_t_client_id"]

    at2 = _new_apptest(_script_client_identity).run()
    assert not at2.exception, f"脚本异常: {at2.exception}"
    id2 = at2.session_state["_t_client_id"]
    assert id1 != id2, "不同会话必须持有各自的客户端（原实现因全局缓存而共享）"
    assert len(CREATED) >= 2


def test_anon_key_used_for_user_client():
    CREATED.clear()
    _install_fake_supabase()
    at = _new_apptest(_script_client_identity).run()
    assert at.session_state["_t_key"] == "anon-key"
    assert at.session_state["_t_url"] == "https://example.com"


def test_sign_out_calls_supabase_and_clears_state():
    CREATED.clear()
    _install_fake_supabase()
    at = _new_apptest(_script_sign_out).run()
    assert not at.exception, f"脚本异常: {at.exception}"
    assert at.session_state["_t_signed_out"] is True, "必须调用 sb.auth.sign_out()"
    assert at.session_state["_t_cleared"] is True, "业务数据键必须被清空"
    assert at.session_state["_t_active_tab"] == 0, "登出后应回到导入页"


def test_register_rejects_when_claim_fails():
    """认领失败（码无效/被占用）时不得创建账号。"""
    CREATED.clear()
    _install_fake_supabase({"claim_ok": False})
    at = _new_apptest(_script_register_claim_fails).run()
    assert not at.exception, f"脚本异常: {at.exception}"
    assert "邀请码无效" in at.session_state["auth_error"]
    client = CREATED[-1]
    assert "create_user" not in client.names(), "认领失败却建了账号"


def _script_register_uses_hash():
    import streamlit as st

    import auth

    if st.session_state.get("_t_done"):
        return
    st.session_state["_t_done"] = True
    auth._dns_precheck = lambda host: None
    auth._register_with_invite(
        auth.get_supabase(), "new@user.com", "password1", "GOODCODE"
    )


def _admin_client():
    """取最后一次创建的管理客户端（service_role 密钥那个）。"""
    admins = [c for c in CREATED if getattr(c, "key", None) == "service-key"]
    assert admins, "未创建管理客户端"
    return admins[-1]


def test_register_releases_claim_when_create_user_fails():
    """建号失败时必须释放认领，让码可被再次使用。"""
    CREATED.clear()
    _install_fake_supabase({"claim_ok": True, "create_user_error": "boom"})
    at = _new_apptest(_script_register_create_fails).run()
    assert not at.exception, f"脚本异常: {at.exception}"
    calls = _admin_client().calls
    names = [c[0] for c in calls]
    assert "create_user" in names
    assert any(
        c[0] == "rpc" and c[1] == "release_invite_code" for c in calls
    ), "建号失败后未释放认领"
    assert "建账号失败" in at.session_state["auth_error"]


def test_register_rolls_back_when_consume_fails():
    """核销失败时必须删除刚建的账号并释放认领（一码一账号不变量）。"""
    CREATED.clear()
    _install_fake_supabase({"claim_ok": True, "consume_error": "rpc down"})
    at = _new_apptest(_script_register_consume_fails).run()
    assert not at.exception, f"脚本异常: {at.exception}"
    calls = _admin_client().calls
    assert any(c[0] == "delete_user" for c in calls), "核销失败未回滚账号"
    assert any(
        c[0] == "rpc" and c[1] == "release_invite_code" for c in calls
    ), "核销失败未释放认领"
    assert "已回滚" in at.session_state["auth_error"]


def test_register_sends_hash_not_plaintext():
    """R-22：认领与核销传给数据库的是 SHA-256 摘要，不是明文邀请码。"""
    CREATED.clear()
    _install_fake_supabase({"claim_ok": True})
    at = _new_apptest(_script_register_uses_hash).run()
    assert not at.exception, f"脚本异常: {at.exception}"

    expected = hashlib.sha256("GOODCODE".encode("utf-8")).hexdigest()
    assert len(expected) == 64

    anon = [c for c in CREATED if getattr(c, "key", None) == "anon-key"][-1]
    claim = [c[2] for c in anon.calls if c[0] == "rpc" and c[1] == "claim_invite_code"]
    assert claim and claim[0]["p_code"] == expected, claim

    admin = _admin_client()
    consume = [c[2] for c in admin.calls if c[0] == "rpc" and c[1] == "consume_invite_code"]
    assert consume and consume[0]["p_code"] == expected, consume
    assert "GOODCODE" not in str(claim) + str(consume), "明文邀请码不得进入请求参数"


def test_clean_url_normalizes():
    """URL 清洗：去 REST 路径、补协议、去尾斜杠。"""
    _install_fake_supabase()
    import auth

    assert auth._clean_url("https://x.supabase.co/rest/v1/") == "https://x.supabase.co"
    assert auth._clean_url("x.supabase.co/rest/v1") == "https://x.supabase.co"
    assert auth._clean_url("  https://x.supabase.co//  ") == "https://x.supabase.co"
    assert auth._clean_url("") == ""


# ============================================================
# 无 pytest 时的入口
# ============================================================
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
    print(f"\n{'FAILED' if failed else 'ALL PASSED'} ({failed} 个失败)")
    sys.exit(1 if failed else 0)
