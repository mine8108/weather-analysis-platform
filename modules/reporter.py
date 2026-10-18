"""报告导出入口：专业版 / 通俗版 Word 与数据 CSV。

批次 4 把排版工具、专业版与通俗版正文拆到 modules/report/，本文件只保留
导出入口与 Streamlit 渲染。对外名称继续 re-export，避免调用方改动。
"""

from io import BytesIO
from datetime import datetime
import traceback

import streamlit as st

from modules.report.base import (  # noqa: F401
    Cm, export_data_csv, _add_page_break, _add_table, _build_cover_meta,
    _build_cover_table, _build_toc, _compute_report_title, _number,
    _resolve_field, _resolve_stats, _sanitize_cell_for_csv,
    _set_default_styles,
)
from modules.report.plain import _build_plain_report  # noqa: F401
from modules.report.professional import _build_professional_report  # noqa: F401


def export_report_word(df, warnings_list, score, source="",
                       forecast_df=None, forecast_analysis=None,
                       plain_language=False, life_indices=None):
    """生成 Word 分析报告主入口。

    自动根据数据可用性选择章节，字段名自适应。
    plain_language=True 时输出叙述式通俗版，否则输出完整专业版。
    """
    try:
        from docx import Document
    except ImportError:
        st.error("python-docx 未安装，无法导出 Word 报告")
        return None

    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(2.0)
        section.bottom_margin = Cm(2.0)
        section.left_margin = Cm(2.5)
        section.right_margin = Cm(2.0)
    _set_default_styles(doc)

    if plain_language:
        _build_plain_report(doc, df, forecast_df, forecast_analysis,
                            life_indices, warnings_list, source)
    else:
        _build_professional_report(doc, df, forecast_df, forecast_analysis,
                                    life_indices, warnings_list, score, source)

    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


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
    st.write("#### [文档] Word 分析报告 (含统计 + 预报)")

    report_style = st.radio("报告风格", ["📊 专业版", "💬 通俗版"],
                            horizontal=True, key="report_style")
    if report_style == "💬 通俗版":
        st.caption("用生活化语言叙述数据，减少术语，适合非专业用户阅读。"
                   "包含「这天气怎么样」一句话回答、问答式预警、出门穿衣指南等。")
    else:
        st.caption("完整章节结构：封面 + 目录 + 报告说明 + 观测统计 + 预报概况 "
                   "+ 事件检测 + 生活指南 + 防御建议 + 技术说明。报告以表格化排版"
                   "呈现（不含图片），交互式图表请回应用界面查看。")

    fc_analysis = st.session_state.get("fc_analysis", None)

    btn_label = ("[生成] 生成通俗版叙述报告"
                 if report_style == "💬 通俗版"
                 else "[生成] 生成专业版表格报告")
    if st.button(btn_label, use_container_width=True, key="gen_report"):
        with st.spinner("正在生成图文报告..."):
            try:
                doc_data = export_report_word(
                    df, warnings_list, score, source,
                    forecast_df=st.session_state.get("fc_df"),
                    forecast_analysis=fc_analysis,
                    plain_language=(report_style == "💬 通俗版"),
                    life_indices=st.session_state.get("life_indices"),
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

    # ---- 统计摘要 ----
    if df is not None and not df.empty:
        stats_fields = ["temperature", "pressure", "humidity",
                        "wind_speed", "visibility", "precipitation"]
        label_map = {"temperature": "气温", "pressure": "气压", "humidity": "湿度",
                     "wind_speed": "风速", "visibility": "能见度",
                     "precipitation": "降水量"}
        resolved = _resolve_stats(df, stats_fields)
        if resolved:
            st.write("---")
            st.write("#### [列表] 快速统计摘要")
            cols = st.columns(min(len(resolved), 6))
            for i, f in enumerate(stats_fields):
                if f in resolved:
                    with cols[i % len(cols)]:
                        st.metric(label_map.get(f, f), f"{resolved[f].mean():.1f}")
