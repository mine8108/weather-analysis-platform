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
    nwp = detection.get("nwp")

    sections = []
    nwp_hint = ""
    if nwp:
        nwp_hint = (
            f"下面给出的全部是未来短期（{nwp['period']['hours']} 小时）"
            "数值预报模式（GFS）的客观数据摘要，并非实测，也非气候统计。"
        )
    sections.append(
        "你是一名气象防灾减灾分析助手。下面是一段气象数据，"
        "基于中国国家标准气象预警阈值自动检测的结果。请据此生成一份"
        "面向公众与基层管理人员的自然语言解读报告。"
        + nwp_hint
    )
    sections.append(
        "要求：中文，简洁专业，300-400 字；按【总体概览】【关键预警】"
        "【多要素耦合风险】【空气质量】【综合建议】五段组织；"
        "若无某项风险，明确说明“未检测到”；"
        "必须严格基于下方给出的具体数值、出现时刻与时段进行解读；"
        "不得编造任何数据；不得将短期预报外推为气候趋势或长期预测；"
        "涉及预警等级仅作参考提示，最终以官方气象部门发布为准；"
        "语气客观、可操作。"
    )

    # 关键预警
    if warnings:
        w_lines = [f"- {w['icon']} {w['type']}{w['level']}（{w['level_num']}）：{w['detail']}" for w in warnings]
        sections.append("【关键预警】\n" + "\n".join(w_lines))
    else:
        sections.append("【关键预警】\n未检测到符合国标阈值的气象预警事件。")

    # 耦合风险
    nwp_coupling_lines = (nwp or {}).get("coupling", []) if nwp else []
    if coupling or nwp_coupling_lines:
        c_lines = [f"- {c['icon']} {c['type']}（{c['severity']}）：{c['detail']}" for c in coupling]
        c_lines += [f"- 数值预报耦合：{c}" for c in nwp_coupling_lines]
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

    # 数值预报结构化事实（严格依据，禁止外推）
    if nwp:
        p = nwp.get("period", {})
        fact_lines = [
            f"预报时效：{p.get('start')} 至 {p.get('end')}，共 {p.get('hours')} 小时。",
        ]
        t = nwp.get("temperature")
        if t:
            fact_lines.append(
                f"气温：最高 {t['max']}℃（{t['max_time']}），最低 {t['min']}℃（{t['min_time']}），"
                f"平均 {t['mean']}℃；≥35℃ {t['hot_hours']} 小时，≥37℃ {t['severe_hot_hours']} 小时。"
            )
        at = nwp.get("apparent_temperature")
        if at:
            fact_lines.append(f"体感温度最高 {at['max']}℃（{at['max_time']}）。")
        h = nwp.get("humidity")
        if h:
            fact_lines.append(f"相对湿度：{h['min']}%~{h['max']}%（均值 {h['mean']}%）。")
        pr = nwp.get("precipitation")
        if pr:
            fact_lines.append(
                f"降水：累计 {pr['total']}mm，最大 1 小时 {pr['max_1h']}mm（{pr['max_1h_time']}），"
                f"降雨时段 {pr['rain_hours']} 小时，其中大雨量级（>10mm/h）{pr['heavy_hours']} 小时。"
            )
        w = nwp.get("wind_speed")
        if w:
            fact_lines.append(
                f"风速：最大 {w['max']}m/s（{w['max_time']}），"
                f"≥6 级（10.8m/s）{w['gale_hours']} 小时，≥5 级（8m/s）{w['strong_hours']} 小时。"
            )
        segs = nwp.get("segments", [])
        if segs:
            seg_text = "；".join(
                f"{s['window']} 段：T∈[{s.get('min_temp','-')},{s.get('max_temp','-')}]℃"
                f"、降水 {s.get('total_precip', 0)}mm、最大风 {s.get('max_wind', 0)}m/s"
                for s in segs
            )
            fact_lines.append("分时段： " + seg_text + "。")
        nwp_coupling = nwp.get("coupling", [])
        if nwp_coupling:
            fact_lines.append("多要素耦合： " + "；".join(nwp_coupling) + "。")
        alerts = nwp.get("alerts", [])
        if alerts:
            al_text = "；".join(f"{a['type']}{a['level']}（依据：{a['basis']}）" for a in alerts)
            fact_lines.append("国标等级初步判定（仅供参考）： " + al_text + "。")
        sections.append("【数值预报事实数据】\n" + "\n".join(fact_lines))

    sections.append("请直接输出报告正文（不要重复系统指令，也不要重复上述事实数据原文，应转化为连贯的自然语言解读）。")
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
