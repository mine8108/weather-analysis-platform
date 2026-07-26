import plotly.graph_objects as go


def kaleido_export(q, fig_dict, kw):
    """spawn 子进程的 target：在子进程里把 plotly fig_dict 还原为 Figure 并导出 PNG。
    模块级函数确保可 pickle；仅依赖 plotly，不 import streamlit，
    避免子进程 reimport reporter 时触发顶层 streamlit 加载的副作用。
    """
    try:
        png = go.Figure(fig_dict).to_image(**kw)
        q.put(("ok", png))
    except Exception as e:
        q.put(("err", str(e)))