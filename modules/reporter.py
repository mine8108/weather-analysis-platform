"""
报告导出模块：图表 PNG 导出、分析报告 Word、数据 CSV 导出
"""

import pandas as pd
import streamlit as st
from io import BytesIO
from datetime import datetime


def export_chart_as_png(fig, filename="chart.png"):
    """导出 Plotly 图为 PNG"""
    if fig is None:
        return None
    try:
        img_bytes = fig.to_image(format="png", scale=2, width=1200, height=800)
        return img_bytes
    except Exception as e:
        st.error(f"导出图片失败: {e}")
        return None


def export_data_csv(df):
    """导出数据为 CSV"""
    if df is None or df.empty:
        return None
    csv = df.to_csv(index=False, encoding="utf-8-sig")
    return csv.encode("utf-8-sig")


def export_report_word(df, warnings_list, score, source=""):
    """导出分析报告为 Word 文档"""
    try:
        from docx import Document
        from docx.shared import Inches, Pt, Cm, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.enum.table import WD_TABLE_ALIGNMENT
    except ImportError:
        st.error("python-docx 未安装，无法导出 Word 报告")
        return None

    doc = Document()

    # 页面设置
    for section in doc.sections:
        section.top_margin = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.left_margin = Cm(2.5)
        section.right_margin = Cm(2.0)

    # 标题
    title = doc.add_heading("气象数据分析报告", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # 基本信息
    doc.add_paragraph(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if source:
        doc.add_paragraph(f"数据来源：{source}")
    if df is not None:
        doc.add_paragraph(f"数据记录数：{len(df)}")
        doc.add_paragraph(f"数据质量评分：{score}/100")

    doc.add_paragraph("")

    # 预警信号
    if warnings_list:
        doc.add_heading("一、预警信号", level=1)
        for warn in warnings_list:
            p = doc.add_paragraph()
            run = p.add_run(f"[{warn['level']}预警] {warn['type']} - {warn['detail']}")
            run.font.size = Pt(12)
            # 按级别设置颜色
            color_map = {
                "蓝色": RGBColor(0, 102, 204),
                "黄色": RGBColor(245, 166, 35),
                "橙色": RGBColor(242, 101, 34),
                "红色": RGBColor(208, 2, 27),
            }
            run.font.color.rgb = color_map.get(warn["level"], RGBColor(0, 0, 0))
    else:
        doc.add_heading("一、预警信号", level=1)
        doc.add_paragraph("未触发任何预警信号。")

    # 数据统计
    if df is not None:
        doc.add_heading("二、数据统计摘要", level=1)

        stats_fields = ["temperature", "pressure", "humidity", "wind_speed", "visibility", "precipitation"]
        labels = {"temperature": "气温 (℃)", "pressure": "气压 (hPa)", "humidity": "湿度 (%)",
                  "wind_speed": "风速 (m/s)", "visibility": "能见度 (km)", "precipitation": "降水量 (mm)"}

        for field in stats_fields:
            if field in df.columns and not df[field].dropna().empty:
                series = df[field].dropna()
                doc.add_paragraph(
                    f"{labels.get(field, field)}: "
                    f"均值={series.mean():.2f}, "
                    f"最小={series.min():.2f}, "
                    f"最大={series.max():.2f}, "
                    f"标准差={series.std():.2f}"
                )

    # 防御建议
    doc.add_heading("三、防御建议", level=1)

    from config import PUBLIC_ADVICE, AGRI_ADVICE

    if warnings_list:
        doc.add_heading("公众出行", level=2)
        for warn in warnings_list:
            if warn["type"] in PUBLIC_ADVICE and warn["level"] in PUBLIC_ADVICE[warn["type"]]:
                doc.add_paragraph(
                    f"【{warn['type']}{warn['level']}预警】{PUBLIC_ADVICE[warn['type']][warn['level']]}",
                    style="List Bullet"
                )

        doc.add_heading("农业生产", level=2)
        for warn in warnings_list:
            if warn["type"] in AGRI_ADVICE and warn["level"] in AGRI_ADVICE[warn["type"]]:
                doc.add_paragraph(
                    f"【{warn['type']}{warn['level']}预警】{AGRI_ADVICE[warn['type']][warn['level']]}",
                    style="List Bullet"
                )
    else:
        doc.add_paragraph("当前无特殊预警，可正常开展活动。")

    # 保存
    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


def render_export_tab(df, warnings_list, score, source=""):
    """渲染报告导出 Tab"""
    st.subheader("[导出] 报告导出")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.write("#### [统计] 数据导出")
        if df is not None and not df.empty:
            csv_data = export_data_csv(df)
            if csv_data:
                st.download_button(
                    label="⬇️ 导出处理后的数据 (CSV)",
                    data=csv_data,
                    file_name=f"气象数据_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            else:
                st.info("无法导出数据")

    with col2:
        st.write("#### [文档] 分析报告")
        if st.button("[笔记] 生成 Word 分析报告", use_container_width=True):
            with st.spinner("正在生成报告..."):
                doc_data = export_report_word(df, warnings_list, score, source)
                if doc_data:
                    st.session_state["report_data"] = doc_data
                    st.rerun()

        if "report_data" in st.session_state:
            st.download_button(
                label="⬇️ 下载分析报告 (Word)",
                data=st.session_state["report_data"],
                file_name=f"气象分析报告_{datetime.now().strftime('%Y%m%d_%H%M')}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
            )

    with col3:
        st.write("#### [列表] 统计摘要")
        stats_fields = ["temperature", "pressure", "humidity", "wind_speed", "visibility", "precipitation"]
        if df is not None and not df.empty:
            for f in stats_fields:
                if f in df.columns:
                    s = df[f].dropna()
                    if len(s) > 0:
                        st.metric(
                            {"temperature": "气温", "pressure": "气压", "humidity": "湿度",
                             "wind_speed": "风速", "visibility": "能见度", "precipitation": "降水量"}.get(f, f),
                            f"{s.mean():.1f}",
                        )
