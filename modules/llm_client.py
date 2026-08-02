# -*- coding: utf-8 -*-
"""
LLM 分析代码生成客户端（M3 · 向导第二模式「AI 生成」分支）

职责（按层分离，各层可独立测试）：
- build_analysis_prompt(): 由探测上下文 + 用户需求构造 system/user prompt。
- extract_python_code(): 从 LLM 回复中提取纯 Python 代码（markdown 围栏/说明文字）。
- generate_analysis_code(): 调用 OpenAI 兼容 chat/completions 接口获取代码。

架构约束（继承项目硬规则「先模板后 LLM」）：
- LLM 永不接触原始变量名/单位——它只看到规范名（2m_temperature 等）与已换算
  后的语义；真实变量映射（ACTUAL）与单位换算由模板骨架完成。
- 生成的代码只作为脚本「处理段」执行，运行在受控骨架中（ds/ACTUAL/out_prefix
  已就绪），并经 llm_validator 二次把关（白名单 + 禁止调用）。
- 无 API key / 网络失败 / 回复为空 → 抛 LlmUnavailable / LlmCallError，
  调用方回退模板场景体（灰度友好）。

环境配置（Streamlit Secrets 或显式参数）：
    LLM_API_KEY / LLM_BASE_URL（默认 https://api.openai.com/v1） / LLM_MODEL
"""

from __future__ import annotations

import json
import re
from typing import Optional

# ---- 常量 ----
DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"

# 允许 LLM 生成代码导入的模块（与 llm_validator.SAFE_MODULES_BASE 对齐，绘图除外——
# 绘图场景代码需要 matplotlib，校验层允许，这里同步列出）
_ALLOWED_IMPORTS = (
    "xarray, numpy, pandas, datetime, calendar, math, statistics, json, csv, "
    "os, os.path, pathlib, glob, sys, itertools, collections, functools, "
    "scipy.stats, scipy.interpolate, matplotlib"
)

SYSTEM_PROMPT = f"""你是一名气象数据处理专家，精通 xarray / numpy / pandas。
你负责为一个已就绪的脚本骨架编写「处理段」代码，完成用户指定的数据分析任务。

## 运行环境（骨架已提供，禁止重复定义/重新读取文件）
- ds: xarray.Dataset，变量已按【规范名】命名（见任务中的变量列表），单位已换算：
  - 温度: ℃（K→℃ 已完成）
  - 降水: mm（m→mm 已完成，total_precipitation 为时段累计量）
  - 风速: m/s（U/V 分量已合成为 10m_wind_speed）
- ACTUAL: dict（规范名 → 原始变量名），一般无需使用，直接操作规范名即可。
- out_prefix: str，输出文件前缀。
- 禁止修改 ds、禁止写回输入文件。

## 输出格式
只输出 Python 代码，用 ```python 围栏包裹。代码将作为脚本的「处理段」直接执行，
请在最后用 print("[OK] ...") 报告关键统计结果；如需保存产物，用
pandas 的 to_csv(out_prefix + "_<名称>.csv", index=False, encoding="utf-8-sig")。

## 硬性限制（违反任一即整段无效）
- 只允许 import: {_ALLOWED_IMPORTS}
- 禁止: subprocess / os.system / os.popen / exec / eval / compile / 网络请求 /
  文件删除 / 递归删除目录
- 除 out_prefix 相关输出文件外禁止写文件
- 代码必须健壮：某变量缺失时跳过该部分而非崩溃
- 不得虚构数据：只基于 ds 中实际存在的变量计算"""


class LlmUnavailable(Exception):
    """LLM 未配置（缺 API key 等），调用方应回退模板。"""


class LlmCallError(Exception):
    """LLM 调用失败（网络/超时/空回复/HTTP 错误）。"""


def build_analysis_prompt(context: dict, user_requirement: str) -> dict:
    """由探测上下文 + 用户需求构造 {system, user} prompt。

    context 关键字段（由调用方组装）:
        scene / scene_name: 场景标识与中文名；
        expected_vars: 期望变量规范名列表；
        detected: probe_netcdf_file 结果（可为 None）；
        scene_opts: 场景参数（如 months）；
        out_prefix: 输出前缀。
    """
    scene = context.get("scene", "custom")
    scene_name = context.get("scene_name", "自定义分析")
    expected_vars = context.get("expected_vars") or []
    detected = context.get("detected")
    scene_opts = context.get("scene_opts") or {}
    out_prefix = context.get("out_prefix", "era5_process")

    var_lines = "\n".join(f"- {v}（单位已换算）" for v in expected_vars) or "- （未指定，请以探测信息为准）"

    if detected and detected.get("ok"):
        det_lines = "\n".join(
            f"- {v['orig']} → 规范名 {v.get('norm') or '未识别'} | 单位 {v.get('units') or '?'} | 维度 {v.get('dims')}"
            for v in detected.get("variables", [])
        )
        det_block = f"文件探测结果（norm 已识别可安全使用）:\n{det_lines}"
    else:
        det_block = "文件探测结果: 无（未上传探测，请按 expected_vars 的规范名处理）"

    user_prompt = f"""## 任务需求
{user_requirement}

## 处理场景
{scene_name}（scene={scene}）

## 可用变量（规范名）
{var_lines}

## 文件探测信息
{det_block}

## 场景参数
{json.dumps(scene_opts, ensure_ascii=False)}

## 输出前缀
{out_prefix}

请按「输出格式」与「硬性限制」生成处理段代码。"""

    return {"system": SYSTEM_PROMPT, "user": user_prompt}


def extract_python_code(text: str) -> str:
    """从 LLM 回复提取纯 Python 代码。

    支持形态: ```python 围栏 / 裸代码（首行非自然语言说明）/ 围栏+前后说明文字。
    提取不到 → 抛 LlmCallError("回复中未找到 Python 代码")。
    """
    if not text or not text.strip():
        raise LlmCallError("LLM 回复为空")
    # 1) markdown 围栏（python 或裸围栏）
    m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.S)
    if m:
        code = m.group(1)
        if code.strip():
            return code.strip()
    # 2) 无围栏：剥掉明显的说明首行/尾行后按代码处理
    stripped = text.strip()
    # 以 import / 赋值 / def / 缩进块开头视为纯代码
    if re.match(r"^(import |from |\w+\s*=|def |# |if __name__)", stripped):
        return stripped
    raise LlmCallError("回复中未找到可执行的 Python 代码")


def _resolve_config(*, api_key=None, base_url=None, model=None):
    """优先显式参数，其次 Streamlit Secrets，否则 None。"""
    key, url, mdl = api_key, base_url, model
    try:
        import streamlit as st  # type: ignore
        key = key or st.secrets.get("LLM_API_KEY")
        url = url or st.secrets.get("LLM_BASE_URL", DEFAULT_BASE_URL)
        mdl = mdl or st.secrets.get("LLM_MODEL", DEFAULT_MODEL)
    except Exception:
        url = url or DEFAULT_BASE_URL
        mdl = mdl or DEFAULT_MODEL
    return key, url, mdl


def generate_analysis_code(
    prompt: dict,
    *,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    timeout: float = 90.0,
    temperature: float = 0.2,
) -> str:
    """调用 OpenAI 兼容 chat/completions，返回提取后的纯 Python 代码。

    异常契约:
        LlmUnavailable — 未配置 API key；
        LlmCallError — HTTP 非 2xx / 网络异常 / 回复结构异常 / 提取失败。
    """
    key, url, mdl = _resolve_config(api_key=api_key, base_url=base_url, model=model)
    if not key:
        raise LlmUnavailable(
            "未配置 LLM API Key（Streamlit Secrets 需含 LLM_API_KEY；本地可传 api_key 参数）"
        )
    try:
        import requests
    except ImportError as e:  # pragma: no cover
        raise LlmUnavailable("缺少 requests 依赖，无法调用 LLM") from e

    endpoint = url.rstrip("/") + "/chat/completions"
    payload = {
        "model": mdl,
        "messages": [
            {"role": "system", "content": prompt["system"]},
            {"role": "user", "content": prompt["user"]},
        ],
        "temperature": temperature,
    }
    try:
        resp = requests.post(
            endpoint,
            headers={"Authorization": f"Bearer {key}"},
            json=payload,
            timeout=timeout,
        )
    except Exception as e:  # noqa: BLE001
        raise LlmCallError(f"LLM 请求失败: {e}") from e
    if resp.status_code != 200:
        raise LlmCallError(f"LLM 接口返回 HTTP {resp.status_code}: {resp.text[:300]}")
    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise LlmCallError(f"LLM 回复结构异常: {e}") from e
    return extract_python_code(content)
