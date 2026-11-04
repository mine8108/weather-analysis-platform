"""Download small immutable snapshots without a separate media HTTP request."""
from __future__ import annotations

import base64
from contextlib import nullcontext
from html import escape

import streamlit as st

from modules.design_tokens import token_value


# Bound the WebSocket/iframe payload. Larger files use Streamlit's supported
# deferred-download API rather than embedding an unbounded base64 document.
INLINE_LIMIT_BYTES = 8 * 1024 * 1024


def _payload(data):
    if isinstance(data, str):
        return data.encode("utf-8")
    if isinstance(data, (bytes, bytearray, memoryview)):
        return bytes(data)
    raise TypeError("下载内容须为文本或字节")


def _inline_html(label, data, file_name, mime, *, dark=False, stretch=False, help_text=None):
    """Only base64 bytes and HTML-escaped attributes enter the sandboxed iframe."""
    encoded = base64.b64encode(_payload(data)).decode("ascii")
    name = escape(str(file_name or "download"), quote=True)
    content_type = escape(str(mime or "application/octet-stream"), quote=True)
    title = escape(str(help_text or ""), quote=True)
    text = escape(str(label))
    bg = token_value("bg-primary", dark)
    ink = token_value("text-primary", dark)
    border = token_value("border-color", dark)
    accent = token_value("accent", dark)
    width = "100%" if stretch else "auto"
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
html,body{{margin:0;padding:0;background:transparent}}
button{{box-sizing:border-box;width:{width};min-height:38px;padding:7px 12px;
border:1px solid {border};border-radius:8px;background:{bg};color:{ink};
font:400 14px/1.35 system-ui,sans-serif;cursor:pointer}}
button:hover{{border-color:{accent};color:{accent}}}
button:focus-visible{{outline:2px solid {accent};outline-offset:2px}}
</style></head><body><button type="button" id="download" data-name="{name}"
data-mime="{content_type}" title="{title}">{text}</button>
<script>
document.getElementById('download').addEventListener('click', function () {{
  const raw = atob('{encoded}');
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  const url = URL.createObjectURL(new Blob([bytes], {{type: this.dataset.mime}}));
  const a = document.createElement('a');
  a.href = url; a.download = this.dataset.name; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}});
</script></body></html>"""


def download_button(label, data, *, file_name=None, mime=None, key=None, width="content",
                    use_container_width=None, help=None, icon=None, target=None):
    """Snapshot data at render time; large files retain Streamlit's deferred path."""
    content = _payload(data)
    stretch = width == "stretch" or use_container_width is True
    with target if target is not None else nullcontext():
        if len(content) <= INLINE_LIMIT_BYTES:
            markup = _inline_html(label, content, file_name, mime,
                                  dark=bool(st.session_state.get("dark_mode", False)),
                                  stretch=stretch, help_text=help)
            st.iframe(markup, height=42, alt=f"文件下载：{file_name or label}")
        else:
            # No eager frontend probe and no rerun on the click. The immutable
            # snapshot ensures concurrent session changes cannot alter the file.
            st.download_button(label, lambda: content, file_name=file_name, mime=mime,
                               key=key, width="stretch" if stretch else "content",
                               help=help, icon=icon, on_click="ignore")
