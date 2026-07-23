"""登录鉴权模块：基于 Supabase Auth 的邮箱密码登录/注册。

设计要点：
- 使用 Supabase 匿名密钥 (anon key) + 行级安全 (RLS) 即可安全做客户端登录，
  无需自建后端。匿名密钥可安全暴露在前端。
- 所有用户数据按 user_id 隔离，由数据库 RLS 强制保证（见 supabase/schema.sql）。
- 密钥从 Streamlit Secrets 读取：SUPABASE_URL / SUPABASE_ANON_KEY。
"""

import streamlit as st


# ============================================================
# 一、Supabase 客户端
# ============================================================
@st.cache_resource
def get_supabase():
    """返回 Supabase 客户端（带缓存，避免重复连接）。

    缺失依赖或密钥时，给出可读提示并终止当前脚本渲染。
    """
    try:
        from supabase import create_client
    except ImportError:
        st.error(
            "❌ 缺少依赖 `supabase`。请在 requirements.txt 添加 `supabase` 后重新部署。"
        )
        st.stop()
        return None

    url = st.secrets.get("SUPABASE_URL")
    key = st.secrets.get("SUPABASE_ANON_KEY")
    if not url or not key:
        st.error(
            "❌ 未配置 Supabase 密钥。\n\n"
            "请在 Streamlit Cloud 的 **Settings → Secrets** 中添加：\n"
            "```\nSUPABASE_URL = \"https://xxxx.supabase.co\"\n"
            "SUPABASE_ANON_KEY = \"eyJ...\"\n```\n"
            "本地运行时可写入 `.streamlit/secrets.toml`。"
        )
        st.stop()
        return None

    return create_client(url, key)


# ============================================================
# 二、登录态判定
# ============================================================
def is_authenticated() -> bool:
    """当前会话是否已登录"""
    return bool(st.session_state.get("auth_user"))


def sign_out_user():
    """退出登录：清掉会话态里的用户信息"""
    st.session_state.pop("auth_user", None)
    # 顺带清掉仅属于当前用户的工作数据，防止串号
    for k in ("df", "source", "manual_data", "warnings_list", "_import_history",
              "_auto_load_done"):
        st.session_state.pop(k, None)


# ============================================================
# 三、登录 / 注册 页面
# ============================================================
_LOGIN_CSS = """
<style>
.auth-wrap {
    max-width: 420px;
    margin: 6vh auto 0 auto;
    padding: 36px 32px 28px 32px;
    background: var(--bg-secondary, #f8fafc);
    border: 1px solid var(--border-color, #e2e8f0);
    border-radius: 14px;
    box-shadow: 0 12px 24px -4px rgba(0,0,0,0.08);
}
.auth-wrap h2 { margin: 0 0 4px 0; color: var(--accent, #1d4ed8); }
.auth-wrap .sub { color: #94a3b8; font-size: 0.85rem; margin-bottom: 20px; }
.auth-tip {
    margin-top: 16px; font-size: 0.78rem; color: #64748b;
    background: #fffbeb; border-left: 3px solid #f59e0b;
    padding: 8px 12px; border-radius: 0 8px 8px 0;
}
</style>
"""


def render_auth_page():
    """渲染登录/注册页。调用方在判断未登录后应紧接着 st.stop()。"""
    # 登录页需要的基础变量（不依赖主 CSS 是否加载）
    st.markdown(
        "<style>:root{--bg-secondary:#f8fafc;--border-color:#e2e8f0;"
        "--accent:#1d4ed8;}</style>",
        unsafe_allow_html=True,
    )
    st.markdown(_LOGIN_CSS, unsafe_allow_html=True)

    with st.container():
        st.markdown('<div class="auth-wrap">', unsafe_allow_html=True)
        st.markdown("🌤️ 气象数据交互分析平台")
        st.markdown('<div class="sub">请登录或注册后使用（数据按账号私有隔离）</div>',
                    unsafe_allow_html=True)

        mode = st.radio("模式", ["登录", "注册"], horizontal=True,
                        key="auth_mode")
        email = st.text_input("邮箱", key="auth_email",
                              placeholder="you@example.com")
        password = st.text_input("密码", type="password", key="auth_password",
                                 placeholder="至少 6 位")

        if st.button("进入", type="primary", use_container_width=True,
                     key="auth_submit"):
            if not email or not password:
                st.warning("请输入邮箱和密码。")
            elif len(password) < 6:
                st.warning("密码至少 6 位。")
            else:
                _do_auth(mode, email, password)

        st.markdown(
            '<div class="auth-tip">首次使用请选「注册」。'
            "若注册后无法登录，请到 Supabase 控制台关闭「Confirm email」"
            "或先完成邮箱验证。</div>",
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)


def _do_auth(mode: str, email: str, password: str):
    sb = get_supabase()
    if sb is None:
        return
    try:
        if mode == "注册":
            res = sb.auth.sign_up({"email": email, "password": password})
            if res.user is None:
                st.error("注册失败：邮箱可能已被注册或格式不正确。")
                return
            st.success("✅ 注册成功！如开启邮箱验证，请先查收确认邮件再登录。")
            # 若 Supabase 关闭了邮箱确认，可直接登录
            if res.session is not None:
                st.session_state["auth_user"] = {
                    "id": res.user.id,
                    "email": res.user.email,
                }
                st.rerun()
        else:  # 登录
            res = sb.auth.sign_in_with_password(
                {"email": email, "password": password}
            )
            st.session_state["auth_user"] = {
                "id": res.user.id,
                "email": res.user.email,
            }
            st.rerun()
    except Exception as e:
        msg = str(e)
        if "Invalid login" in msg or "invalid" in msg.lower():
            st.error("登录失败：邮箱或密码错误。")
        elif "User already registered" in msg:
            st.error("该邮箱已注册，请直接登录。")
        else:
            st.error(f"操作失败：{msg[:200]}")
