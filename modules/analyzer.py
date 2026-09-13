"""
国标事件检测与建议引擎。

职责边界：本模块只做**纯逻辑**——8 类国家预警标准的事件检测、多要素耦合分析、
按事件生成公众出行与农业建议。它不渲染任何 Tab：
- 读图解析页见 ``modules/chart_reader``；
- 空气质量分指数见 ``modules/aqi``（本模块已不再自行计算 AQI）；
- 报告导出见 ``modules/reporter``。

``multi_factor_coupling`` 与 ``generate_advice`` 目前没有生产调用者（检测结果由
``app.py`` 顶层汇总后交给报告导出），保留为公开逻辑并由测试覆盖。
"""

import pandas as pd

from config import (
    HIGH_TEMP_WARNING, COLD_WAVE_WARNING, GALE_WARNING,
    FOG_WARNING, RAINSTORM_WARNING, FROST_WARNING,
    THUNDER_WARNING, HAZE_WARNING,
    PUBLIC_ADVICE, AGRI_ADVICE,
    get_beaufort_level,
)

# 可配置的事件检测规则（用户可在侧边栏自定义覆盖）
CUSTOM_THRESHOLDS = {}


def set_custom_thresholds(custom):
    global CUSTOM_THRESHOLDS
    CUSTOM_THRESHOLDS = custom


def heat_index_celsius(t_c, rh):
    """Rothfusz 热指数：摄氏度输入、摄氏度输出（修复 R-27 / R-29）。

    该回归式的系数以华氏度为单位（NWS 标准式），必须先换算到 °F 计算、
    再把结果换回 ℃；否则 36℃/70% 会算出 146.8℃ 这种物理上不可能的值。
    原先代码里另有一处 `mean(t) + 0.05*mean(rh)` 的简化式，现统一到本函数。
    """
    tf = float(t_c) * 9.0 / 5.0 + 32.0
    rh = float(rh)
    hi_f = (-42.379 + 2.04901523 * tf + 10.14333127 * rh
            - 0.22475541 * tf * rh - 6.83783e-3 * tf ** 2
            - 5.481717e-2 * rh ** 2 + 1.22874e-3 * tf ** 2 * rh
            + 8.5282e-4 * tf * rh ** 2 - 1.99e-6 * tf ** 2 * rh ** 2)
    return (hi_f - 32.0) * 5.0 / 9.0


def check_high_temperature(df):
    """高温事件检测

    修复 R-30：等级从高到低判定，红色分支不再不可达（原实现「橙→红」顺序
    首个命中即 break，41℃ 只报橙色）。
    修复 R-14：黄色阈值与连续天数改读 config，可被侧边栏自定义覆盖。
    修复 R-32：timestamp 先做 to_datetime 转换，字符串时间列不再抛
    AttributeError 导致整页检测中断。
    """
    warnings_list = []
    if "temperature" not in df.columns:
        return warnings_list

    temps = pd.to_numeric(df["temperature"], errors="coerce").dropna()
    if len(temps) < 24:  # 至少24条小时数据
        return warnings_list

    cfg = HIGH_TEMP_WARNING
    yellow_cfg = cfg["黄色"]
    custom = CUSTOM_THRESHOLDS.get("high_temp", {})

    # 检查连续 N 天日最高气温≥阈值
    if "timestamp" in df.columns:
        ts = pd.to_datetime(df["timestamp"], errors="coerce")
        valid = ts.notna()
        if valid.any():
            daily = pd.DataFrame({
                "date": ts[valid].dt.date,
                "temperature": pd.to_numeric(df.loc[valid, "temperature"], errors="coerce"),
            }).dropna()
            if not daily.empty:
                yellow_temp = custom.get("黄色", yellow_cfg["temp"])
                need_days = yellow_cfg.get("days", 3)
                daily_max = daily.groupby("date")["temperature"].max()
                consecutive = max_consecutive = 0
                for hit in (daily_max >= yellow_temp):
                    consecutive = consecutive + 1 if hit else 0
                    max_consecutive = max(max_consecutive, consecutive)
                if max_consecutive >= need_days:
                    warnings_list.append({
                        "type": "高温",
                        "level": "黄色",
                        "level_num": yellow_cfg["level"],
                        "detail": f"已连续 {max_consecutive} 天日最高气温≥{yellow_temp}℃",
                        "icon": yellow_cfg["icon"],
                    })

    # 检查24h内最高气温：从高到低判级，只取最高级别
    max_recent = temps.tail(24).max()
    for level in ["红色", "橙色"]:
        threshold = custom.get(level, cfg[level]["temp"])
        if max_recent >= threshold:
            warnings_list.append({
                "type": "高温",
                "level": level,
                "level_num": cfg[level]["level"],
                "detail": f"24h 内最高气温达 {max_recent:.1f}℃，≥{threshold}℃",
                "icon": cfg[level]["icon"],
            })
            break  # 只取最高级别

    return warnings_list


def check_cold_wave(df):
    """寒潮事件检测

    修复 R-31：等级从高到低判定，最强级优先（原实现「蓝→黄→橙→红」顺序
    首个命中即返回，48h 降温 30℃ 只报蓝色）。
    修复 R-34：数据不足 49 条时蓝色（48h 口径）改为跳过，不再把 48h 降温
    硬置为 0。
    修复 R-14：降温与最低气温阈值统一读 config，并支持自定义覆盖。
    """
    warnings_list = []
    if "temperature" not in df.columns:
        return warnings_list

    temps = pd.to_numeric(df["temperature"], errors="coerce").dropna()
    if len(temps) < 24:
        return warnings_list

    t_now = float(temps.iloc[-1])
    t_24h_ago = float(temps.iloc[-25]) if len(temps) >= 25 else float(temps.iloc[0])
    drop_24h = t_24h_ago - t_now  # 降温为正
    drop_48h = (float(temps.iloc[-49]) - t_now) if len(temps) >= 49 else None
    min_temp = float(temps.tail(24).min())

    custom = CUSTOM_THRESHOLDS.get("cold_wave", {})
    checks = [
        ("红色", drop_24h),
        ("橙色", drop_24h),
        ("黄色", drop_24h),
        ("蓝色", drop_48h),
    ]

    for level, drop in checks:
        if drop is None:
            continue
        cfg = COLD_WAVE_WARNING[level]
        drop_thresh = custom.get(level, {}).get("temp_drop", cfg["temp_drop"])
        min_thresh = custom.get(level, {}).get("min_temp", cfg["min_temp"])
        if drop >= drop_thresh and min_temp <= min_thresh:
            warnings_list.append({
                "type": "寒潮",
                "level": level,
                "level_num": cfg["level"],
                "detail": (f"降温 {drop:.1f}℃（≥{drop_thresh}℃），"
                           f"最低气温 {min_temp:.1f}℃（≤{min_thresh}℃）"),
                "icon": cfg["icon"],
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
    """大雾事件检测

    修复 R-36：判据改为严格小于，与 config 的「能见度<Xm」措辞一致
    （原实现用 `<=`，能见度恰好 500 m 也会输出「＜500 m」）。
    """
    warnings_list = []
    if "visibility" not in df.columns:
        return warnings_list

    vis = pd.to_numeric(df["visibility"], errors="coerce").dropna()
    if len(vis) == 0:
        return warnings_list

    min_vis_m = float(vis.tail(24).min()) * 1000  # 转为米

    for level in ["红色", "橙色", "黄色"]:  # 从高到低检查
        threshold = CUSTOM_THRESHOLDS.get("fog", {}).get(level, FOG_WARNING[level]["visibility"])
        if min_vis_m < threshold:
            warnings_list.append({
                "type": "大雾",
                "level": level,
                "level_num": FOG_WARNING[level]["level"],
                "detail": f"最低能见度 {min_vis_m:.0f} m（＜{threshold} m）",
                "icon": FOG_WARNING[level]["icon"],
            })
            break

    return warnings_list


def check_rainstorm(df):
    """暴雨事件检测

    修复 R-14：阈值改读 RAINSTORM_WARNING，支持自定义覆盖。
    修复 R-37：增加最小样本长度校验（原实现 2 条数据即可报橙色）。
    """
    warnings_list = []
    if "precipitation" not in df.columns:
        return warnings_list

    precip = pd.to_numeric(df["precipitation"], errors="coerce").dropna()
    if len(precip) < 3 or precip.sum() == 0:
        return warnings_list

    # 滚动窗口求和
    rain_12h = precip.tail(12).sum()
    rain_6h = precip.tail(6).sum()
    rain_3h = precip.tail(3).sum()

    custom = CUSTOM_THRESHOLDS.get("rainstorm", {})

    def _thr(level):
        return custom.get(level, RAINSTORM_WARNING[level]["rain"])

    if rain_3h >= _thr("红色"):
        level = "红色"
        detail = f"3h 降雨量 {rain_3h:.1f} mm（≥{_thr('红色')} mm）"
    elif rain_3h >= _thr("橙色"):
        level = "橙色"
        detail = f"3h 降雨量 {rain_3h:.1f} mm（≥{_thr('橙色')} mm）"
    elif rain_6h >= _thr("黄色"):
        level = "黄色"
        detail = f"6h 降雨量 {rain_6h:.1f} mm（≥{_thr('黄色')} mm）"
    elif rain_12h >= _thr("蓝色"):
        level = "蓝色"
        detail = f"12h 降雨量 {rain_12h:.1f} mm（≥{_thr('蓝色')} mm）"
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
    """霜冻事件检测（用气温近似地温，见 R-38）

    修复 R-14：阈值改读 FROST_WARNING，支持自定义覆盖，等级从高到低判定。
    """
    warnings_list = []
    if "temperature" not in df.columns:
        return warnings_list

    temps = pd.to_numeric(df["temperature"], errors="coerce").dropna()
    if len(temps) == 0:
        return warnings_list

    min_temp = float(temps.tail(24).min())
    custom = CUSTOM_THRESHOLDS.get("frost", {})

    for level in ["橙色", "黄色", "蓝色"]:
        cfg = FROST_WARNING[level]
        threshold = custom.get(level, cfg["ground_temp"])
        if min_temp <= threshold:
            warnings_list.append({
                "type": "霜冻",
                "level": level,
                "level_num": cfg["level"],
                "detail": f"最低气温 {min_temp:.1f}℃（≤{threshold}℃，以气温近似地温）",
                "icon": cfg["icon"],
            })
            break
    return warnings_list


def check_thunderstorm(df):
    """雷电事件检测（基于天气码）

    修复 R-14：等级与图标改读 THUNDER_WARNING（原为硬编码字符串）。
    修复 R-39：窗口改为「最近 6 小时」而非最近 6 条记录，避免窗口外漏报。

    说明：WMO 天气码无法区分国标橙/红两级（那属预报口径），观测侧固定黄色。
    """
    if "weather_code" not in df.columns:
        return []

    codes = pd.to_numeric(df["weather_code"], errors="coerce")
    if len(codes.dropna()) < 3:
        return []  # 修复 R-37：与暴雨一致，要求最小样本长度
    thunder_codes = [95, 96, 97, 99]
    is_thunder = codes.isin(thunder_codes)
    # R-14 补齐：检测窗口可在侧边栏调整
    window_hours = float(CUSTOM_THRESHOLDS.get("thunder", {}).get("hours", 6) or 6)

    if "timestamp" in df.columns:
        ts = pd.to_datetime(df["timestamp"], errors="coerce")
        if ts.notna().any():
            last_ts = ts.max()
            in_window = ts >= (last_ts - pd.Timedelta(hours=window_hours))
            has_thunder = bool((is_thunder & in_window).any())
        else:
            has_thunder = bool(is_thunder.any())
    else:
        has_thunder = bool(codes.dropna().tail(6).isin(thunder_codes).any())

    if not has_thunder:
        return []

    cfg = THUNDER_WARNING["黄色"]
    return [{
        "type": "雷电",
        "level": "黄色",
        "level_num": cfg["level"],
        "detail": f"最近 {window_hours:g} 小时内检测到雷暴天气码 (WMO 95-99)",
        "icon": cfg["icon"],
    }]


def check_haze(df):
    """霾事件检测

    修复 R-33：霾只在能见度不低于大雾黄色阈值（默认 500 m）时判定，
    避免同一观测同时报「大雾」与「霾」的矛盾结论。
    修复 R-14：阈值改读 HAZE_WARNING，支持自定义覆盖。
    """
    if "visibility" not in df.columns:
        return []

    vis = pd.to_numeric(df["visibility"], errors="coerce").dropna()
    if len(vis) == 0:
        return []

    min_vis = float(vis.tail(24).min()) * 1000  # 转为米
    if min_vis < FOG_WARNING["黄色"]["visibility"]:
        return []  # 低于大雾黄色阈值，归入大雾，不重复报霾

    custom = CUSTOM_THRESHOLDS.get("haze", {})
    for level in ["橙色", "黄色"]:
        cfg = HAZE_WARNING[level]
        threshold = custom.get(level, cfg["visibility"])
        if min_vis < threshold:
            return [{
                "type": "霾",
                "level": level,
                "level_num": cfg["level"],
                "detail": f"能见度 {min_vis:.0f} m（＜{threshold} m，可能为霾）",
                "icon": cfg["icon"],
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
        # 修复 R-29：改用统一的热指数函数（先换算 °F 再回归、结果换回 ℃）
        hi = heat_index_celsius(avg_t, avg_h)
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


