"""一次性迁移脚本：把 ``COLORS["key"]`` 替换为 ``_C("key")``（主题感知）。

背景
----
``config.COLORS`` 是项目早期的图表配色表，键名被各模块大量引用。
它存的是固定 hex，因此图表配色无法跟随亮/暗主题——这正是「同一张图在
两个主题下用同一套颜色」的根因。

``modules.design_tokens.color_var` 提供了「键 → 当前主题 var(--token)」的解析。
本脚本把调用点从 ``COLORS["temp_color"]`` 改写为 ``_C("temp_color")``，
并在文件顶部注入一个模块级别的别名：

    from modules.design_tokens import color_var as _C

安全措施
--------
- 只替换 ``COLORS["..."]`` 字面量下标形式，不碰 ``COLORS`` 的其它用法；
- 不改 ``config.py`` 自身（那里是定义处）；
- 改完做 ``ast.parse`` 语法自检；
- 幂等：已改写为 ``_C(...)`` 的部分不会被重复处理。
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PATTERN = re.compile(r'\bCOLORS\["([a-z0-9_]+)"\]')
IMPORT_LINE = "from modules.design_tokens import color_var as _C\n"

TARGETS = [
    ROOT / "modules" / "visualizer.py",
    ROOT / "modules" / "nwp_forecast.py",
]


def ensure_import(text: str) -> str:
    """在最后一个顶层 import 之后插入别名的导入行（幂等）。"""
    if IMPORT_LINE.strip() in text:
        return text
    lines = text.splitlines(keepends=True)
    last_import = -1
    for i, line in enumerate(lines):
        if re.match(r"^(from|import)\s", line):
            last_import = i
    if last_import < 0:
        raise RuntimeError("未找到任何 import 语句，放弃")
    lines.insert(last_import + 1, IMPORT_LINE)
    return "".join(lines)


def migrate(path: Path, apply: bool) -> int:
    text = path.read_text(encoding="utf-8")
    print(f"\n--- {path.relative_to(ROOT)} ---")
    new_text, n = PATTERN.subn(r'_C("\1")', text)
    if not n:
        print("  （无匹配）")
        return 0
    new_text = ensure_import(new_text)
    try:
        ast.parse(new_text)
    except SyntaxError as exc:
        print(f"  !! 语法错误，放弃本文件：{exc}")
        return 0
    print(f"  [{n}] COLORS[...] → _C(...)")
    if apply:
        path.write_text(new_text, encoding="utf-8")
        print("  已写入")
    else:
        print("  （dry-run；加 --apply 生效）")
    return n


def main() -> int:
    apply = "--apply" in sys.argv
    total = sum(migrate(t, apply) for t in TARGETS)
    print(f"\n合计 {total} 处")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
