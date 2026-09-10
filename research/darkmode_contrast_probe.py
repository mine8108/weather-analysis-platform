"""暗色模式对比度探针（纯 CSS，content 即测量结果）。

原理：浏览器无法通过本插件的结构化工具执行 JS，但 CSS 的 content 属性可以读取
var() 与环境色。本脚本生成一段 <style>，用 ::before 的 content 把关键元素的
实际前景/背景色渲染成文字，截图即可读出「真实生效值」。

用法：
    python research/darkmode_contrast_probe.py            # 输出探针 CSS
    python research/darkmode_contrast_probe.py --check    # 校验 token 对比度
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------
# 一、探针 CSS：把真实生效的变量值打印出来
# ---------------------------------------------------------------
def probe_css(selector: str, label: str, prop: str = "color") -> str:
    """在 selector 上挂一个探针，显示 label 与 prop 的真实生效值。"""
    return f"""
{selector}::after {{
    content: "{label} {prop}=" var(--probe-{prop}) ;
    background: {prop};
    color: {prop};
    font-size: 1px;
    position: absolute;
    left: -9999px;
}}
"""


def build_probe() -> str:
    """构造自检块：逐条显示当前主题下每个语义 token 的真实取值。"""
    keys = [
        "bg-primary", "bg-secondary", "bg-tertiary", "bg-hover",
        "text-primary", "text-secondary", "text-muted",
        "border-color", "border-hover", "accent", "accent-hover",
        "accent-soft", "success-bg", "warning-bg", "error-bg",
    ]
    rows = []
    for k in keys:
        rows.append(
            f'<div style="display:flex;gap:10px;align-items:center;margin:3px 0;">'
            f'<code style="width:120px;color:var(--text-muted);">--{k}</code>'
            f'<span style="width:150px;color:var(--text-primary);font-family:monospace;">'
            f'var(--{k})</span>'
            f'<span style="flex:1;height:20px;border-radius:4px;'
            f'background:var(--{k});box-shadow:0 0 0 1px var(--border-color) inset;"></span>'
            f"</div>"
        )
    return (
        '<div style="font-family:monospace;font-size:12px;">'
        + "".join(rows)
        + "</div>"
    )


# ---------------------------------------------------------------
# 二、离线对比度校验（WCAG 2.1）
# ---------------------------------------------------------------
def _srgb_to_lin(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _lum(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * _srgb_to_lin(r) + 0.7152 * _srgb_to_lin(g) + 0.0722 * _srgb_to_lin(b)


def contrast(fg: str, bg: str) -> float:
    """WCAG 对比度。fg/bg 需为不含 alpha 的 hex（含 alpha 的先做合成）。"""
    l1, l2 = _lum(fg), _lum(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def blend(fg: str, alpha: float, bg: str) -> str:
    """把带 alpha 的前景合成到实底背景上，返回不透明 hex。"""
    f = fg.lstrip("#")
    b = bg.lstrip("#")
    out = []
    for i in (0, 2, 4):
        fv = int(f[i:i + 2], 16)
        bv = int(b[i:i + 2], 16)
        out.append(round(fv * alpha + bv * (1 - alpha)))
    return "#" + "".join(f"{v:02x}" for v in out)


def audit() -> int:
    """对两套 token 做 WCAG 审计，返回不合规条数。

    每个主题都用**自己**的 surface token 当背景，因为卡片的实际底色来自
    ``--bg-primary`` / ``--bg-secondary``，用写死的探针色会误判。
    """
    from modules.design_tokens import DARK_TOKENS, LIGHT_TOKENS

    surfaces = {
        "light": {"page": "app-base", "card": "surface", "sidebar": "sidebar"},
        "dark": {"page": "app-base", "card": "surface", "sidebar": "sidebar"},
    }
    text_keys = ["text-primary", "text-secondary", "text-muted"]
    # 语义色前景也必须在卡片底上可读
    semantic = [
        "success-ink", "warning-ink", "error-ink", "info-ink", "accent",
        # 严重度梯度会作为卡片正文色（分数、等级、建议文字），必须过 AA
        "sev-best", "sev-good", "sev-mid", "sev-warn", "sev-bad",
        # 图表色系作为卡片内数值色时同样必须可读
        "temp", "pres", "humid", "wind", "vis", "rain",
    ]
    fails = 0
    for name, tokens in (("light", LIGHT_TOKENS), ("dark", DARK_TOKENS)):
        print(f"\n=== {name.upper()} 主题对比度审计 ===")
        for sk, token_key in surfaces[name].items():
            base = tokens[token_key]
            if not base.startswith("#"):
                print(f"  [skip] {sk} 底色非 hex: {base}")
                continue
            for tk in text_keys:
                fg = tokens[tk]
                ratio = contrast(fg, base)
                need = 4.5
                bad = ratio < need
                fails += bad
                print(f"  [{'FAIL' if bad else 'OK  '}] {tk:15s} on {sk:9s} ({base}) = {ratio:5.2f}:1 (需 {need})")
        # 语义前景色：在卡片底上校验
        card = tokens["surface"]
        for tk in semantic:
            fg = tokens[tk]
            if not fg.startswith("#"):
                print(f"  [skip] {tk} 含 alpha: {fg}")
                continue
            ratio = contrast(fg, card)
            bad = ratio < 4.5
            fails += bad
            print(f"  [{'FAIL' if bad else 'OK  '}] {tk:15s} on card      ({card}) = {ratio:5.2f}:1 (需 4.5)")
        # 语义背景色上的正文：带 alpha 的先合成到卡片底
        for bk, ik in (("success-bg", "success-ink"), ("warning-bg", "warning-ink"),
                       ("error-bg", "error-ink"), ("info-bg", "info-ink")):
            bg = tokens[bk]
            fg = tokens[ik]
            if bg.startswith("#") and fg.startswith("#"):
                base = bg
            else:
                import re as _re
                m = _re.match(r"rgba\((\d+),(\d+),(\d+),([\d.]+)\)", bg)
                if not m:
                    continue
                r, g, b, a = (float(x) for x in m.groups())
                base = blend(f"#{int(r):02x}{int(g):02x}{int(b):02x}", a, card)
            ratio = contrast(fg, base)
            bad = ratio < 4.5
            fails += bad
            print(f"  [{'FAIL' if bad else 'OK  '}] {ik:15s} on {bk:11s} ({base}) = {ratio:5.2f}:1 (需 4.5)")
    print(f"\n合计不合规 {fails} 项")
    return fails


if __name__ == "__main__":
    if "--check" in sys.argv:
        raise SystemExit(1 if audit() else 0)
    print(build_probe())
