"""登录鉴权模块：基于 Supabase Auth 的邮箱密码登录/注册。

设计要点：
- 使用 Supabase 匿名密钥 (anon key) + 行级安全 (RLS) 即可安全做客户端登录，
  无需自建后端。匿名密钥可安全暴露在前端。
- 所有用户数据按 user_id 隔离，由数据库 RLS 强制保证（见 supabase/schema.sql）。
- 密钥从 Streamlit Secrets 读取：SUPABASE_URL / SUPABASE_ANON_KEY。
- 登录页背景为 Three.js + 自定义 GLSL 实现的**全天气实时场景**：按用户当地
  实时 WMO 天气代码（Open-Meteo）渲染晴/多云/雾/雨（牛毛↔瓢泼分级）/雪/雷暴，
  并由昼夜状态联动色温。定位用 ipapi.co。
- 登录/注册表单使用标准 Streamlit 控件，输入框与提示更明显、可访问性更好；
  交互卡片为黑色透明「液态玻璃」质感（backdrop-filter + SVG 湍流折射），
  文字用互补色保证可读性。
"""

import json
import socket
from urllib.parse import urlparse

import streamlit as st
import streamlit.components.v1 as components


# ============================================================
# 一、Supabase 客户端
# ============================================================
@st.cache_resource
def get_supabase():
    """返回 Supabase 客户端（带缓存，避免重复连接）。

    缺失依赖、密钥或网络不可达时，给出可读提示并终止当前脚本渲染。
    """
    try:
        from supabase import create_client
    except ImportError:
        st.error(
            "❌ 缺少依赖 `supabase`。请在 requirements.txt 添加 `supabase` 后重新部署。"
        )
        st.stop()
        return None

    url = str(st.secrets.get("SUPABASE_URL", "")).strip()
    key = str(st.secrets.get("SUPABASE_ANON_KEY", "")).strip()
    # 清理常见复制错误：去掉 REST 路径、协议前后空格、尾部斜杠
    if url.endswith("/rest/v1/"):
        url = url[:-9]
    elif url.endswith("/rest/v1"):
        url = url[:-8]
    url = url.rstrip("/")
    if url and not url.startswith(("http://", "https://")):
        url = "https://" + url
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

    # 提前解析域名：create_client 本身不会立即联网，真正出错往往在 sign_up/sign_in
    parsed = urlparse(url)
    host = parsed.hostname or url.replace("https://", "").replace("http://", "").split("/")[0]
    try:
        socket.getaddrinfo(host, 443)
    except socket.gaierror as e:
        st.error(
            f"❌ DNS 解析失败：{e}\n\n"
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
        st.error(
            f"❌ 创建 Supabase 客户端失败：{e}\n\n"
            f"当前 SUPABASE_URL：`{url}`"
        )
        st.stop()
        return None


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
# 三、全天气沉浸式背景（Three.js + GLSL）
# ============================================================
def load_weather_html() -> str:
    """读取 assets/login_weather.html 作为登录页全屏背景。

    该文件是自包含的 Three.js + GLSL 天气引擎，按用户当地实时 WMO 天气代码
    渲染晴/多云/雾/雨/雪/雷暴，并随昼夜联动。天气数据在 HTML 内部自取，
    不回传 Python（Streamlit component 当前不支持稳定双向通信）。
    """
    import os
    path = os.path.join(os.path.dirname(__file__), "assets", "login_weather.html")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return (
            "<!DOCTYPE html><html><body style='background:#070b14'></body></html>"
        )


# ============================================================
# 四、登录/注册页面
# ============================================================
def render_auth_page():
    """渲染沉浸式雨景登录/注册页。

    用 st.components.v1.html 嵌入全屏 Three.js 雨景背景；
    用标准 Streamlit 表单承载登录/注册，输入框和提示更明显。
    调用方在判断未登录后应紧接着 st.stop()。
    """
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&display=swap');

        :root {
            --glass-bg: rgba(5, 7, 12, 0.55);
            --glass-bg-soft: rgba(5, 7, 12, 0.32);
            --glass-border: rgba(255, 255, 255, 0.14);
            --accent: #ffcf8f;            /* 深蓝场景的互补色：暖琥珀 */
            --accent-strong: #ff9d5c;
            --text: #eef3fb;
            --text-dim: #aebfd6;
            --label: #c7d4e8;
            --err: #ff7a8a;
        }

        html, body, [data-testid="stAppViewContainer"], .stApp {
            background: #070b14 !important;
        }
        header[data-testid="stHeader"] { display: none !important; }
        [data-testid="stToolbar"] { display: none !important; }
        footer { display: none !important; }
        [data-testid="stAppViewBlockContainer"] { padding: 0 !important; }

        /* 背景组件容器：不占空间，iframe 全屏固定 */
        .stHtml {
            height: 0 !important;
            min-height: 0 !important;
            padding: 0 !important;
            margin: 0 !important;
            overflow: visible !important;
        }
        .stHtml > iframe {
            position: fixed;
            top: 0;
            left: 0;
            width: 100vw;
            height: 100vh;
            z-index: -1;
            border: none;
        }

        /* 液态玻璃登录卡片：黑色透明 + 折射边，文字互补色 */
        form[data-testid="stForm"] {
            position: relative;
            max-width: 440px;
            margin: 9vh auto 0;
            padding: 40px 38px 34px;
            border-radius: 22px;
            border: 1px solid var(--glass-border);
            box-shadow: 0 30px 80px -28px rgba(0,0,0,0.85),
                        inset 0 1px 0 rgba(255,255,255,0.16);
            font-family: 'Space Grotesk', system-ui, sans-serif;
            isolation: isolate;
        }
        form[data-testid="stForm"]::before {
            content: "";
            position: absolute;
            inset: 0;
            z-index: -1;
            border-radius: 22px;
            background: var(--glass-bg);
            -webkit-backdrop-filter: blur(18px) saturate(140%);
            backdrop-filter: blur(18px) saturate(140%);
            filter: url(#liquidGlass);   /* SVG 湍流折射（不支持时自动降级为纯模糊） */
        }
        form[data-testid="stForm"] h2 {
            color: var(--accent) !important;
            margin-bottom: 0.25rem;
            font-family: 'Space Grotesk', system-ui, sans-serif;
            letter-spacing: .3px;
        }
        form[data-testid="stForm"] .stMarkdown p {
            color: var(--text-dim) !important;
        }
        form[data-testid="stForm"] .stRadio > div {
            flex-direction: row;
            gap: 8px;
        }
        form[data-testid="stForm"] .stRadio label,
        form[data-testid="stForm"] .stTextInput label {
            color: var(--label) !important;
        }
        form[data-testid="stForm"] .stTextInput input {
            background: rgba(255, 255, 255, 0.06);
            border: 1px solid rgba(255, 255, 255, 0.12);
            color: var(--text);
            border-radius: 12px;
            transition: border-color .18s, box-shadow .18s;
        }
        form[data-testid="stForm"] .stTextInput input::placeholder {
            color: rgba(174, 191, 214, 0.55);
        }
        form[data-testid="stForm"] .stTextInput input:focus {
            border-color: var(--accent);
            box-shadow: 0 0 0 2px rgba(255, 207, 143, 0.18);
        }
        form[data-testid="stForm"] .stButton > button {
            width: 100%;
            background: linear-gradient(135deg, var(--accent), var(--accent-strong));
            color: #1a1205;
            border: none;
            border-radius: 12px;
            font-weight: 700;
            letter-spacing: .5px;
            padding: 14px;
            transition: filter .18s, transform .12s;
        }
        form[data-testid="stForm"] .stButton > button:hover {
            filter: brightness(1.07);
        }
        form[data-testid="stForm"] .stButton > button:active {
            transform: translateY(1px);
        }
        form[data-testid="stForm"] .stAlert {
            background: rgba(255, 122, 138, 0.10);
            border-left: 3px solid var(--err);
        }
        </style>

        <!-- 液态玻璃折射滤镜：feTurbulence + 位移贴图 -->
        <svg style="position:absolute;width:0;height:0;pointer-events:none" aria-hidden="true">
          <filter id="liquidGlass">
            <feTurbulence type="fractalNoise" baseFrequency="0.009 0.013"
                          numOctaves="2" seed="7" result="noise"/>
            <feGaussianBlur in="noise" stdDeviation="0.5" result="blur"/>
            <feDisplacementMap in="SourceGraphic" in2="blur" scale="13"
                              xChannelSelector="R" yChannelSelector="G"/>
          </filter>
        </svg>
        """,
        unsafe_allow_html=True,
    )

    # 全屏全天气背景（不传递 key，st.components.v1.html 不支持）
    components.html(load_weather_html(), height=820, scrolling=False)

    # 标准 Streamlit 登录/注册表单
    with st.form("auth_form"):
        st.markdown("## 气象数据交互分析平台")
        st.caption("登录或注册后使用 · 数据按账号私有隔离")

        mode = st.radio("操作", ["登录", "注册"], horizontal=True, key="auth_mode")
        email = st.text_input("邮箱", placeholder="you@example.com", key="auth_email")
        password = st.text_input(
            "密码", type="password", placeholder="至少 6 位", key="auth_password"
        )

        submitted = st.form_submit_button("进入平台", use_container_width=True)
        if submitted:
            if not email or not password:
                st.error("请输入邮箱和密码。")
            elif len(password) < 6:
                st.error("密码至少 6 位。")
            else:
                st.session_state.pop("auth_error", None)
                _do_auth(mode, email, password)

        error = st.session_state.get("auth_error")
        if error:
            if isinstance(error, str):
                st.error(error)
            else:
                # 旧版本可能遗留非字符串值，清空避免 st.error 报错
                st.session_state.pop("auth_error", None)
                st.error("登录状态异常，请刷新页面后重试。")

        st.info(
            "首次使用请选「注册」。若注册后无法登录，"
            "请到 Supabase 控制台关闭 Confirm email。"
        )


def _do_auth(mode: str, email: str, password: str):
    sb = get_supabase()
    if sb is None:
        return
    try:
        if mode == "注册":
            res = sb.auth.sign_up({"email": email, "password": password})
            if res.user is None:
                st.session_state["auth_error"] = "注册失败：邮箱可能已被注册或格式不正确。"
                st.rerun()
                return
            # 若 Supabase 关闭了邮箱确认，可直接登录
            if res.session is not None:
                st.session_state["auth_user"] = {
                    "id": res.user.id,
                    "email": res.user.email,
                }
                st.session_state.pop("auth_error", None)
                st.rerun()
            else:
                st.session_state["auth_error"] = (
                    "注册成功，但需邮箱验证。请查收确认邮件后登录，"
                    "或到 Supabase 控制台关闭 Confirm email。"
                )
                st.rerun()
        else:  # 登录
            res = sb.auth.sign_in_with_password(
                {"email": email, "password": password}
            )
            st.session_state["auth_user"] = {
                "id": res.user.id,
                "email": res.user.email,
            }
            st.session_state.pop("auth_error", None)
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
        elif "weak password" in msg or "password" in msg and "6" in msg:
            st.session_state["auth_error"] = "密码强度不足：至少 6 位。"
        else:
            st.session_state["auth_error"] = f"登录/注册失败：{e}"
        st.rerun()
