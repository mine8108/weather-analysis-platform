"""
AI 预警叙事模块（C 方案）

把 analyzer.py 的国标事件检测、多要素耦合、空气质量评估结果，
转化为面向公众与基层管理人员的自然语言报告。

设计约束（来自方案定稿）：
- 仅生成报告（不含聊天追问），降低复杂度
- 纯 requests 调用，无新增第三方依赖（requests 已在 requirements.txt）
- 密钥走 st.secrets，绝不进代码/前端
- 无密钥 / 调用失败时优雅降级，绝不阻断主流程
"""

import streamlit as st
import requests


# ============================================================
# 一、提示词构造
# ============================================================
def build_prompt(detection):
    """依据检测结果构造发送给 LLM 的提示词。

    detection 结构:
    {
        "warnings":   [ {type, level, level_num, detail, icon}, ... ],   # 8 类国标事件
        "coupling":   [ {type, severity, detail, icon}, ... ],          # 耦合风险
        "air_quality": {aqi, primary, level, color, advice, details} | None,
    }
    返回: 纯文本提示词（含系统指令 + 结构化数据）
    """
    warnings = detection.get("warnings", []) or []
    coupling = detection.get("coupling", []) or []
    aq = detection.get("air_quality")

    sections = []
    sections.append(
        "你是一名气象防灾减灾分析助手。下面是一段气象观测数据，"
        "基于中国国家标准气象预警阈值自动检测的结果。请据此生成一份"
        "面向公众与基层管理人员的自然语言解读报告。"
    )
    sections.append(
        "要求：中文，简洁专业，300 字以内；按【总体概览】【关键预警】"
        "【多要素耦合风险】【空气质量】【综合建议】五段组织；"
        "若无某项风险，明确说明“未检测到”；不要编造数据；语气客观、可操作。"
    )

    # 关键预警
    if warnings:
        w_lines = [f"- {w['icon']} {w['type']}{w['level']}（{w['level_num']}）：{w['detail']}" for w in warnings]
        sections.append("【关键预警】\n" + "\n".join(w_lines))
    else:
        sections.append("【关键预警】\n未检测到符合国标阈值的气象预警事件。")

    # 耦合风险
    if coupling:
        c_lines = [f"- {c['icon']} {c['type']}（{c['severity']}）：{c['detail']}" for c in coupling]
        sections.append("【多要素耦合风险】\n" + "\n".join(c_lines))
    else:
        sections.append("【多要素耦合风险】\n未检测到显著的多要素耦合风险。")

    # 空气质量
    if aq:
        details = aq.get("details", []) or []
        d_lines = [
            f"- {d['label']}：均值 {d['avg']} μg/m³，IAQI {d['iaqi']}，等级 {d['level']}"
            f"{'（超标）' if (d.get('exceed_daily') or d.get('exceed_hourly')) else ''}"
            for d in details
        ]
        aq_text = (
            f"综合 AQI {aq['aqi']}，等级 {aq['level']}，首要污染物 {aq.get('primary') or '无'}。\n"
            + "\n".join(d_lines)
        )
        sections.append("【空气质量】\n" + aq_text)
    else:
        sections.append("【空气质量】\n当前数据未含大气污染物字段，无法评估空气质量。")

    sections.append("请直接输出报告正文（不要重复系统指令）。")
    return "\n\n".join(sections)


# ============================================================
# 二、LLM 调用（DeepSeek，OpenAI 兼容协议）
# ============================================================
def call_llm(prompt, api_key, base_url=None, model=None):
    """调用 LLM 生成解读文本。失败时抛异常，由调用方降级处理。

    密钥来源：st.secrets（LLM_API_KEY / LLM_BASE_URL / LLM_MODEL）。
    """
    base_url = (base_url or st.secrets.get("LLM_BASE_URL", "https://api.deepseek.com")).rstrip("/")
    model = model or st.secrets.get("LLM_MODEL", "deepseek-chat")

    system_msg = (
        "你是严谨的气象分析助手，仅基于用户提供的数据生成解读，"
        "不做无根据的推测，中文输出。"
    )
    resp = requests.post(
        f"{base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 800,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


# ============================================================
# 三、降级：结构化 Markdown 摘要（无密钥或调用失败时兜底）
# ============================================================
def build_fallback_markdown(detection):
    """无 LLM 时，把结构化结果直接渲染成可读 Markdown，保证信息不丢失。"""
    warnings = detection.get("warnings", []) or []
    coupling = detection.get("coupling", []) or []
    aq = detection.get("air_quality")

    parts = ["### AI 解读不可用（已降级为结构化摘要）\n"]
    if warnings:
        parts.append("**关键预警**")
        for w in warnings:
            parts.append(f"- {w['icon']} {w['type']}{w['level']}：{w['detail']}")
    else:
        parts.append("**关键预警**：未检测到符合阈值的事件。")

    if coupling:
        parts.append("**耦合风险**")
        for c in coupling:
            parts.append(f"- {c['icon']} {c['type']}（{c['severity']}）：{c['detail']}")

    if aq:
        parts.append(
            f"**空气质量**：AQI {aq['aqi']}（{aq['level']}），首要污染物 {aq.get('primary') or '无'}。"
        )
    return "\n".join(parts)


# ============================================================
# 四、UI 渲染入口
# ============================================================
def render_ai_block():
    """检测 Tab 末尾的 AI 解读块。依赖 session_state['detection_result']。"""
    detection = st.session_state.get("detection_result")
    if not detection:
        return

    st.write("---")
    st.write("### [AI] 智能预警解读")

    api_key = st.secrets.get("LLM_API_KEY", "")
    if not api_key:
        st.info(
            "AI 解读未启用：请在 Streamlit Cloud 的 Secrets 中配置 "
            "`LLM_API_KEY`（DeepSeek）。配置后将出现「生成 AI 解读报告」按钮。"
        )
        return

    if st.button("生成 AI 解读报告", key="ai_generate_report"):
        with st.spinner("AI 正在生成解读..."):
            try:
                prompt = build_prompt(detection)
                text = call_llm(prompt, api_key)
                st.session_state["ai_narrative_text"] = text
            except Exception as e:  # noqa: BLE001 - 任何失败都降级，不阻断
                st.error(f"AI 生成失败：{e}")
                st.markdown(build_fallback_markdown(detection))
                return

    cached = st.session_state.get("ai_narrative_text")
    if cached:
        st.markdown(cached)
