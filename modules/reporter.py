"""报告导出入口：专业版 / 通俗版 Word 与数据 CSV。

批次 4 把排版工具、专业版与通俗版正文拆到 modules/report/，本文件只保留
导出入口与 Streamlit 渲染。对外名称继续 re-export，避免调用方改动。
"""

from io import BytesIO
from datetime import datetime
import traceback

import streamlit as st

from config import get_debug_mode

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
                       plain_language=False, life_indices=None, analysis_notes=None):
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

    if analysis_notes:
        doc.add_heading("观测分析范围与数据限制", level=1)
        for note in analysis_notes:
            doc.add_paragraph(str(note))
        doc.add_paragraph("未检出事件不等于所有风险均已排除；缺字段或时间覆盖不足的项目无法判定。")
    buf = BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


def render_export_tab(df, warnings_list, score, source=""):
    from modules.analysis_service import ensure_analysis, analysis_key
    from modules.nwp.calc import _analyze_forecast
    from modules.report.preview import preview_html
    from modules.ui.shell import page_heading
    from utils import df_fingerprint
    page_heading("报告导出", "选择报告风格，核对内容，再下载文档与数据。")
    assessment = ensure_analysis(st.session_state, df)
    warnings_list, score = assessment["warnings"], assessment["score"]
    fc_df = st.session_state.get("fc_df")
    has_obs = df is not None and not df.empty
    has_fc = fc_df is not None and not fc_df.empty
    if not has_obs and not has_fc:
        st.info("导入观测数据或获取数值预报后，即可生成分析报告。")
        return
    options, preview = st.columns([1, 2.6])
    with options, st.container(border=True, key="report_options_panel"):
        st.markdown("#### 导出设置")
        if "report_style" not in st.session_state:
            st.session_state["report_style"] = st.session_state.get("report_style_saved", "📊 专业版")
        report_style = st.radio("报告风格", ["📊 专业版", "💬 通俗版"],
                                format_func=lambda value: value.split(" ", 1)[-1], key="report_style",
                                on_change=lambda: st.session_state.update(report_style_saved=st.session_state["report_style"]))
        plain = report_style == "💬 通俗版"
        st.caption("用日常语言解释天气特点与注意事项。" if plain else "保留统计、事件检测、预报与技术说明，适合分析留档。")
        st.markdown("**包含的数据**")
        if has_obs:
            st.caption(f"观测数据 {len(df):,} 条 · {source or '当前数据集'}")
            if "timestamp" in df:
                st.caption(f"{df['timestamp'].min()} 至 {df['timestamp'].max()}")
        if has_fc:
            result = st.session_state.get("fc_result_context") or {}
            city = result.get("city", {}).get("name", "当前预报")
            st.caption(f"{city} · 预报数据 {len(fc_df):,} 条")
        if assessment["notes"]:
            st.info("报告包含观测分析范围与数据限制说明。")
        st.caption("本报告采用文本与表格；图表请在可视化页面导出。AI 读图报告在 AI 模块单独下载并包含原图。")
        fc_analysis = _analyze_forecast(fc_df) if has_fc else None
        # 内容模板更新后使已有会话中的预览和下载一并失效。
        report_key = ("report-content-20261028-2", analysis_key(df), df_fingerprint(fc_df), source, report_style,
                      repr(st.session_state.get("life_indices")), repr(warnings_list), score, repr(assessment["notes"]))
        if st.session_state.get("_report_fp") != report_key:
            st.session_state.pop("report_data", None)
        if st.session_state.get("_report_preview_fp") != report_key:
            st.session_state.pop("_report_preview_bytes", None)
            try:
                prepared = export_report_word(df, warnings_list, score, source,
                    forecast_df=fc_df, forecast_analysis=fc_analysis, plain_language=plain,
                    life_indices=st.session_state.get("life_indices"), analysis_notes=assessment["notes"])
                if prepared:
                    st.session_state["_report_preview_bytes"] = prepared
                    st.session_state["_report_preview_fp"] = report_key
            except Exception as exc:
                st.error(f"内容预览生成失败：{str(exc)[:180]}")
                if get_debug_mode():
                    st.code(traceback.format_exc(), language="python")
        prepared = st.session_state.get("_report_preview_bytes")
        if st.button("生成 Word 文件", icon=":material/description:", type="primary", width="stretch", key="gen_report", disabled=not prepared):
            st.session_state["report_data"] = prepared
            st.session_state["_report_fp"] = report_key
        if st.session_state.get("report_data"):
            st.download_button("下载 Word 报告", st.session_state["report_data"], file_name="气象分析报告.docx",
                               mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                               width="stretch", key="report_word_download")
            st.caption("文档已就绪，与右侧预览使用同一份内容。")
        st.divider()
        st.markdown("**数据文件**")
        if has_obs:
            st.download_button("处理后观测 CSV", export_data_csv(df), file_name="气象观测数据.csv", mime="text/csv",
                               width="stretch", key="report_obs_csv")
        if has_fc:
            st.download_button("逐时预报 CSV", export_data_csv(fc_df), file_name="气象预报数据.csv", mime="text/csv",
                               width="stretch", key="report_fc_csv")
    with preview:
        st.markdown("#### 报告内容预览")
        st.caption("内容与下载文档同步；字体换行、目录域与最终分页以 Word 中的显示为准。")
        if prepared:
            with st.container(height=700, border=True):
                st.markdown(preview_html(prepared), unsafe_allow_html=True)
