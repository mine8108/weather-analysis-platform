"""Thin data-import page, preserving existing loader and quality contracts."""
import pandas as pd
import streamlit as st
from modules.data_loader import (merge_manual_rows, render_file_upload_section,
    render_manual_input_section, render_api_section, render_template_download)
from modules.data_quality import (render_quality_report, range_check, temporal_consistency_check, completeness_check)
from modules.ui.shell import page_heading
from config import FIELD_LABELS


def render_import_page(safe_render, adopt_dataset, navigate_to, render_summary):
    _safe_render, _adopt_dataset, _navigate_to = safe_render, adopt_dataset, navigate_to
    st.session_state.setdefault("import_step", 0)
    st.session_state.setdefault("import_method", None)
    heading, actions = st.columns([5, 1], vertical_alignment="center")
    with heading:
        page_heading("数据导入", "选择来源，检查质量，再进入分析。支持观测文件、手动记录、在线数据与 ERA5。")
    if actions.button("跳过向导", key="skip_wizard"):
        st.session_state["import_step"] = 999
        st.rerun()
    step = st.session_state["import_step"]
    stage = 0 if step in (0, 1, 999) else min(step - 1, 2)
    labels = ["选择来源", "数据检查", "准备分析"]
    steps_html = ''.join(f'<div class="wb-step {"is-active" if i == stage else "is-done" if i < stage else ""}"><span>{i + 1:02d}</span>{label}</div>' for i, label in enumerate(labels))
    st.markdown(f'<div class="wb-steps">{steps_html}</div>', unsafe_allow_html=True)
    if step == 3:
        render_summary()
        left, right = st.columns(2)
        if left.button("前往可视化分析", key="import_complete_analysis", type="primary", width="stretch"):
            _navigate_to(1)
        if right.button("导入其他数据", key="import_complete_new", width="stretch"):
            st.session_state["import_step"] = 0
            st.rerun()
        return
    step = st.session_state["import_step"]

    # ===== 向导模式 =====
    if step == 0:
        st.write("### 选择数据导入方式")
        st.caption("选择以下任一方式开始导入数据")
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("上传文件 · CSV / Excel", icon=":material/upload_file:", use_container_width=True, key="wiz_file"):
                st.session_state["import_method"] = "file"
                st.session_state["import_step"] = 1
                st.rerun()
        with c2:
            if st.button("手动录入 · 逐条观测", icon=":material/edit_note:", use_container_width=True, key="wiz_manual"):
                st.session_state["import_method"] = "manual"
                st.session_state["import_step"] = 1
                st.rerun()
        with c3:
            if st.button("在线数据 · API / ERA5", icon=":material/cloud_download:", use_container_width=True, key="wiz_api"):
                st.session_state["import_method"] = "api"
                st.session_state["import_step"] = 1
                st.rerun()

    elif step == 1:
        method = st.session_state["import_method"]
        labels = {"file": "上传文件", "manual": "手动录入", "api": "在线数据 / ERA5"}
        st.markdown(f"#### {labels.get(method, method)}")

        # 返回按钮
        if st.button("← 返回选择方式", key="wiz_back_step0"):
            st.session_state["import_step"] = 0
            st.session_state["import_method"] = None
            st.rerun()

        if method == "file":
            df_file, source_file = _safe_render("导入-文件", render_file_upload_section) or (None, None)
            _safe_render("导入-模板", render_template_download)
            if df_file is not None and st.button("检查这份数据", key="import_check_file", type="primary", icon=":material/fact_check:"):
                _adopt_dataset(df_file, source=source_file)
                st.session_state["import_step"] = 2
                st.rerun()
        elif method == "manual":
            df_manual = _safe_render("导入-手动", render_manual_input_section)
            if df_manual is not None:
                _adopt_dataset(merge_manual_rows(
                    st.session_state.get("df"), df_manual),
                    source=st.session_state.get("source") or "手动录入")
                st.session_state["import_step"] = 2
                st.rerun()
        elif method == "api":
            df_api, source_api = _safe_render("导入-API", render_api_section) or (None, None)
            if df_api is not None:
                _adopt_dataset(df_api, source=source_api or "Open-Meteo API")
                st.session_state["import_step"] = 2
                st.rerun()

    elif step == 2:
        st.markdown("#### 数据预览与质量检查")
        df = st.session_state.get("df")
        if df is not None:
            issues = range_check(df) + temporal_consistency_check(df) + completeness_check(df)
            cols = st.columns(4)
            cols[0].metric("成功读取", f"{len(df):,} 条")
            cols[1].metric("已识别字段", f"{len(df.columns)} 项")
            cols[2].metric("待核查项目", f"{len(issues)} 项")
            cols[3].metric("缺失率", f"{df.isna().sum().sum() / max(df.size, 1) * 100:.2f}%")
            st.caption(f"来源 {st.session_state.get('source', '当前数据')} · 预览前 10 条，完整数据 {len(df):,} 条。")
            with st.container(border=True):
                column_config = {name: st.column_config.NumberColumn(FIELD_LABELS.get(name, name), format="%.1f")
                                 for name in df.select_dtypes(include="number").columns}
                column_config.update({name: st.column_config.Column(label) for name, label in FIELD_LABELS.items()
                                      if name in df and name not in column_config})
                st.dataframe(df.head(10), height=260, use_container_width=True, hide_index=True, column_config=column_config)

            # 数据质量控制：导入后默认显示（R-09 接入）。
            # 返回的百分制评分写入 session_state，供报告导出与摘要卡复用；
            # 原实现该键恒为 0.0，Word 报告里的「质量评分」一直是 0 分。
            _qr = _safe_render("导入-质控", render_quality_report, df, compact=True)
            if _qr:
                st.session_state["quality_score"] = _qr[0]

            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("确认数据，前往可视化分析", icon=":material/arrow_forward:", type="primary", use_container_width=True, key="wiz_confirm"):
                    st.session_state["import_step"] = 3
                    _navigate_to(1)  # 可视化 Tab 已互换至 index 1
            with c2:
                if st.button("← 返回上一步", use_container_width=True, key="wiz_back_step1"):
                    st.session_state["import_step"] = 1
                    st.rerun()
            with c3:
                if st.button("重新导入", icon=":material/refresh:", use_container_width=True, key="wiz_retry"):
                    st.session_state["import_step"] = 0
                    st.session_state["import_method"] = None
                    st.session_state["df"] = None
                    st.session_state["source"] = ""
                    st.session_state["_dataset_schema_version"] = None
                    st.session_state["_dataset_created_at"] = None
                    st.session_state["warnings_list"] = []
                    st.session_state["quality_score"] = 0.0
                    st.session_state["climate_data"] = None
                    st.session_state["climate_extreme"] = None
                    st.session_state["_import_history"] = []
                    st.session_state["_filter_date_range"] = None
                    st.rerun()
        else:
            st.warning("未检测到数据，请返回重新导入")
            if st.button("← 返回", key="wiz_back"):
                st.session_state["import_step"] = 0
                st.rerun()

    else:
        # 跳过向导：传统多标签模式
        sub_tab1, sub_tab2, sub_tab3 = st.tabs(["[文件] 文件导入", "[编辑] 手动录入", "[网络] API 获取"])
        with sub_tab1:
            df_file, source_file = _safe_render("导入-文件", render_file_upload_section) or (None, None)
            if df_file is not None:
                _adopt_dataset(df_file, source=source_file)
            _safe_render("导入-模板", render_template_download)
        with sub_tab2:
            df_manual = _safe_render("导入-手动", render_manual_input_section)
            if df_manual is not None:
                _adopt_dataset(merge_manual_rows(
                    st.session_state.get("df"), df_manual),
                    source=st.session_state.get("source") or "手动录入")
        with sub_tab3:
            df_api, source_api = _safe_render("导入-API", render_api_section) or (None, None)
            if df_api is not None:
                _adopt_dataset(df_api, source=source_api or "Open-Meteo API")

        if st.session_state["df"] is not None:
            st.divider()
            c_a, c_b = st.columns(2)
            with c_a:
                st.metric("当前数据", f"{len(st.session_state['df'])} 条记录")
            with c_b:
                st.metric("数据来源", st.session_state.get("source", "多源"))
            # 数据质量控制：跳过向导时同样默认展示（R-09）
            _qr_skip = _safe_render("导入-质控", render_quality_report,
                                    st.session_state["df"])
            if _qr_skip:
                st.session_state["quality_score"] = _qr_skip[0]
            if st.button("🔄 返回向导模式", key="back_to_wizard"):
                st.session_state["import_step"] = 0
                st.rerun()
