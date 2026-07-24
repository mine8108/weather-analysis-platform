"""登录鉴权模块：基于 Supabase Auth 的邮箱密码登录/注册。

设计要点：
- 使用 Supabase 匿名密钥 (anon key) + 行级安全 (RLS) 即可安全做客户端登录，
  无需自建后端。匿名密钥可安全暴露在前端。
- 所有用户数据按 user_id 隔离，由数据库 RLS 强制保证（见 supabase/schema.sql）。
- 密钥从 Streamlit Secrets 读取：SUPABASE_URL / SUPABASE_ANON_KEY。
- 登录页背景为 Three.js + 自定义 GLSL 实现的实时粒子雨景，降雨强度由
  用户当地实时降水数据驱动（ipapi.co 定位 + Open-Meteo 降水）。
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
# 三、沉浸式雨景登录页（Three.js + GLSL）
# ============================================================
# 该 HTML 通过 streamlit-component-lib 与 Python 通信：
#   - JS 用 window.Streamlit.setComponentValue({mode, email, password, ts})
#     把凭证回传 Python；
#   - Python 把 auth_error 以 __ERROR_JSON__ 占位符注入，JS 读取并显示。
RAIN_LOGIN_HTML = r"""
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet" />
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body {
    height: 100%; background: #070b14; color: #e8eef7; overflow: hidden;
    font-family: 'Space Grotesk', system-ui, -apple-system, sans-serif;
  }
  #rain-canvas { position: fixed; inset: 0; width: 100%; height: 100%; z-index: 0; display: block; }

  .auth-wrap {
    position: relative; z-index: 10;
    width: min(440px, 90vw); margin: 9vh auto 0; padding: 40px 38px 34px;
    background: rgba(11, 17, 30, 0.78);
    border: 1px solid rgba(79, 156, 255, 0.22);
    border-radius: 20px;
    box-shadow: 0 30px 70px -24px rgba(0,0,0,0.8);
    backdrop-filter: blur(10px);
  }
  .brand { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
  .brand .dot { width: 10px; height: 10px; border-radius: 50%; background: #4f9cff; box-shadow: 0 0 14px #4f9cff; }
  .brand h1 { font-size: 1.4rem; font-weight: 600; letter-spacing: -0.02em; }
  .sub { color: #8da2c0; font-size: 0.9rem; margin-bottom: 26px; }

  .mode-tabs { display: flex; gap: 6px; margin-bottom: 24px; padding: 4px;
    background: rgba(255,255,255,0.04); border-radius: 13px; }
  .mode-tabs button { flex: 1; padding: 11px; border: none; background: transparent;
    color: #8da2c0; font-family: inherit; font-size: 0.95rem; font-weight: 500;
    border-radius: 9px; cursor: pointer; transition: all 0.22s; }
  .mode-tabs button.active { background: #4f9cff; color: #04101f; font-weight: 600; }

  .field { margin-bottom: 18px; }
  .field label { display: block; font-size: 0.82rem; font-weight: 500;
    color: #b8c6dd; margin-bottom: 8px; letter-spacing: 0.02em; }
  .field input { width: 100%; padding: 15px 16px; font-family: inherit; font-size: 1rem;
    color: #e8eef7; background: rgba(255,255,255,0.05);
    border: 2px solid rgba(255,255,255,0.1); border-radius: 12px; outline: none;
    transition: border-color 0.2s, background 0.2s; }
  .field input:focus { border-color: #4f9cff; background: rgba(79,156,255,0.07); }
  .field input::placeholder { color: #5a6b85; }

  .hint { font-size: 0.8rem; color: #7e90ad; margin: 2px 0 20px; line-height: 1.55;
    padding: 11px 14px; background: rgba(79,156,255,0.09);
    border-left: 3px solid #4f9cff; border-radius: 0 9px 9px 0; }
  .error { color: #ff8a8a; font-size: 0.85rem; margin-bottom: 14px; min-height: 1.1em; font-weight: 500; }

  .submit-btn { width: 100%; padding: 16px; font-family: inherit; font-size: 1.04rem;
    font-weight: 600; color: #04101f; background: #4f9cff; border: none; border-radius: 12px;
    cursor: pointer; transition: background 0.2s, transform 0.1s; }
  .submit-btn:hover { background: #6aacff; }
  .submit-btn:active { transform: scale(0.985); }

  .loc { position: fixed; bottom: 18px; left: 0; right: 0; text-align: center; z-index: 10;
    font-size: 0.74rem; color: rgba(141,162,192,0.55); letter-spacing: 0.02em; }
</style>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/streamlit-component-lib@1.0.0/streamlit.js"></script>
</head>
<body>
<canvas id="rain-canvas"></canvas>

<div class="auth-wrap">
  <div class="brand"><span class="dot"></span><h1>气象数据交互分析平台</h1></div>
  <p class="sub">登录或注册后使用 · 数据按账号私有隔离</p>

  <div class="mode-tabs">
    <button id="tab-login" class="active" data-mode="login">登录</button>
    <button id="tab-signup" data-mode="signup">注册</button>
  </div>

  <div class="field">
    <label for="email">邮箱</label>
    <input id="email" type="email" placeholder="you@example.com" autocomplete="email" />
  </div>
  <div class="field">
    <label for="password">密码</label>
    <input id="password" type="password" placeholder="至少 6 位" autocomplete="current-password" />
  </div>

  <p class="hint" id="hint">首次使用请选「注册」。若开启邮箱验证，请先查收确认邮件再登录。</p>
  <div class="error" id="error"></div>
  <button class="submit-btn" id="submit">进入</button>
</div>

<div class="loc" id="loc">正在获取当地降雨数据…</div>

<script>
(function () {
  // ---------- 表单交互 ----------
  let currentMode = 'login';
  const tabs = document.querySelectorAll('.mode-tabs button');
  const hintEl = document.getElementById('hint');
  const errEl = document.getElementById('error');

  tabs.forEach(function (b) {
    b.addEventListener('click', function () {
      tabs.forEach(function (x) { x.classList.remove('active'); });
      b.classList.add('active');
      currentMode = b.dataset.mode;
      hintEl.textContent = currentMode === 'login'
        ? '输入注册时的邮箱与密码登录。'
        : '设置邮箱与密码（至少 6 位）创建新账号。';
    });
  });

  // 注入 Python 传来的错误信息
  const ERROR_MSG = __ERROR_JSON__;
  if (ERROR_MSG) errEl.textContent = ERROR_MSG;

  document.getElementById('submit').addEventListener('click', function () {
    const email = document.getElementById('email').value.trim();
    const password = document.getElementById('password').value;
    if (!email || !password) { errEl.textContent = '请输入邮箱和密码。'; return; }
    if (password.length < 6) { errEl.textContent = '密码至少 6 位。'; return; }
    errEl.textContent = '';
    if (window.Streamlit && window.Streamlit.setComponentValue) {
      window.Streamlit.setComponentValue({ mode: currentMode, email: email, password: password, ts: Date.now() });
    }
  });

  // ---------- Three.js 雨景 ----------
  const canvas = document.getElementById('rain-canvas');
  const renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, alpha: true });
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x070b14, 0.022);
  const camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.1, 120);
  camera.position.set(0, 2.5, 16);
  camera.lookAt(0, 0, -6);

  let targetIntensity = 0.5;
  let currentIntensity = 0.5;

  // --- 粒子雨 ---
  const COUNT = 6000;
  const geo = new THREE.BufferGeometry();
  const pos = new Float32Array(COUNT * 3);
  const aSpeed = new Float32Array(COUNT);
  const aOffset = new Float32Array(COUNT);
  for (let i = 0; i < COUNT; i++) {
    pos[i * 3] = (Math.random() - 0.5) * 46;
    pos[i * 3 + 1] = Math.random() * 24;
    pos[i * 3 + 2] = (Math.random() - 0.5) * 34 - 12;
    aSpeed[i] = 0.5 + Math.random() * 1.8;
    aOffset[i] = Math.random();
  }
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('aSpeed', new THREE.BufferAttribute(aSpeed, 1));
  geo.setAttribute('aOffset', new THREE.BufferAttribute(aOffset, 1));

  const rainMat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    uniforms: { uTime: { value: 0 }, uIntensity: { value: 0.5 } },
    vertexShader: [
      'uniform float uTime;',
      'uniform float uIntensity;',
      'attribute float aSpeed;',
      'attribute float aOffset;',
      'varying float vAlpha;',
      'void main() {',
      '  vec3 p = position;',
      '  float fall = mod(uTime * (1.6 + aSpeed * 2.2) + aOffset, 1.0);',
      '  p.y = 14.0 - fall * 28.0;',
      '  vec4 mv = modelViewMatrix * vec4(p, 1.0);',
      '  gl_PointSize = (1.4 + uIntensity * 4.0) * (340.0 / -mv.z);',
      '  gl_Position = projectionMatrix * mv;',
      '  vAlpha = 0.22 + uIntensity * 0.55;',
      '}'
    ].join('\n'),
    fragmentShader: [
      'varying float vAlpha;',
      'void main() {',
      '  vec2 c = gl_PointCoord - vec2(0.5);',
      '  float d = length(c * vec2(1.0, 3.6));',
      '  if (d > 0.5) discard;',
      '  float a = smoothstep(0.5, 0.0, d) * vAlpha;',
      '  gl_FragColor = vec4(0.72, 0.82, 1.0, a);',
      '}'
    ].join('\n')
  });
  const rain = new THREE.Points(geo, rainMat);
  scene.add(rain);

  // --- 水面波纹 ---
  const waterGeo = new THREE.PlaneGeometry(90, 70, 1, 1);
  const waterMat = new THREE.ShaderMaterial({
    uniforms: { uTime: { value: 0 }, uIntensity: { value: 0.5 } },
    vertexShader: [
      'varying vec2 vUv;',
      'void main() {',
      '  vUv = uv;',
      '  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);',
      '}'
    ].join('\n'),
    fragmentShader: [
      'uniform float uTime;',
      'uniform float uIntensity;',
      'varying vec2 vUv;',
      'void main() {',
      '  vec2 uv = vUv * 9.0;',
      '  float w = sin(uv.x * 3.0 + uTime * 2.0) * 0.5 + sin(uv.y * 2.5 - uTime * 1.7) * 0.5;',
      '  w += sin((uv.x + uv.y) * 4.0 + uTime * 3.0) * 0.25;',
      '  w *= (0.28 + uIntensity * 0.72);',
      '  float shade = 0.04 + w * 0.06 + uIntensity * 0.05;',
      '  vec3 col = vec3(0.04, 0.09, 0.18) + shade * vec3(0.4, 0.6, 1.0);',
      '  gl_FragColor = vec4(col, 1.0);',
      '}'
    ].join('\n')
  });
  const water = new THREE.Mesh(waterGeo, waterMat);
  water.rotation.x = -Math.PI / 2;
  water.position.y = -6.5;
  scene.add(water);

  function onResize() {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
  }
  window.addEventListener('resize', onResize);

  function animate(t) {
    const time = t * 0.001;
    currentIntensity += (targetIntensity - currentIntensity) * 0.02;
    rainMat.uniforms.uTime.value = time;
    rainMat.uniforms.uIntensity.value = currentIntensity;
    waterMat.uniforms.uTime.value = time;
    waterMat.uniforms.uIntensity.value = currentIntensity;
    camera.position.x = Math.sin(time * 0.15) * 0.7;
    camera.lookAt(0, 0, -6);
    renderer.render(scene, camera);
    requestAnimationFrame(animate);
  }
  requestAnimationFrame(animate);

  // ---------- 实时降雨数据 → 强度 ----------
  async function getIntensity() {
    const locEl = document.getElementById('loc');
    try {
      const ip = await fetch('https://ipapi.co/json/').then(function (r) { return r.json(); });
      const lat = ip.latitude, lon = ip.longitude;
      const meteo = await fetch('https://api.open-meteo.com/v1/forecast?latitude=' +
        lat + '&longitude=' + lon + '&current=precipitation').then(function (r) { return r.json(); });
      const precip = (meteo.current && meteo.current.precipitation) || 0;
      targetIntensity = Math.max(0.08, Math.min(precip / 8.0, 1.0));
      locEl.textContent = '当地实时降雨：' + precip.toFixed(1) + ' mm/h · 雨景已同步';
    } catch (e) {
      targetIntensity = 0.5;
      locEl.textContent = '无法获取当地降雨，已使用默认雨景';
    }
  }
  getIntensity();
})();
</script>
</body>
</html>
"""


def render_auth_page():
    """渲染沉浸式雨景登录/注册页。

    通过 st.components.v1.html 嵌入 Three.js 雨景背景 + 明显表单。
    调用方在判断未登录后应紧接着 st.stop()。
    """
    # 登录态强制深色背景，避免雨景 iframe 周围出现白底
    st.markdown(
        "<style>"
        "html,body,[data-testid='stAppViewContainer'],"
        "[data-testid='stHeader']{background:#070b14 !important;}"
        "[data-testid='stAppViewBlockContainer']{padding-top:0;}"
        "</style>",
        unsafe_allow_html=True,
    )

    error = st.session_state.get("auth_error", "")
    html = RAIN_LOGIN_HTML.replace("__ERROR_JSON__", json.dumps(error))
    res = components.html(html, height=820, scrolling=False, key="auth_rain")

    # 只处理一次提交（用 ts 去重，避免 rerun 后重复触发）
    if res and isinstance(res, dict):
        ts = res.get("ts", 0)
        if ts and ts != st.session_state.get("_last_auth_ts", 0):
            st.session_state["_last_auth_ts"] = ts
            st.session_state.pop("auth_error", None)
            _do_auth(res.get("mode"), res.get("email"), res.get("password"))


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
        msg = str(e)
        if "Invalid login" in msg or "invalid" in msg.lower():
            st.session_state["auth_error"] = "登录失败：邮箱或密码错误。"
        elif "User already registered" in msg:
            st.session_state["auth_error"] = "该邮箱已注册，请直接登录。"
        else:
            st.session_state["auth_error"] = f"操作失败：{msg[:200]}"
        st.rerun()
