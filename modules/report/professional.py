"""专业版 Word 报告：封面、目录、表格化章节。

从 reporter.py 拆出（批次 4）。
"""

from datetime import datetime

import pandas as pd

from config import LIFE_INDEX_META, WARN_LEVEL_ORDER
from modules.report.base import (
    Cm, Pt, RGBColor, WD_ALIGN_PARAGRAPH,
    _add_table, _build_cover_meta, _build_cover_table, _build_toc,
    _compute_report_title, _number, _render_defense_advice, _resolve_field,
    _resolve_stats,
)


def _build_professional_report(doc, df, fc_df, fc_analysis, life_indices,
                               warnings_list, score, source):
    """专业版：完整章节 + 表格 + 防御建议（不含图片）"""
    has_obs = df is not None and not df.empty
    has_fc = fc_df is not None or fc_analysis is not None
    has_warnings = bool(warnings_list)

    # ---- 封面 ----
    title_text = _compute_report_title(has_obs, has_fc)
    title = doc.add_heading(title_text, level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _build_cover_table(doc, _build_cover_meta(
        df, fc_df, fc_analysis, warnings_list, score, source))

    # ---- 目录 ----
    sections = ["报告说明"]
    if has_obs:
        sections.append("观测数据统计摘要")
        if warnings_list:
            sections.append("事件检测与预警")
    if has_fc:
        sections.append("数值预报概况")
    if life_indices:
        sections.append("生活出行指南")
    sections.append("技术说明")
    if has_obs and has_warnings:
        sections.append("防御建议")
    section_titles = {
        name: f"{_number(index)}、{name}"
        for index, name in enumerate(sections, start=1)
    }
    _build_toc(doc, [(title, "") for title in section_titles.values()])

    # ---- 一、报告说明 ----
    # 紧凑排列：目录后不分页，后续章节也不分页（除非内容特别长）
    doc.add_heading(section_titles["报告说明"], level=1)
    doc.add_paragraph(
        "本报告基于观测数据和/或数值预报数据自动生成，结合统计、图表、事件检测、"
        "生活指南、防御建议等多个维度，为气象工作者和决策者提供专业的分析参考。"
    )
    doc.add_paragraph(
        "数据处理遵循标准质量控制流程，事件检测采用国家预警分级标准，"
        "生活指数参照气象行业常用分级方法。预报数据使用 NOAA GFS 全球预报系统，"
        "免注册、可商用、空间分辨率约 0.25°，最长预报周期 16 天。"
    )
    doc.add_paragraph(
        "本报告中的数据以结构化表格形式呈现，清晰可读、便于检索；"
        "如需可视化图表，请回到应用界面查看交互式 Plotly 图表。"
    )

    # ---- 二、观测数据统计摘要 ----
    if has_obs:
        doc.add_heading(section_titles["观测数据统计摘要"], level=1)

        stats_fields = ["temperature", "pressure", "humidity",
                        "wind_speed", "visibility", "precipitation"]
        labels = {
            "temperature": "气温 (℃)", "pressure": "气压 (hPa)",
            "humidity": "湿度 (%)", "wind_speed": "风速 (m/s)",
            "visibility": "能见度 (km)", "precipitation": "降水量 (mm)",
        }
        resolved = _resolve_stats(df, stats_fields)
        if resolved:
            rows = []
            for f in stats_fields:
                if f in resolved:
                    s = resolved[f]
                    rows.append([
                        labels.get(f, f),
                        f"{s.mean():.2f}",
                        f"{s.min():.2f}",
                        f"{s.max():.2f}",
                        f"{s.std():.2f}",
                        str(len(s)),
                    ])
            _add_table(doc,
                       headers=["字段", "均值", "最小", "最大", "标准差", "记录数"],
                       rows=rows,
                       col_widths=[3, 2.2, 2.2, 2.2, 2.2, 2.2])

        # 观测数据表格（替代图片嵌入）
        if df is not None and not df.empty:
            _render_obs_data_tables(doc, df)

    # ---- 三、事件检测与预警 ----
    if has_obs and warnings_list:
        doc.add_heading(section_titles["事件检测与预警"], level=1)
        doc.add_paragraph(
            "以下事件根据国家预警分级标准（《气象灾害预警信号发布与传播办法》）"
            "自动识别，按等级由高到低排列。")
        _render_warnings_table_pro(doc, warnings_list)

    # ---- 四、数值预报概况 ----
    if has_fc:
        doc.add_heading(section_titles["数值预报概况"], level=1)
        if fc_analysis:
            _render_forecast_section(doc, fc_analysis)
        # 预报数据表格（替代图片嵌入）
        if fc_df is not None and not fc_df.empty:
            _render_fc_data_tables(doc, fc_df)

    # ---- 五、生活出行指南 ----
    if life_indices:
        doc.add_heading(section_titles["生活出行指南"], level=1)
        doc.add_paragraph(
            "基于预报数据计算的 7 项生活指数，覆盖穿衣、带伞、体感、运动、"
            "紫外线、洗车、晾晒等日常决策场景。")
        _render_life_indices_table(doc, life_indices)

    # ---- 六、技术说明 ----
    doc.add_heading(section_titles["技术说明"], level=1)
    doc.add_heading("数据来源", level=2)
    doc.add_paragraph(
        "• 观测数据：用户上传的 CSV/Excel 气象观测记录\n"
        "• 预报数据：Open-Meteo GFS（全球预报系统），空间分辨率 0.25°，"
        "时间分辨率 1 小时，最长 16 天"
    )
    doc.add_heading("预警分级标准", level=2)
    doc.add_paragraph(
        "采用国家预警四级体系：蓝色（IV级，一般）→ 黄色（III级，较重）"
        "→ 橙色（II级，严重）→ 红色（I级，特别严重）。"
        "具体阈值见 config.py 中的各类预警阈值常量"
        "（HIGH_TEMP_WARNING / COLD_WAVE_WARNING / GALE_WARNING / FOG_WARNING / "
        "RAINSTORM_WARNING / FROST_WARNING / THUNDER_WARNING / HAZE_WARNING）。"
    )
    doc.add_heading("生活指数计算方法", level=2)
    doc.add_paragraph(
        "穿衣指数：按气温分 6 档（0 酷热 / 1 夏装 / 2 轻便 / 3 春秋装 / 4 初冬装 / 5 厚冬装）\n"
        "带伞建议：按未来 72 小时累计降水与天气码分 3 档（0 无需带伞 / 2 建议备伞 / 3 必带伞）\n"
        "体感舒适度：Thom 不适指数（SSD = T - 0.55·(1-RH)·(T-14) - V^(1/3)·(T-10)/20）\n"
        "运动指数：按温湿度组合折算 0-100 分后分级\n"
        "紫外线：由天气码近似分 4 档（弱/中/强/很强）\n"
        "洗车指数：按未来 72 小时累计降水分 3 档（适宜/较适宜/不适宜）\n"
        "晾晒指数：按降水与湿度组合折算 0-100 分后分级"
    )

    # ---- 七、防御建议 ----
    if has_obs and has_warnings:
        doc.add_heading(section_titles["防御建议"], level=1)
        _render_defense_advice(doc, warnings_list)

    # ---- 无数据友好提示 ----
    if not has_obs and not has_fc:
        doc.add_paragraph("")
        doc.add_paragraph("⚠ 当前没有数据可生成报告。请先导入观测数据或生成数值预报。")


def _render_warnings_table_pro(doc, warnings_list):
    """专业版预警表格"""
    from config import WARN_LEVEL_ORDER
    sorted_w = sorted(warnings_list,
                      key=lambda w: WARN_LEVEL_ORDER.get(w["level"], 4))
    color_map = {
        "蓝色": RGBColor(0, 102, 204),
        "黄色": RGBColor(245, 166, 35),
        "橙色": RGBColor(242, 101, 34),
        "红色": RGBColor(208, 2, 27),
    }
    rows = []
    for w in sorted_w:
        rows.append([
            f"[{w['level']}] {w['level_num']}",
            w["type"],
            w["detail"][:80] + ("…" if len(w["detail"]) > 80 else ""),
        ])
    _add_table(doc,
               headers=["等级", "类型", "详情"],
               rows=rows,
               col_widths=[3.5, 2.5, 9])
    # 在表格后逐条标注颜色
    for w in sorted_w:
        p = doc.add_paragraph()
        run = p.add_run(f"  → {w['icon']} {w['type']}{w['level']}事件：{w['detail']}")
        run.font.size = Pt(10)
        if w["level"] in color_map:
            run.font.color.rgb = color_map[w["level"]]


def _render_forecast_section(doc, fc_analysis):
    """渲染数值预报概况（不含图表）"""
    summary = fc_analysis.get("summary", "")
    if summary:
        doc.add_paragraph(f"总述：{summary}")

    # 极值表
    ex = fc_analysis.get("extremes", {})
    if ex:
        doc.add_heading("预报期极值", level=2)
        t_max = ex.get("max_temp", (0, ""))
        t_min = ex.get("min_temp", (0, ""))
        max_wind = ex.get("max_wind", (0, ""))
        rows = [
            ["最高气温", f"{t_max[0]:.1f} ℃", str(t_max[1])],
            ["最低气温", f"{t_min[0]:.1f} ℃", str(t_min[1])],
            ["累计降水", f"{ex.get('total_precip', 0):.1f} mm", "—"],
            ["最大风速", f"{max_wind[0]:.1f} m/s", str(max_wind[1])],
        ]
        if "max_daily_precip" in ex:
            mdp = ex["max_daily_precip"]
            rows.append(["最大日降水", f"{mdp[0]:.1f} mm", str(mdp[1])])
        _add_table(doc,
                   headers=["指标", "数值", "日期/说明"],
                   rows=rows,
                   col_widths=[4, 4, 7])

    # 趋势与精度
    prec = fc_analysis.get("precision", {})
    if prec:
        doc.add_heading("趋势与精度详情", level=2)
        rows = []
        tt = prec.get("temp_trend", {})
        if tt:
            rows.append([
                "趋势变化",
                f"{tt.get('diff_mean', 0):+.1f} ℃",
                f"±{tt.get('diff_std', 0):.1f} ℃",
            ])
            rows.append([
                "波动程度",
                tt.get("volatility", ""),
                f"标准差 {tt.get('overall_std', 0):.1f} ℃",
            ])
        rows.append([
            "连续高温",
            f"{prec.get('consecutive_hot', 0)} 天",
            f"最长 {prec.get('consecutive_hot', 0)} 天"
            if prec.get('consecutive_hot', 0) > 0 else "未出现",
        ])
        if "consecutive_rain" in prec:
            rows.append([
                "连续降水",
                f"{prec['consecutive_rain']} 天",
                "累计最长连续降水",
            ])
        diurnal = prec.get("diurnal", {})
        if diurnal:
            rows.append([
                "日较差",
                f"最大 {diurnal.get('max_range', (0, ''))[0]:.1f} ℃",
                f"平均 {diurnal.get('mean_range', 0):.1f} ℃",
            ])
        if rows:
            _add_table(doc,
                       headers=["指标", "数值", "说明"],
                       rows=rows,
                       col_widths=[4, 4, 7])

    # 预警
    fw = fc_analysis.get("warnings", [])
    if fw:
        doc.add_heading("预报预警信号", level=2)
        for w in fw:
            doc.add_paragraph(
                f"- [{w['level']}] {w['type']}: {w['detail']}",
                style="List Bullet")

    # 出行/农业建议
    recs = fc_analysis.get("recommendations", {})
    if recs:
        travel = recs.get("travel", [])
        agri = recs.get("agri", [])
        if travel or agri:
            doc.add_heading("建议", level=2)
        if travel:
            doc.add_paragraph("出行建议：")
            for r in travel[:6]:
                doc.add_paragraph(f"- {r}", style="List Bullet")
        if agri:
            doc.add_paragraph("农业建议：")
            for r in agri[:6]:
                doc.add_paragraph(f"- {r}", style="List Bullet")

    # 耦合风险
    coupling = fc_analysis.get("coupling", [])
    if coupling:
        doc.add_heading("多要素耦合风险", level=2)
        for c in coupling:
            doc.add_paragraph(
                f"- {c['icon']} {c['type']}（{c['severity']}）：{c['detail']}",
                style="List Bullet")


def _render_fc_data_tables(doc, fc_df):
    """预报数据表格（替代图片嵌入）：逐时温度/降水/风力/湿度摘要"""
    try:
        ts_col = _resolve_field(fc_df, "timestamp")
        temp_col = _resolve_field(fc_df, "temperature")
        app_col = _resolve_field(fc_df, "apparent_temperature")
        hum_col = _resolve_field(fc_df, "humidity")
        prec_col = _resolve_field(fc_df, "precipitation")
        wind_col = _resolve_field(fc_df, "wind_speed")
        prob_col = _resolve_field(fc_df, "precipitation_probability")

        if ts_col is None or fc_df.empty:
            return

        # ---- 1. 逐时温度表（仅当天，每 1 小时一行）----
        if temp_col:
            doc.add_heading("逐时气温详情（当日）", level=2)
            sorted_df = fc_df.sort_values(ts_col)
            # 取预报第一天（最早日期）的数据，只看当天
            try:
                dt_series = pd.to_datetime(sorted_df[ts_col])
                min_date = dt_series.min().date()
                today_df = sorted_df[dt_series.dt.date == min_date]
            except Exception:
                today_df = sorted_df
            rows = []
            for _, r in today_df.iterrows():
                try:
                    t = pd.to_datetime(r[ts_col])
                    t_str = f"{t.hour:02d}:{t.minute:02d}"
                except Exception:
                    t_str = str(r[ts_col])
                temp_val = r.get(temp_col)
                app_val = r.get(app_col) if app_col else None
                hum_val = r.get(hum_col) if hum_col else None
                rows.append([
                    t_str,
                    f"{temp_val:.1f}" if pd.notna(temp_val) else "—",
                    f"{app_val:.1f}" if pd.notna(app_val) else "—",
                    f"{hum_val:.0f}%" if pd.notna(hum_val) else "—",
                ])
            if rows:
                _add_table(doc,
                           headers=["时间", "气温(℃)", "体感(℃)", "湿度"],
                           rows=rows,
                           col_widths=[2.2, 2.2, 2.2, 2.2])
            else:
                doc.add_paragraph("当日无逐时气温数据。")

        # ---- 2. 降水时段表（仅显示有降水的时段）----
        if prec_col:
            rain_rows = []
            for _, row in fc_df.iterrows():
                p = row.get(prec_col, 0)
                if pd.notna(p) and float(p) > 0.05:
                    t_str = str(row[ts_col])[-8:-3] if len(str(row[ts_col])) > 5 else str(row[ts_col])
                    prob_val = row.get(prob_col) if prob_col else None
                    rain_rows.append([
                        t_str,
                        f"{float(p):.1f}",
                        f"{prob_val:.0f}%" if pd.notna(prob_val) else "—",
                    ])
            if rain_rows:
                doc.add_heading("降水时段分布", level=2)
                _add_table(doc,
                           headers=["时间", "降水量(mm)", "概率"],
                           rows=rain_rows[:20],
                           col_widths=[2.5, 3, 3])
            else:
                # 无降水也标注
                doc.add_paragraph("预报期内无明显降水。")

        # ---- 3. 风力概况表（Top 5 大风时段）----
        if wind_col:
            wind_list = []
            for _, row in fc_df.iterrows():
                w = row.get(wind_col, 0)
                if pd.notna(w) and float(w) > 1.5:  # > 1.5m/s 才记录
                    t_str = str(row[ts_col])[-8:-3] if len(str(row[ts_col])) > 5 else str(row[ts_col])
                    wind_list.append((t_str, float(w)))
            wind_list.sort(key=lambda x: x[1], reverse=True)
            if wind_list:
                doc.add_heading("主要风力时段", level=2)
                w_rows = [[t, f"{w:.1f}", f"{'微风' if w < 2 else '轻风' if w < 4 else '和风' if w < 6 else '清风' if w < 8 else '强风'}"]
                          for t, w in wind_list[:8]]
                _add_table(doc,
                           headers=["时间", "风速(m/s)", "风力等级"],
                           rows=w_rows,
                           col_widths=[2.5, 3, 3])

    except Exception:
        pass


def _render_obs_data_tables(doc, df):
    """观测数据表格（替代图片嵌入）：按天汇总关键指标"""
    try:
        ts_col = _resolve_field(df, "timestamp")
        temp_col = _resolve_field(df, "temperature")
        prec_col = _resolve_field(df, "precipitation")
        wind_col = _resolve_field(df, "wind_speed")
        hum_col = _resolve_field(df, "humidity")

        if ts_col is None or df.empty:
            return

        # 按日期分组统计
        df_copy = df.copy()
        try:
            df_copy["_date"] = pd.to_datetime(df_copy[ts_col]).dt.date
        except Exception:
            return

        daily = df_copy.groupby("_date")
        doc.add_heading("逐日观测摘要", level=2)

        rows = []
        for date, group in daily:
            t_mean = group[temp_col].mean() if temp_col in group.columns and group[temp_col].notna().any() else None
            t_max = group[temp_col].max() if temp_col in group.columns and group[temp_col].notna().any() else None
            t_min = group[temp_col].min() if temp_col in group.columns and group[temp_col].notna().any() else None
            p_sum = group[prec_col].sum() if prec_col in group.columns and group[prec_col].notna().any() else None
            w_max = group[wind_col].max() if wind_col in group.columns and group[wind_col].notna().any() else None
            h_mean = group[hum_col].mean() if hum_col in group.columns and group[hum_col].notna().any() else None

            rows.append([
                str(date),
                f"{t_mean:.1f}/{t_max:.1f}/{t_min:.1f}" if t_mean is not None else "—",
                f"{p_sum:.1f}" if p_sum is not None else "—",
                f"{w_max:.1f}" if w_max is not None else "—",
                f"{h_mean:.0f}%" if h_mean is not None else "—",
                f"{len(group)}",
            ])

        if rows:
            _add_table(doc,
                       headers=["日期", "气温(均/高/低℃)", "降水(mm)", "最大风速(m/s)", "平均湿度%", "记录数"],
                       rows=rows,
                       col_widths=[2.2, 3.2, 2, 2.4, 2.4, 1.6])
    except Exception:
        pass


def _render_life_indices_table(doc, life_indices):
    """生活出行指南 - 表格化"""
    from config import LIFE_INDEX_META
    order = ["clothing", "umbrella", "comfort", "exercise",
             "uv", "carwash", "drying"]
    rows = []
    for key in order:
        if key in life_indices:
            info = life_indices[key]
            icon, name = LIFE_INDEX_META.get(key, ("", key))
            score = info.get("score", "")
            score_text = (f"{score}" if isinstance(score, int)
                          else f"{score:.1f}" if isinstance(score, float) else str(score))
            rows.append([
                f"{icon} {name}",
                info.get("level", ""),
                score_text,
                info.get("advice", ""),
            ])
    _add_table(doc,
               headers=["指标", "等级", "评分", "建议"],
               rows=rows,
               col_widths=[3.5, 2.5, 1.5, 7.5])
