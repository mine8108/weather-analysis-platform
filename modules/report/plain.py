"""通俗版 Word 报告：叙述式结论、生活语言与问答式结构。

从 reporter.py 拆出（批次 4）。
"""

from datetime import datetime

from config import AGRI_ADVICE, LIFE_INDEX_META, WARN_LEVEL_ORDER
from modules.report.base import (
    Pt, RGBColor, WD_ALIGN_PARAGRAPH, _TITLE_COLOR,
    _build_cover_table, _compute_report_title, _resolve_field,
)


_PLAIN_TYPE_DESC = {
    "高温": "天气会很热，可能会让人中暑、心情烦躁，要多喝水、避免长时间在太阳下暴晒。",
    "寒潮": "天气会突然变得很冷，温度下降得很快，注意添衣保暖、老人小孩尽量减少外出。",
    "大风": "风会很大，可能会吹倒东西、广告牌脱落，骑车走路都要小心，避免在广告牌下停留。",
    "暴雨": "雨会下得很大，可能会有积水、低洼处可能内涝，尽量避免外出，如必须外出注意安全。",
    "大雾": "能见度很低，开车要特别小心、要开雾灯、保持车距，走路也要注意车辆。",
    "霜冻": "夜里温度会降到零度以下，会结冰，注意水管防冻、作物防寒。",
    "冰雹": "天会下冰球，会砸坏车玻璃、屋顶、庄稼，尽快到室内躲避，远离窗户。",
    "雷电": "会有打雷闪电，避免在空旷地或树下躲雨，远离金属物品，关闭电器电源。",
    "暴雪": "雪会下得很大，路上会积雪结冰，少开车、必要外出穿防滑鞋。",
    "霾": "空气会比较脏，敏感人群戴 N95 口罩，减少户外运动。",
    "道路结冰": "路面会结冰，走路开车都容易打滑，谨慎慢行。",
    "干旱": "长时间没下雨，水源紧张，注意节约用水，农作物可能需要灌溉。",
    "台风": "热带气旋会带来狂风暴雨，可能造成严重破坏，密切关注、做好防风准备。",
}


def _plain_event_text(warn):
    """生成单个预警的通俗描述（含数据支撑）"""
    base = _PLAIN_TYPE_DESC.get(warn["type"], "")
    if not base:
        base = f"会有{warn['type']}情况，请关注具体影响。"
    support = warn.get("detail", "")
    if support:
        return f"{base}\n    数据说：{support[:80]}"
    return base


def _build_plain_report(doc, df, fc_df, fc_analysis, life_indices,
                        warnings_list, source):
    """通俗版：叙述式 + 生活语言 + 问答式"""
    has_obs = df is not None and not df.empty
    has_fc = fc_df is not None or fc_analysis is not None
    has_warnings = bool(warnings_list)

    # ---- 封面 ----
    title_text = _compute_report_title(has_obs, has_fc) + "（通俗版）"
    title = doc.add_heading(title_text, level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cover_rows = [
        ("生成时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    ]
    if source:
        cover_rows.append(("数据来源", source))
    if has_obs:
        ts_col = _resolve_field(df, "timestamp")
        if ts_col and len(df) > 0:
            try:
                cover_rows.append(
                    ("数据时段",
                     f"{df[ts_col].min()} 至 {df[ts_col].max()}"))
            except Exception:
                pass
        cover_rows.append(("数据量", f"{len(df)} 条记录"))
    _build_cover_table(doc, cover_rows)

    # ---- 摘要：回答"这天气怎么样" ----
    doc.add_heading("一句话回答：这天气怎么样？", level=1)
    one_liner = _build_one_liner(df, fc_df, fc_analysis)
    if one_liner:
        p = doc.add_paragraph()
        run = p.add_run(one_liner)
        run.bold = True
        run.font.size = Pt(13)

    # ---- 一、这几天天气会怎么变？ ----
    if has_fc:
        doc.add_heading("一、这几天天气会怎么变？", level=1)
        _render_plain_forecast(doc, fc_df, fc_analysis)

    # ---- 二、要小心什么？ ----
    if has_warnings or (has_fc and fc_analysis and fc_analysis.get("warnings")):
        doc.add_heading("二、要小心什么？", level=1)
        # 优先用观测期检测到的预警，更贴近用户实际
        all_warnings = []
        if has_warnings:
            all_warnings.extend(warnings_list)
        if has_fc and fc_analysis:
            for w in fc_analysis.get("warnings", []):
                all_warnings.append(w)
        _render_plain_warnings(doc, all_warnings)

    # ---- 三、出门穿什么？要不要带伞？ ----
    if life_indices:
        doc.add_heading("三、出门穿什么？要不要带伞？", level=1)
        _render_plain_life_indices(doc, life_indices)

    # ---- 四、给种地朋友的建议 ----
    if has_warnings:
        doc.add_heading("四、给种地朋友的建议", level=1)
        _render_plain_agri_advice(doc, warnings_list)

    # ---- 五、如果你想知道更多 ----
    doc.add_heading("五、如果你想知道更多", level=1)
    doc.add_paragraph(
        "这份报告的「专业版」里有更详细的数据：每小时的温度、湿度、风速、"
        "降水等具体数字，以及气象专业的统计指标和判断标准。如果你是从事气象、"
        "农业、能源、保险等相关工作的朋友，可以切换到专业版查看。"
    )
    doc.add_paragraph(
        "如果对某个数据有疑问，比如「为什么这次报的气温和上次不一样」「这条建议"
        "是怎么算出来的」，可以参考专业版的「技术说明」一节。"
    )
    p = doc.add_paragraph()
    run = p.add_run("💡 提示：")
    run.bold = True
    run.font.color.rgb = RGBColor.from_string(_TITLE_COLOR)
    p.add_run("本报告基于 Open-Meteo GFS 数值预报自动生成，"
              "如有重要决策建议，请同时参考国家气象部门权威预报。")


def _build_one_liner(df, fc_df, fc_analysis):
    """生成一句话总览"""
    parts = []
    if fc_analysis:
        summary = fc_analysis.get("summary", "")
        if summary:
            parts.append(summary)
        # 极值
        ex = fc_analysis.get("extremes", {})
        if ex:
            t_max = ex.get("max_temp", (None, ""))
            t_min = ex.get("min_temp", (None, ""))
            if t_max[0] is not None and t_min[0] is not None:
                if t_max[0] - t_min[0] > 15:
                    parts.append(
                        f"未来温差较大（{t_min[0]:.0f}℃ 到 {t_max[0]:.0f}℃），"
                        "要注意衣物调整。")
                elif t_max[0] >= 35:
                    parts.append("未来会很热，注意防暑。")
                elif t_min[0] <= 0:
                    parts.append("未来会比较冷，注意保暖。")
                else:
                    parts.append("未来气温总体适宜。")
        fw = fc_analysis.get("warnings", [])
        if fw:
            types = sorted({w["type"] for w in fw})
            parts.append(f"未来需要关注 {', '.join(types)} 等天气。")
    if df is not None and not df.empty:
        temp_col = _resolve_field(df, "temperature")
        if temp_col:
            t = df[temp_col].dropna()
            if len(t) > 0:
                avg = t.mean()
                parts.append(
                    f"近期历史平均温度约 {avg:.0f}℃。"
                    + (" 偏热。" if avg > 25 else " 适中。" if avg > 10 else " 偏冷。"))
    return " ".join(parts) if parts else "暂无足够数据生成总览。"


def _render_plain_forecast(doc, fc_df, fc_analysis):
    """通俗版 - 预报概况叙述式"""
    if not fc_analysis:
        doc.add_paragraph("暂无预报分析数据。")
        return

    summary = fc_analysis.get("summary", "")
    if summary:
        doc.add_paragraph(f"【总述】{summary}")

    ex = fc_analysis.get("extremes", {})
    if ex:
        t_max = ex.get("max_temp", (None, ""))
        t_min = ex.get("min_temp", (None, ""))
        if t_max[0] is not None:
            feeling = ""
            if t_max[0] >= 35:
                feeling = "（很热）"
            elif t_max[0] >= 30:
                feeling = "（偏热）"
            elif t_max[0] >= 25:
                feeling = "（暖和）"
            doc.add_paragraph(
                f"【温度】最热的一天：{t_max[1]} 达 {t_max[0]:.0f}℃{feeling}；"
                f"最冷的一天：{t_min[1]} 降到 {t_min[0]:.0f}℃。")
        max_wind = ex.get("max_wind", (None, ""))
        if max_wind[0] is not None and max_wind[0] >= 8:
            doc.add_paragraph(
                f"【风】最大风速出现在 {max_wind[1]}，达 {max_wind[0]:.1f} m/s，"
                "户外作业要小心。")
        total_p = ex.get("total_precip", 0)
        if total_p > 50:
            doc.add_paragraph(
                f"【降水】预报期累计降水 {total_p:.0f} mm，雨量较大，"
                "出门一定要带伞，注意防范积水。")
        elif total_p > 10:
            doc.add_paragraph(
                f"【降水】预报期累计降水 {total_p:.0f} mm，"
                "有一定雨量，建议常备雨具。")
        elif total_p > 0:
            doc.add_paragraph(
                f"【降水】预报期累计降水 {total_p:.0f} mm，雨量不大。")
        else:
            doc.add_paragraph("【降水】预报期内基本无有效降水。")

    prec = fc_analysis.get("precision", {})
    if prec:
        hot = prec.get("consecutive_hot", 0)
        if hot >= 3:
            doc.add_paragraph(
                f"【高温持续】连续 {hot} 天日最高气温 ≥ 35℃，"
                "持续高温对身体负担较大，老人小孩尤其注意。")

    coupling = fc_analysis.get("coupling", [])
    if coupling:
        doc.add_paragraph("【特别提示】")
        for c in coupling:
            doc.add_paragraph(f"  • {c['type']}（{c['severity']}）：{c['detail']}",
                              style="List Bullet")


def _render_plain_warnings(doc, all_warnings):
    """通俗版 - 预警信号问答式"""
    if not all_warnings:
        doc.add_paragraph("目前没有触发预警信号，可以放心安排活动。")
        return

    # 按等级排序
    from config import WARN_LEVEL_ORDER
    sorted_w = sorted(all_warnings,
                      key=lambda w: WARN_LEVEL_ORDER.get(w["level"], 4))

    level_intro = {
        "红色": "🔴 红色预警（特别严重）——请立即采取行动，避免不必要外出：",
        "橙色": "🟠 橙色预警（严重）——尽量避免相关活动，做好防护：",
        "黄色": "🟡 黄色预警（较重）——有所准备，减少不必要外出：",
        "蓝色": "🔵 蓝色预警（一般）——关注即可，正常生活工作：",
    }
    for warn in sorted_w:
        intro = level_intro.get(warn["level"], "")
        if intro:
            p = doc.add_paragraph()
            run = p.add_run(intro)
            run.bold = True
        text = _plain_event_text(warn)
        doc.add_paragraph(text)


def _render_plain_life_indices(doc, life_indices):
    """通俗版 - 生活指南叙述化"""
    from config import LIFE_INDEX_META
    order = ["clothing", "umbrella", "comfort", "exercise",
             "uv", "carwash", "drying"]
    guides = {
        "clothing": "出门穿什么？",
        "umbrella": "要不要带伞？",
        "comfort": "体感舒服吗？",
        "exercise": "能不能户外运动？",
        "uv": "紫外线强不强？",
        "carwash": "今天能洗车吗？",
        "drying": "适合晾晒衣物吗？",
    }
    for key in order:
        if key in life_indices:
            info = life_indices[key]
            icon, name = LIFE_INDEX_META.get(key, ("", key))
            question = guides.get(key, name)
            p = doc.add_paragraph()
            run = p.add_run(f"  【{question}】")
            run.bold = True
            doc.add_paragraph(
                f"      {icon} {name}：{info.get('level', '')} — {info.get('advice', '')}")


def _render_plain_agri_advice(doc, warnings_list):
    """通俗版 - 农业建议通俗化"""
    from config import AGRI_ADVICE
    agri_rows = []
    for warn in warnings_list:
        if (warn["type"] in AGRI_ADVICE
                and warn["level"] in AGRI_ADVICE[warn["type"]]):
            agri_rows.append((warn, AGRI_ADVICE[warn["type"]][warn["level"]]))
    if not agri_rows:
        doc.add_paragraph("近期天气对农业生产没有特别不利的影响，可以按计划安排农事。")
        return
    for warn, text in agri_rows:
        p = doc.add_paragraph()
        run = p.add_run(f"  【{warn['type']}{warn['level']}】")
        run.bold = True
        doc.add_paragraph(f"      {text}")
        if warn.get("detail"):
            doc.add_paragraph(
                f"      （数据支撑：{warn['detail'][:60]}）")
