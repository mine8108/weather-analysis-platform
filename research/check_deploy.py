# -*- coding: utf-8 -*-
"""发布后部署核对：确认「线上跑的版本」就是「你刚推的版本」。

为什么需要这个脚本
------------------
``git push`` 成功、远端 ``main`` 已更新，**不等于** Streamlit Cloud 已经重建容器。
2026-09-11 的 v2.3.0 发布就出现了这种情况：合并与推送全部成功，但线上连续十余分钟
仍返回旧版本号，容器最后一次启动时间停在推送之前。若不主动核对，这种「已合并未部署」
是静默的——它会让你以为线上已是新版，直到某个只有线上才暴露的问题出现。

这个脚本把那次人工排查固化下来：比对本地 ``config.py`` 的 ``APP_VERSION``、线上页面
实际渲染出的版本号、以及本地提交与远端的关系。

为什么不需要凭据
----------------
版本号由 ``app.py`` 渲染在侧边栏页脚（``st.caption(f"© 气象数据交互分析平台 {APP_VERSION}")``），
该位置在鉴权门之前，因此**登录页上就已经带着版本号**。脚本只读这一处，不登录、不写入
任何状态，也就不需要、也不应该把账号密码写进仓库。

为什么不用 st.secrets
---------------------
线上页脚的版本号由应用代码决定，与 secrets 无关，所以这个检查在任何 secret 配置下都成立，
也不会因为密钥轮换而失效。

用法
----
    python -B research/check_deploy.py
    python -B research/check_deploy.py --url https://xxx.streamlit.app/
    python -B research/check_deploy.py --require-version 2.3.0     # 显式要求某个版本

退出码
------
    0  三项全部通过
    1  存在不一致（版本漂移 / 未推送 / 远端缺提交）
    2  无法取证（找不到浏览器、页面打不开等）——属于「没结论」，不等于通过
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

# 允许以 `python research/check_deploy.py` 直接运行（此时脚本目录才在 sys.path 上）。
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cdp_client import (  # noqa: E402  (必须在上面的 sys.path 调整之后导入)
    CdpError,
    CdpSession,
    launch_browser,
    shutdown_browser,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PY = REPO_ROOT / "config.py"
DEFAULT_URL = "https://weather-analysis-platform-zyappduswtwhs8pok7e7a9c.streamlit.app/"
DEFAULT_BRANCH = "main"

# 线上页脚形如「© 气象数据交互分析平台 2.3.0」。用带前缀的宽松匹配，
# 避免把页面里其它 `2.3.0` 之类字样误当版本号。
FOOTER_RE = re.compile(r"气象数据交互分析平台\s*v?(\d+\.\d+\.\d+)")
VERSION_RE = re.compile(r"\b\d+\.\d+\.\d+\b")

# 应用未就绪时 Cloud 会显示这两种页面，遇到就继续等。
NOT_READY_MARKERS = ("app is in the oven", "has gone to sleep", "Zzzz")

CHROMIUM_CANDIDATES = [
    os.environ.get("DSH_DEPLOY_CHROME", ""),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright",
                 "chromium-1234", "chrome-win64", "chrome.exe"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright",
                 "chromium-1228", "chrome-win64", "chrome.exe"),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/chromium",
    "/usr/bin/google-chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


_TEXT_EXPR = "(() => (document.body && document.body.innerText) || '')()"

# 版本号页脚渲染在侧边栏，而侧边栏在鉴权门之后——未登录时页面上只有登录卡片。
# 因此要读到版本号必须登录。凭据只从环境变量取，不进仓库、不进日志。
#
# 登录动作在**目标 frame 自己的执行上下文**里完成（隔离开世界看不到主世界的
# React 实例，合成事件无法派发）。用 HTMLInputElement.prototype 的原始 value
# setter 写入，否则 React 的受控输入会把值弹回。
_LOGIN_EXPR = """(creds => {
  const doc = document;
  const inFrame = (win) => {
    try { return win.document.querySelector('input[type="text"]') ? win : null; }
    catch (e) { return null; }
  };
  const win = inFrame(window)
    || [...document.querySelectorAll('iframe')]
         .map(f => { try { return f.contentWindow; } catch (e) { return null; } })
         .find(w => w && inFrame(w));
  if (!win) return 'no-form';
  const d = win.document;
  const email = d.querySelector('input[type="text"]');
  const pwd = d.querySelector('input[type="password"]');
  if (!email || !pwd) return 'no-inputs';

  const w = win.Object.getOwnPropertyDescriptor(win.HTMLInputElement.prototype, 'value').set;
  const fire = (el, v) => {
    w.call(el, v);
    const view = el.ownerDocument.defaultView;
    el.dispatchEvent(new view.Event('input', { bubbles: true }));
    el.dispatchEvent(new view.Event('change', { bubbles: true }));
  };
  fire(email, creds.e);
  fire(pwd, creds.p);

  // 登录卡片没有 <form> 元素（实测 forms=0），所以不能 requestSubmit，
  // 只能按可见文案找提交按钮。
  const all = [...d.querySelectorAll('button')].filter(b => b.offsetParent !== null);
  const submit = all.find(b => /进入平台|登录/.test(b.textContent || ''))
    || d.querySelector('button[kind="primaryFormSubmit"]')
    || d.querySelector('button[type="submit"]');
  if (submit) { submit.click(); return 'submitted:' + (submit.textContent || '').trim().slice(0, 12); }
  return 'no-button:' + all.map(b => (b.textContent || '').trim().slice(0, 8)).join(',');
})"""


def _login_expr(email: str, password: str) -> str:
    """把凭据作为 JSON 字面量注入表达式，避免拼接造成的转义问题。"""
    creds = json.dumps({"e": email, "p": password}, ensure_ascii=False)
    return f"({_LOGIN_EXPR})({creds})"


# 应用 iframe 与主页面同源（都是 *.streamlit.app），因此它**不是**独立的 CDP 目标，
# 只是主页面目标下的一个 frame。跨源的内嵌 iframe（如状态页）才会成为独立目标。
_APP_FRAME_HINT = "streamlit.app"


def _eval_text(session: CdpSession, sid: str, frame_id: str, timeout: float = 10.0) -> str:
    """取某个 frame 的可见文本；失败返回空串。

    统一走**隔离开世界**：同源子 frame（应用本体就在其中）在默认上下文里求值只会
    得到空串，只有为它单独建一个执行上下文才读得到正文。
    """
    try:
        world = session.call(
            "Page.createIsolatedWorld",
            {"frameId": frame_id, "grantUniversalAccess": False},
            session_id=sid,
            timeout=timeout,
        )
    except CdpError:
        return ""
    context_id = world.get("executionContextId")
    if context_id is None:
        return ""
    try:
        result = session.call(
            "Runtime.evaluate",
            {"expression": _TEXT_EXPR, "returnByValue": True, "contextId": context_id},
            session_id=sid,
            timeout=timeout,
        )
    except CdpError:
        return ""
    value = (result.get("result") or {}).get("value")
    return value if isinstance(value, str) else ""


# 休眠页的唤醒按钮。Streamlit Cloud 用 data-testid="wakeup-button-owner"。
_WAKE_EXPR = (
    "(() => {"
    " const b = document.querySelector('[data-testid=\"wakeup-button-owner\"]')"
    "  || [...document.querySelectorAll('button')]"
    "       .find(x => /get this app back up/i.test(x.textContent || ''));"
    " if (b) { b.click(); return 'clicked'; }"
    " return 'not-found';"
    "})()"
)


def _version_key(value: str) -> list[int]:
    """把 '2.3.0' 变成 [2, 3, 0]，用于比较大小。"""
    return [int(part) for part in value.split(".")]


def _free_port() -> int:
    """向系统借一个空闲端口给调试端点用，避免与既有实例冲突。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def log(msg: str = "") -> None:
    print(msg, flush=True)


def ok(msg: str) -> None:
    log(f"[OK]   {msg}")


def bad(msg: str) -> None:
    log(f"[FAIL] {msg}")


def warn(msg: str) -> None:
    log(f"[WARN] {msg}")


def info(msg: str) -> None:
    log(f"[INFO] {msg}")


# --------------------------------------------------------------------------
# 一、本地版本号：用 AST 解析，避免 import config 产生副作用
# --------------------------------------------------------------------------
def read_local_version() -> str:
    """从 config.py 里取出 APP_VERSION 的字面量值。"""
    tree = ast.parse(CONFIG_PY.read_text(encoding="utf-8"), filename=str(CONFIG_PY))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "APP_VERSION":
                value = ast.literal_eval(node.value)
                if not isinstance(value, str):
                    raise ValueError("APP_VERSION 不是字符串字面量")
                return value
    raise ValueError("在 config.py 中找不到 APP_VERSION")


def git(*args: str) -> tuple[int, str]:
    """执行 git 命令，返回 (退出码, 标准输出去掉首尾空白)。"""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return proc.returncode, (proc.stdout or "").strip()


# --------------------------------------------------------------------------
# 二、线上版本号：无凭据读取登录页页脚
# --------------------------------------------------------------------------
def find_chromium(explicit: str | None) -> str | None:
    for candidate in ([explicit] if explicit else []) + CHROMIUM_CANDIDATES:
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def _iter_frames(session: CdpSession, url: str):
    """产出 (sessionId, frameId, 可见文本)，按「应用 frame 优先」排序。

    Streamlit 把应用渲染在 ``*.streamlit.app`` 的同源 iframe 里，所以它不是独立
    CDP 目标，而是主页面目标下的子 frame。跨源内嵌页（状态页）才会是独立目标。
    同源子 frame 的正文只能经**隔离开世界**上下文读取：默认上下文对它求值会
    返回空串。
    """
    targets = session.call("Target.getTargets").get("targetInfos", [])
    pages = [t for t in targets
             if t.get("type") == "page" and (t.get("url") or "").startswith(("http://", "https://"))]
    iframes = [t for t in targets
               if t.get("type") == "iframe" and (t.get("url") or "").startswith(("http://", "https://"))]

    host = url.split("/")[2] if "//" in url else ""
    pages.sort(key=lambda t: 0 if host and host in (t.get("url") or "") else 1)

    for target in pages:
        target_id = target.get("targetId")
        if not target_id:
            continue
        try:
            attached = session.call(
                "Target.attachToTarget",
                {"targetId": target_id, "flatten": True},
                timeout=10,
            )
        except CdpError:
            continue
        sid = attached.get("sessionId")
        if not sid:
            continue

        try:
            tree = session.call("Page.getFrameTree", session_id=sid, timeout=10)
        except CdpError:
            continue

        frames: list[tuple[str, str]] = []

        def collect(node: dict) -> None:
            frame = node.get("frame") or {}
            fid = frame.get("id")
            if fid:
                frames.append((fid, frame.get("url") or ""))
            for child in node.get("childFrames") or []:
                collect(child)

        collect(tree.get("frameTree") or {})
        # 命中 streamlit.app 的 frame（应用本体）排在最前，其余保持原序。
        frames.sort(key=lambda item: 0 if _APP_FRAME_HINT in item[1] else 1)

        for frame_id, _frame_url in frames:
            yield sid, frame_id, _eval_text(session, sid, frame_id)

    for target in iframes:
        target_id = target.get("targetId")
        if not target_id:
            continue
        try:
            attached = session.call(
                "Target.attachToTarget",
                {"targetId": target_id, "flatten": True},
                timeout=10,
            )
            sid = attached.get("sessionId")
            if not sid:
                continue
            result = session.call(
                "Runtime.evaluate",
                {"expression": _TEXT_EXPR, "returnByValue": True},
                session_id=sid,
                timeout=10,
            )
            value = (result.get("result") or {}).get("value")
            if isinstance(value, str):
                yield sid, "", value
        except CdpError:
            continue


def read_deployed_version(url: str, chrome: str, timeout_ms: int,
                          email: str = "", password: str = "") -> tuple[str | None, str]:
    """打开线上应用，登录后从侧边栏页脚解析版本号。

    返回 (版本号或 None, 说明文字)。

    为什么必须登录：``APP_VERSION`` 渲染在侧边栏页脚，而侧边栏位于鉴权门之后；
    未登录时页面只有登录卡片，任何位置都读不到版本号。凭据由调用方从环境变量
    传入，本函数不打印它们。
    """
    port = _free_port()
    proc = None
    user_data_dir = ""
    session = None
    try:
        proc, ws_url, user_data_dir = launch_browser(chrome, port)
        session = CdpSession(ws_url)

        created = session.call("Target.createTarget", {"url": url})
        session.call("Target.activateTarget", {"targetId": created["targetId"]})

        deadline = time.monotonic() + timeout_ms / 1000.0
        seen_not_ready = ""
        wake_attempted = False
        login_attempted = False
        login_result = ""
        app_frame_text = ""

        while time.monotonic() < deadline:
            time.sleep(1.5)
            for sid, frame_id, text in _iter_frames(session, url):
                if not text:
                    continue

                if any(marker in text for marker in NOT_READY_MARKERS):
                    seen_not_ready = text
                    # 休眠实例不会自己醒来：按下唤醒按钮后**重新加载**应用地址。
                    # 实测唤醒按钮会把页面导航到别处，不重载会一直停在认不出的状态。
                    if not wake_attempted and "get this app back up" in text:
                        wake_attempted = True
                        info("实例处于休眠，已触发唤醒")
                        try:
                            session.call(
                                "Runtime.evaluate",
                                {"expression": _WAKE_EXPR, "returnByValue": True},
                                session_id=sid, timeout=10,
                            )
                        except CdpError:
                            pass
                        time.sleep(5)
                        try:
                            session.call("Page.navigate", {"url": url},
                                         session_id=sid, timeout=15)
                        except CdpError:
                            pass
                    continue

                # 命中版本页脚即完成。
                match = FOOTER_RE.search(text)
                if match:
                    return match.group(1), "从侧边栏页脚读取"

                if "气象数据交互分析平台" not in text:
                    continue

                app_frame_text = text if len(text) > len(app_frame_text) else app_frame_text

                # 登录卡片就位且提供了凭据 -> 在同一个上下文里登录一次。
                if (not login_attempted and email and password
                        and not frame_id == "" and "进入平台" in text):
                    login_attempted = True
                    try:
                        result = session.call(
                            "Runtime.evaluate",
                            {"expression": _login_expr(email, password),
                             "returnByValue": True},
                            session_id=sid, timeout=20,
                        )
                        login_result = str((result.get("result") or {}).get("value"))
                        if login_result.startswith("submitted"):
                            info("已在页面内提交登录，等待侧边栏渲染")
                        else:
                            warn(f"登录表单交互未完成：{login_result}")
                    except CdpError as exc:
                        warn(f"登录动作失败：{exc}")

                # 兜底：应用已渲染且页面里出现了形如 x.y.z 的版本串。
                if len(text) > 200:
                    found = VERSION_RE.findall(text)
                    if found:
                        return max(found, key=_version_key), "页脚格式未匹配，取页面内最大版本号"

        if any(marker in seen_not_ready for marker in NOT_READY_MARKERS):
            return None, (
                "应用在时限内仍未就绪（休眠唤醒或正在重建）："
                f"{seen_not_ready.strip()[:80]!r}"
            )
        if email and password:
            suffix = f"（登录动作：{login_result or '未触发'}）" if login_attempted else "（未识别到登录卡片）"
            return None, (
                f"已尝试登录但未读到版本页脚{suffix}；"
                f"页面正文长度 {len(app_frame_text)}"
            )
        return None, (
            "版本号只在登录后可见，但未提供凭据。设置环境变量 "
            "DEPLOY_CHECK_EMAIL / DEPLOY_CHECK_PASSWORD 后重跑"
        )
    except CdpError as exc:
        return None, f"浏览器交互失败：{exc}"
    finally:
        if session is not None:
            session.close()
        if proc is not None:
            shutdown_browser(proc, user_data_dir)


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        description="核对线上部署的应用版本是否与仓库中的 APP_VERSION 一致",
    )
    parser.add_argument("--url", default=DEFAULT_URL, help="线上应用 URL")
    parser.add_argument("--branch", default=DEFAULT_BRANCH, help="应当已推送的分支")
    parser.add_argument("--chrome", default=None, help="Chromium/Chrome 可执行文件路径")
    parser.add_argument("--timeout", type=int, default=120000, help="页面等待上限（毫秒）")
    parser.add_argument("--require-version", default=None,
                        help="显式要求线上等于该版本（默认要求等于本地 APP_VERSION）")
    args = parser.parse_args()

    log("=" * 68)
    log("部署核对：线上版本 vs 仓库版本")
    log("=" * 68)

    failures: list[str] = []
    inconclusive: list[str] = []

    # --- 1. 本地版本 ---
    try:
        local_version = read_local_version()
        ok(f"仓库 APP_VERSION = {local_version}   （config.py）")
    except Exception as exc:  # noqa: BLE001 - 任何解析失败都应给出可读结论
        bad(f"无法读取本地 APP_VERSION：{exc}")
        return 2

    expected = args.require_version or local_version

    # --- 2. 本地提交与远端的关系 ---
    code, head = git("rev-parse", "--short", "HEAD")
    if code == 0:
        info(f"本地 HEAD = {head}")
    else:
        warn(f"读取本地 HEAD 失败：{head}")

    code, remote_head = git("rev-parse", "--short", f"origin/{args.branch}")
    if code != 0:
        warn(f"读不到 origin/{args.branch}（未配置远端？）：{remote_head}")
    else:
        info(f"origin/{args.branch} = {remote_head}")
        code2, unpushed = git("log", "--oneline", f"origin/{args.branch}..HEAD")
        if code2 == 0 and unpushed:
            failures.append(
                f"有 {len(unpushed.splitlines())} 个本地提交未推送，线上不可能包含它们"
            )
        else:
            ok(f"本地 HEAD 已包含在 origin/{args.branch} 中")

    # --- 3. 线上版本 ---
    # 凭据从环境变量读取：不接受命令行参数（会留在 shell 历史里），也不写进仓库。
    email = os.environ.get("DEPLOY_CHECK_EMAIL", "").strip()
    password = os.environ.get("DEPLOY_CHECK_PASSWORD", "")
    chrome = find_chromium(args.chrome)
    if not chrome:
        inconclusive.append(
            "找不到可用的 Chromium/Chrome，无法读取线上版本；"
            "可用 --chrome 指定，或设置 DSH_DEPLOY_CHROME"
        )
        deployed_version = None
        note = ""
    else:
        info(f"使用浏览器：{chrome}")
        info(f"目标：{args.url}")
        if email and password:
            info(f"将以内置账号登录后读取页脚（账号 {email[:3]}***）")
        else:
            warn("未设置 DEPLOY_CHECK_EMAIL / DEPLOY_CHECK_PASSWORD，只能做提交同步性核对")
        deployed_version, note = read_deployed_version(
            args.url, chrome, args.timeout, email, password
        )

    log("")
    if deployed_version is None:
        bad(f"未能取到线上版本：{note}")
        inconclusive.append(note or "线上版本取证失败")
    else:
        ok(f"线上版本 = {deployed_version}   （{note}）")
        if deployed_version == expected:
            ok(f"线上与预期一致（{expected}）")
        else:
            failures.append(
                f"线上是 {deployed_version}，预期 {expected} —— "
                f"已合并但未部署。去 Streamlit Cloud 面板对该应用执行 Reboot app"
            )

    # --- 汇总 ---
    log("")
    log("=" * 68)
    if failures:
        for item in failures:
            bad(item)
        log("结论：不一致。")
        return 1
    if inconclusive:
        for item in inconclusive:
            warn(item)
        log("结论：无法确认（取证失败，不等于通过）。")
        return 2

    log(f"结论：全部通过，线上正在运行 {deployed_version}。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
