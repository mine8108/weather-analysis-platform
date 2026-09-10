"""一次性迁移脚本：把图表代码里的主题三元表达式替换为 CSS 变量引用。

模式
----
改造前各模块用 ``"#aaaaaa" if dark else "#bbbbbb"`` 的形式在 Python 侧选色。
这类分支有四个问题：
1. 同一语义色在不同模块取不同值（图表背景有 #0f172a 与 #1e293b 两种深色）；
2. 切换主题必须重新跑一遍 Python，无法享受 CSS 变量的即时生效；
3. ``{color}22`` 这类 hex 拼接在换成 var() 后会产出非法 CSS；
4. 每新增一个主题就要改 N 处。

统一替换成 ``css_var("<token>")``（由 design_tokens 提供）。

安全措施
--------
- 只匹配**完整的**三引号/单引号字符串字面量 + if/else 形式，不做行号定位
  （行号锚定在编辑过程中会漂移，本项目已踩过一次）；
- 每个文件改完后做 ``ast.parse`` 语法自检，失败即整文件回滚；
- dry-run 默认开启。
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (旧表达式正则, 替换文本, 说明)
# 顺序有意义：更具体的模式排前面。
RULES: list[tuple[str, str, str]] = [
    # ---- 图表提示框底色（4 处，含 nwp_forecast 的三处悬浮标注）----
    (r'"rgba\(15,23,42,0\.9\)" if _is_dark\(\) else "rgba\(255,255,255,0\.8[25]\)"',
     'css_var("chart-tip-bg")', "图表提示框底色"),
    (r'"rgba\(15,23,42,0\.85\)" if dark else "rgba\(255,255,255,0\.9\)"',
     'css_var("chart-tip-bg")', "峰值标注底色"),
    # ---- 参考线 ----
    (r'"#334155" if not dark else "#cbd5e1"',
     'css_var("chart-ref-line")', "参考线/标注色"),
    # ---- 风玫瑰图配色（4 处绑定）----
    (r'"#0f172a" if dark else "#ffffff"',
     'css_var("surface")', "图表背景"),
    (r'"#475569" if dark else "#cbd5e1"',
     'css_var("chart-grid")', "网格线"),
    (r'"#94a3b8" if dark else "#6b7280"',
     'css_var("chart-axis")', "坐标轴刻度文字"),
    (r'"#e2e8f0" if dark else "#1f2937"',
     'css_var("chart-title")', "图表标题"),
    (r'"rgba\(15,23,42,0\.35\)" if dark else "rgba\(255,255,255,0\.9\)"',
     'css_var("chart-marker-line")', "数据点描边"),
    # ---- 数据点标记描边 ----
    (r'"#ffffff" if not dark else "#0f172a"',
     'css_var("chart-marker-line")', "峰值点描边"),
    # ---- visualizer 的网格色（三元在表达式位置，无引号包裹整体）----
    (r'"#334155" if st\.session_state\.get\("dark_mode", False\) else "#e0e0e0"',
     'css_var("chart-grid")', "visualizer 网格线"),
]


def migrate(path: Path, apply: bool) -> int:
    text = path.read_text(encoding="utf-8")
    original = text
    hits = 0
    print(f"\n--- {path.relative_to(ROOT)} ---")
    for pattern, repl, label in RULES:
        new_text, n = re.subn(pattern, repl, text)
        if n:
            print(f"  [{n:>2}] {label}")
            text = new_text
            hits += n
    if not hits:
        print("  （无匹配）")
        return 0

    # 语法自检：ast.parse 比 import 更严格地抓语法错误且无副作用
    try:
        ast.parse(text)
    except SyntaxError as exc:
        print(f"  !! 替换后语法错误，已放弃本文件：{exc}")
        return 0

    if apply:
        path.write_text(text, encoding="utf-8")
        print(f"  已写入（{hits} 处）")
    else:
        print(f"  （dry-run，{hits} 处待改；加 --apply 生效）")
    return hits


def main() -> int:
    apply = "--apply" in sys.argv
    targets = [
        ROOT / "modules" / "nwp_forecast.py",
        ROOT / "modules" / "visualizer.py",
    ]
    total = 0
    for t in targets:
        total += migrate(t, apply)
    print(f"\n合计 {total} 处")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
