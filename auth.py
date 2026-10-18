"""登录鉴权模块：基于 Supabase Auth 的邮箱密码登录/注册。

设计要点：
- 使用 Supabase 匿名密钥 (anon key) + 行级安全 (RLS) 即可安全做客户端登录，
  无需自建后端。匿名密钥可安全暴露在前端。
- 所有用户数据按 user_id 隔离，由数据库 RLS 强制保证（见 sql/schema.sql）。
- 密钥从 Streamlit Secrets 读取：SUPABASE_URL / SUPABASE_ANON_KEY。
- 注册采用「邀请码」授权模式：关闭了 Supabase 公开注册，仅持有效邀请码、
  并经服务端 service_role 建账号后方可注册（见 _register_with_invite）。
- 服务端管理操作（生成邀请码、列用户、配额）使用 SUPABASE_SERVICE_ROLE_KEY，
  该密钥绕过 RLS，仅存于 Streamlit Secrets（服务端），绝不进入前端 JS。
- 登录页为标准 Streamlit 表单，简洁清晰，无额外动画背景。
"""

import hashlib
import logging
import socket
from urllib.parse import urlparse

import streamlit as st

from modules.supabase_backend import selfcheck_problems
from utils import safe_error_text

_LOG = logging.getLogger(__name__)


# ============================================================
# 一、Supabase 客户端（按会话持有）
# ============================================================
# 安全修复 P0-1：客户端不再使用 @st.cache_resource。该装饰器在 Streamlit 中
# 是全局单例，所有用户、所有会话、所有 rerun 共享同一个对象；而
# sign_in_with_password() 会把登录会话写进这个对象，于是并发用户之间身份
# 互相串号（A 的保存落到 B 的账号、B 的读取被 RLS 判为无权）。现改为每个
# 浏览器会话各自持有一个客户端，登录态互不可见。
_SESSION_CLIENT_KEY = "_sb_client"
_SESSION_ADMIN_KEY = "_sb_admin_client"


def _secrets_get(name: str, default: str = "") -> str:
    """读 Streamlit secrets；缺文件或缺键时返回 default 而不抛异常。

    安全修复 P0-4：缺少 secrets.toml 时 st.secrets.get 抛
    StreamlitSecretNotFoundError（基类 FileNotFoundError，Mapping.get 不吞），
    导致后面的配置指引永远显示不出来。
    """
    try:
        return str(st.secrets.get(name, default)).strip()
    except Exception:
        return default


def _clean_url(url: str) -> str:
    """清理常见复制错误：REST 路径、协议前后空格、尾部斜杠。"""
    url = (url or "").strip()
    if url.endswith("/rest/v1/"):
        url = url[:-9]
    elif url.endswith("/rest/v1"):
        url = url[:-8]
    url = url.rstrip("/")
    if url and not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


@st.cache_data(ttl=600, show_spinner=False)
def _dns_precheck(host: str):
    """DNS 预检，返回 None 表示可解析，否则返回错误说明。

    纯连通性信息，不含任何用户状态，可安全共享，避免每个新会话重复解析。
    """
    try:
        socket.getaddrinfo(host, 443)
        return None
    except socket.gaierror as e:
        return str(e)


def _create_client(key_name: str, *, fatal: bool = True):
    """按密钥名创建 Supabase 客户端。

    fatal=True 时缺依赖/缺密钥/DNS 失败会给出可读提示并终止渲染；
    fatal=False（管理客户端）时静默返回 None，由调用方降级处理。
    """
    try:
        from supabase import create_client
    except ImportError:
        if not fatal:
            return None
        st.error(
            "❌ 缺少依赖 `supabase`。请在 requirements.txt 添加 `supabase` 后重新部署。"
        )
        st.stop()
        return None

    url = _clean_url(_secrets_get("SUPABASE_URL"))
    key = _secrets_get(key_name)
    if not url or not key:
        if not fatal:
            return None
        st.error(
            "❌ 未配置 Supabase 密钥。\n\n"
            "请在 Streamlit Cloud 的 **Settings → Secrets** 中添加：\n"
            "```\nSUPABASE_URL = \"https://xxxx.supabase.co\"\n"
            "SUPABASE_ANON_KEY = \"eyJ...\"\n```\n"
            "本地运行时可写入 `.streamlit/secrets.toml`。"
        )
        st.stop()
        return None

    # 提前解析域名：create_client 本身不会立即联网，真正出错往往在 sign_up/sign_in
    parsed = urlparse(url)
    host = parsed.hostname or url.split("//")[-1].split("/")[0]
    dns_error = _dns_precheck(host)
    if dns_error:
        if not fatal:
            return None
        st.error(
            f"❌ DNS 解析失败：{dns_error}\n\n"
            f"当前 SUPABASE_URL：`{url}`\n"
            f"解析主机名：`{host}`\n\n"
            "请检查：\n"
            "1. Streamlit Cloud Secrets 里的 URL 是否完整、无多余空格；\n"
            "2. Supabase 项目是否已创建完成（Project Settings → API 里的 URL）；\n"
            "3. 如刚创建项目，DNS 生效可能需要 3–5 分钟；\n"
            "4. 复制 URL 时不要带 `/rest/v1/` 路径。"
        )
        st.stop()
        return None

    try:
        return create_client(url, key)
    except Exception as e:
        if not fatal:
            return None
        st.error(
            "❌ 创建 Supabase 客户端失败："
            + safe_error_text(e, "请检查 SUPABASE_URL 与密钥配置。")
            + f"\n\n当前 SUPABASE_URL：`{url}`"
        )
        st.stop()
        return None


def _session_client(key_name: str, session_key: str, *, fatal: bool):
    """按会话缓存一个 Supabase 客户端；创建失败返回 None。"""
    cached = st.session_state.get(session_key)
    if cached is not None:
        return cached
    client = _create_client(key_name, fatal=fatal)
    if client is not None:
        st.session_state[session_key] = client
    return client


def get_supabase():
    """返回**当前会话专属**的 Supabase 客户端（含本会话登录态）。"""
    return _session_client("SUPABASE_ANON_KEY", _SESSION_CLIENT_KEY, fatal=True)


def get_supabase_admin():
    """返回当前会话的管理客户端（service_role，绕过 RLS）。

    仅用于受 ADMIN_PASSWORD 保护的服务端管理操作与 GFS 缓存写入。
    该密钥绝不进入前端。未配置时返回 None，由调用方降级处理。
    """
    return _session_client(
        "SUPABASE_SERVICE_ROLE_KEY", _SESSION_ADMIN_KEY, fatal=False
    )


# ============================================================
# 二、登录态判定
# ============================================================
def is_authenticated() -> bool:
    """当前会话是否已登录"""
    return bool(st.session_state.get("auth_user"))


# 退出登录时保留的键：仅导航栈，不含任何用户数据。
# 由 modules.app_state 统一声明，避免第二份手写清单。
from modules.app_state import LOGOUT_KEEP as _LOGOUT_KEEP


def sign_out_user():
    """退出登录：先让服务端会话失效，再清空本会话全部业务状态。

    安全修复 P0-2：历史实现只删 session_state 里的用户信息，从不调用
    sb.auth.sign_out()，也不丢弃客户端对象，于是登出后仍持有上一用户的有效
    令牌；同时漏清了 api_df/quality_score/climate_* 等键。
    """
    sb = st.session_state.get(_SESSION_CLIENT_KEY)
    if sb is not None:
        try:
            sb.auth.sign_out()
        except Exception:
            _LOG.warning("服务端退出登录失败，继续清理本地会话", exc_info=True)
    for k in list(st.session_state.keys()):
        if k not in _LOGOUT_KEEP:
            del st.session_state[k]
    st.session_state["active_tab"] = 0
    st.session_state["import_step"] = 0
    st.session_state["import_method"] = None


# ============================================================
# 二点五、会话过期处理（S5）
# ============================================================
# 只认登录态失效类错误。网络抖动、服务端 5xx 不在这里处理，避免一次故障
# 就把用户踢回登录页。
_SESSION_ERROR_MARKERS = (
    "jwt expired",
    "invalid jwt",
    "token is expired",
    "token has expired",
    "invalid claim",
    "session missing",
    "refresh token",
    "401",
    "pgrst301",
)


def is_session_error(exc) -> bool:
    """判断异常是否属于登录态失效（过期、刷新失败、令牌无效）。"""
    text = str(exc).lower()
    return any(marker in text for marker in _SESSION_ERROR_MARKERS)


def expire_session():
    """会话失效：清空本会话并回到登录页。"""
    sign_out_user()
    st.session_state["auth_error"] = "登录已过期，请重新登录。"
    st.rerun()


def ensure_session():
    """已登录页面的 rerun 入口：校验会话，刷新失败则回登录页。

    supabase-auth 的 ``get_session()`` 会在过期前自动刷新；刷新失败会抛
    异常，返回 None 表示本地会话已丢失。网络错误不强制登出。
    """
    if not is_authenticated():
        return
    sb = st.session_state.get(_SESSION_CLIENT_KEY)
    if sb is None:
        # 测试桩或极端残缺状态下可能只有 auth_user 没有客户端；不在这里
        # 强制登出，避免把一次内部状态不完整误判成会话过期。
        _LOG.warning("已登录但缺少会话客户端，跳过会话校验")
        return
    try:
        getter = getattr(getattr(sb, "auth", None), "get_session", None)
        if getter is None:
            return
        session = getter()
    except Exception as exc:
        if is_session_error(exc):
            expire_session()
        else:
            _LOG.warning("会话校验失败，保留当前登录态", exc_info=True)
        return
    if session is None:
        expire_session()


def _apply_cloud_theme(user) -> None:
    """登录成功后，把 Supabase user_metadata 里的偏好应用到当前会话。

    theme_aether 在页面加载时可能已按本地文件初始化，云端值优先级更高，
    这里做登录后的覆盖同步。同时读回天气墙偏好（城市列表 cities JSON 串
    + 显示开关 show_wall）。读取失败只记日志，不阻断登录。
    """
    try:
        from modules import theme_aether, city_prefs
        meta = getattr(user, "user_metadata", None) or {}
        theme_aether.apply_cloud_theme(meta.get("theme"))
        city_prefs.apply_cloud_prefs(meta.get("cities"), meta.get("show_wall"))
    except Exception:
        _LOG.warning("应用云端偏好失败", exc_info=True)


# ============================================================
# 三、登录/注册页面
# ============================================================
def render_auth_page():
    """渲染简洁的登录/注册页。

    使用标准 Streamlit 表单，输入框与提示明显、可读性好。
    注册需填写有效邀请码，并经服务端建账号（授权模式）。
    调用方在判断未登录后应紧接着 st.stop()。
    """
    st.markdown("## 气象数据交互分析平台")
    st.caption("登录或注册后使用 · 数据按账号私有隔离 · 注册需邀请码")

    with st.form("auth_form"):
        mode = st.radio("操作", ["登录", "注册"], horizontal=True, key="auth_mode")
        email = st.text_input("邮箱", placeholder="you@example.com", key="auth_email")
        password = st.text_input(
            "密码", type="password", placeholder="至少 6 位", key="auth_password"
        )
        invite_code = ""
        if mode == "注册":
            invite_code = st.text_input(
                "邀请码", placeholder="向管理员索取", key="auth_invite"
            ).strip().upper()

        submitted = st.form_submit_button("进入平台", use_container_width=True)
        if submitted:
            if not email or not password:
                st.error("请输入邮箱和密码。")
            elif len(password) < 6:
                st.error("密码至少 6 位。")
            elif mode == "注册" and not invite_code:
                st.error("请填写邀请码（注册需管理员授权）。")
            else:
                st.session_state.pop("auth_error", None)
                _do_auth(mode, email, password, invite_code)

    error = st.session_state.get("auth_error")
    if error:
        if isinstance(error, str):
            st.error(error)
        else:
            # 旧版本可能遗留非字符串值，清空避免 st.error 报错
            st.session_state.pop("auth_error", None)
            st.error("登录状态异常，请刷新页面后重试。")

    st.info(
        "注册需有效邀请码，由管理员在下方「管理员入口」生成并分发。"
    )

    # 管理员入口：生成邀请码、管理用户与配额
    from modules.admin.panel import render_admin_panel
    render_admin_panel()


# ============================================================
# 四、鉴权动作
# ============================================================
def _do_auth(mode: str, email: str, password: str, invite_code: str = ""):
    sb = get_supabase()
    if sb is None:
        return
    try:
        if mode == "注册":
            _register_with_invite(sb, email, password, invite_code)
        else:  # 登录
            res = sb.auth.sign_in_with_password(
                {"email": email, "password": password}
            )
            st.session_state["auth_user"] = {
                "id": res.user.id,
                "email": res.user.email,
            }
            st.session_state.pop("auth_error", None)
            _apply_cloud_theme(res.user)  # 读回云端主题偏好（重启保持）
            st.rerun()
    except Exception as e:
        # 常见错误：Invalid login credentials / Email not confirmed / weak password
        msg = str(e).lower()
        if "invalid login credentials" in msg or "invalid_credentials" in msg:
            st.session_state["auth_error"] = "邮箱或密码错误，请重新输入。"
        elif "email not confirmed" in msg or "email_not_confirmed" in msg:
            st.session_state["auth_error"] = (
                "邮箱尚未确认。请查收邮件，或到 Supabase 控制台关闭 Confirm email。"
            )
        elif "weak password" in msg or ("password" in msg and "6" in msg):
            st.session_state["auth_error"] = "密码强度不足：至少 6 位。"
        else:
            st.session_state["auth_error"] = safe_error_text(e, "登录或注册失败，请稍后重试。")
        st.rerun()


def _release_invite_code(sb_admin, code: str) -> None:
    """释放已认领但未核销的邀请码（建号失败时回滚）。失败静默。"""
    if sb_admin is None:
        return
    try:
        sb_admin.rpc("release_invite_code", {"p_code": _hash_invite_code(code)}).execute()
    except Exception:
        pass


def _register_with_invite(sb, email: str, password: str, code: str):
    """邀请码授权注册流程（原子认领）：
    1) 原子认领邀请码；2) 用 service_role 建账号；3) 核销绑定；4) 自动登录。

    安全修复 P1-1：原实现是「只读验码 → 建号 → 核销」三步非原子，并发持同一
    邀请码的两个请求可双双通过只读验码、各建一个账号（一码多账号）。现改为
    「原子认领 → 建号 → 核销」，认领在数据库函数内用 update ... where 的行锁
    完成，并发只有一个请求能认领成功。
    """
    # 1) 先确认服务端具备管理密钥，再认领，避免认领后无法回滚
    sb_admin = get_supabase_admin()
    if sb_admin is None:
        st.session_state["auth_error"] = (
            "服务端未配置 SUPABASE_SERVICE_ROLE_KEY，无法授权注册。"
            "请在 Secrets 中添加该密钥。"
        )
        st.rerun()
        return

    # 2) 原子认领（认领成功的码在 15 分钟内对其他请求不可用）
    # 安全修复 R-22：库里只存 SHA-256 摘要，因此传哈希而不是明文
    code_hash = _hash_invite_code(code)
    try:
        claimed = sb.rpc("claim_invite_code", {"p_code": code_hash}).execute()
    except Exception as e:
        st.session_state["auth_error"] = _schema_error_msg(e)
        st.rerun()
        return
    if not claimed.data:
        st.session_state["auth_error"] = "邀请码无效、已被使用或正在被处理。"
        st.rerun()
        return

    # 3) 用 service_role 建账号（绕过已关闭的公开注册）
    try:
        au = sb_admin.auth.admin.create_user(
            {"email": email, "password": password, "email_confirm": True}
        )
        new_uid = au.user.id if au.user else None
        if not new_uid:
            raise RuntimeError("未返回用户标识")
    except Exception as e:
        _release_invite_code(sb_admin, code)
        msg = str(e).lower()
        if "already" in msg or "registered" in msg or "exists" in msg:
            st.session_state["auth_error"] = "该邮箱已注册，请直接登录。"
        else:
            st.session_state["auth_error"] = safe_error_text(e, "建账号失败，请稍后重试或联系管理员。")
        st.rerun()
        return

    # 4) 核销（绑定新用户）
    # consume_invite_code 仅 authenticated/service_role 可调，注册时用户尚未
    # 登录（anon），故必须由 service_role 客户端调用。
    try:
        sb_admin.rpc(
            "consume_invite_code", {"p_code": code_hash, "p_user_id": new_uid}
        ).execute()
    except Exception as e:
        # 核销失败必须回滚：删除刚建的账号并释放认领，
        # 否则会留下一个没有消耗邀请码的孤儿账号，破坏「一码一账号」不变量。
        try:
            sb_admin.auth.admin.delete_user(new_uid)
        except Exception:
            pass
        _release_invite_code(sb_admin, code)
        st.session_state["auth_error"] = (
            "邀请码核销失败，本次注册已回滚：" + _schema_error_msg(e)
        )
        st.rerun()
        return

    # 5) 自动登录
    _auto_login(sb, email, password)


def _auto_login(sb, email: str, password: str):
    try:
        res = sb.auth.sign_in_with_password(
            {"email": email, "password": password}
        )
        st.session_state["auth_user"] = {
            "id": res.user.id,
            "email": res.user.email,
        }
        st.session_state.pop("auth_error", None)
        _apply_cloud_theme(res.user)
        st.rerun()
    except Exception as e:
        st.session_state["auth_error"] = safe_error_text(
            e, "账号已创建但自动登录失败，请手动登录。"
        )
        st.rerun()


# ============================================================
# 五、管理员面板（ADMIN_PASSWORD 保护，服务端操作）
# 安全修复（P-05）：常量时间比较 + 失败限流锁定 + 解锁会话超时
# ============================================================

# 安全修复（R-18）：失败计数与锁定时间放在模块级（进程内全局），而不是
# st.session_state。原实现新开浏览器会话或清 cookie 即可重置计数，限流形同
# 虚设。Streamlit Cloud 单进程服务，进程内全局对全部会话生效。












def _hash_invite_code(code: str) -> str:
    """邀请码哈希（安全修复 R-22）。

    invite_codes.code 列改存 SHA-256 十六进制摘要而不是明文，即使数据库被读走
    也无法反推可用的邀请码。校验 / 认领 / 核销全部按哈希比对，SQL 函数签名不变。
    注意：迁移后库里遗留的明文码不再匹配，需由管理员重新生成（见 schema.sql 说明）。
    """
    return hashlib.sha256((code or "").strip().upper().encode("utf-8")).hexdigest()


# ============================================================
# 六、工具函数
# ============================================================












def _schema_error_msg(e) -> str:
    """把常见 Supabase/PostgREST 报错翻译成中文操作指引。"""
    msg = str(e).lower()
    if "could not find the table" in msg or "pgrst205" in msg:
        return (
            "数据库表未创建：请在 Supabase 控制台 → SQL Editor 中，"
            "运行 `sql/schema.sql` 全部内容，然后刷新页面。"
        )
    if "could not find the function" in msg or "pgrst201" in msg:
        return (
            "数据库函数未创建：请在 Supabase 控制台 → SQL Editor 中，"
            "运行 `sql/schema.sql` 全部内容，然后刷新页面。"
        )
    return safe_error_text(e, "操作失败，请检查数据库配置或联系管理员。")


