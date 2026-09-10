"""Plotly 图表主题：把设计 token 映射成 Plotly 模板。

问题背景
--------
改造前图表配色散落在四处，彼此矛盾：

- ``visualizer.py``：``gridcolor="#334155" if dark else "#e0e0e0"``，但
  ``paper_bgcolor`` / ``plot_bgcolor`` 一个字都没设；
- ``nwp_forecast.py``：``bg = "#0f172a" if dark else "#ffffff"``（**另一套深色**，
  比应用主体的 #161c2e 更黑）、``grid = "#475569"``、``tick_col = "#94a3b8"``；
- ``verify.py``：完全不管主题；
- ``analyzer.py``：不设图表背景。

更关键的是 ``st.plotly_chart`` 默认会用 Streamlit 自己的主题覆盖 figure 的
``layout``，因此即便 Python 侧设了颜色也常被前端盖掉。本模块同时解决两点：
统一取值来源，并在调用处显式传 ``theme=None`` 关闭 Streamlit 的覆盖
（见 ``config.safe_chart``）。
"""

from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

from modules.design_tokens import css_var_name, tokens_for

TEMPLATE_NAME = "dsh_weather"


def _build_template(dark: bool) -> go.layout.Template:
    """按主题构造 Plotly 模板。

    ``layout`` 里的取值都会被 Streamlit 的主题覆盖掉，因此这些颜色只有在
    调用处传 ``theme=None`` 时才生效；``data`` 段与 Streamlit 无关，始终有效。
    """
    t = tokens_for(dark)
    axis = dict(
        gridcolor=t["chart-grid"],
        zerolinecolor=t["chart-grid"],
        linecolor=t["chart-grid"],
        tickfont=dict(color=t["chart-axis"]),
        title=dict(font=dict(color=t["chart-axis"])),
        # 网格线压到背景里，避免暗色下网格比数据线还抢眼
        gridwidth=1,
    )
    return go.layout.Template(
        layout=go.Layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color=t["text-secondary"]),
            title=dict(font=dict(color=t["chart-title"])),
            colorway=[
                t["temp"], t["humid"], t["pres"], t["wind"],
                t["vis"], t["rain"], t["nox"], t["pm25"],
            ],
            xaxis=dict(**axis),
            yaxis=dict(**axis),
            legend=dict(
                bgcolor="rgba(0,0,0,0)",
                bordercolor=t["chart-tip-line"],
                font=dict(color=t["text-secondary"]),
            ),
            hoverlabel=dict(
                bgcolor=t["chart-tip-bg"],
                bordercolor=t["chart-tip-line"],
                font=dict(color=t["text-primary"]),
            ),
            colorscale=dict(
                sequential=[[0, t["chart-grid"]], [1, t["accent"]]],
            ),
        ),
        data=dict(
            scatter=[
                go.Scatter(
                    line=dict(width=2),
                    marker=dict(line=dict(width=0)),
                    hoverlabel=dict(
                        bgcolor=t["chart-tip-bg"],
                        bordercolor=t["chart-tip-line"],
                        font=dict(color=t["text-primary"]),
                    ),
                )
            ],
            bar=[
                go.Bar(
                    marker=dict(line=dict(width=0)),
                    hoverlabel=dict(
                        bgcolor=t["chart-tip-bg"],
                        bordercolor=t["chart-tip-line"],
                        font=dict(color=t["text-primary"]),
                    ),
                )
            ],
        ),
    )


def register() -> None:
    """把两套模板注册进 Plotly，并设为默认。幂等，可重复调用。"""
    pio.templates[f"{TEMPLATE_NAME}_light"] = _build_template(False)
    pio.templates[f"{TEMPLATE_NAME}_dark"] = _build_template(True)
    pio.templates.default = f"{TEMPLATE_NAME}_light"


# 导入即注册：各业务模块会在函数体内用 fig.update_layout(...) 覆盖图表样式，
# 默认模板必须在那些调用之前就已注册，否则模板合并的先后顺序不可控
# （模板晚于 layout 生效会把调用方写好的取值盖掉）。放模块级即可保证时序。
register()


def apply(fig, dark: bool | None = None) -> go.Figure:
    """把当前主题的模板套到 figure 上，并补齐模板覆盖不到的取值。

    背景色必须写进 figure 的 layout 本身，不能只留在 template 里：
    Streamlit 的图表前端组件会用**自己的**主题色绘制最底层背景 rect
    （模板里 paper/plot_bgcolor 为透明时，实测被覆盖成 secondaryBackgroundColor
    #f8fafc，于是在深色页面上留下整块浅色画布）。
    把取值直接落在 layout 上，合并时优先级高于模板，才能压住前端主题。
    """
    if dark is None:
        dark = _is_dark()
    name = f"{TEMPLATE_NAME}_dark" if dark else f"{TEMPLATE_NAME}_light"
    if name not in pio.templates:
        register()
    fig.update_layout(template=name)

    t = tokens_for(dark)
    # 画布透明 + 悬停提示色：显式落在 layout 上以压过前端主题
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=t["text-secondary"]),
        hoverlabel=dict(
            bgcolor=t["chart-tip-bg"],
            bordercolor=t["chart-tip-line"],
            font=dict(color=t["text-primary"]),
        ),
    )
    return fig


def _is_dark() -> bool:
    try:
        import streamlit as st

        return bool(st.session_state.get("dark_mode", False))
    except Exception:
        return False


def token_var(token: str) -> str:
    """供 Plotly 之外（如内联 SVG / HTML 图例）取当前主题变量名。"""
    return css_var_name(token)
