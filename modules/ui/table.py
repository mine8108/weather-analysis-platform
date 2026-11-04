"""Readable tables that do not depend on the interactive dataframe bundle."""
from __future__ import annotations

import pandas as pd
import streamlit as st


def table_html(data, *, hide_index=False, labels=None, float_precision=None, max_rows=200, offset=0):
    """Return escaped HTML and the total row count; never interpret cell content as HTML."""
    frame = pd.DataFrame(data).iloc[offset:offset + max_rows].copy()
    if labels:
        frame = frame.rename(columns=labels)
    formatter = (lambda value: f"{value:.{float_precision}f}") if float_precision is not None else None
    html = frame.to_html(index=not hide_index, escape=True, render_links=False, border=0,
                         na_rep="—", float_format=formatter, classes="wb-table")
    return '<div class="wb-table-scroll" tabindex="0">' + html + '</div>', len(data)


def render_table(data, *, hide_index=False, labels=None, float_precision=None, max_rows=200, key=None):
    total = len(data)
    page = 1
    if total > max_rows:
        pages = (total + max_rows - 1) // max_rows
        if key and key in st.session_state and st.session_state[key] > pages:
            st.session_state[key] = pages
        page = st.number_input(f"表格页码（共 {pages} 页）", min_value=1, max_value=pages,
                               value=1, step=1, key=key)
    offset = (page - 1) * max_rows
    html, total = table_html(data, hide_index=hide_index, labels=labels,
                             float_precision=float_precision, max_rows=max_rows, offset=offset)
    st.html(html)
    if total > max_rows:
        st.caption(f"显示第 {offset + 1:,}–{min(offset + max_rows, total):,} 条，共 {total:,} 条。")
