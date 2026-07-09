"""
生成示例气象数据：覆盖高温、大风、大雾、暴雨、正常等多种场景
用于测试软件的完整分析流程
"""

import pandas as pd
import numpy as np

np.random.seed(2026)

start = pd.Timestamp("2026-07-01 00:00")
hours = 5 * 24  # 5天逐时数据
timestamps = [start + pd.Timedelta(hours=i) for i in range(hours)]

temps = []
pressures = []
humids = []
winds = []
dirs = []
clouds = []
vis = []
precip = []
codes = []

# 场景设计：
# Day1 (07-01): 正常夏季，温 26-32
# Day2 (07-02): 升温，最高 35.x
# Day3 (07-03): 高温，最高 38.5 → 高温橙色
# Day4 (07-04): 续高温 + 午后大风 → 大风预警
# Day5 (07-05): 凌晨大雾(低能见度) → 上午转小雨 → 午后暴雨

for i in range(hours):
    day = i // 24
    hod = i % 24  # hour of day

    # 基础日变化：白天高、夜间低
    diurnal = 6 * np.sin((hod - 9) / 24 * 2 * np.pi)

    if day == 0:
        base_t = 28 + diurnal
    elif day == 1:
        base_t = 31 + diurnal
    elif day == 2:
        base_t = 34 + diurnal  # 午后可达 38+
    elif day == 3:
        base_t = 33 + diurnal  # 持续高温
    else:  # day 4
        if hod < 6:
            base_t = 27 + diurnal * 0.5  # 凌晨偏凉
        else:
            base_t = 30 + diurnal

    t = base_t + np.random.normal(0, 0.6)
    temps.append(round(t, 1))

    # 气压：随天气系统变化，Day4午后骤降
    if day == 3 and 14 <= hod <= 20:
        p = 1005 - (hod - 14) * 1.5 + np.random.normal(0, 0.5)
    else:
        p = 1008 - day * 1.5 + np.random.normal(0, 0.8)
    pressures.append(round(p, 1))

    # 湿度
    if day == 4 and hod < 6:
        rh = 96 + np.random.normal(0, 1.5)  # 雾天高湿
    elif day <= 2:
        rh = 55 - 10 * np.sin((hod - 6) / 24 * 2 * np.pi) + np.random.normal(0, 3)
    else:
        rh = 65 + np.random.normal(0, 4)
    humids.append(round(min(max(rh, 20), 100), 0))

    # 风：Day4午后大风
    if day == 3 and 14 <= hod <= 19:
        ws = 13 + np.random.normal(0, 1.5)  # 强风 6-7级
    elif day == 4 and hod < 6:
        ws = 1.5 + np.random.normal(0, 0.5)  # 静风（雾）
    else:
        ws = 4 + np.random.normal(0, 1.5)
    winds.append(round(max(ws, 0), 1))
    dirs.append(round((180 + 90 * np.sin(i / 5)) % 360, 0))

    # 云量
    if day == 3 and hod >= 15:
        cl = 9 + np.random.normal(0, 0.5)
    elif day == 4:
        cl = 8 + np.random.normal(0, 1)
    else:
        cl = 3 + np.random.normal(0, 2)
    clouds.append(round(min(max(cl, 0), 10), 0))

    # 能见度
    if day == 4 and hod < 6:
        v = 0.3 + np.random.normal(0, 0.1)  # 大雾 <500m
    elif day == 4 and 6 <= hod < 10:
        v = 3 + np.random.normal(0, 1)
    else:
        v = 18 + np.random.normal(0, 3)
    vis.append(round(max(v, 0.1), 1))

    # 降水
    if day == 4 and 12 <= hod < 24:
        # 午后暴雨
        pr = max(0, 8 - abs(hod - 16) * 1.2 + np.random.normal(0, 1.5))
    else:
        pr = 0.0
    precip.append(round(max(pr, 0), 1))

    # 天气码
    if day == 4 and hod < 6:
        c = 40  # 雾
    elif day == 4 and 12 <= hod < 24:
        c = 95 if hod >= 15 else 61  # 雷暴/雨
    elif day == 3 and hod >= 15:
        c = 3  # 云增多
    else:
        c = 1
    codes.append(c)

df = pd.DataFrame({
    "timestamp": [t.strftime("%Y-%m-%d %H:%M") for t in timestamps],
    "temperature": temps,
    "pressure": pressures,
    "humidity": humids,
    "wind_speed": winds,
    "wind_direction": dirs,
    "cloud_cover": clouds,
    "visibility": vis,
    "precipitation": precip,
    "weather_code": codes,
    "station_id": "DEMO01",
})

df.to_csv("示例数据/示例气象数据.csv", index=False, encoding="utf-8-sig")

print(f"已生成示例数据: {len(df)} 条记录")
print(f"时间范围: {df['timestamp'].iloc[0]} ~ {df['timestamp'].iloc[-1]}")
print(f"最高温: {df['temperature'].max()}℃ | 最低能见度: {df['visibility'].min()}km")
print(f"最大风速: {df['wind_speed'].max()}m/s | 总降水: {df['precipitation'].sum():.1f}mm")

# 统计会触发的预警
print("\n预期触发的预警:")
print("  高温橙色: 07-03 午后 ≥37℃")
print("  大风蓝色: 07-04 午后 ≥10.8m/s")
print("  大雾黄色: 07-05 凌晨能见度 <500m")
print(f"  暴雨: 07-05 午后累计降水 {df[df['precipitation']>0]['precipitation'].sum():.1f}mm")
