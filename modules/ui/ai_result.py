"""Evidence-first AI result layout. Every displayed source belongs to this result."""
from html import escape

import streamlit as st

from modules.ai_report_model import report_markdown, report_sections


def _paragraph(text, kind="wb-ai-text"):
    st.markdown(f'<div class="{kind}">{escape(str(text)).replace(chr(10), "<br>")}</div>', unsafe_allow_html=True)


def _select_evidence(identity, image_id):
    st.session_state["chart_reader_selected_evidence"] = identity
    st.session_state["chart_reader_source_image"] = image_id


def render_ai_result(model, meta, images):
    from modules.ai_narrative import _build_docx, _report_html
    st.caption(f"{meta.get('generated', '')} · {meta.get('scope', '')} · AI 提取内容，需结合原图核查")
    st.markdown('<a class="wb-ai-source-link" href="#ai-result-original">查看生成时原图 ↓</a>', unsafe_allow_html=True)
    # Keep conclusions first in document order on narrow screens; desktop CSS
    # restores the side-by-side original-image comparison on the left.
    with st.container(key="ai_result_layout"):
        right, left = st.columns([1, 1.05])
    evidence = model.get("evidence") or []
    picked = next((e for e in evidence if e["id"] == st.session_state.get("chart_reader_selected_evidence")), evidence[0] if evidence else None)
    with left, st.container(border=True, key="ai_original_panel"):
        st.markdown('<div id="ai-result-original"></div><h4>原图核对</h4>', unsafe_allow_html=True)
        available = {item.get("id", f"img_{i+1}"): item for i, item in enumerate(images or [])}
        if available:
            if st.session_state.get("chart_reader_source_image") not in available:
                st.session_state["chart_reader_source_image"] = picked["image_id"] if picked else next(iter(available))
            selected = st.selectbox("生成时原图", list(available), key="chart_reader_source_image",
                                    format_func=lambda key: available[key].get("name", key), label_visibility="collapsed")
            item = available[selected]
            if item.get("data_bytes"):
                st.image(item["data_bytes"], caption=f"{item['name']} · 本次生成时的原图", width="stretch")
                st.caption(f"图像标识 {selected} · SHA-256 {item.get('sha256', '')[:12]}")
            if picked and picked["image_id"] == selected:
                _paragraph(f"当前依据 {picked['id']} · {picked['location']}", "wb-ai-kind")
                _paragraph(picked["feature"])
            st.caption("点击解读中的依据切换原图。位置用文字描述，数值仍需人工核对。")
        else:
            st.info("此结果没有保存原图快照，无法进行图面核对。")
    with right:
        if model.get("structured"):
            with st.container(border=True, key="ai_conclusions"):
                st.markdown("#### 核心结论")
                for i, finding in enumerate(model["findings"]):
                    text_col, action = st.columns([3, 1])
                    with text_col:
                        _paragraph(f"{i + 1:02d}  {'图面描述' if finding['kind'] == 'visible' else '条件性推断'}", "wb-ai-kind")
                        _paragraph(finding["text"], "wb-ai-finding")
                    e = next(e for e in evidence if e["id"] == finding["evidence_ids"][0])
                    action.button("依据 " + " / ".join(finding["evidence_ids"]), key=f"ai_evidence_{finding['id']}",
                                  on_click=_select_evidence, args=(e["id"], e["image_id"]), width="stretch")
            with st.container(border=True, key="ai_evidence_panel"):
                st.markdown("#### 原图依据")
                for e in evidence:
                    detail, action = st.columns([3, 1])
                    with detail:
                        _paragraph(f"{e['id']} · {e['location']}", "wb-ai-kind")
                        _paragraph(e["feature"])
                    action.button("核对原图", key=f"ai_source_{e['id']}", on_click=_select_evidence,
                                  args=(e["id"], e["image_id"]), width="stretch")
                if picked and st.session_state.get("chart_reader_selected_evidence"):
                    st.markdown(f'<a class="wb-ai-source-link" href="#ai-result-original">查看已选依据 {escape(picked["id"])} 的原图 ↓</a>', unsafe_allow_html=True)
            with st.container(border=True, key="ai_uncertainty"):
                st.markdown("#### 不确定性与补充信息")
                for limit in model["limitations"]:
                    _paragraph(limit["missing"], "wb-ai-uncertainty")
                    _paragraph("影响：" + limit["impact"])
                    st.caption("建议补充 " + limit["next_input"])
        else:
            st.info(model.get("format_notice") or "旧版结果未提供结构化依据，完整解读保留如下。")
        with st.expander("完整六段解读", expanded=not model.get("structured")):
            st.markdown(_report_html([(s["title"], s["body"]) for s in model.get("sections", [])], meta), unsafe_allow_html=True)
        word, markdown = st.columns(2)
        try:
            word.download_button("导出 Word", _build_docx(report_sections(model), meta, images), file_name="气象读图解析报告.docx",
                                 mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                 key="report_download_docx", width="stretch", icon=":material/description:")
        except Exception as exc:
            word.warning(f"Word 导出失败：{str(exc)[:160]}")
        markdown.download_button("导出 Markdown", report_markdown(model, meta).encode("utf-8"), file_name="气象读图解析报告.md",
                                 mime="text/markdown", key="report_download_md", width="stretch")
        st.caption("Word 包含生成时原图、核心结论、依据、不确定性及完整正文。")
        with st.expander("模型原始输出"):
            st.download_button("保存原始输出", model.get("raw_response", "").encode("utf-8"), file_name="读图模型原始输出.txt",
                               mime="text/plain", key="chart_reader_raw_download")
