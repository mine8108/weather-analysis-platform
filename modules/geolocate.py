"""浏览器定位组件（Python 封装）。

前端实现：modules/locator/index.html（纯静态 HTML/JS，无 React 构建链）。
协议：iframe 内 navigator.geolocation → streamlit:setComponentValue 回传
{status:"ok"|"denied"|"unsupported", lat, lon, error} → Python 端 rerun 后取到 value。

用法：
    loc = geo_locator(clear=_relocate, key="wall_geo")
    if loc and loc.get("status") == "ok":
        # 消费定位结果

- clear=True：前端清缓存并重新请求授权（用户点「重新定位」时传）。
- 首次 mount 无浏览器环境（AppTest / 无 JS）时返回 default None。
"""

import os

import streamlit as st
import streamlit.components.v1 as components

_component = components.declare_component(
    "aether_geo_locator",
    path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "locator"),
)


def geo_locator(clear: bool = False, key: str = "wall_geo"):
    """返回定位结果 dict（status/lat/lon/error）或 None（未就绪）。"""
    return _component(clear=bool(clear), key=key, default=None)
