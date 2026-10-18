"""GFS 预报的纯计算层。

不 import streamlit，也不读会话状态，可独立单测。页面渲染与网络请求留在
modules/nwp_forecast.py，本模块只负责：热指数、舒适度、生活指数、预警分析。
"""

import numpy as np
import pandas as pd

from config import level_label
from modules import warn_rules



def heat_index(temp_c, rh):
    """Rothfusz 热指数 (℃)。

    仅在 T >= 26.7℃ 且 RH > 40% 时有效，其余返回 NaN。
    用于高温预报面板中作为「计算热指数」参考。
    """
    t = np.asarray(temp_c, dtype=float)
    r = np.asarray(rh, dtype=float)
    hi = np.full_like(t, np.nan, dtype=float)
    mask = (t >= 26.7) & (r > 40)
    if not mask.any():
        return hi
    tt = t[mask]
    rr = r[mask]
    hi_val = (
        -8.78469475556
        + 1.61139411 * tt
        + 2.338548842 * rr
        - 0.14611605 * tt * rr
        - 0.012308094 * tt ** 2
        - 0.016424828 * rr ** 2
        + 0.002211732 * tt ** 2 * rr
        + 0.00072546 * tt * rr ** 2
        - 0.000003582 * tt ** 2 * rr ** 2
    )
    hi[mask] = hi_val
    return hi


def _analyze_forecast(fdf):
    """分析 GFS 预报数据（增强版：6h 滚动 + 趋势置信 + 连续事件 + 昼夜温差）。

    返回 dict：
      warnings, extremes, trends, coupling, summary, recommendations,
      precision (新增: 趋势数值详情, 6h断片, 连续事件, 日较差)
    """
    daily = fdf.copy()
    daily["date"] = fdf["timestamp"].dt.date
    # 6h 滚动窗口
    daily["hour6"] = daily["timestamp"].dt.floor("6h")

    dmax_t = daily.groupby("date")["temperature"].max()
    dmin_t = daily.groupby("date")["temperature"].min()
    dprecip = daily.groupby("date")["precipitation"].sum()
    dmax_ws = daily.groupby("date")["wind_speed"].max()
    davg_rh = daily.groupby("date")["humidity"].mean()
    # 昼夜温差
    diurnal = dmax_t - dmin_t

    # 6h 聚合：温度和降水
    h6_temp = daily.groupby("hour6")["temperature"].max()
    h6_precip = daily.groupby("hour6")["precipitation"].sum()

    ndays = len(dmax_t)
    results = {
        "warnings": [],
        "extremes": {},
        "trends": {},
        "coupling": [],
        "summary": "",
        "recommendations": {"travel": [], "agri": []},
        "precision": {},  # 新增精度信息
    }

    # ----- 1. 高温预警（含连续事件检测）-----
    # 阈值与等级串统一走 modules/warn_rules，自定义阈值在预报侧同样生效。
    _high = warn_rules.high_temp_levels()
    hot = dmax_t[dmax_t >= _high["黄色"]]
    # 连续高温检测
    consecutive_hot = 0
    max_consec_hot = 0
    hot_streak_dates = []
    for d, val in dmax_t.items():
        if val >= _high["黄色"]:
            consecutive_hot += 1
            if consecutive_hot > max_consec_hot:
                max_consec_hot = consecutive_hot
                hot_streak_dates = list(dmax_t.index)[max(0, dmax_t.index.get_loc(d) - consecutive_hot + 1):dmax_t.index.get_loc(d) + 1]
        else:
            consecutive_hot = 0
    results["precision"]["consecutive_hot"] = max_consec_hot
    results["precision"]["hot_streak"] = [str(d) for d in hot_streak_dates]

    if len(hot) > 0:
        peak = hot.max()
        peak_date = str(hot.idxmax())
        if peak >= _high["红色"]:
            level, icon_ = "红色", "[红]"
        elif peak >= _high["橙色"]:
            level, icon_ = "橙色", "[橙]"
        else:
            level, icon_ = "黄色", "[黄]"
        lv_num = level_label(level)
        hot_detail = f"未来{ndays}天中{len(hot)}天日最高气温>={_high['黄色']:.0f}C，峰值{peak:.1f}C ({peak_date})"
        if max_consec_hot >= 3:
            # dmax_t 的索引是 datetime.date，拼进文案前必须先转字符串；
            # 原实现直接 join 日期对象，连续 3 天高温时会抛 TypeError。
            streak_text = [str(d) for d in hot_streak_dates]
            hot_detail += f"，其中连续{max_consec_hot}天高温（"
            hot_detail += ("~".join(streak_text[:2]) if len(streak_text) >= 2
                           else streak_text[0])
            hot_detail += "）"
        hot_detail += "。"
        results["warnings"].append({
            "type": "高温", "level": level, "level_num": lv_num,
            "detail": hot_detail, "icon": icon_,
        })

    # ----- 2. 暴雨预警（含连续降水检测 + 强度分类）-----
    # 预报侧按日累计降水量判定，阈值集中在 warn_rules.DAILY_RAIN_LEVELS。
    _rain = warn_rules.DAILY_RAIN_LEVELS
    precip_cats = {"大雨(25-50mm)": 0, "暴雨(50-100mm)": 0, "大暴雨(>=100mm)": 0}
    heavy = dprecip[dprecip >= _rain["大雨"]]
    consecutive_rain = 0
    max_consec_rain = 0
    for d, val in dprecip.items():
        if val >= 0.1:
            consecutive_rain += 1
            max_consec_rain = max(max_consec_rain, consecutive_rain)
        else:
            consecutive_rain = 0
    results["precision"]["consecutive_rain"] = max_consec_rain

    for d, val in dprecip.items():
        if val >= _rain["红色"]:
            precip_cats["大暴雨(>=100mm)"] += 1
            lv = "红色"
        elif val >= _rain["橙色"]:
            precip_cats["暴雨(50-100mm)"] += 1
            lv = "橙色"
        elif val >= _rain["黄色"]:
            precip_cats["暴雨(50-100mm)"] += 1
            lv = "黄色"
        elif val >= _rain["大雨"]:
            precip_cats["大雨(25-50mm)"] += 1
            continue
        else:
            continue
        results["warnings"].append({
            "type": "暴雨", "level": lv, "level_num": level_label(lv),
            "detail": f"{d} 日降水量 {val:.1f} mm，需关注短时强降水。",
            "icon": "[暴]",
        })
    results["precision"]["precip_cats"] = precip_cats
    # 6h 最大降水片段
    if len(h6_precip) > 0:
        results["precision"]["max_6h_precip"] = (float(h6_precip.max()), str(h6_precip.idxmax()))

    # ----- 3. 大风预警 -----
    _gale = warn_rules.gale_levels()
    windy = dmax_ws[dmax_ws >= _gale["蓝色"]]
    for d, val in windy.items():
        if val >= _gale["橙色"]:
            lv = "橙色"
        elif val >= _gale["黄色"]:
            lv = "黄色"
        elif val >= _gale["蓝色"]:
            lv = "蓝色"
        else:
            continue
        results["warnings"].append({
            "type": "大风", "level": lv, "level_num": level_label(lv),
            "detail": f"{d} 最大风速 {val:.1f} m/s，需注意户外作业安全。",
            "icon": "[风]",
        })

    # ----- 4. 极端值 + 日较差 -----
    results["extremes"] = {
        "max_temp": (float(dmax_t.max()), str(dmax_t.idxmax())),
        "min_temp": (float(dmin_t.min()), str(dmin_t.idxmin())),
        "max_daily_precip": (float(dprecip.max()), str(dprecip.idxmax())),
        "total_precip": float(dprecip.sum()),
        "max_wind": (float(dmax_ws.max()), str(dmax_ws.idxmax())),
        "ndays": ndays,
    }
    results["precision"]["diurnal"] = {
        "max_range": (float(diurnal.max()), str(diurnal.idxmax())),
        "mean_range": float(diurnal.mean()),
        "warm_nights": int((dmin_t >= 25).sum()),  # 热带夜
    }

    # ----- 5. 趋势（含置信区间 + 波动） -----
    first3 = dmax_t.iloc[:min(3, ndays)]
    last3 = dmax_t.iloc[-min(3, ndays):]
    diff_mean = last3.mean() - first3.mean()
    diff_std = np.sqrt(first3.std() ** 2 + last3.std() ** 2)
    t_parts = []
    if abs(diff_mean) > 3:
        t_parts.append("明显" + ("升温" if diff_mean > 0 else "降温"))
    elif abs(diff_mean) > 1:
        t_parts.append("小幅" + ("升温" if diff_mean > 0 else "降温"))
    else:
        t_parts.append("基本平稳")
    t_trend = t_parts[0]
    # 波动程度
    overall_std = float(dmax_t.std())
    if overall_std > 5:
        t_volatility = "剧烈波动"
    elif overall_std > 3:
        t_volatility = "波动较大"
    elif overall_std > 1.5:
        t_volatility = "小幅波动"
    else:
        t_volatility = "变化平缓"
    results["trends"]["temperature"] = t_trend
    results["precision"]["temp_trend"] = {
        "diff_mean": float(diff_mean),
        "diff_std": float(diff_std),
        "overall_std": overall_std,
        "volatility": t_volatility,
    }

    # 降水趋势（含强度分布）
    precip_days = int((dprecip > 0.1).sum())
    results["trends"]["precip_days"] = precip_days
    if precip_days == 0:
        results["trends"]["precip"] = "全程无有效降水"
    elif precip_days <= ndays * 0.3:
        results["trends"]["precip"] = "降水日数较少"
    else:
        results["trends"]["precip"] = "降水日数偏多"
    # 降水强度摘要
    results["precision"]["precip_summary"] = (
        f"大雨{precip_cats.get('大雨(25-50mm)', 0)}天，"
        f"暴雨{precip_cats.get('暴雨(50-100mm)', 0)}天，"
        f"大暴雨{precip_cats.get('大暴雨(>=100mm)', 0)}天。"
        if any(precip_cats.values()) else None
    )

    # ----- 6. 耦合分析（含 SSD 体感舒适度联动）-----
    if len(hot) > 0:
        hot_dates = list(hot.index)
        hot_rh = davg_rh.loc[[d for d in hot_dates if d in davg_rh.index]]
        if len(hot_rh) > 0 and hot_rh.mean() > 60:
            # 计算 SSD 体感舒适度
            hot_ws = dmax_ws.loc[[d for d in hot_dates if d in dmax_ws.index]]
            ssd_hot = _calc_ssd(hot.max(), hot_rh.mean(), hot_ws.mean() if len(hot_ws) > 0 else 2)
            ssd_note = f"，体感舒适度 SSD={ssd_hot:.1f}（炎热不舒适）" if ssd_hot >= 29 else ""
            results["coupling"].append({
                "type": "热应激风险", "severity": "危险",
                "detail": f"高温({hot.max():.1f}C)叠加高湿({hot_rh.mean():.0f}%)，体感温度显著升高{ssd_note}，户外活动需防范中暑。",
                "icon": "[热]",
            })
    if len(windy) > 0 and len(heavy) > 0:
        overlap = set(windy.index) & set(heavy.index)
        if overlap:
            results["coupling"].append({
                "type": "风雨耦合", "severity": "危险",
                "detail": f"{len(overlap)} 天同时出现大风和强降水，出行风险加剧。",
                "icon": "[风]",
            })
    # 昼夜温差过大
    if diurnal.max() >= 15:
        results["coupling"].append({
            "type": "温差过大", "severity": "注意",
            "detail": f"日较差最大达 {diurnal.max():.1f}C ({diurnal.idxmax()})，昼夜温差显著，注意适时增减衣物。",
            "icon": "[差]",
        })
    # 热带夜
    warm_nights = int((dmin_t >= 25).sum())
    if warm_nights > 0:
        results["coupling"].append({
            "type": "夜间闷热", "severity": "注意",
            "detail": f"{warm_nights} 天夜间最低温 >=25C（热带夜），影响睡眠质量，注意通风降温。",
            "icon": "[夜]",
        })

    # ----- 7. 总述（更精准） -----
    parts = [f"未来{ndays}天气温{t_trend} ({diff_mean:+.1f}C, 波动 {t_volatility}, 标准差 {overall_std:.1f}C)"]
    if precip_days > 0:
        parts.append(f"共{precip_days}个降水日，累计{results['extremes']['total_precip']:.0f} mm")
        if max_consec_rain >= 3:
            parts.append(f"最长连续{max_consec_rain}天有降水")
    else:
        parts.append("全程无明显降水")
    if len(results["warnings"]) > 0:
        types = set(w["type"] for w in results["warnings"])
        parts.append(f"触发{'/'.join(types)}预警信号")
    else:
        parts.append("无预警风险")
    results["summary"] = "。".join(parts) + "。"

    # ----- 8. 建议（比原有更细） -----
    t = {"travel": results["recommendations"]["travel"],
         "agri": results["recommendations"]["agri"]}

    if len(hot) > 0:
        t["travel"].append(f"未来{len(hot)}天有高温 ({hot.max():.0f}C)，外出避开 11:00-15:00 时段，备足饮水。")
        t["agri"].append(f"高温天气 ({len(hot)} 天 >=35C, 连续最多{max_consec_hot}天)：及时灌溉降温；设施大棚覆盖遮阳网；禽畜采取喷淋降温。")

    if max_consec_hot >= 5:
        t["travel"].append(f"连续{max_consec_hot}天高温将形成热浪，老人/儿童/慢性病患者避免户外活动。")
        t["agri"].append(f"热浪持续{max_consec_hot}天：增加灌溉频次至每日2-3次；大棚强制通风降温。")

    if len(heavy) > 0:
        t["travel"].append("强降水日外出备雨具，低洼路段注意内涝；涉水谨慎。")
        t["agri"].append("注意清沟排水；加固大棚基础；鱼塘检查防逃设施。")

    if precip_cats.get("大暴雨(>=100mm)", 0) > 0:
        t["travel"].append("预报有大暴雨：尽量避免出行；远离河道和低洼地区。")

    if len(windy) > 0:
        t["travel"].append("大风天气远离广告牌/临时搭建物；高空作业暂停。")
        t["agri"].append("加固设施农业骨架；收起晾晒物；检查禽畜舍牢固性。")

    if precip_days == 0 and len(hot) > 0:
        t["agri"].append("高温少雨天气：增加灌溉频次，严防干旱；旱地作物覆盖保墒。")

    if warm_nights > 0:
        t["travel"].append(f"{warm_nights}天热带夜(夜间>=25C)：睡前通风，空调温度不宜过低。")

    if diurnal.max() >= 15:
        t["travel"].append(f"昼夜温差大 ({diurnal.max():.0f}C)：早晚凉午间热，建议叠穿方便增减。")

    if len(results["coupling"]) > 0:
        for c in results["coupling"]:
            if c["severity"] == "危险":
                t["travel"].append(f"[{c['type']}] {c['detail']}")

    # 去重 + 限制条数
    for k in ("travel", "agri"):
        seen = set()
        uniq = []
        for s in t[k]:
            if s not in seen:
                seen.add(s)
                uniq.append(s)
        results["recommendations"][k] = uniq[:8]

    return results


def _calc_ssd(temp, humidity, wind_speed):
    """体感舒适度指数 (Thom Discomfort Index)
    SSD = T - 0.55*(1-RH)*(T-14) - V^(1/3)*(T-10)/20
    高值(>=29)表示炎热不舒适，低值(<10)表示寒冷不舒适，15-19为舒适区。
    """
    T = float(temp)
    RH = float(humidity) / 100.0
    V = max(float(wind_speed), 0.1)  # 防除零
    return T - 0.55 * (1 - RH) * (T - 14) - (V ** (1/3)) * (T - 10) / 20


def _get_now_row(fdf):
    """按当前真实时间在 fdf 中查找对应小时行，session 内跨小时会推进。

    缓存策略不变（仍是 fetch 时的预报），仅切换「当前小时」指针。
    """
    if fdf is None or fdf.empty:
        return None
    now = pd.Timestamp.now(tz="Asia/Shanghai").tz_localize(None)
    if "timestamp" in fdf.columns:
        mask = fdf["timestamp"] >= now
        if mask.any():
            return fdf[mask].iloc[0]
    return fdf.iloc[-1]


def _calc_life_indices(fdf, current=None):
    """计算生活指标，返回 dict。

    纯计算：实时观测由调用方通过 ``current`` 传入（可为 None），本函数
    不读 session_state、不发网络请求。7 项指标的语义见返回结构。
    """
    if fdf is None or fdf.empty:
        return {}

    cur = current

    if cur and cur.get("temperature") is not None:
        # 真实时实测路径
        temp = float(cur["temperature"])
        app_temp = float(cur.get("apparent_temperature") or temp)
        humid = float(cur.get("humidity") or 50)
        wind = float(cur.get("wind_speed") or 2)
        precip = float(cur.get("precipitation") or 0)
        precip_prob = float(cur.get("precipitation_probability") or 0)
        wcode = float(cur.get("weather_code") or 0)
    else:
        # Fallback: fdf 当前小时行
        now_row = _get_now_row(fdf)
        if now_row is None:
            return {}
        temp = float(now_row.get("temperature", 20))
        app_temp = float(now_row.get("apparent_temperature", temp))
        humid = float(now_row.get("humidity", 50))
        wind = float(now_row.get("wind_speed", 2))
        precip = float(now_row.get("precipitation", 0))
        precip_prob = float(now_row.get("precipitation_probability", 0))
        wcode = float(now_row.get("weather_code", 0))

    # 取未来 72h 数据用于部分指标(始终从 fdf 取,不受真实时接口影响)
    h72 = fdf.head(72) if len(fdf) >= 72 else fdf

    avg_temp_72 = float(h72["temperature"].mean())
    total_precip_72 = float(h72["precipitation"].sum())
    avg_humid_72 = float(h72["humidity"].mean())
    avg_wind_72 = float(h72["wind_speed"].mean())

    ssd = _calc_ssd(temp, humid, wind)

    indices = {}

    # 1. 穿衣指数
    ref_temp = app_temp if abs(app_temp - temp) > 2 else temp
    if ref_temp < 5:
        indices["clothing"] = {"level": "厚冬装", "score": 5, "advice": "羽绒/棉服+毛衣+保暖内衣", "color": "accent"}
    elif ref_temp < 12:
        indices["clothing"] = {"level": "初冬装", "score": 4, "advice": "风衣/外套+毛衣或薄羽绒", "color": "humid"}
    elif ref_temp < 18:
        indices["clothing"] = {"level": "春秋装", "score": 3, "advice": "薄外套/夹克+长裤", "color": "sev-best"}
    elif ref_temp < 25:
        indices["clothing"] = {"level": "轻便", "score": 2, "advice": "长袖/薄衫+单裤", "color": "sev-good"}
    elif ref_temp < 30:
        indices["clothing"] = {"level": "夏装", "score": 1, "advice": "短袖/短裤/短裙", "color": "sev-mid"}
    else:
        indices["clothing"] = {"level": "酷热", "score": 0, "advice": "透气浅色衣物，注意防晒", "color": "sev-bad"}

    # 2. 带伞建议
    rain_codes = set(range(50, 70)) | set(range(80, 87)) | set(range(95, 100))
    has_rain_code = wcode in rain_codes
    if total_precip_72 > 10 or (has_rain_code and precip > 0.5):
        indices["umbrella"] = {"level": "必带伞", "score": 3, "advice": "未来72h有明显降水，出门务必带伞", "color": "humid"}
    elif total_precip_72 > 0.1 or precip_prob >= 40 or has_rain_code:
        indices["umbrella"] = {"level": "建议备伞", "score": 2, "advice": "有降水可能，建议随身携带雨具", "color": "rain"}
    else:
        indices["umbrella"] = {"level": "无需带伞", "score": 0, "advice": "未来72h无明显降水", "color": "sev-best"}

    # 3. 体感舒适度 (Thom 不适指数: 高值=炎热, 低值=寒冷, 15-19=舒适)
    if ssd >= 29:
        indices["comfort"] = {"level": "炎热不舒适", "score": round(ssd, 1), "advice": "体感闷热，减少户外停留，注意防暑", "color": "sev-bad"}
    elif ssd >= 24:
        indices["comfort"] = {"level": "偏热", "score": round(ssd, 1), "advice": "多数人感到偏热，注意通风降温", "color": "sev-mid"}
    elif ssd >= 20:
        indices["comfort"] = {"level": "较舒适", "score": round(ssd, 1), "advice": "少部分人可能感觉微热", "color": "sev-mid"}
    elif ssd >= 15:
        indices["comfort"] = {"level": "舒适", "score": round(ssd, 1), "advice": "体感舒适宜人，适合户外活动", "color": "sev-best"}
    elif ssd >= 10:
        indices["comfort"] = {"level": "偏凉", "score": round(ssd, 1), "advice": "体感偏凉，适当添衣", "color": "humid"}
    else:
        indices["comfort"] = {"level": "寒冷不舒适", "score": round(ssd, 1), "advice": "体感寒冷，注意保暖防寒", "color": "accent"}

    # 4. 运动指数
    exercise_score = 100
    # 偏离舒适区(15-19)越远越不适合运动
    if ssd >= 29:
        exercise_score -= min(40, (ssd - 29) * 8)  # 炎热扣分
    elif ssd < 10:
        exercise_score -= min(40, (10 - ssd) * 8)  # 寒冷扣分
    exercise_score -= min(30, total_precip_72 * 2)
    exercise_score -= min(20, max(0, (avg_wind_72 - 10.8) * 3))
    if exercise_score >= 70:
        indices["exercise"] = {"level": "适宜", "score": int(exercise_score), "advice": "天气适合户外运动", "color": "sev-best"}
    elif exercise_score >= 50:
        indices["exercise"] = {"level": "较适宜", "score": int(exercise_score), "advice": "可适度户外活动", "color": "sev-good"}
    elif exercise_score >= 30:
        indices["exercise"] = {"level": "一般", "score": int(exercise_score), "advice": "建议室内运动为主", "color": "sev-mid"}
    else:
        indices["exercise"] = {"level": "不适宜", "score": int(exercise_score), "advice": "天气条件差，避免户外运动", "color": "sev-bad"}

    # 5. 紫外线指数 (天气码近似推断)
    sunny_codes = set(range(0, 3))
    cloudy_codes = set(range(3, 6)) | {45, 48}
    if wcode in sunny_codes and avg_temp_72 > 15:
        indices["uv"] = {"level": "很强", "score": 4, "advice": "紫外线强，外出涂防晒霜、戴帽子和太阳镜", "color": "sev-bad"}
    elif wcode in sunny_codes:
        indices["uv"] = {"level": "强", "score": 3, "advice": "紫外线较强，注意防晒", "color": "sev-mid"}
    elif wcode in cloudy_codes:
        indices["uv"] = {"level": "中等", "score": 2, "advice": "紫外线中等，可适当防护", "color": "sev-mid"}
    else:
        indices["uv"] = {"level": "低", "score": 1, "advice": "紫外线弱，无需特别防护", "color": "sev-best"}

    # 6. 洗车指数 (72h 累计降水)
    if total_precip_72 < 0.1:
        indices["carwash"] = {"level": "适宜", "score": 3, "advice": "未来三天基本无雨，放心洗车", "color": "sev-best"}
    elif total_precip_72 < 5:
        indices["carwash"] = {"level": "较适宜", "score": 2, "advice": "小雨可能，影响不大", "color": "sev-good"}
    elif total_precip_72 < 15:
        indices["carwash"] = {"level": "一般", "score": 1, "advice": "有降水，建议暂缓洗车", "color": "sev-mid"}
    else:
        indices["carwash"] = {"level": "不适宜", "score": 0, "advice": "雨水较多，别洗了", "color": "sev-bad"}

    # 7. 晾晒指数
    dry_score = 100
    dry_score -= min(40, total_precip_72 * 3)
    dry_score -= min(30, max(0, (avg_humid_72 - 70) * 2))
    dry_score += min(20, avg_wind_72 * 2)  # 微风有利晾晒
    if dry_score >= 70:
        indices["drying"] = {"level": "非常适宜", "score": int(dry_score), "advice": "天气干燥有风，适合晾晒衣物", "color": "sev-best"}
    elif dry_score >= 50:
        indices["drying"] = {"level": "适宜", "score": int(dry_score), "advice": "可以晾晒，但注意天气变化", "color": "sev-good"}
    elif dry_score >= 30:
        indices["drying"] = {"level": "一般", "score": int(dry_score), "advice": "湿度偏大，晾晒较慢", "color": "sev-mid"}
    else:
        indices["drying"] = {"level": "不适宜", "score": int(dry_score), "advice": "潮湿多雨，不宜室外晾晒", "color": "sev-bad"}

    return indices
