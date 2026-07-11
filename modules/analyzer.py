"""
分析建议引擎：历史事件检测（基于国家预警标准阈值）、多要素耦合分析、空气质量评估、公众出行/农业建议生成
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
    _AQI_BREAKPOINTS, AQI_LEVELS, AQI_ADVICE, AIR_POLLUTANT_LIMITS,
    get_beaufort_level,
)

# 可配置的事件检测规则（用户可在侧边栏自定义覆盖）
CUSTOM_THRESHOLDS = {}


def set_custom_thresholds(custom):
    global CUSTOM_THRESHOLDS
    CUSTOM_THRESHOLDS = custom


def check_high_temperature(df):
    """高温事件检测"""
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
    """寒潮事件检测"""
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
    """大风事件检测"""
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
    """大雾事件检测"""
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
    """暴雨事件检测"""
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
    """霜冻事件检测（用气温近似地温）"""
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
    """雷电事件检测（基于天气码）"""
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
    """霾事件检测"""
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


# ============================================================
# 大气环境质量评估 (GB 3095-2026 + HJ 633-2026)
# ============================================================

def _calc_single_aqi(conc, pollutant):
    """计算单个污染物的AQI分指数 (IAQI)"""
    if pollutant not in _AQI_BREAKPOINTS or np.isnan(conc):
        return 0
    bp = _AQI_BREAKPOINTS[pollutant]
    for (clo, chi, ilo, ihi) in bp:
        if clo <= conc <= chi:
            return (ihi - ilo) / (chi - clo) * (conc - clo) + ilo
    return 0


def _aqi_level_name(aqi):
    """AQI → 等级标签"""
    for lv, info in sorted(AQI_LEVELS.items()):
        lo, hi = info["range"]
        if lo <= aqi <= hi:
            return info["label"], info["color"]
    return "严重污染", "#7e0023"


def check_air_quality(df):
    """
    基于 HJ 633-2012 计算综合 AQI + 逐污染物分析 + 健康建议
    返回: (综合AQI, 首要污染物, 等级标签, 逐项检测结果列表)
    """
    pollutant_fields = [
        ("so2",  "SO₂"),
        ("nox",  "NO₂"),
        ("pm10", "PM10"),
        ("pm25", "PM2.5"),
    ]
    available = [(field, label) for field, label in pollutant_fields
                 if field in df.columns and df[field].dropna().any()]

    if not available:
        return None

    results = []
    max_iaqi = 0
    primary_pollutant = None

    for field, label in available:
        vals = df[field].dropna()
        if len(vals) == 0:
            continue

        avg_conc = vals.mean()
        max_conc = vals.max()

        # 计算日均值的AQI分指数
        iaqi = round(_calc_single_aqi(avg_conc, field))
        if iaqi > max_iaqi:
            max_iaqi = iaqi
            primary_pollutant = label

        # 达标判断 (GB 3095-2026 二级标准)
        limits = AIR_POLLUTANT_LIMITS.get(field, {})
        daily_limit = limits.get("daily")

        hourly_limit = limits.get("hourly")
        exceed_daily = avg_conc > daily_limit if daily_limit else False
        exceed_hourly = max_conc > hourly_limit if hourly_limit and hourly_limit else False

        label_name, color = _aqi_level_name(iaqi)

        results.append({
            "field": field,
            "label": label,
            "avg": round(avg_conc, 1),
            "max": round(max_conc, 1),
            "iaqi": iaqi,
            "level": label_name,
            "color": color,
            "limit": daily_limit,
            "exceed_daily": exceed_daily,
            "exceed_hourly": exceed_hourly,
        })

    overall_level, overall_color = _aqi_level_name(max_iaqi)

    return {
        "aqi": max_iaqi,
        "primary": primary_pollutant,
        "level": overall_level,
        "color": overall_color,
        "advice": AQI_ADVICE.get(overall_level, ""),
        "details": results,
    }


def _render_air_quality_section(df):
    """渲染空气质量评估区域"""
    result = check_air_quality(df)
    if result is None:
        st.info("当前数据中未检测到大气污染物字段 (SO₂/NOx/PM2.5/PM10)，无法进行空气质量评估。")
        return

    aqi = result["aqi"]
    level = result["level"]
    color = result["color"]
    primary = result["primary"] or "无"

    # ---- AQI 概览卡 ----
    st.markdown(f"""
    <div style="
        background: linear-gradient(135deg, {color}22 0%, {color}08 100%);
        border: 2px solid {color};
        border-radius: 12px;
        padding: 20px 24px;
        margin: 12px 0;
        text-align: center;
    ">
        <div style="font-size: 0.85rem; color: {'#94a3b8' if st.session_state.get('dark_mode', False) else '#888'}; margin-bottom: 4px;">空气质量指数 (AQI)</div>
        <div style="font-size: 3rem; font-weight: 800; color: {color}; line-height: 1.1;">{aqi}</div>
        <div style="font-size: 1.2rem; font-weight: 600; color: {color}; margin: 4px 0;">{level}</div>
        <div style="font-size: 0.82rem; color: {'#94a3b8' if st.session_state.get('dark_mode', False) else '#666'};">首要污染物: {primary}</div>
    </div>
    """, unsafe_allow_html=True)

    st.caption(result["advice"])

    # ---- 逐项详情表 ----
    detail_rows = []
    for d in result["details"]:
        flag = ""
        if d["exceed_daily"]:
            flag = " ⚠️ 超标"
        elif d["exceed_hourly"]:
            flag = " ⚡ 小时超标"
        detail_rows.append({
            "污染物": d["label"],
            f"均值 (μg/m³)": d["avg"],
            f"峰值 (μg/m³)": d["max"],
            "标准限值": f"{d['limit']} μg/m³" if d["limit"] else "—",
            "IAQI": d["iaqi"],
            "等级": d["level"],
            "状态": "✓ 达标" if not d["exceed_daily"] else flag.strip(),
        })

    st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)

    # ---- 超标警告 ----
    exceeded = [d for d in result["details"] if d["exceed_daily"] or d["exceed_hourly"]]
    if exceeded:
        st.warning("⚠️ 以下污染物超过 GB 3095-2026 二级标准限值：")
        for e in exceeded:
            limit_type = "日均值" if e["exceed_daily"] else "小时值"
            st.write(f"- {e['label']}: 均 {e['avg']} μg/m³ / 峰 {e['max']} μg/m³ (超过{e['limit']} 的{limit_type}限值)")


def _render_nwp_analysis_section(nwp_df):
    """P1: 基于数值预报数据的智能分析"""
    if nwp_df is None or nwp_df.empty:
        return

    advices = []

    # 温度分析
    temp_col = "temperature" if "temperature" in nwp_df.columns else "temperature_2m" if "temperature_2m" in nwp_df.columns else None
    if temp_col:
        temps = nwp_df[temp_col].dropna()
        max_temp = temps.max()
        avg_temp = temps.mean()
        hot_count = (temps >= 35).sum()
        cold_count = (temps <= 0).sum()

        st.markdown(f"""
        **温度预报**：最高 {max_temp:.1f}℃ | 平均 {avg_temp:.1f}℃ | {len(temps)} 小时预报
        """)
        if hot_count > 0:
            advices.append(f"高温预警：预报期内有 {hot_count} 小时≥35℃，做好防暑准备。")
        if cold_count > 0:
            advices.append(f"低温预警：预报期内有 {cold_count} 小时≤0℃，注意防寒保暖。")

    # 降水分析
    precip_col = "precipitation" if "precipitation" in nwp_df.columns else "precipitation_sum" if "precipitation_sum" in nwp_df.columns else None
    if precip_col:
        precip = nwp_df[precip_col].dropna()
        total_p = precip.sum()
        heavy_p = (precip > 10).sum()

        st.markdown(f"**降水预报**：累计 {total_p:.1f}mm")
        if total_p > 100:
            advices.append(f"暴雨风险：预报累计降水 {total_p:.1f}mm，可能引发城市内涝，请关注。")
        elif total_p > 50:
            advices.append(f"大雨预警：预报累计降水 {total_p:.1f}mm，注意防汛。")
        elif total_p < 1:
            advices.append("干旱趋势：预报期内几乎无降水，注意节水。")

    # 风速分析
    wind_col = "wind_speed" if "wind_speed" in nwp_df.columns else "wind_speed_10m" if "wind_speed_10m" in nwp_df.columns else None
    if wind_col:
        winds = nwp_df[wind_col].dropna()
        max_wind = winds.max()
        gale = (winds > 10.7).sum()
        st.markdown(f"**风速预报**：最大 {max_wind:.1f} m/s | 强风时段 {gale} 小时")
        if gale > 0:
            advices.append(f"大风注意：预报有 {gale} 小时风速≥六级，户外作业注意安全。")

    if advices:
        st.write("---")
        for a in advices:
            st.warning(a)
    else:
        st.success("预报期内无明显极端天气风险。")


def _render_trend_section(df):
    """趋势分析与异常检测"""
    st.write("### [趋势] 要素趋势与异常检测")

    trend_fields = ["temperature", "humidity", "pressure", "wind_speed",
                   "pm25", "pm10", "so2", "nox"]
    available = [f for f in trend_fields if f in df.columns and not df[f].dropna().empty]
    if not available:
        st.info("暂无足够数据用于趋势分析")
        return

    labels = {
        "temperature": "气温", "humidity": "湿度", "pressure": "气压",
        "wind_speed": "风速", "pm25": "PM2.5", "pm10": "PM10",
        "so2": "SO₂", "nox": "NOx",
    }

    results = []
    import numpy as np

    for field in available[:6]:  # 最多6个要素
        vals = df[field].dropna()
        if len(vals) < 10:
            continue

        # 简单线性趋势 (按索引序号)
        x = np.arange(len(vals))
        slope, intercept = np.polyfit(x, vals.values, 1)
        trend_line = slope * x + intercept
        change_rate = slope * len(vals)  # 全程变化量

        # 异常检测 (IQR)
        q1, q3 = np.percentile(vals, [25, 75])
        iqr = q3 - q1
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr
        anomalies = vals[(vals < lower) | (vals > upper)]
        n_anomalies = len(anomalies)

        trend_dir = "↑ 上升" if slope > 0 else "↓ 下降" if slope < 0 else "→ 平稳"
        results.append({
            "要素": labels.get(field, field),
            "均值": f"{vals.mean():.1f}",
            "趋势": trend_dir,
            "变化量": f"{change_rate:+.2f}",
            "异常点": f"{n_anomalies}/{len(vals)}",
            "状态": "⚠️ 关注" if abs(change_rate) > vals.std() * 2 or n_anomalies > len(vals) * 0.05 else "✓ 正常",
        })

    if results:
        st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)
        st.caption("趋势基于线性回归斜率，异常点基于 IQR 方法 (Q1-1.5IQR ~ Q3+1.5IQR)")


def _render_smart_advice(df):
    """智能综合分析建议"""
    st.write("### [建议] 智能综合分析建议")

    advices = []
    has_temp = "temperature" in df.columns
    has_precip = "precipitation" in df.columns
    has_pm25 = "pm25" in df.columns

    if has_temp:
        temps = df["temperature"].dropna()
        if len(temps) >= 24:
            avg_temp = temps.mean()
            max_temp = temps.max()
            if max_temp >= 35:
                advices.append(f"🔥 高温事件: 最高气温达 {max_temp:.1f}℃，建议做好防暑降温，户外工作者注意防护。")
            elif avg_temp > 30:
                advices.append(f"☀️ 气温偏高: 平均 {avg_temp:.1f}℃，注意补水防晒。")

    if has_precip:
        precip = df["precipitation"].dropna()
        total_p = precip.sum()
        if total_p > 50:
            advices.append(f"🌧️ 累计降水量 {total_p:.1f}mm，需关注城市内涝和地质灾害风险。")
        elif total_p < 5 and len(precip) >= 24:
            advices.append(f"🏜️ 累计降水仅 {total_p:.1f}mm，存在干旱风险，注意节水灌溉。")

    if has_pm25:
        pm25 = df["pm25"].dropna()
        avg_pm25 = pm25.mean()
        exceed_rate = (pm25 > 50).sum() / len(pm25) * 100
        if avg_pm25 > 50:
            advices.append(f"😷 PM2.5 均值 {avg_pm25:.1f}μg/m³ (超标率 {exceed_rate:.0f}%)，建议减少户外活动，敏感人群佩戴口罩。")
        elif avg_pm25 > 35:
            advices.append(f"🟡 PM2.5 偏高达 {avg_pm25:.1f}μg/m³，敏感人群注意防护。")

    # 温湿耦合
    if has_temp and "humidity" in df.columns:
        temps = df["temperature"].dropna()
        humids = df["humidity"].dropna()
        if len(temps) >= 10 and len(humids) >= 10:
            hi = temps.mean() + 0.05 * humids.mean()  # 简化热指数
            if hi > 35:
                advices.append(f"🥵 高温高湿 (热指数≈{hi:.0f})，中暑风险高，避免长时间户外活动。")

    # 风-污染物耦合
    if has_pm25 and "wind_speed" in df.columns and len(df) >= 10:
        corr = df[["pm25", "wind_speed"]].corr().iloc[0, 1]
        if corr < -0.3:
            advices.append(f"💨 风速与 PM2.5 呈负相关 (r={corr:.2f})，大风天气有利于污染物扩散。")

    if advices:
        for a in advices:
            st.write(f"- {a}")
    else:
        st.info("当前数据未触发特殊建议，各项指标均在正常范围。")


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
    """根据检测到的事件生成建议"""
    public_advices = []
    agri_advices = []

    for warn in warnings_list:
        w_type = warn["type"]
        level = warn["level"]

        if w_type in PUBLIC_ADVICE and level in PUBLIC_ADVICE[w_type]:
            public_advices.append(f"**{w_type}{level}事件** — {PUBLIC_ADVICE[w_type][level]}")

        if w_type in AGRI_ADVICE and level in AGRI_ADVICE[w_type]:
            agri_advices.append(f"**{w_type}{level}事件** — {AGRI_ADVICE[w_type][level]}")

    return public_advices, agri_advices


def render_analysis_tab(df):
    """渲染智能分析 Tab"""
    st.subheader("[检测] 智能分析与建议")

    if df is None or df.empty:
        st.info("请先导入数据")
        return

    # ----- 事件检测 -----
    st.write("### 历史事件检测（参照国家气象预警阈值标准）")

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
        is_dark = st.session_state.get("dark_mode", False)
        dark_styles = {
            "蓝色": {"color": "#60a5fa", "bg": "#1e3a5f", "text_color": "white"},
            "黄色": {"color": "#f59e0b", "bg": "#3d2e0c", "text_color": "#e2e8f0"},
            "橙色": {"color": "#fb923c", "bg": "#3d1f0c", "text_color": "white"},
            "红色": {"color": "#ef4444", "bg": "#3d0c0c", "text_color": "white"},
        }
        for i, warn in enumerate(all_warnings):
            style = dark_styles.get(warn["level"], dark_styles["蓝色"]) if is_dark else WARN_STYLES.get(warn["level"], WARN_STYLES["蓝色"])
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
                        {warn['icon']} {warn['type']}{warn['level']}事件
                    </div>
                    <div style="font-size: 13px; color: {'#94a3b8' if is_dark else '#666'}; margin: 4px 0;">
                        {warn['level_num']} | {warn['detail']}
                    </div>
                </div>
                """, unsafe_allow_html=True)
    else:
        st.success("[OK] 未检测到符合阈值的事件")

    # ----- 耦合分析 -----
    st.write("---")
    st.write("### [链] 多要素耦合分析")
    coupling = multi_factor_coupling(df)
    if coupling:
        for alert in coupling:
            sev = "[红]" if alert["severity"] == "危险" else "[黄]"
            st.warning(f"{sev} {alert['icon']} **{alert['type']}**: {alert['detail']}")
    else:
        st.info("当前未检测到显著的多要素耦合风险")

    # ----- 空气质量评估 -----
    # 检测是否有污染物数据
    has_pollution = any(f in df.columns for f in ["so2", "nox", "pm10", "pm25"])
    if has_pollution:
        st.write("---")
        st.write("### [大气] 空气质量评估 (GB 3095-2026)")
        _render_air_quality_section(df)

    # ----- 建议 -----
    st.write("---")
    public_adv, agri_adv = generate_advice(all_warnings)

    col1, col2 = st.columns(2)

    with col1:
        st.write("### [出行] 公众出行建议")
        if public_adv:
            for adv in public_adv:
                st.write(f"- {adv}")
        else:
            st.info("当前无特殊出行建议，天气状况良好。")

    with col2:
        st.write("### [农业] 农业生产建议")
        if agri_adv:
            for adv in agri_adv:
                st.write(f"- {adv}")
        else:
            st.info("当前无特殊农业生产建议，可正常开展农事活动。")

    # ----- 统计摘要 -----
    st.write("---")
    st.write("### [统计] 数据统计摘要")
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

    # 污染物统计行（有数据时才显示）
    has_pollution = any(f in df.columns for f in ["so2", "nox", "pm10", "pm25"])
    if has_pollution:
        poll_cols = st.columns(4)
        poll_stats = [
            ("pm25", "PM2.5 均值", "μg/m³", lambda x: x.mean(), poll_cols[0]),
            ("pm10", "PM10 均值", "μg/m³", lambda x: x.mean(), poll_cols[1]),
            ("so2",  "SO₂ 均值",  "μg/m³", lambda x: x.mean(), poll_cols[2]),
            ("nox",  "NOx 均值",  "μg/m³", lambda x: x.mean(), poll_cols[3]),
        ]
        for field, label, unit, func, col in poll_stats:
            if field in df.columns:
                series = df[field].dropna()
                if len(series) > 0:
                    val = func(series)
                    col.metric(label, f"{val:.1f} {unit}")

    # ----- 趋势分析与异常检测 -----
    st.write("---")
    _render_trend_section(df)

    # ----- 数值预报驱动分析 (P1) -----
    nwp_df = st.session_state.get("nwp_forecast_for_analysis")
    if nwp_df is not None:
        st.write("---")
        st.write("### [预报] 数值预报驱动分析")
        st.caption("以下分析基于 Open-Meteo 数值预报模型数据")
        _render_nwp_analysis_section(nwp_df)

    # ----- 综合建议 -----
    st.write("---")
    _render_smart_advice(df)
