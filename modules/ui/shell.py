"""Shared, full-width workbench surface; business functions remain independent."""
from __future__ import annotations

from html import escape
from pathlib import Path
from uuid import uuid4

import streamlit as st

_CSS = Path(__file__).with_name("workbench.css")


def inject_workbench_style():
    media = Path(st.__file__).parent / "static" / "static" / "media"
    font = next(media.glob("MaterialSymbols-Rounded*.woff2"), None)
    base = (st.get_option("server.baseUrlPath") or "").strip("/")
    # Cloud serves the app inside /~/+/; a root-absolute URL returns its HTML shell.
    prefix = f"/{base}/" if base else ""
    font_url = f"{prefix}static/media/{font.name}" if font else ""
    st.html("<style>" + _CSS.read_text(encoding="utf-8").replace("__MATERIAL_FONT_URL__", font_url) + "</style>")


def render_brand(*, preview=False):
    from modules.ui.weather_component import asset_base
    with st.container(key="workbench_brand"):
        st.html(f'<div class="wb-brand"><img class="wb-brand-logo" src="{asset_base()}/brand-cloud.png" alt="">'
                '<div class="wb-brand-title">气象分析工作台</div>'
                + ('<span class="wb-preview">本地设计预览 · 示例数据</span>' if preview else '') + '</div>')


def page_heading(title, description="", *, eyebrow=""):
    with st.container(key="workbench_heading"):
        st.html((f'<div class="wb-eyebrow">{escape(eyebrow)}</div>' if eyebrow else '')
                + f'<h1 class="wb-page-title">{escape(title)}</h1>'
                + (f'<p class="wb-page-description">{escape(description)}</p>' if description else ''))


def entry_identity(route):
    """Entry changes on actual route changes, never on ordinary Streamlit reruns."""
    state = st.session_state
    if "_workbench_session" not in state:
        state["_workbench_session"] = uuid4().hex
    if state.get("_workbench_route") != route:
        state["_workbench_route"] = route
        state["_workbench_entry"] = uuid4().hex
    return state["_workbench_session"], state["_workbench_entry"]
