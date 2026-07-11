"""
报告导出模块：图表 PNG 导出、增强 Word 分析报告、数据 CSV 导出
"""

import pandas as pd
import numpy as np
import streamlit as st
import plotly.graph_objects as go
from io import BytesIO
from datetime import datetime
import traceback

# 报告用：字段名别名映射（预报字段 → 标准字段）
_FIELD_ALIAS_REPORT = {
    "temperature_2m": "temperature",
    "relative_humidity_2m": "humidity",
    "surface_pressure": "pressure",
    "wind_speed_10m": "wind_speed",
    "precipitation_sum": "precipitation",
    "precipitation_hours": "precipitation",
}


def _resolve_field(df, field):
    """按别名解析字段，返回实际列名或 None"""
    if field in df.columns:
        return field
    for alias, target in _FIELD_ALIAS_REPORT.items():
        if target == field and alias in df.columns:
            return alias
    return None


def export_chart_as_png(fig, filename="chart.png"):
    """导出 Plotly 图为 PNG 字节流"""
    if fig is None:
        return None
    try:
        return fig.to_image(format="png", scale=2, width=1200, height=800)
    except Exception:
        return None


def export_data_csv(df):
    """导出数据为 CSV 字节流"""
    if df is None or df.empty:
        return None
    return df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")


# ---- 报告用图表生成 ----
def _generate_report_charts(df):
    """从数据生成一组常规分析图表，供 Word 报告嵌入和 PNG 独立下载。"""
    figs = {}
    if df is None or df.empty:
        return figs
    try:
        x = df["timestamp"] if "timestamp" in df.columns else df.index
        # 气温 — 支持标准字段和预报字段
        temp_col = _resolve_field(df, "temperature")
        if temp_col and df[temp_col].dropna().size > 0:
            figs["temperature"] = go.Figure(go.Scatter(
                x=x, y=df[temp_col], mode="lines", name="气温",
                line=dict(color="#e74c3c", width=2),
            ))
            figs["temperature"].update_layout(title="气温时序图", height=320,
                                               margin=dict(l=40, r=20, t=40, b=40))
        # 降水
        prec_col = _resolve_field(df, "precipitation")
        if prec_col and df[prec_col].dropna().size > 0:
            daily = df.copy()
            if "timestamp" in df.columns:
                daily["date"] = daily["timestamp"].dt.date
                daily_p = daily.groupby("date")[prec_col].sum()
            else:
                daily_p = df[prec_col]
            figs["precipitation"] = go.Figure(go.Bar(
                x=[str(d) for d in daily_p.index], y=daily_p.values,
                marker_color="#2980b9", name="降水",
            ))
            figs["precipitation"].update_layout(title="逐日降水量", height=320,
                                                 margin=dict(l=40, r=20, t=40, b=40))
        # 气压
        pres_col = _resolve_field(df, "pressure")
        if pres_col and df[pres_col].dropna().size > 0:
            figs["pressure"] = go.Figure(go.Scatter(
                x=x, y=df[pres_col], mode="lines", name="气压",
                line=dict(color="#27ae60", width=2),
            ))
            figs["pressure"].update_layout(title="气压时序图", height=320,
                                            margin=dict(l=40, r=20, t=40, b=40))
        # 风速
        wind_col = _resolve_field(df, "wind_speed")
        if wind_col and df[wind_col].dropna().size > 0:
            figs["wind_speed"] = go.Figure(go.Scatter(
                x=x, y=df[wind_col], mode="lines", name="风速",
                line=dict(color="#8e44ad", width=2),
            ))
            figs["wind_speed"].update_layout(title="风速时序图", height=320,
                                              margin=dict(l=40, r=20, t=40, b=40))
    except Exception:
        pass
    return figs


def _resolve_stats(df, stats_fields):
    """解析统计字段（支持别名），返回实际可统计的 field_name 列表"""
    result = {}
    for f in stats_fields:
        actual = _resolve_field(df, f)
        if actual and not df[actual].dropna().empty:
            result[f] = df[actual].dropna()
    return result


def export_report_word(df, warnings_list, score, source="",
                       forecast_df=None, forecast_analysis=None, plain_language=False):
    """生成 Word 分析报告（含嵌入图表、预报摘要）。自动隐藏空节，字段名自适应。"""
    try:
        from docx import Document
        from docx.shared import Inches, Pt, Cm, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH
    except ImportError:
        st.error("python-docx 未安装，无法导出 Word 报告")
        return None

    has_obs = df is not None and not df.empty
    has_fc = forecast_df is not None or forecast_analysis is not None
    has_warnings = bool(warnings_list)

    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.left_margin = Cm(2.5)
        section.right_margin = Cm(2.0)

    # ---- 封面（动态标题） ----
    if has_obs and has_fc:
        report_title = "气象数据与预报分析报告"
    elif has_fc:
        report_title = "数值预报分析报告"
    else:
        report_title = "气象数据分析报告"

    title = doc.add_heading(report_title, level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if source:
        doc.add_paragraph(f"数据来源：{source}")
    if has_obs:
        doc.add_paragraph(f"观测记录数：{len(df)}")
        doc.add_paragraph(f"数据质量评分：{score}/100")
    doc.add_paragraph("")

    section_num = 0

    # ---- 一、事件检测（仅当有历史数据时） ----
    if has_obs and has_warnings:
        section_num += 1
        doc.add_heading(f"{_number(section_num)}、事件检测", level=1)
        color_map = {
            "蓝色": RGBColor(0, 102, 204),
            "黄色": RGBColor(245, 166, 35),
            "橙色": RGBColor(242, 101, 34),
            "红色": RGBColor(208, 2, 27),
        }
        for warn in warnings_list:
            p = doc.add_paragraph()
            if plain_language:
                plain_text = {
                    "高温": "天气会很热，可能会让人中暑，注意防暑降温、多喝水。",
                    "寒潮": "天气会突然变得很冷，注意添衣保暖、减少外出。",
                    "大风": "风会很大，可能会吹倒东西，在外面走路要小心。",
                    "暴雨": "雨会很大，可能会有积水，尽量避免外出。",
                    "大雾": "能见度很低，开车要特别小心、开雾灯。",
                }
                hint = plain_text.get(warn["type"], warn["detail"])
                run = p.add_run(f"[{warn['level']}事件] {warn['type']} — {hint}")
            else:
                run = p.add_run(f"[{warn['level']}事件] {warn['type']} - {warn['detail']}")
            run.font.size = Pt(12)
            if warn["level"] in color_map:
                run.font.color.rgb = color_map[warn["level"]]

    # ---- 二、数据统计摘要 ----
    if has_obs:
        stats_fields = ["temperature", "pressure", "humidity", "wind_speed", "visibility", "precipitation"]
        labels = {
            "temperature": "气温 (C)", "pressure": "气压 (hPa)", "humidity": "湿度 (%)",
            "wind_speed": "风速 (m/s)", "visibility": "能见度 (km)", "precipitation": "降水量 (mm)",
        }
        resolved = _resolve_stats(df, stats_fields)
        if resolved:
            section_num += 1
            doc.add_heading(f"{_number(section_num)}、数据统计摘要", level=1)
            for field in stats_fields:
                if field in resolved:
                    s = resolved[field]
                    doc.add_paragraph(
                        f"{labels.get(field, field)}: "
                        f"均值={s.mean():.2f}, 最小={s.min():.2f}, "
                        f"最大={s.max():.2f}, 标准差={s.std():.2f}"
                    )

    # ---- 三、可视化图表 ----
    if has_obs:
        chart_figs = _generate_report_charts(df)
        if chart_figs:
            section_num += 1
            doc.add_heading(f"{_number(section_num)}、可视化图表", level=1)
            captions = {
                "temperature": "气温时序变化", "precipitation": "逐日降水量分布",
                "pressure": "气压时序变化", "wind_speed": "风速时序变化",
            }
            for name, fig in chart_figs.items():
                png_data = export_chart_as_png(fig)
                if png_data:
                    try:
                        doc.add_picture(BytesIO(png_data), width=Inches(5.5))
                        last_paragraph = doc.paragraphs[-1]
                        last_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        cap = doc.add_paragraph(f"图：{captions.get(name, name)}")
                        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        cap.runs[0].font.size = Pt(10)
                        cap.runs[0].font.color.rgb = RGBColor(120, 120, 120)
                    except Exception:
                        pass
                else:
                    doc.add_paragraph(f"（图表「{captions.get(name, name)}」因缺少 kaleido 包无法嵌入，请在部署环境安装 kaleido）")

    # ---- 四、数值预报 + 建议（合并为单节） ----
    if has_fc and forecast_analysis:
        section_num += 1
        doc.add_heading(f"{_number(section_num)}、数值预报与建议", level=1)
        doc.add_paragraph(f"总述：{forecast_analysis.get('summary', '')}")

        ex = forecast_analysis.get("extremes", {})
        if ex:
            t_max = ex.get("max_temp", (0, ""))
            t_min = ex.get("min_temp", (0, ""))
            doc.add_paragraph(
                f"预报期极值：最高气温 {t_max[0]:.0f}C ({t_max[1]}), "
                f"最低气温 {t_min[0]:.0f}C ({t_min[1]}), "
                f"累计降水 {ex.get('total_precip', 0):.0f} mm, "
                f"最大风速 {ex.get('max_wind', (0, ''))[0]:.1f} m/s"
            )

        fw = forecast_analysis.get("warnings", [])
        if fw:
            doc.add_paragraph("预报预警信号：")
            for w in fw:
                doc.add_paragraph(f"- [{w['level']}] {w['type']}: {w['detail']}", style="List Bullet")

        recs = forecast_analysis.get("recommendations", {})
        if recs:
            travel = recs.get("travel", [])
            agri = recs.get("agri", [])
            if travel:
                doc.add_paragraph("出行建议：")
                for r in travel[:4]:
                    doc.add_paragraph(f"- {r}", style="List Bullet")
            if agri:
                doc.add_paragraph("农业建议：")
                for r in agri[:4]:
                    doc.add_paragraph(f"- {r}", style="List Bullet")

    # ---- 五、防御建议（仅当有历史检测结果时） ----
    if has_obs and has_warnings:
        section_num += 1
        doc.add_heading(f"{_number(section_num)}、防御建议", level=1)
        from config import PUBLIC_ADVICE, AGRI_ADVICE
        doc.add_heading("公众出行", level=2)
        for warn in warnings_list:
            if warn["type"] in PUBLIC_ADVICE and warn["level"] in PUBLIC_ADVICE[warn["type"]]:
                doc.add_paragraph(
                    f"【{warn['type']}{warn['level']}事件】{PUBLIC_ADVICE[warn['type']][warn['level']]}",
                    style="List Bullet",
                )
        doc.add_heading("农业生产", level=2)
        for warn in warnings_list:
            if warn["type"] in AGRI_ADVICE and warn["level"] in AGRI_ADVICE[warn["type"]]:
                doc.add_paragraph(
                    f"【{warn['type']}{warn['level']}事件】{AGRI_ADVICE[warn['type']][warn['level']]}",
                    style="List Bullet",
                )

    # ---- 无数据友好提示 ----
    if not has_obs and not has_fc:
        doc.add_paragraph("当前没有数据可生成报告。请先导入观测数据或生成数值预报。")

    # ---- 通俗版附录 ----
    if plain_language:
        doc.add_page_break()
        doc.add_heading("附录：一句话总结", level=1)
        doc.add_paragraph("这份报告的通俗版总结，帮您快速了解最重要的信息：")
        if has_obs:
            temp_col = _resolve_field(df, "temperature")
            if temp_col:
                t = df[temp_col].dropna()
                if len(t) > 0:
                    doc.add_paragraph(f"- 温度：平均约 {t.mean():.0f}℃，最高 {t.max():.0f}℃，" +
                        ("偏热，注意防暑" if t.mean() > 25 else "适中，体感舒适" if t.mean() > 10 else "偏冷，注意保暖"))
            prec_col = _resolve_field(df, "precipitation")
            if prec_col:
                p = df[prec_col].dropna()
                if len(p) > 0:
                    total = p.sum()
                    doc.add_paragraph(f"- 降水：累计 {total:.0f}mm，" +
                        ("雨量较大，出行带伞" if total > 10 else "雨量不大" if total > 0 else "基本无降水"))
            if "pm25" in df.columns:
                pm = df["pm25"].dropna()
                if len(pm) > 0:
                    avg_pm = pm.mean()
                    doc.add_paragraph(f"- 空气质量：PM2.5 均值 {avg_pm:.0f}，" +
                        ("良好" if avg_pm <= 35 else "一般，敏感人群注意" if avg_pm <= 50 else "偏差，减少户外活动"))
        doc.add_paragraph("")
        doc.add_paragraph("💡 提示：如需详细数据，请查看报告中的专业图表和统计表格。")

    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


def _number(n):
    """中文数字映射"""
    nums = ["", "一", "二", "三", "四", "五", "六"]
    return nums[n] if n < len(nums) else str(n)


def render_export_tab(df, warnings_list, score, source=""):
    """渲染增强版报告导出 Tab"""
    st.subheader("[导出] 报告导出")

    # ---- 数据导出 ----
    st.write("#### [统计] 数据导出")
    c1, c2, c3 = st.columns(3)
    with c1:
        if df is not None and not df.empty:
            csv_data = export_data_csv(df)
            if csv_data:
                st.download_button(
                    label="[下载] 处理后数据 (CSV)",
                    data=csv_data,
                    file_name=f"气象数据_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
    with c2:
        fc_df = st.session_state.get("fc_df", None)
        if fc_df is not None and not fc_df.empty:
            fc_csv = export_data_csv(fc_df)
            if fc_csv:
                st.download_button(
                    label="[下载] GFS 预报数据 (CSV)",
                    data=fc_csv,
                    file_name=f"GFS预报_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
    with c3:
        pass

    # ---- Word 报告 ----
    st.write("---")
    st.write("#### [文档] Word 分析报告 (含图表 + 统计 + 预报)")

    report_style = st.radio("报告风格", ["📊 专业版", "💬 通俗版"], horizontal=True, key="report_style")
    if report_style == "💬 通俗版":
        st.caption("用生活化语言解释数据，减少术语，适合非专业用户阅读。")
    else:
        st.caption("报告嵌入气温/降水/气压/风速时序图、统计摘要、事件检测及防御建议。如有 GFS 预报数据自动附加预报分析。")

    fc_analysis = st.session_state.get("fc_analysis", None)

    btn_label = "[生成] 生成通俗版分析报告" if report_style == "💬 通俗版" else "[生成] 生成 Word 图文分析报告"
    if st.button(btn_label, use_container_width=True, key="gen_report"):
        with st.spinner("正在生成图文报告..."):
            try:
                doc_data = export_report_word(
                    df, warnings_list, score, source,
                    forecast_df=st.session_state.get("fc_df"),
                    forecast_analysis=fc_analysis,
                    plain_language=(report_style == "💬 通俗版"),
                )
                if doc_data:
                    st.session_state["report_data"] = doc_data
                    st.success("报告已生成，点击下方按钮下载。")
                    st.rerun()
            except Exception as e:
                st.error(f"报告生成失败: {e}")
                if st.session_state.get("debug_mode"):
                    st.code(traceback.format_exc(), language="python")

    if "report_data" in st.session_state:
        st.download_button(
            label="[下载] 下载 Word 分析报告",
            data=st.session_state["report_data"],
            file_name=f"气象分析报告_{datetime.now().strftime('%Y%m%d_%H%M')}.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True,
        )

    # ---- 图表 PNG 下载 ----
    if df is not None and not df.empty:
        st.write("---")
        st.write("#### [图表] 独立图表 PNG 下载")
        chart_figs = _generate_report_charts(df)
        if chart_figs:
            cols = st.columns(len(chart_figs))
            names = {"temperature": "气温时序", "precipitation": "降水分布",
                     "pressure": "气压时序", "wind_speed": "风速时序"}
            for idx, (name, fig) in enumerate(chart_figs.items()):
                png_bytes = export_chart_as_png(fig)
                with cols[idx]:
                    st.caption(names.get(name, name))
                    if png_bytes:
                        st.download_button(
                            label=f"[图片] 下载 PNG",
                            data=png_bytes,
                            file_name=f"{names.get(name, name)}_{datetime.now().strftime('%Y%m%d')}.png",
                            mime="image/png",
                            use_container_width=True,
                        )
                        st.plotly_chart(fig, use_container_width=True, key=f"rpt_chart_{name}")
                    else:
                        st.info("kaleido 未安装，无法导出图片")

    # ---- 统计摘要 ----
    if df is not None and not df.empty:
        stats_fields = ["temperature", "pressure", "humidity", "wind_speed", "visibility", "precipitation"]
        label_map = {"temperature": "气温", "pressure": "气压", "humidity": "湿度",
                     "wind_speed": "风速", "visibility": "能见度", "precipitation": "降水量"}
        resolved = _resolve_stats(df, stats_fields)
        if resolved:
            st.write("---")
            st.write("#### [列表] 快速统计摘要")
            cols = st.columns(min(len(resolved), 6))
            for i, f in enumerate(stats_fields):
                if f in resolved:
                    with cols[i % len(cols)]:
                        st.metric(label_map.get(f, f), f"{resolved[f].mean():.1f}")
