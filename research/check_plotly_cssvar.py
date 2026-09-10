"""检查 Plotly 图表代码里是否误用了 var(--token)。

plotly.js 绘制 SVG，SVG 的 fill/stroke 属性**不解析 CSS 自定义属性**，
因此图表参数里写 var() 会静默失效（渲染成默认色或空白），
必须用 design_tokens.token_value() 取真实色值。

本脚本按"最近的函数定义"判断上下文：函数名以 _chart/_fig/plot/_render_* 等
图表相关词命名，或函数体内出现 go.Figure / add_trace / update_layout 时，
视为图表上下文，其中的 css_var() 需要人工复核。

用法：python research/check_plotly_cssvar.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 图表函数的识别特征
CHART_TOKENS = ("go.Figure", "add_trace", "update_layout", "update_xaxes",
                "update_yaxes", "add_hrect", "add_vline", "add_hline",
                "safe_chart", "make_subplots")

TARGETS = [
    ROOT / "modules" / "nwp_forecast.py",
    ROOT / "modules" / "visualizer.py",
    ROOT / "modules" / "verify.py",
    ROOT / "modules" / "analyzer.py",
    ROOT / "modules" / "weather_wall.py",
]


def uses_css_var(node: ast.AST) -> list[int]:
    """返回节点内所有 css_var(...) / _C(...) 调用的行号。"""
    lines = []
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            if n.func.id in ("css_var", "_C", "color_var"):
                lines.append(n.lineno)
    return lines


def main() -> int:
    total = 0
    for path in TARGETS:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        src_lines = src.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body_src = "\n".join(src_lines[node.lineno - 1:node.end_lineno])
            if not any(t in body_src for t in CHART_TOKENS):
                continue
            hits = uses_css_var(node)
            if not hits:
                continue
            # 过滤掉纯粹用于 HTML 字符串的调用：该行含 "<" 表示在拼 HTML
            real = [ln for ln in hits if "<" not in src_lines[ln - 1]]
            if not real:
                continue
            print(f"\n{path.relative_to(ROOT)} :: {node.name}() 第 {node.lineno} 行起")
            for ln in real:
                print(f"   L{ln}: {src_lines[ln - 1].strip()[:100]}")
            total += len(real)
    print(f"\n疑似图表内误用 var(--token) 共 {total} 处")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
