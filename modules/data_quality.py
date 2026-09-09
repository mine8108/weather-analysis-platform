"""
数据质量控制模块：范围校验、时间一致性检测、完整性检查、质量评分
"""

import pandas as pd
import streamlit as st
from config import FIELD_RANGES


def _numeric(df, field):
    """取数值列；非数值（object/字符串）列安全转为 NaN。

    修复 R-16：导入链路从不保证数值列 dtype，原实现对 object 列直接做
    `col < lo` 或 `.diff()` 会抛 TypeError，整个质控页面因此崩掉。
    """
    return pd.to_numeric(df[field], errors="coerce")


def range_check(df):
    """范围校验：检测各字段是否在合理范围内。

    修复 R-16：百分比统一以总行数为分母，与 compute_quality_score 的扣分
    口径一致（原实现以非空样本为分母，两处口径不同）。
    """
    issues = []
    total = max(len(df), 1)
    for field, (lo, hi) in FIELD_RANGES.items():
        if field not in df.columns:
            continue
        col = _numeric(df, field).dropna()
        if len(col) == 0:
            continue
        out_of_range = (col < lo) | (col > hi)
        if out_of_range.any():
            count = int(out_of_range.sum())
            pct = count / total * 100
            issues.append({
                "type": "范围异常",
                "field": field,
                "detail": f"{count} 条 ({pct:.1f}%) 超出范围 [{lo}, {hi}]",
                "count": count,
                "severity": "error" if pct > 5 else "warning",
            })
    return issues


def temporal_consistency_check(df):
    """时间一致性检测：按站点分组，检测真实 1 小时步长上的相邻时次突跳。

    修复 R-16：
    - 原实现不按 station_id 分组，多站点数据会把不同站点的相邻行当成同一序列；
    - 原实现不校验时间步长，规则文案却写「1h 变化」，非逐时数据会产生假阳性；
    - 原实现对 object 列调用 .diff() 会抛 TypeError，现先数值化。
    """
    issues = []
    if "timestamp" not in df.columns:
        return issues

    if not df["timestamp"].is_monotonic_increasing:
        issues.append({
            "type": "时间乱序",
            "field": "timestamp",
            "detail": "数据未按时间升序排列，已自动排序",
            "count": 1,
            "severity": "warning",
        })

    # 检测突跳（温度1h变化≥8℃）
    check_rules = {
        "temperature": (8.0, "1h 温度变化≥8℃"),
        "pressure": (10.0, "1h 气压变化≥10 hPa"),
        "humidity": (30.0, "1h 湿度变化≥30%"),
    }

    if "station_id" in df.columns:
        groups = [g for _, g in df.groupby("station_id", dropna=False)]
    else:
        groups = [df]

    for field, (threshold, desc) in check_rules.items():
        if field not in df.columns:
            continue
        total_spikes = 0
        for g in groups:
            if field not in g.columns or len(g) < 2:
                continue
            g = g.sort_values("timestamp")
            values = _numeric(g, field)
            diffs = values.diff().abs()
            step_hours = (
                pd.to_datetime(g["timestamp"], errors="coerce")
                .diff()
                .dt.total_seconds()
                / 3600.0
            )
            is_hourly = step_hours.between(0.5, 1.5)
            total_spikes += int(((diffs > threshold) & is_hourly).sum())
        if total_spikes:
            issues.append({
                "type": "数据突跳",
                "field": field,
                "detail": f"{total_spikes} 处 {desc}",
                "count": total_spikes,
                "severity": "warning",
            })
    return issues


def completeness_check(df):
    """完整性检查：缺失率统计"""
    issues = []
    total = len(df)

    for col in df.columns:
        if col == "station_id":
            continue
        missing = df[col].isna().sum() if col in df.columns else total
        if missing > 0:
            pct = missing / total * 100
            severity = "error" if pct > 30 else ("warning" if pct > 10 else "info")
            issues.append({
                "type": "数据缺失",
                "field": col,
                "detail": f"{missing}/{total} 条缺失 ({pct:.1f}%)",
                "count": missing,
                "severity": severity,
            })
    return issues


def compute_quality_score(df, issues):
    """计算数据质量评分（百分制）"""
    total = len(df)
    if total == 0:
        return 0.0

    # 基础分100
    score = 100.0

    # 每种问题扣分
    penalty_map = {
        "error": 5.0,
        "warning": 2.0,
        "info": 1.0,
    }

    for issue in issues:
        penalty = penalty_map.get(issue["severity"], 1.0) * min(issue["count"] / max(total, 1) * 10, 5)
        score -= penalty

    return max(0.0, round(score, 1))


def render_quality_report(df):
    """渲染数据质量报告"""
    st.subheader("[质控] 数据质量控制")

    if df is None or df.empty:
        st.info("请先导入数据")
        return

    issues = []
    issues += range_check(df)
    issues += temporal_consistency_check(df)
    issues += completeness_check(df)

    score = compute_quality_score(df, issues)

    # 质量评分
    col1, col2, col3 = st.columns([1, 1, 2])

    with col1:
        if score >= 90:
            st.success(f"### [统计] {score}/100 分")
            st.caption("数据质量：优秀")
        elif score >= 70:
            st.warning(f"### [统计] {score}/100 分")
            st.caption("数据质量：一般")
        else:
            st.error(f"### [统计] {score}/100 分")
            st.caption("数据质量：较差，建议检查")

    with col2:
        st.metric("总记录数", len(df))
    with col3:
        st.metric("有效字段数", len([c for c in df.columns if c != "station_id"]))

    # 详细问题列表
    if issues:
        st.write("---")
        for issue in issues:
            sev_icon = {"error": "[红]", "warning": "[黄]", "info": "[蓝]"}.get(issue["severity"], "[正常]")
            col = issue["field"]
            if col == "timestamp":
                col = "时间"
            st.write(f"{sev_icon} **{col}** — {issue['detail']} ({issue['type']})")
    else:
        st.success("[OK] 未检测到数据质量问题")

    return score, issues
