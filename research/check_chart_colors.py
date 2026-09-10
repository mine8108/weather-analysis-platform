"""验证 AQI 预报图表在两种主题下均可构建，且没有把 token 名当颜色值传给 Plotly。

背景：`_AQ_LEVELS` / `_WF_LEVELS` 等表里的第 4 个元素已改为 **token 名**
（如 "aqi-1"），若某处忘记经 `_aq_color()` / `token_value()` 解析就传给
Plotly 的 `color`，会抛 ValueError 并被 `safe_chart` 兜住，
表现为「图表加载出现异常」而整块模块不渲染（R-47）。
"""

import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import plotly.graph_objects as go  # noqa: E402

from modules import nwp_forecast as n  # noqa: E402

# token 名前缀：出现在 Plotly 颜色参数里即为漏解析
TOKEN_PREFIXES = (
    "aqi-", "warn-", "sev-", "beaufort-",
    "temp", "pres", "humid", "wind", "vis", "rain",
    "pm25", "pm10", "so2", "nox", "tsp",
    "chart-", "text-", "bg-", "border-", "accent",
)


def looks_like_token(value) -> bool:
    return isinstance(value, str) and value.startswith(TOKEN_PREFIXES) \
        and not value.startswith("#")


def scan_fig(fig: "go.Figure") -> list:
    """扫描 figure 内所有颜色属性，返回疑似 token 名列表。"""
    bad = []
    for i, tr in enumerate(fig.data):
        # marker.color 可能是字符串、数组或 None
        mc = getattr(tr, "marker", None)
        if mc is not None:
            col = getattr(mc, "color", None)
            if looks_like_token(col):
                bad.append(f"trace[{i}].marker.color={col!r}")
            if isinstance(col, (list, tuple, np.ndarray)):
                for c in list(col)[:50]:
                    if looks_like_token(c):
                        bad.append(f"trace[{i}].marker.color[]={c!r}")
            line = getattr(mc, "line", None)
            if line is not None and looks_like_token(getattr(line, "color", None)):
                bad.append(f"trace[{i}].marker.line.color={getattr(line, 'color')!r}")
        ln = getattr(tr, "line", None)
        if ln is not None and looks_like_token(getattr(ln, "color", None)):
            bad.append(f"trace[{i}].line.color={getattr(ln, 'color')!r}")
    # layout 侧
    for name in ("paper_bgcolor", "plot_bgcolor"):
        v = getattr(fig.layout, name, None)
        if looks_like_token(v):
            bad.append(f"layout.{name}={v!r}")
    for ax in ("xaxis", "yaxis"):
        a = getattr(fig.layout, ax, None)
        if a is not None:
            for prop in ("gridcolor", "linecolor", "zerolinecolor"):
                v = getattr(a, prop, None)
                if looks_like_token(v):
                    bad.append(f"layout.{ax}.{prop}={v!r}")
    return bad


def main() -> int:
    ts = pd.date_range("2026-09-10", periods=24, freq="h")
    aq_df = pd.DataFrame({
        "timestamp": ts,
        "aqi": np.linspace(40, 320, 24).round(),
        "level": ["优"] * 8 + ["良"] * 8 + ["严重污染"] * 8,
        "primary": ["PM2.5"] * 24,
    })

    failures = 0
    for dark in (False, True):
        try:
            fig = n.air_quality_aqi_chart(aq_df, dark=dark)
        except Exception:
            print(f"[FAIL] air_quality_aqi_chart(dark={dark}) 抛异常：")
            traceback.print_exc()
            failures += 1
            continue
        bad = scan_fig(fig)
        if bad:
            print(f"[FAIL] dark={dark} 存在未解析的 token 颜色：{bad}")
            failures += 1
        else:
            print(f"[OK]   dark={dark} traces={len(fig.data)} 颜色全部为具体色值")

    print("\n结果:", "全部通过" if not failures else f"{failures} 项失败")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
