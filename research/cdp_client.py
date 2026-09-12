# -*- coding: utf-8 -*-
"""极简 Chrome DevTools Protocol 客户端（仅标准库）。

存在理由
--------
``research/check_deploy.py`` 需要在无凭据的前提下读取线上页面渲染出的版本号。可选路径
各有代价：Python 侧 playwright 要额外安装（约 30 MB 且要下载浏览器）、Node 侧
playwright-core 依赖 npm install、``websockets`` 是第三方包。这个模块用事件循环里已有的
``socket`` + ``hashlib`` + ``base64`` 自行完成 WebSocket 握手与成帧，因此整个检查脚本
零第三方依赖，跨平台可用（只需本机存在 Chrome / Edge / Chromium）。

范围
----
只实现本项目需要的三件事：建目标、挂载会话、求值一段 JS。不做重连、不做压缩扩展、
不做分片发送。收到的分片消息会被拼装，但发送端永不使用分片。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import socket
import struct
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class CdpError(RuntimeError):
    """CDP 交互失败（协议错误、目标不存在、超时等）。"""


class WebSocket:
    """够用的 WebSocket 客户端：握手、收文本帧、发文本帧。"""

    def __init__(self, url: str, timeout: float = 30.0) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "ws":
            raise CdpError(f"仅支持 ws:// ，收到 {parsed.scheme}://")
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query

        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._sock.settimeout(timeout)
        self._buf = bytearray()

        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "Origin: http://127.0.0.1\r\n"
            "\r\n"
        )
        self._sock.sendall(request.encode("ascii"))

        header = self._read_until(b"\r\n\r\n")
        head_text = header.decode("latin-1", "replace")
        status_line = head_text.split("\r\n", 1)[0]
        if "101" not in status_line:
            raise CdpError(f"WebSocket 握手失败：{status_line}")

        expected = base64.b64encode(
            hashlib.sha1((key + _GUID).encode("ascii")).digest()
        ).decode("ascii")
        if expected.lower() not in head_text.lower():
            raise CdpError("WebSocket 握手响应缺少正确的 Sec-WebSocket-Accept")

    # -- 底层读写 ---------------------------------------------------------
    def _read_until(self, needle: bytes) -> bytes:
        while needle not in self._buf:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise CdpError("连接在握手阶段被关闭")
            self._buf.extend(chunk)
        idx = self._buf.index(needle) + len(needle)
        out = bytes(self._buf[:idx])
        del self._buf[:idx]
        return out

    def _read_exact(self, count: int) -> bytes:
        while len(self._buf) < count:
            chunk = self._sock.recv(max(65536, count - len(self._buf)))
            if not chunk:
                raise CdpError("连接已关闭")
            self._buf.extend(chunk)
        out = bytes(self._buf[:count])
        del self._buf[:count]
        return out

    def send_text(self, text: str) -> None:
        payload = text.encode("utf-8")
        header = bytearray([0x81])  # FIN + text
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < (1 << 16):
            header.append(0x80 | 126)
            header.extend(struct.pack(">H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack(">Q", length))
        mask = secrets.token_bytes(4)
        header.extend(mask)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self._sock.sendall(bytes(header) + masked)

    def recv_text(self) -> str:
        """读一条完整文本消息；分片会被拼装，ping 会被自动回应。"""
        chunks: list[bytes] = []
        while True:
            b0, b1 = self._read_exact(2)
            fin = bool(b0 & 0x80)
            opcode = b0 & 0x0F
            masked = bool(b1 & 0x80)
            length = b1 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read_exact(8))[0]

            mask = self._read_exact(4) if masked else b""
            data = self._read_exact(length)
            if masked:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))

            if opcode == 0x9:  # ping -> pong
                self._sock.sendall(bytes([0x8A, 0x80]) + secrets.token_bytes(4))
                continue
            if opcode == 0xA:  # pong
                continue
            if opcode == 0x8:  # close
                raise CdpError("服务端关闭了 WebSocket")
            chunks.append(data)
            if fin:
                return b"".join(chunks).decode("utf-8", "replace")

    def close(self) -> None:
        try:
            self._sock.sendall(bytes([0x88, 0x80]) + secrets.token_bytes(4))
        except OSError:
            pass
        try:
            self._sock.close()
        except OSError:
            pass


class CdpSession:
    """一次 CDP 会话：连到 browser 端点，可对任意 target 求值。"""

    def __init__(self, ws_url: str, timeout: float = 30.0) -> None:
        self._ws = WebSocket(ws_url, timeout=timeout)
        self._next_id = 1
        self._pending: dict[int, dict] = {}

    def call(self, method: str, params: dict | None = None,
             session_id: str | None = None, timeout: float = 30.0) -> dict:
        msg_id = self._next_id
        self._next_id += 1
        payload: dict = {"id": msg_id, "method": method}
        if params:
            payload["params"] = params
        if session_id:
            payload["sessionId"] = session_id
        self._ws.send_text(json.dumps(payload))

        deadline = time.monotonic() + timeout
        while True:
            if msg_id in self._pending:
                reply = self._pending.pop(msg_id)
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CdpError(f"{method} 超时（{timeout:.0f}s）")
            self._ws._sock.settimeout(min(remaining, 5.0))
            try:
                raw = self._ws.recv_text()
            except socket.timeout:
                continue
            except OSError as exc:
                raise CdpError(f"{method} 读取失败：{exc}") from exc
            message = json.loads(raw)
            rid = message.get("id")
            if rid is not None:
                self._pending[rid] = message

        if "error" in reply:
            raise CdpError(f"{method} 被拒绝：{reply['error'].get('message')}")
        return reply.get("result", {})

    def close(self) -> None:
        self._ws.close()


# --------------------------------------------------------------------------
# 浏览器进程管理
# --------------------------------------------------------------------------
def launch_browser(executable: str, port: int, extra_args: list[str] | None = None,
                   startup_timeout: float = 30.0) -> tuple[subprocess.Popen, str, str]:
    """启动无头浏览器并等待调试端口可用。

    返回 (进程, ws_url, user_data_dir)。调用方负责 terminate() 与清理目录。
    """
    user_data_dir = tempfile.mkdtemp(prefix="dsh-cdp-")
    args = [
        executable,
        "--headless=new",
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-sync",
        "--disable-gpu",
        "--window-size=1440,1000",
        "about:blank",
    ]
    if extra_args:
        args.extend(extra_args)

    kwargs: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(args, **kwargs)

    deadline = time.monotonic() + startup_timeout
    last_error = ""
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise CdpError(f"浏览器进程提前退出（code={proc.returncode}）")
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json/version", timeout=2
            ) as resp:
                info = json.loads(resp.read().decode("utf-8"))
            ws_url = info.get("webSocketDebuggerUrl")
            if ws_url:
                return proc, ws_url, user_data_dir
            last_error = "调试端点未返回 webSocketDebuggerUrl"
        except (urllib.error.URLError, OSError, ValueError) as exc:
            last_error = str(exc)
        time.sleep(0.4)

    proc.terminate()
    raise CdpError(f"浏览器调试端口未就绪：{last_error}")


def shutdown_browser(proc: subprocess.Popen, user_data_dir: str) -> None:
    """结束浏览器并删除临时用户目录（失败不抛异常）。"""
    import shutil

    try:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    except OSError:
        pass
    shutil.rmtree(user_data_dir, ignore_errors=True)
