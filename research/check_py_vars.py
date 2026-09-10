"""检查 Python 源码里引用的 CSS 变量是否都能解析到 token 表。

背景：同一个语义色在项目里会以两种写法出现——
    css_var("line") / color_value("primary")   → token 名（经映射成变量名/色值）
    "var(--border-color)"                       → 直写变量名
漏定义或映射缺失不会报错，只会在页面上表现为「颜色变成继承值或透明」的静默故障。

实现要点：
- 用 ast 收集**代码**区域的行号，只检查代码，跳过注释与文档字符串，
  避免把文档里的示例（如 ``--xxx``）当成真实引用；
- token 名先经 color_key→token→变量名 的完整链路归一化再校验。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SKIP_DIRS = {"__pycache__", "research", "tests", ".git", ".streamlit"}

CALL_NAMES = ("css_var", "token_value", "_sev", "_aq_color", "color_var", "color_value")


def code_line_numbers(tree: ast.AST) -> set[int]:
    """收集所有‘代码’所在行号（表达式、语句、调用中的常量字符串）。"""
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            # 文档字符串/普通字符串常量仍需判断是否在表达式中：
            # 这里只登记非 docstring 的字符串（docstring 是模块/类/函数体的
            # 第一个 Expr 常量，单独排除）
            continue
        if hasattr(node, "lineno"):
            lines.add(node.lineno)
            if getattr(node, "end_lineno", None):
                lines.update(range(node.lineno, node.end_lineno + 1))
    # 排除 docstring 行
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                ds = body[0].value
                lines.difference_update(range(ds.lineno, (ds.end_lineno or ds.lineno) + 1))
    return lines


def main() -> int:
    from modules.design_tokens import (
        COLOR_KEY_TO_TOKEN,
        STATIC_TOKENS,
        css_var_name,
        tokens_for,
    )

    defined: set[str] = set()
    for table in (tokens_for(False), tokens_for(True)):
        for key in table:
            defined.add(css_var_name(key))
    for key in STATIC_TOKENS:
        defined.add(css_var_name(key))

    missing: list[tuple[str, int, str]] = []
    checked = 0

    for path in sorted(ROOT.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        code_lines = code_line_numbers(tree)

        for node in ast.walk(tree):
            # 1) 直写变量名：任意字符串常量里的 var(--x)
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.lineno not in code_lines:
                    continue
                import re
                for m in re.finditer(r"var\(--([a-z0-9-]+)\)", node.value):
                    checked += 1
                    if m.group(1) not in defined:
                        missing.append((str(path.relative_to(ROOT)), node.lineno,
                                        f"--{m.group(1)}"))
            # 2) token 名调用：css_var("x") / color_value("x") …
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id in CALL_NAMES and node.args:
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    checked += 1
                    key = arg.value
                    # 先按 config 色表键映射，再按 token 名映射
                    token = COLOR_KEY_TO_TOKEN.get(key, key)
                    var = css_var_name(token)
                    if var not in defined:
                        missing.append((str(path.relative_to(ROOT)), node.lineno,
                                        f'{key} → --{var}'))

    if missing:
        print(f"发现 {len(missing)} 处无法解析的 CSS 变量引用：")
        for rel, ln, name in missing:
            print(f"  {rel}:{ln}  {name}")
        return 1
    print(f"所有 Python 侧 CSS 变量引用均可解析 OK（共校验 {checked} 处）")
    print(f"（已定义变量 {len(defined)} 个）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
