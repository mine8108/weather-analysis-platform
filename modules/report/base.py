"""Word/CSV 报告的基础排版、表格与字段解析工具。

从 reporter.py 拆出（批次 4）。不依赖 Streamlit，可单独测试。
"""

from io import BytesIO
from datetime import datetime

import pandas as pd

from config import AGRI_ADVICE, PUBLIC_ADVICE

try:
    from docx.shared import RGBColor, Pt, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
except ImportError:  # 无 python-docx 时保持可导入
    RGBColor = Pt = Cm = WD_ALIGN_PARAGRAPH = qn = OxmlElement = None


_FIELD_ALIAS_REPORT = {
    "temperature_2m": "temperature",
    "relative_humidity_2m": "humidity",
    "surface_pressure": "pressure",
    "wind_speed_10m": "wind_speed",
    "precipitation_sum": "precipitation",
    "precipitation_hours": "precipitation",
}


_TITLE_COLOR = "1E3A5F"           # 标题深蓝


_HEADER_BG = "DBEAFE"             # 表头底色浅蓝


_HEADER_FG = "1E3A5F"             # 表头字色深蓝


_SUBTLE_COLOR = "6B7280"          # 副文本灰


def _set_default_styles(doc):
    """设置文档默认样式：正文字号、字体、段间距（紧凑版）"""
    style = doc.styles["Normal"]
    style.font.name = "Microsoft YaHei"
    style.font.size = Pt(10.5)
    pf = style.paragraph_format
    pf.space_before = Pt(2)
    pf.space_after = Pt(4)
    pf.line_spacing = 1.25

    # 压缩各级标题间距
    for level in range(0, 3):
        try:
            h_style = doc.styles[f"Heading {level}"]
            hpf = h_style.paragraph_format
            hpf.space_before = Pt(8 if level == 1 else (6 if level == 2 else 4))
            hpf.space_after = Pt(4 if level == 1 else (2 if level == 2 else 2))
            if hasattr(h_style, "font"):
                if level == 1:
                    h_style.font.size = Pt(14)
                elif level == 2:
                    h_style.font.size = Pt(12)
        except Exception:
            pass


def _add_page_break(doc):
    """添加分页符"""
    doc.add_page_break()


def _build_cover_table(doc, rows, col_widths=(4, 11)):
    """封面信息表：rows=[(label, value), ...]"""
    table = doc.add_table(rows=len(rows), cols=2)
    table.style = "Light Grid Accent 1"
    for row in table.rows:
        for i, w in enumerate(col_widths):
            row.cells[i].width = Cm(w)

    for i, (label, value) in enumerate(rows):
        # 左列标签
        cell_l = table.rows[i].cells[0]
        cell_l.text = ""
        p = cell_l.paragraphs[0]
        run = p.add_run(str(label))
        run.bold = True
        run.font.size = Pt(11)
        run.font.color.rgb = RGBColor.from_string(_HEADER_FG)
        # 右列值
        cell_r = table.rows[i].cells[1]
        cell_r.text = ""
        p = cell_r.paragraphs[0]
        run = p.add_run(str(value))
        run.font.size = Pt(11)
    return table


def _add_table(doc, headers, rows, col_widths=None, header_bg=True):
    """通用表格渲染：headers=列名列表，rows=[[cell, ...], ...]"""
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Light Grid Accent 1"

    # 表头
    hdr_cells = table.rows[0].cells
    for i, h in enumerate(headers):
        cell = hdr_cells[i]
        cell.text = ""
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(str(h))
        run.bold = True
        run.font.size = Pt(11)
        run.font.color.rgb = RGBColor.from_string(_HEADER_FG)
        if header_bg:
            tc_pr = cell._tc.get_or_add_tcPr()
            shd = OxmlElement("w:shd")
            shd.set(qn("w:val"), "clear")
            shd.set(qn("w:color"), "auto")
            shd.set(qn("w:fill"), _HEADER_BG)
            tc_pr.append(shd)

    # 数据行
    for r_idx, row in enumerate(rows):
        cells = table.rows[r_idx + 1].cells
        for c_idx, val in enumerate(row):
            cell = cells[c_idx]
            cell.text = ""
            p = cell.paragraphs[0]
            run = p.add_run(str(val))
            run.font.size = Pt(10)

    # 列宽
    if col_widths:
        for row in table.rows:
            for i, w in enumerate(col_widths):
                if i < len(row.cells):
                    row.cells[i].width = Cm(w)
    return table


def _build_toc(doc, sections):
    """目录：sections=[(title, page_hint), ...]"""
    doc.add_heading("目录", level=1)
    for title, _page in sections:
        p = doc.add_paragraph()
        run = p.add_run(f"  •  {title}")
        run.font.size = Pt(12)


def _resolve_field(df, field):
    """按别名解析字段，返回实际列名或 None"""
    if field in df.columns:
        return field
    for alias, target in _FIELD_ALIAS_REPORT.items():
        if target == field and alias in df.columns:
            return alias
    return None


def _resolve_stats(df, stats_fields):
    """解析统计字段（支持别名），返回 {field: Series}"""
    result = {}
    for f in stats_fields:
        actual = _resolve_field(df, f)
        if actual and not df[actual].dropna().empty:
            result[f] = df[actual].dropna()
    return result


def _number(n):
    """中文数字映射"""
    nums = ["", "一", "二", "三", "四", "五", "六", "七", "八", "九"]
    return nums[n] if n < len(nums) else str(n)


def _sanitize_cell_for_csv(val):
    """安全修复（P-08）：CSV 公式注入清洗。

    以 = + - @ 及制表符/回车开头的单元格，在 Excel/WPS 打开时会被当作公式执行。
    对这类单元格加前缀单引号，使其按纯文本显示。
    """
    if val is None:
        return val
    s = str(val)
    # 安全修复（SEC-36）：Excel/WPS 会忽略前导空白后再解释公式，
    # 因此先剥掉空白/制表/换行再判断危险前缀。
    probe = s.lstrip(" \t\r\n")
    if probe[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return val


def export_data_csv(df):
    """导出数据为 CSV 字节流（含公式注入清洗）"""
    if df is None or df.empty:
        return None
    # 仅清洗字符串类单元格；数值列不受影响，避免破坏数据类型。
    # 注意（pandas 3.0 坑）：默认字符串 dtype 为 str 而非 object，
    # 必须同时判断 object 与 string dtype，否则纯字符串列会漏清洗。
    df_safe = df.copy()
    for col in df_safe.columns:
        dt = df_safe[col].dtype
        if pd.api.types.is_object_dtype(dt) or pd.api.types.is_string_dtype(dt):
            df_safe[col] = df_safe[col].map(_sanitize_cell_for_csv)
    return df_safe.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")


def _compute_report_title(has_obs, has_fc):
    """根据数据可用性决定报告标题"""
    if has_obs and has_fc:
        return "气象数据与预报综合分析报告"
    elif has_fc:
        return "数值预报分析报告"
    else:
        return "气象数据分析报告"


def _build_cover_meta(df, fc_df, fc_analysis, warnings_list, score, source):
    """构建封面信息表的所有元数据行"""
    rows = []
    rows.append(("生成时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    if source:
        rows.append(("数据来源", source))
    has_obs = df is not None and not df.empty
    has_fc = fc_df is not None or fc_analysis is not None
    if has_obs:
        ts_col = _resolve_field(df, "timestamp")
        if ts_col and len(df) > 0:
            try:
                rows.append(("观测时段",
                             f"{df[ts_col].min()} ~ {df[ts_col].max()}"))
            except Exception:
                pass
        rows.append(("观测记录数", f"{len(df)} 条"))
        rows.append(("数据质量评分", f"{score}/100"))
        if warnings_list:
            rows.append(("检出预警事件", f"{len(warnings_list)} 个"))
    if has_fc and fc_df is not None and not fc_df.empty:
        fts_col = _resolve_field(fc_df, "timestamp")
        if fts_col and len(fc_df) > 0:
            try:
                rows.append(("预报时段",
                             f"{fc_df[fts_col].min()} ~ {fc_df[fts_col].max()}"))
            except Exception:
                pass
        if "latitude" in fc_df.columns and "longitude" in fc_df.columns:
            try:
                lat = fc_df["latitude"].dropna().iloc[0]
                lon = fc_df["longitude"].dropna().iloc[0]
                if pd.notna(lat) and pd.notna(lon):
                    rows.append(("预报坐标", f"{lat:.4f}°N, {lon:.4f}°E"))
            except Exception:
                pass
    if has_fc and fc_analysis:
        summary = fc_analysis.get("summary", "")
        if summary:
            # 限制封面总述长度
            rows.append(("预报总述", summary[:120] + ("…" if len(summary) > 120 else "")))
    return rows


def _render_defense_advice(doc, warnings_list):
    """防御建议 - 双列表格 + 数据支撑"""
    from config import PUBLIC_ADVICE, AGRI_ADVICE

    doc.add_heading("公众出行", level=2)
    pub_rows = []
    for warn in warnings_list:
        if (warn["type"] in PUBLIC_ADVICE
                and warn["level"] in PUBLIC_ADVICE[warn["type"]]):
            text = PUBLIC_ADVICE[warn["type"]][warn["level"]]
            support = warn.get("detail", "")
            pub_rows.append([
                f"[{warn['level']}] {warn['type']}",
                text,
                support[:60] + ("…" if len(support) > 60 else ""),
            ])
    if pub_rows:
        _add_table(doc,
                   headers=["事件", "建议", "数据支撑"],
                   rows=pub_rows,
                   col_widths=[3.5, 8, 4])
    else:
        doc.add_paragraph("（暂无公众出行建议）")

    doc.add_heading("农业生产", level=2)
    agri_rows = []
    for warn in warnings_list:
        if (warn["type"] in AGRI_ADVICE
                and warn["level"] in AGRI_ADVICE[warn["type"]]):
            text = AGRI_ADVICE[warn["type"]][warn["level"]]
            support = warn.get("detail", "")
            agri_rows.append([
                f"[{warn['level']}] {warn['type']}",
                text,
                support[:60] + ("…" if len(support) > 60 else ""),
            ])
    if agri_rows:
        _add_table(doc,
                   headers=["事件", "建议", "数据支撑"],
                   rows=agri_rows,
                   col_widths=[3.5, 8, 4])
    else:
        doc.add_paragraph("（暂无农业生产建议）")
