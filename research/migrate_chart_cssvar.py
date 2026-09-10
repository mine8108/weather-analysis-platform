"""把图表上下文里误用的 css_var() 换成 token_value()（精确到行号，一次性）。

背景：plotly.js 绘制 SVG，SVG 的 fill/stroke 不解析 CSS 自定义属性，
因此在 figure 参数里写 var(--x) 会静默失效。HTML 场景（内联 style）仍应使用
css_var()，可随主题即时切换，故不能全量替换，只改图表所在行。
"""

from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

# 行号 → 仅这些行属于 Plotly 参数（由 research/check_plotly_cssvar.py 定位）
TARGETS = {
    "modules/visualizer.py": [563, 572, 665],
    "modules/nwp_forecast.py": [511, 515, 526, 537, 705, 738, 773, 847, 848, 849, 850, 851],
}


def main() -> int:
    apply = "--apply" in sys.argv
    total = 0
    for rel, lines in TARGETS.items():
        p = ROOT / rel
        src = p.read_text(encoding="utf-8").splitlines(keepends=True)
        changed = 0
        for ln in lines:
            i = ln - 1
            if "css_var(" not in src[i]:
                print(f"  {rel}:{ln} 未含 css_var(，跳过（行号可能已漂移）")
                continue
            src[i] = src[i].replace("css_var(", "token_value(")
            changed += 1
        out = "".join(src)
        ast.parse(out)  # 语法自检：不通过就抛错，不写盘
        if apply:
            p.write_text(out, encoding="utf-8")
            print(f"{rel}: 替换 {changed} 处（已写入）")
        else:
            print(f"{rel}: 待替换 {changed} 处（dry-run）")
        total += changed
    print(f"合计 {total} 处")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
