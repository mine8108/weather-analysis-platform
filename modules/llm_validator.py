# -*- coding: utf-8 -*-
"""
LLM 输出校验层（P2.2 · M3 二期预留）

为 LLM 分析代码生成器提供结构化校验：语法检查、导入白名单、禁止调用检测。
返回分级错误（阻断）与警告（提示），调用方据此决定是否采纳生成代码。

设计约束：
- 零外部依赖（仅 ast + re），保证校验器自身不引入不可用模块。
- 白名单可控：默认 SAFE_MODULES + 每场景可追加。
- 禁止列表以正则匹配，覆盖面优先于精确语义分析（拒绝 false negative）。
- analysis_prompt 在 era5_wizard 中为预留接口，本期不实际调用 LLM；
  本模块随代码交付，供 M3 接入时即插即用。
"""

from __future__ import annotations

import ast
import re
from typing import Optional

# ---- 安全模块白名单 ----
SAFE_MODULES_BASE = {
    # 数据处理核心
    "xarray", "numpy", "pandas",
    # 可视化
    "matplotlib", "matplotlib.pyplot",
    # 统计分析
    "scipy", "scipy.stats", "scipy.interpolate",
    "sklearn", "sklearn.cluster", "sklearn.decomposition",
    "statsmodels", "statsmodels.api",
    # 标准库
    "datetime", "calendar", "math", "statistics", "json", "csv",
    "os", "os.path", "pathlib", "glob",
    "sys", "itertools", "collections", "functools",
}

# ---- 禁止调用模式（正则 -> 说明）----
FORBIDDEN_PATTERNS: list[tuple[str, str]] = [
    (r"os\.system\s*\(", "禁止 os.system() 系统调用"),
    (r"os\.popen\s*\(", "禁止 os.popen() 调用外部程序"),
    (r"subprocess\s*\.", "禁止 subprocess 模块调用"),
    (r"__import__\s*\(\s*['\"]os", "禁止动态导入 os"),
    (r"exec\s*\(", "禁止 exec() 动态执行代码"),
    (r"eval\s*\(", "禁止 eval() 动态执行代码"),
    (r"compile\s*\(", "禁止 compile() 动态编译代码"),
    (r"open\s*\([^)]*['\"][wa]", "警告：文件写入操作（open write）"),
    (r"shutil\.rmtree", "禁止递归删除目录"),
    (r"os\.remove\s*\(|os\.unlink\s*\(", "禁止删除文件"),
    (r"requests\.|urllib\.", "禁止网络请求（分析代码应离线）"),
]


def validate_llm_output(
    code: str,
    *,
    allowed_modules: Optional[set[str]] = None,
    forbid_write: bool = True,
) -> dict:
    """校验 LLM 生成的代码片段。

    参数:
        code: 待校验 Python 代码字符串。
        allowed_modules: 允许导入的模块集合（默认 SAFE_MODULES_BASE）。
        forbid_write: True 时文件写入操作为错误而非警告。

    返回:
        {"ok": bool, "errors": [str], "warnings": [str]}
        - ok=False 时调用方应拒绝该代码并展示 errors。
        - warnings 为可忽略提示。
    """
    allowed = allowed_modules if allowed_modules is not None else SAFE_MODULES_BASE
    errors: list[str] = []
    warnings: list[str] = []

    # ---- 1. 语法检查 ----
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return {
            "ok": False,
            "errors": [
                f"语法错误（第 {e.lineno} 行第 {e.offset} 列）: {e.msg}"
            ],
            "warnings": [],
        }

    # ---- 2. 导入白名单检查 ----
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name.split(".")[0]
                if mod not in allowed:
                    errors.append(
                        f"不允许导入模块: {alias.name}（不在白名单中）"
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            mod = node.module.split(".")[0]
            if mod not in allowed:
                errors.append(
                    f"不允许从模块导入: {node.module}（不在白名单中）"
                )

    # ---- 3. 禁止模式检查 ----
    for pattern, msg in FORBIDDEN_PATTERNS:
        m = re.search(pattern, code)
        if m:
            if "警告" in msg:
                warnings.append(f"{msg}: 匹配到 '{m.group().strip()}'")
            else:
                errors.append(f"{msg}: 匹配到 '{m.group().strip()}'")

    # ---- 4. 文件写入升级 ----
    if forbid_write:
        write_errors = [e for e in errors if "写入" in e or "open write" in e.lower()]
        for we in write_errors[:]:
            pass  # 已在上面的禁止模式中归类为 warning，无需额外处理
        # 将文件写入的 warning 提升为 error
        for i, w in enumerate(warnings):
            if "写入操作" in w or "open write" in w.lower():
                errors.append(w.replace("警告：", ""))
                warnings[i] = ""

    warnings = [w for w in warnings if w]

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }


def validate_safe_for_scene(
    code: str,
    scene: str,
    **kwargs,
) -> dict:
    """场景特定校验：在通用校验基础上叠加场景白名单与特定检查。

    scene 参数目前仅预留，M3 接入时扩展（如 clim_stats 允许 CSV 写入，
    绘图场景允许 matplotlib.savefig 等）。
    """
    result = validate_llm_output(code, **kwargs)
    # M3 扩展点：在此叠加场景级规则
    if not result["ok"]:
        return result

    # 场景额外检查（预留）
    if scene == "clim_stats":
        # 必须产出 rows.append / pd.DataFrame
        if "rows.append" not in code and "pd.DataFrame" not in code:
            result["warnings"].append("代码未包含 rows.append/pd.DataFrame 输出，可能不会产生产物")

    return result
