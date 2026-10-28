"""Native page routing with a visible module selector below the brand row."""
import streamlit as st

MODULES = (
    ("数据导入", "import", "upload_file"),
    ("可视化分析", "visualization", "monitoring"),
    ("数值预报", "forecast", "partly_cloudy_day"),
    ("AI 读图解析", "chart-reader", "image_search"),
    ("报告导出", "report", "description"),
    ("报文解码", "decoder", "data_object"),
)


def queue_navigation(index, *, remember=True):
    if type(index) is not int or not 0 <= index < len(MODULES):
        raise ValueError("无效模块")
    current = st.session_state.get("active_tab", 0)
    if remember and current != index:
        st.session_state["_nav_stack"] = (st.session_state.get("_nav_stack", []) + [current])[-10:]
    st.session_state["_route_request"] = index


def navigate(index):
    queue_navigation(index)
    st.rerun()


def _on_navigation_change():
    selected = st.session_state.get("_module_nav")
    if selected is not None:
        queue_navigation(selected)


def render_navigation(renderers):
    if len(renderers) != len(MODULES):
        raise ValueError("六模块入口不完整")
    pages = [st.Page(fn, title=label, url_path=path, default=i == 0, icon=f":material/{icon}:")
             for i, (fn, (label, path, icon)) in enumerate(zip(renderers, MODULES))]
    page = st.navigation(pages, position="hidden")
    current = next(i for i, p in enumerate(pages) if p.url_path == page.url_path)
    pending = st.session_state.pop("_route_request", None)
    if type(pending) is int and 0 <= pending < len(pages) and pending != current:
        st.switch_page(pages[pending])
    st.session_state["active_tab"] = current
    st.session_state["_module_nav"] = current
    with st.container(key="workbench_nav"):
        st.segmented_control("工作台模块", list(range(len(MODULES))),
                             format_func=lambda i: f":material/{MODULES[i][2]}: {MODULES[i][0]}",
                             key="_module_nav", selection_mode="single", label_visibility="collapsed",
                             on_change=_on_navigation_change, width="stretch")
    return page, MODULES[current][1]
