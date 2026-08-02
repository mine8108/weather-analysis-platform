# -*- coding: utf-8 -*-
# ============================================================
# ERA5 数据下载与处理脚本（由天气分析平台 ERA5 向导生成）
# 生成时间: 2026-08-02 01:09
# 产品: ERA5 单层月均值
# 变量: 2m 气温(2m_temperature)、总降水量(total_precipitation)、10m 风速（由 U/V 合成）(10m_wind_speed)
# 区域: 北40.15° 西116.15° 南39.65° 东116.65°
# 时间: 1991-2020 年，12 个月份，月度采样
# 处理: 气候态月统计
# ------------------------------------------------------------
# 用法:
#   1. 注册 CDS 免费账号: https://cds.climate.copernicus.eu
#      （首次使用每个数据集需在网页端勾选接受许可条款）
#   2. 创建 API key，写入本机 ~/.cdsapirc（一行 url 一行 key）:
#        url: https://cds.climate.copernicus.eu/api
#        key: <UID>:<API_KEY>
#      key 获取: CDS 网页右上角用户菜单 -> API key
#   3. 安装依赖（任一 Python 3.9+ 环境）:
#        pip install cdsapi xarray netCDF4 pandas numpy
#   4. 运行: python beijing_climate.py
# 说明: CDS 为排队下载制，大请求等待 30 分钟~数小时属正常现象。
#       首次下载失败多为条款未接受或 key 未生效，登录网页重试即可。
#       宽表中 t_max/t_min 当前取月均值（日极值统计为二期能力）。
# ============================================================
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ---- 0. 认证检查 ----
_rc = Path.home() / ".cdsapirc"
if not _rc.exists():
    print("[!] 未找到 ~/.cdsapirc，请先创建并填入 CDS API key：")
    print("    url: https://cds.climate.copernicus.eu/api")
    print("    key: <你的UID>:<你的API_KEY>")
    sys.exit(1)

# ---- 1. 下载 ----
import cdsapi

REQUEST = {
    "product_type": "monthly_averaged_reanalysis",
    "variable": [
            "2m_temperature",
            "total_precipitation",
            "10m_u_component_of_wind",
            "10m_v_component_of_wind"
    ],
    "year": [
            "1991",
            "1992",
            "1993",
            "1994",
            "1995",
            "1996",
            "1997",
            "1998",
            "1999",
            "2000",
            "2001",
            "2002",
            "2003",
            "2004",
            "2005",
            "2006",
            "2007",
            "2008",
            "2009",
            "2010",
            "2011",
            "2012",
            "2013",
            "2014",
            "2015",
            "2016",
            "2017",
            "2018",
            "2019",
            "2020"
    ],
    "month": [
            "01",
            "02",
            "03",
            "04",
            "05",
            "06",
            "07",
            "08",
            "09",
            "10",
            "11",
            "12"
    ],
    "time": ["00:00"],
    "data_format": "netcdf",
    "download_format": "unarchived",
    "area": [40.15, 116.15, 39.65, 116.65],
}

TARGET = "beijing_climate_download.nc"
print(f"[1/3] 请求 CDS 数据集 reanalysis-era5-single-levels-monthly-means，排队+下载可能需要较长时间...")
client = cdsapi.Client()
try:
    client.retrieve("reanalysis-era5-single-levels-monthly-means", REQUEST, TARGET)
except Exception as e:
    print(f"[!] 下载失败: {e}")
    print("    常见原因: 数据集许可条款未接受 / key 错误 / 参数不合法")
    sys.exit(1)

# ---- 2. 读取与单位换算 ----
import numpy as np
import xarray as xr

ds = xr.open_dataset(TARGET)
ds["2m_temperature"] = ds["2m_temperature"] - 273.15
ds["total_precipitation"] = ds["total_precipitation"] * 1000.0
ds["10m_wind_speed"] = np.sqrt(ds["10m_u_component_of_wind"] ** 2 + ds["10m_v_component_of_wind"] ** 2)

# ---- 3. 时间处理 ----
output_climate_csv = true
# 气候态：先月均（逐小时产品），再跨年同月平均
ds_month = ds.resample(time="1MS").mean()
CLIM = ds_month.groupby("time.month").mean("time")
DS_OUT = CLIM


# ---- 4. 输出 ----
if output_climate_csv:
    import pandas as pd
    LAT, LON = 39.9, 116.4
    rows = []
    for m in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]:
        pt = CLIM.sel(month=1)
        row = {"lat": round(LAT, 2), "lon": round(LON, 2), "month": 1,
               "t_mean": None, "t_max": None, "t_min": None,
               "precip": None, "wind_max_mean": None,
               "base_period": "1991-2020",
               "t_max_val": None, "t_max_year": None,
               "t_min_val": None, "t_min_year": None,
               "precip_max": None, "precip_max_year": None,
               "wind_max": None, "wind_max_year": None}
        row["t_mean"] = float(pt["2m_temperature"].isel(pressure_level=0).values) if "2m_temperature" in pt else None
        row["t_max"] = row["t_mean"]  # 简化：日极值统计二期提供
        row["t_min"] = row["t_mean"]
        row["precip"] = float(pt["total_precipitation"].values) if "total_precipitation" in pt else None
        row["wind_max_mean"] = float(pt["10m_wind_speed"].values) if "10m_wind_speed" in pt else None
        rows.append(row)
        pt = CLIM.sel(month=2)
        row = {"lat": round(LAT, 2), "lon": round(LON, 2), "month": 2,
               "t_mean": None, "t_max": None, "t_min": None,
               "precip": None, "wind_max_mean": None,
               "base_period": "1991-2020",
               "t_max_val": None, "t_max_year": None,
               "t_min_val": None, "t_min_year": None,
               "precip_max": None, "precip_max_year": None,
               "wind_max": None, "wind_max_year": None}
        row["t_mean"] = float(pt["2m_temperature"].isel(pressure_level=0).values) if "2m_temperature" in pt else None
        row["t_max"] = row["t_mean"]  # 简化：日极值统计二期提供
        row["t_min"] = row["t_mean"]
        row["precip"] = float(pt["total_precipitation"].values) if "total_precipitation" in pt else None
        row["wind_max_mean"] = float(pt["10m_wind_speed"].values) if "10m_wind_speed" in pt else None
        rows.append(row)
        pt = CLIM.sel(month=3)
        row = {"lat": round(LAT, 2), "lon": round(LON, 2), "month": 3,
               "t_mean": None, "t_max": None, "t_min": None,
               "precip": None, "wind_max_mean": None,
               "base_period": "1991-2020",
               "t_max_val": None, "t_max_year": None,
               "t_min_val": None, "t_min_year": None,
               "precip_max": None, "precip_max_year": None,
               "wind_max": None, "wind_max_year": None}
        row["t_mean"] = float(pt["2m_temperature"].isel(pressure_level=0).values) if "2m_temperature" in pt else None
        row["t_max"] = row["t_mean"]  # 简化：日极值统计二期提供
        row["t_min"] = row["t_mean"]
        row["precip"] = float(pt["total_precipitation"].values) if "total_precipitation" in pt else None
        row["wind_max_mean"] = float(pt["10m_wind_speed"].values) if "10m_wind_speed" in pt else None
        rows.append(row)
        pt = CLIM.sel(month=4)
        row = {"lat": round(LAT, 2), "lon": round(LON, 2), "month": 4,
               "t_mean": None, "t_max": None, "t_min": None,
               "precip": None, "wind_max_mean": None,
               "base_period": "1991-2020",
               "t_max_val": None, "t_max_year": None,
               "t_min_val": None, "t_min_year": None,
               "precip_max": None, "precip_max_year": None,
               "wind_max": None, "wind_max_year": None}
        row["t_mean"] = float(pt["2m_temperature"].isel(pressure_level=0).values) if "2m_temperature" in pt else None
        row["t_max"] = row["t_mean"]  # 简化：日极值统计二期提供
        row["t_min"] = row["t_mean"]
        row["precip"] = float(pt["total_precipitation"].values) if "total_precipitation" in pt else None
        row["wind_max_mean"] = float(pt["10m_wind_speed"].values) if "10m_wind_speed" in pt else None
        rows.append(row)
        pt = CLIM.sel(month=5)
        row = {"lat": round(LAT, 2), "lon": round(LON, 2), "month": 5,
               "t_mean": None, "t_max": None, "t_min": None,
               "precip": None, "wind_max_mean": None,
               "base_period": "1991-2020",
               "t_max_val": None, "t_max_year": None,
               "t_min_val": None, "t_min_year": None,
               "precip_max": None, "precip_max_year": None,
               "wind_max": None, "wind_max_year": None}
        row["t_mean"] = float(pt["2m_temperature"].isel(pressure_level=0).values) if "2m_temperature" in pt else None
        row["t_max"] = row["t_mean"]  # 简化：日极值统计二期提供
        row["t_min"] = row["t_mean"]
        row["precip"] = float(pt["total_precipitation"].values) if "total_precipitation" in pt else None
        row["wind_max_mean"] = float(pt["10m_wind_speed"].values) if "10m_wind_speed" in pt else None
        rows.append(row)
        pt = CLIM.sel(month=6)
        row = {"lat": round(LAT, 2), "lon": round(LON, 2), "month": 6,
               "t_mean": None, "t_max": None, "t_min": None,
               "precip": None, "wind_max_mean": None,
               "base_period": "1991-2020",
               "t_max_val": None, "t_max_year": None,
               "t_min_val": None, "t_min_year": None,
               "precip_max": None, "precip_max_year": None,
               "wind_max": None, "wind_max_year": None}
        row["t_mean"] = float(pt["2m_temperature"].isel(pressure_level=0).values) if "2m_temperature" in pt else None
        row["t_max"] = row["t_mean"]  # 简化：日极值统计二期提供
        row["t_min"] = row["t_mean"]
        row["precip"] = float(pt["total_precipitation"].values) if "total_precipitation" in pt else None
        row["wind_max_mean"] = float(pt["10m_wind_speed"].values) if "10m_wind_speed" in pt else None
        rows.append(row)
        pt = CLIM.sel(month=7)
        row = {"lat": round(LAT, 2), "lon": round(LON, 2), "month": 7,
               "t_mean": None, "t_max": None, "t_min": None,
               "precip": None, "wind_max_mean": None,
               "base_period": "1991-2020",
               "t_max_val": None, "t_max_year": None,
               "t_min_val": None, "t_min_year": None,
               "precip_max": None, "precip_max_year": None,
               "wind_max": None, "wind_max_year": None}
        row["t_mean"] = float(pt["2m_temperature"].isel(pressure_level=0).values) if "2m_temperature" in pt else None
        row["t_max"] = row["t_mean"]  # 简化：日极值统计二期提供
        row["t_min"] = row["t_mean"]
        row["precip"] = float(pt["total_precipitation"].values) if "total_precipitation" in pt else None
        row["wind_max_mean"] = float(pt["10m_wind_speed"].values) if "10m_wind_speed" in pt else None
        rows.append(row)
        pt = CLIM.sel(month=8)
        row = {"lat": round(LAT, 2), "lon": round(LON, 2), "month": 8,
               "t_mean": None, "t_max": None, "t_min": None,
               "precip": None, "wind_max_mean": None,
               "base_period": "1991-2020",
               "t_max_val": None, "t_max_year": None,
               "t_min_val": None, "t_min_year": None,
               "precip_max": None, "precip_max_year": None,
               "wind_max": None, "wind_max_year": None}
        row["t_mean"] = float(pt["2m_temperature"].isel(pressure_level=0).values) if "2m_temperature" in pt else None
        row["t_max"] = row["t_mean"]  # 简化：日极值统计二期提供
        row["t_min"] = row["t_mean"]
        row["precip"] = float(pt["total_precipitation"].values) if "total_precipitation" in pt else None
        row["wind_max_mean"] = float(pt["10m_wind_speed"].values) if "10m_wind_speed" in pt else None
        rows.append(row)
        pt = CLIM.sel(month=9)
        row = {"lat": round(LAT, 2), "lon": round(LON, 2), "month": 9,
               "t_mean": None, "t_max": None, "t_min": None,
               "precip": None, "wind_max_mean": None,
               "base_period": "1991-2020",
               "t_max_val": None, "t_max_year": None,
               "t_min_val": None, "t_min_year": None,
               "precip_max": None, "precip_max_year": None,
               "wind_max": None, "wind_max_year": None}
        row["t_mean"] = float(pt["2m_temperature"].isel(pressure_level=0).values) if "2m_temperature" in pt else None
        row["t_max"] = row["t_mean"]  # 简化：日极值统计二期提供
        row["t_min"] = row["t_mean"]
        row["precip"] = float(pt["total_precipitation"].values) if "total_precipitation" in pt else None
        row["wind_max_mean"] = float(pt["10m_wind_speed"].values) if "10m_wind_speed" in pt else None
        rows.append(row)
        pt = CLIM.sel(month=10)
        row = {"lat": round(LAT, 2), "lon": round(LON, 2), "month": 10,
               "t_mean": None, "t_max": None, "t_min": None,
               "precip": None, "wind_max_mean": None,
               "base_period": "1991-2020",
               "t_max_val": None, "t_max_year": None,
               "t_min_val": None, "t_min_year": None,
               "precip_max": None, "precip_max_year": None,
               "wind_max": None, "wind_max_year": None}
        row["t_mean"] = float(pt["2m_temperature"].isel(pressure_level=0).values) if "2m_temperature" in pt else None
        row["t_max"] = row["t_mean"]  # 简化：日极值统计二期提供
        row["t_min"] = row["t_mean"]
        row["precip"] = float(pt["total_precipitation"].values) if "total_precipitation" in pt else None
        row["wind_max_mean"] = float(pt["10m_wind_speed"].values) if "10m_wind_speed" in pt else None
        rows.append(row)
        pt = CLIM.sel(month=11)
        row = {"lat": round(LAT, 2), "lon": round(LON, 2), "month": 11,
               "t_mean": None, "t_max": None, "t_min": None,
               "precip": None, "wind_max_mean": None,
               "base_period": "1991-2020",
               "t_max_val": None, "t_max_year": None,
               "t_min_val": None, "t_min_year": None,
               "precip_max": None, "precip_max_year": None,
               "wind_max": None, "wind_max_year": None}
        row["t_mean"] = float(pt["2m_temperature"].isel(pressure_level=0).values) if "2m_temperature" in pt else None
        row["t_max"] = row["t_mean"]  # 简化：日极值统计二期提供
        row["t_min"] = row["t_mean"]
        row["precip"] = float(pt["total_precipitation"].values) if "total_precipitation" in pt else None
        row["wind_max_mean"] = float(pt["10m_wind_speed"].values) if "10m_wind_speed" in pt else None
        rows.append(row)
        pt = CLIM.sel(month=12)
        row = {"lat": round(LAT, 2), "lon": round(LON, 2), "month": 12,
               "t_mean": None, "t_max": None, "t_min": None,
               "precip": None, "wind_max_mean": None,
               "base_period": "1991-2020",
               "t_max_val": None, "t_max_year": None,
               "t_min_val": None, "t_min_year": None,
               "precip_max": None, "precip_max_year": None,
               "wind_max": None, "wind_max_year": None}
        row["t_mean"] = float(pt["2m_temperature"].isel(pressure_level=0).values) if "2m_temperature" in pt else None
        row["t_max"] = row["t_mean"]  # 简化：日极值统计二期提供
        row["t_min"] = row["t_mean"]
        row["precip"] = float(pt["total_precipitation"].values) if "total_precipitation" in pt else None
        row["wind_max_mean"] = float(pt["10m_wind_speed"].values) if "10m_wind_speed" in pt else None
        rows.append(row)
    df = pd.DataFrame(rows)
    out_csv = "beijing_climate_climate_stats.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"[OK] 气候态宽表已输出: {out_csv}")
    print("     将该 CSV 上传到平台「再分析数据处理」板块即可直接使用")

DS_OUT.to_netcdf("beijing_climate_processed.nc")
print("[3/3] 完成。处理结果已保存为 beijing_climate_processed.nc")
