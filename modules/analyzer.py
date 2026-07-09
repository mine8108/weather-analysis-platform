"""
分析建议引擎：国家预警标准检测、多要素耦合分析、公众出行/农业建议生成
"""

import pandas as pd
import numpy as np
import streamlit as st
from datetime import timedelta
from config import (
    HIGH_TEMP_WARNING, COLD_WAVE_WARNING, GALE_WARNING,
    FOG_WARNING, RAINSTORM_WARNING, FROST_WARNING,
    THUNDER_WARNING, HAZE_WARNING,
    PUBLIC_ADVICE, AGRI_ADVICE, WARN_STYLES,
    get_beaufort_level,
)

# 可配置的预警规则（用户可在侧边栏自定义覆盖）
CUSTOM_THRESHOLDS = {}


def set_custom_thresholds(custom):
    global CUSTOM_THRESHOLDS
    CUSTOM_THRESHOLDS = custom


def check_high_temperature(df):
    """高温预警检测"""
    warnings_list = []
    if "temperature" not in df.columns:
        return warnings_list

    temps = df["temperature"].dropna()
    if len(temps) < 24:  # 至少24条小时数据
        return warnings_list

    # 检查连续3天日最高气温≥35℃
    if "timestamp" in df.columns:
        df_copy = df.copy()
        df_copy["date"] = df_copy["timestamp"].dt.date
        daily_max = df_copy.groupby("date")["temperature"].max()
        hot_days = (daily_max >= 35).sum()
        # 检查连续3天
        consecutive = 0
        max_consecutive = 0
        for val in (daily_max >= 35):
            if val:
                consecutive += 1
                max_consecutive = max(max_consecutive, consecutive)
            else:
                consecutive = 0

        if max_consecutive >= 3:
            warnings_list.append({
                "type": "高温",
                "level": "黄色",
                "level_num": "Ⅲ级",
                "detail": f"已连续 {max_consecutive} 天日最高气温≥35℃",
                "icon": "\u2600",
            })

    # 检查24h内最高气温≥37℃ 或 ≥40℃
    recent_24h = temps.tail(24) if len(temps) >= 24 else temps
    max_recent = recent_24h.max()

    for level in ["橙色", "红色"]:
        threshold = CUSTOM_THRESHOLDS.get("high_temp", {}).get(level, HIGH_TEMP_WARNING[level]["temp"])
        if max_recent >= threshold:
            warnings_list.append({
                "type": "高温",
                "level": level,
                "level_num": HIGH_TEMP_WARNING[level]["level"],
                "detail": f"24h 内最高气温达 {max_recent:.1f}℃，≥{threshold}℃",
                "icon": HIGH_TEMP_WARNING[level]["icon"],
            })
            break  # 只取最高级别

    return warnings_list


def check_cold_wave(df):
    """寒潮预警检测"""
    warnings_list = []
    if "temperature" not in df.columns or len(df) < 48:
        return warnings_list

    temps = df["temperature"].dropna()
    if len(temps) < 48:
        return warnings_list

    # 计算48h和24h降温
    t_now = temps.iloc[-1]
    t_24h_ago = temps.iloc[-25] if len(temps) >= 25 else temps.iloc[0]
    t_48h_ago = temps.iloc[-49] if len(temps) >= 49 else temps.iloc[0]

    min_temp = temps.tail(24).min()

    checks = [
        ("蓝色", COLD_WAVE_WARNING["蓝色"]["temp_drop"], COLD_WAVE_WARNING["蓝色"]["min_temp"], 48,
         t_now - t_48h_ago if len(temps) >= 49 else 0),
        ("黄色", COLD_WAVE_WARNING["黄色"]["temp_drop"], COLD_WAVE_WARNING["黄色"]["min_temp"], 24,
         t_now - t_24h_ago),
        ("橙色", COLD_WAVE_WARNING["橙色"]["temp_drop"], COLD_WAVE_WARNING["橙色"]["min_temp"], 24,
         t_now - t_24h_ago),
        ("红色", COLD_WAVE_WARNING["红色"]["temp_drop"], COLD_WAVE_WARNING["红色"]["min_temp"], 24,
         t_now - t_24h_ago),
    ]

    for level, drop_thresh, min_thresh, _, actual_drop in checks:
        actual_drop = -actual_drop  # 降温为正
        custom_drop = CUSTOM_THRESHOLDS.get("cold_wave", {}).get(level, {}).get("temp_drop", drop_thresh)
        if actual_drop >= custom_drop and min_temp <= min_thresh:
            warnings_list.append({
                "type": "寒潮",
                "level": level,
                "level_num": COLD_WAVE_WARNING[level]["level"],
                "detail": f"降温 {actual_drop:.1f}℃（≥{custom_drop}℃），最低气温 {min_temp:.1f}℃（≤{min_thresh}℃）",
                "icon": COLD_WAVE_WARNING[level]["icon"],
            })
            break

    return warnings_list


def check_gale(df):
    """大风预警检测"""
    warnings_list = []
    if "wind_speed" not in df.columns:
        return warnings_list

    ws = df["wind_speed"].dropna()
    if len(ws) < 6:
        return warnings_list

    max_recent_24h = ws.tail(24).max() if len(ws) >= 24 else ws.max()
    max_recent_12h = ws.tail(12).max() if len(ws) >= 12 else ws.max()
    max_recent_6h = ws.tail(6).max() if len(ws) >= 6 else ws.max()

    level_checks = [
        ("蓝色", 24, max_recent_24h, GALE_WARNING["蓝色"]["avg_wind"]),
        ("黄色", 12, max_recent_12h, GALE_WARNING["黄色"]["avg_wind"]),
        ("橙色", 6, max_recent_6h, GALE_WARNING["橙色"]["avg_wind"]),
        ("红色", 6, max_recent_6h, GALE_WARNING["红色"]["avg_wind"]),
    ]

    triggered = None
    for level, _, actual, threshold in reversed(level_checks):
        custom_thresh = CUSTOM_THRESHOLDS.get("gale", {}).get(level, threshold)
        if actual >= custom_thresh:
            bf, bf_name = get_beaufort_level(actual)
            triggered = (level, actual, bf, bf_name, custom_thresh)
            break

    if triggered:
        level, actual, bf, bf_name, thresh = triggered
        warnings_list.append({
            "type": "大风",
            "level": level,
            "level_num": GALE_WARNING[level]["level"],
            "detail": f"风速 {actual:.1f} m/s（{bf_name}，{bf}级），≥{thresh} m/s",
            "icon": GALE_WARNING[level]["icon"],
        })

    return warnings_list


def check_fog(df):
    """大雾预警检测"""
    warnings_list = []
    if "visibility" not in df.columns:
        return warnings_list

    vis = df["visibility"].dropna()
    if len(vis) == 0:
        return warnings_list

    min_vis = vis.tail(24).min()

    for level in ["红色", "橙色", "黄色"]:  # 从高到低检查
        threshold = CUSTOM_THRESHOLDS.get("fog", {}).get(level, FOG_WARNING[level]["visibility"])
        if min_vis <= threshold / 1000:  # 转换为km
            warnings_list.append({
                "type": "大雾",
                "level": level,
                "level_num": FOG_WARNING[level]["level"],
                "detail": f"最低能见度 {min_vis * 1000:.0f} m（＜{threshold} m）",
                "icon": FOG_WARNING[level]["icon"],
            })
            break

    return warnings_list


def check_rainstorm(df):
    """暴雨预警检测"""
    warnings_list = []
    if "precipitation" not in df.columns:
        return warnings_list

    precip = df["precipitation"].dropna()
    if len(precip) == 0 or precip.sum() == 0:
        return warnings_list

    # 滚动窗口求和
    rain_12h = precip.tail(12).sum() if len(precip) >= 12 else precip.sum()
    rain_6h = precip.tail(6).sum() if len(precip) >= 6 else precip.sum()
    rain_3h = precip.tail(3).sum() if len(precip) >= 3 else precip.sum()

    if rain_3h >= 100:
        level, detail = "红色", f"3h 降雨量 {rain_3h:.1f} mm（≥100 mm）"
    elif rain_3h >= 50:
        level, detail = "橙色", f"3h 降雨量 {rain_3h:.1f} mm（≥50 mm）"
    elif rain_6h >= 50:
        level, detail = "黄色", f"6h 降雨量 {rain_6h:.1f} mm（≥50 mm）"
    elif rain_12h >= 50:
        level, detail = "蓝色", f"12h 降雨量 {rain_12h:.1f} mm（≥50 mm）"
    else:
        return warnings_list

    warnings_list.append({
        "type": "暴雨",
        "level": level,
        "level_num": RAINSTORM_WARNING[level]["level"],
        "detail": detail,
        "icon": RAINSTORM_WARNING[level]["icon"],
    })

    return warnings_list


def check_frost(df):
    """霜冻预警检测（用气温近似地温）"""
    warnings_list = []
    if "temperature" not in df.columns:
        return warnings_list

    temps = df["temperature"].dropna()
    min_temp = temps.tail(24).min()

    if min_temp <= -5:
        level, detail = "橙色", f"最低气温 {min_temp:.1f}℃（≤-5℃）"
    elif min_temp <= -3:
        level, detail = "黄色", f"最低气温 {min_temp:.1f}℃（≤-3℃）"
    elif min_temp <= 0:
        level, detail = "蓝色", f"最低气温 {min_temp:.1f}℃（≤0℃）"
    else:
        return warnings_list

    warnings_list.append({
        "type": "霜冻",
        "level": level,
        "level_num": FROST_WARNING[level]["level"],
        "detail": detail,
        "icon": FROST_WARNING[level]["icon"],
    })

    return warnings_list


def check_thunderstorm(df):
    """雷电预警检测（基于天气码）"""
    if "weather_code" not in df.columns:
        return []

    codes = df["weather_code"].dropna().tail(6)
    thunder_codes = [95, 96, 97, 99]
    has_thunder = codes.isin(thunder_codes).any()

    if has_thunder:
        return [{
            "type": "雷电",
            "level": "黄色",
            "level_num": "Ⅲ级",
            "detail": "检测到雷暴天气码 (WMO 95-99)",
            "icon": "\u26a1",
        }]
    return []


def check_haze(df):
    """霾预警检测"""
    if "visibility" not in df.columns:
        return []

    vis = df["visibility"].dropna()
    if len(vis) == 0:
        return []

    min_vis = vis.tail(24).min() * 1000  # 转为米

    if min_vis < 2000:
        return [{
            "type": "霾",
            "level": "橙色",
            "level_num": "Ⅱ级",
            "detail": f"能见度 {min_vis:.0f} m（＜2000 m，可能为霾）",
            "icon": "\ud83d\udfe0",
        }]
    elif min_vis < 3000:
        return [{
            "type": "霾",
            "level": "黄色",
            "level_num": "Ⅲ级",
            "detail": f"能见度 {min_vis:.0f} m（＜3000 m，可能为霾）",
            "icon": "\ud83d\udfe1",
        }]
    return []


def multi_factor_coupling(df):
    """多要素耦合分析"""
    alerts = []

    if "temperature" not in df.columns or "humidity" not in df.columns:
        return alerts

    t = df["temperature"].dropna().tail(24)
    h = df["humidity"].dropna().tail(24)

    if len(t) < 6 or len(h) < 6:
        return alerts

    avg_t = t.mean()
    avg_h = h.mean()

    # 高温+高湿 → 热应激
    if avg_t >= 35 and avg_h >= 60:
        hi = -42.379 + 2.04901523 * avg_t + 10.14333127 * avg_h - \
             0.22475541 * avg_t * avg_h - 6.83783e-3 * avg_t ** 2 - \
             5.481717e-2 * avg_h ** 2 + 1.22874e-3 * avg_t ** 2 * avg_h + \
             8.5282e-4 * avg_t * avg_h ** 2 - 1.99e-6 * avg_t ** 2 * avg_h ** 2
        alerts.append({
            "type": "热应激（耦合）",
            "severity": "危险",
            "detail": f"高温 ({avg_t:.1f}℃) + 高湿 ({avg_h:.0f}%)，体感热指数 {hi:.1f}℃，注意防暑降温",
            "icon": "\ud83d\udd25",
        })

    # 气压骤降 + 高湿 → 降水可能性
    if "pressure" in df.columns:
        p = df["pressure"].dropna()
        if len(p) >= 6:
            p_drop = p.iloc[-6] - p.iloc[-1]
            if p_drop >= 3 and avg_h >= 70:
                alerts.append({
                    "type": "降水可能性（耦合）",
                    "severity": "注意",
                    "detail": f"气压骤降 {p_drop:.1f} hPa（6h）+ 高湿 ({avg_h:.0f}%)，出现降水的可能性较大",
                    "icon": "\ud83c\udf27\ufe0f",
                })

    # 低温 + 大风 → 风寒效应
    if avg_t <= 0 and "wind_speed" in df.columns:
        ws = df["wind_speed"].dropna().tail(24)
        if len(ws) >= 6 and ws.mean() >= 10.8:
            alerts.append({
                "type": "风寒效应（耦合）",
                "severity": "注意",
                "detail": f"低温 ({avg_t:.1f}℃) + 大风 ({ws.mean():.1f} m/s)，体感温度显著下降",
                "icon": "\ud83e\udd76",
            })

    return alerts


def generate_advice(warnings_list):
    """根据预警生成建议"""
    public_advices = []
    agri_advices = []

    for warn in warnings_list:
        w_type = warn["type"]
        level = warn["level"]

        if w_type in PUBLIC_ADVICE and level in PUBLIC_ADVICE[w_type]:
            public_advices.append(f"**{w_type}{level}预警** — {PUBLIC_ADVICE[w_type][level]}")

        if w_type in AGRI_ADVICE and level in AGRI_ADVICE[w_type]:
            agri_advices.append(f"**{w_type}{level}预警** — {AGRI_ADVICE[w_type][level]}")

    return public_advices, agri_advices


def render_analysis_tab(df):
    """渲染智能分析 Tab"""
    st.subheader("🚨 智能分析与建议")

    if df is None or df.empty:
        st.info("请先导入数据")
        return

    # ----- 预警检测 -----
    st.write("### 预警信号检测（国家气象预警标准）")

    all_warnings = []
    all_warnings += check_high_temperature(df)
    all_warnings += check_cold_wave(df)
    all_warnings += check_gale(df)
    all_warnings += check_fog(df)
    all_warnings += check_rainstorm(df)
    all_warnings += check_frost(df)
    all_warnings += check_thunderstorm(df)
    all_warnings += check_haze(df)

    if all_warnings:
        # 按严重程度排序（红>橙>黄>蓝）
        level_order = {"红色": 0, "橙色": 1, "黄色": 2, "蓝色": 3}
        all_warnings.sort(key=lambda w: level_order.get(w["level"], 4))

        cols = st.columns(min(len(all_warnings), 3))
        for i, warn in enumerate(all_warnings):
            style = WARN_STYLES.get(warn["level"], WARN_STYLES["蓝色"])
            with cols[i % 3]:
                st.markdown(f"""
                <div style="
                    background-color: {style['bg']};
                    border-left: 4px solid {style['color']};
                    padding: 12px 16px;
                    border-radius: 4px;
                    margin-bottom: 8px;
                ">
                    <div style="font-size: 18px; font-weight: bold; color: {style['color']};">
                        {warn['icon']} {warn['type']}{warn['level']}预警
                    </div>
                    <div style="font-size: 13px; color: #666; margin: 4px 0;">
                        {warn['level_num']} | {warn['detail']}
                    </div>
                </div>
                """, unsafe_allow_html=True)
    else:
        st.success("✅ 未触发任何预警信号")

    # ----- 耦合分析 -----
    st.write("---")
    st.write("### \ud83d\udd17 多要素耦合分析")
    coupling = multi_factor_coupling(df)
    if coupling:
        for alert in coupling:
            sev = "🔴" if alert["severity"] == "危险" else "🟡"
            st.warning(f"{sev} {alert['icon']} **{alert['type']}**: {alert['detail']}")
    else:
        st.info("当前未检测到显著的多要素耦合风险")

    # ----- 建议 -----
    st.write("---")
    public_adv, agri_adv = generate_advice(all_warnings)

    col1, col2 = st.columns(2)

    with col1:
        st.write("### 🚶 公众出行建议")
        if public_adv:
            for adv in public_adv:
                st.write(f"- {adv}")
        else:
            st.info("当前无特殊出行建议，天气状况良好。")

    with col2:
        st.write("### 🌾 农业生产建议")
        if agri_adv:
            for adv in agri_adv:
                st.write(f"- {adv}")
        else:
            st.info("当前无特殊农业生产建议，可正常开展农事活动。")

    # ----- 统计摘要 -----
    st.write("---")
    st.write("### 📊 数据统计摘要")
    stat_cols = st.columns(4)

    stats_config = [
        ("temperature", "平均气温", "℃", lambda x: x.mean(), stat_cols[0]),
        ("pressure", "平均气压", "hPa", lambda x: x.mean(), stat_cols[1]),
        ("humidity", "平均湿度", "%", lambda x: x.mean(), stat_cols[2]),
        ("wind_speed", "最大风速", "m/s", lambda x: x.max(), stat_cols[3]),
    ]

    for field, label, unit, func, col in stats_config:
        if field in df.columns:
            series = df[field].dropna()
            if len(series) > 0:
                val = func(series)
                col.metric(label, f"{val:.1f} {unit}")
