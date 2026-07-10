"""
数据导入模块：CSV/Excel 文件上传、手动录入、API 获取、模板下载
"""

import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from io import BytesIO, StringIO
from config import FIELD_ALIASES, STANDARD_FIELDS


def normalize_columns(df):
    """将用户数据列名映射为标准字段名"""
    mapping = {}
    for col in df.columns:
        col_stripped = col.strip()
        for alias, std in FIELD_ALIASES.items():
            if col_stripped.lower() == alias.lower():
                mapping[col] = std
                break
    df = df.rename(columns=mapping)
    return df


def detect_field_types(df):
    """检测已识别的标准字段"""
    recognized = [c for c in df.columns if c in STANDARD_FIELDS]
    unrecognized = [c for c in df.columns if c not in STANDARD_FIELDS and c not in recognized]
    return recognized, unrecognized


def load_csv(file) -> pd.DataFrame:
    """加载CSV文件，尝试多种编码和分隔符"""
    content = file.read()
    encodings = ["utf-8", "gbk", "gb2312", "gb18030", "latin-1"]

    for enc in encodings:
        try:
            df = pd.read_csv(StringIO(content.decode(enc, errors="replace")))
            if len(df.columns) > 1:
                break
        except Exception:
            continue
    else:
        df = pd.read_csv(StringIO(content.decode("utf-8", errors="replace")))

    # 去除全空行
    df = df.dropna(how="all").reset_index(drop=True)
    return df


def load_excel(file) -> pd.DataFrame:
    """加载Excel文件"""
    df = pd.read_excel(file, engine="openpyxl")
    df = df.dropna(how="all").reset_index(drop=True)
    return df


def parse_timestamp(df):
    """尝试解析时间列（多级降级策略）"""

    # ---- 第1级：精确名称匹配 ----
    ts_col = None
    exact_candidates = [
        "timestamp", "时间", "日期", "时刻", "datetime", "date", "time",
        "观测时间", "观测时次", "记录时间", "采集时间", "数据时间",
        "资料时间", "年月日", "TIMESTAMP", "obs_time", "record_time",
        "t", "Unnamed: 0", "unnamed",
    ]
    for c in df.columns:
        if c.strip().lower() in [e.lower() for e in exact_candidates]:
            ts_col = c
            break

    # ---- 第2级：子串/关键词模糊匹配 ----
    if ts_col is None:
        for c in df.columns:
            cl = c.strip().lower()
            if any(kw in cl for kw in ["时间", "时刻", "date", "time", "timestamp", "obs"]):
                ts_col = c
                break

    # ---- 第3级：pandas dtype 推断（自动检测 datetime64 列）----
    if ts_col is None:
        for c in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[c]):
                ts_col = c
                break

    # ---- 第4级：逐列尝试解析为 datetime（取第一个能成功转为 datetime 的列）----
    # 但需过滤：数值列被 pd.to_datetime 误解析为 Unix 纳秒时间戳的情况
    if ts_col is None:
        for c in df.columns:
            try:
                parsed = pd.to_datetime(df[c], errors="coerce")
                valid_count = parsed.notna().sum()
                if valid_count >= len(df) * 0.5:
                    # 过滤：如果解析结果全部在 1970-1980 年之间，且原始数据是数值类型，则视为误解析
                    if valid_count > 0:
                        min_ts = parsed[parsed.notna()].min()
                        max_ts = parsed[parsed.notna()].max()
                        if min_ts.year >= 1970 and max_ts.year <= 1980 and pd.api.types.is_numeric_dtype(df[c]):
                            continue  # 拒绝：误解析为 Unix 纳秒时间戳
                    ts_col = c
                    break
            except Exception:
                continue

    # ---- 第5级：尝试解析数值型 HMMSS / HHMMSS 格式（如 81829 = 8:18:29）----
    if ts_col is None:
        for c in df.columns:
            if pd.api.types.is_numeric_dtype(df[c]):
                vals = df[c].dropna()
                if len(vals) > 0 and vals.min() >= 0 and vals.max() <= 240000:
                    # 尝试解析为 HMMSS / HHMMSS
                    try:
                        str_vals = vals.astype(int).astype(str).str.zfill(6)
                        parsed = pd.to_datetime(str_vals, format="%H%M%S", errors="coerce")
                        if parsed.notna().sum() >= len(df) * 0.5:
                            # 使用今天的日期拼接
                            today = pd.Timestamp.now().strftime("%Y-%m-%d")
                            df["timestamp"] = pd.to_datetime(
                                today + " " + str_vals,
                                format="%Y-%m-%d %H%M%S",
                                errors="coerce"
                            )
                            return df.sort_values("timestamp").reset_index(drop=True)
                    except Exception:
                        pass

    # ---- 全部失败：用索引生成伪时间戳（每小时递增，从今天0点起）----
    if ts_col is None:
        import streamlit as st
        st.warning(
            "**未检测到时间列** — 已自动按行号生成时间序列（从今日00:00起，逐小时）。"
            "如需真实时间轴，请确保数据中包含含「时间」/「date」/「time」的列名。"
        )
        base = pd.Timestamp.now().normalize()
        df["timestamp"] = [base + pd.Timedelta(hours=i) for i in range(len(df))]
        return df.sort_values("timestamp").reset_index(drop=True)

    # ---- 成功定位到时间列：尝试多种格式解析 ----
    # 特殊处理：如果列是数值型且值在 0-240000 之间，尝试 HMMSS 格式
    if pd.api.types.is_numeric_dtype(df[ts_col]):
        vals = df[ts_col].dropna()
        if len(vals) > 0 and vals.min() >= 0 and vals.max() <= 240000:
            try:
                str_vals = vals.astype(int).astype(str).str.zfill(6)
                parsed = pd.to_datetime(str_vals, format="%H%M%S", errors="coerce")
                if parsed.notna().sum() >= len(df) * 0.5:
                    today = pd.Timestamp.now().strftime("%Y-%m-%d")
                    df["timestamp"] = pd.to_datetime(
                        today + " " + str_vals,
                        format="%Y-%m-%d %H%M%S",
                        errors="coerce"
                    )
                    return df.sort_values("timestamp").reset_index(drop=True)
            except Exception:
                pass

    formats = [
        None,  # pandas 自动推断
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y%m%d%H%M",
        "%Y%m%d%H",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y年%m月%d日%H时%M分",
        "%Y年%m月%d日",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y",
        "%d-%m-%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%H%M%S",  # HMMSS / HHMMSS 纯时间格式
        "%H:%M:%S",
        "%H:%M",
    ]

    for fmt in formats:
        try:
            if fmt is None:
                df["timestamp"] = pd.to_datetime(df[ts_col])
            else:
                df["timestamp"] = pd.to_datetime(df[ts_col], format=fmt)
            break
        except Exception:
            continue

    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def render_file_upload_section():
    """渲染文件上传区域"""
    st.subheader("[文件] 文件导入")

    col1, col2 = st.columns(2)

    with col1:
        uploaded_csv = st.file_uploader(
            "上传 CSV 文件",
            type=["csv", "txt"],
            key="csv_upload"
        )

    with col2:
        uploaded_xlsx = st.file_uploader(
            "上传 Excel 文件",
            type=["xlsx", "xls"],
            key="xlsx_upload"
        )

    df = None
    source = ""

    if uploaded_csv is not None:
        with st.spinner("正在解析 CSV 文件..."):
            df = load_csv(uploaded_csv)
            source = f"CSV: {uploaded_csv.name}"

    elif uploaded_xlsx is not None:
        with st.spinner("正在解析 Excel 文件..."):
            df = load_excel(uploaded_xlsx)
            source = f"Excel: {uploaded_xlsx.name}"

    if df is not None:
        df = normalize_columns(df)
        df = parse_timestamp(df)
        recognized, unrecognized = detect_field_types(df)

        st.success(f"[OK] 成功导入: {source} | {len(df)} 条记录 | 识别字段: {len(recognized)} 个")

        with st.expander("[列表] 数据预览（前20行）"):
            st.dataframe(df.head(20), use_container_width=True)

        with st.expander("[搜索] 字段识别详情"):
            st.write("**已识别标准字段**:", recognized if recognized else "无")
            st.write("**未识别字段**:", unrecognized if unrecognized else "无")
            if unrecognized:
                st.info("未识别字段不会参与分析和预警，可在手动录入区补充。")

    return df, source


def render_manual_input_section(existing_df=None):
    """渲染手动录入区域"""
    st.subheader("[编辑] 手动录入")

    with st.expander("添加观测记录", expanded=False):
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            obs_time = st.text_input("时间", placeholder="2026-07-08 14:00")
            temp = st.number_input("气温 (℃)", value=None, step=0.1, format="%.1f")

        with col2:
            pres = st.number_input("气压 (hPa)", value=None, step=0.1, format="%.1f")
            humid = st.number_input("相对湿度 (%)", value=None, min_value=0.0, max_value=100.0, step=0.1)

        with col3:
            ws = st.number_input("风速 (m/s)", value=None, step=0.1, format="%.1f")
            wd = st.number_input("风向 (°)", value=None, min_value=0.0, max_value=360.0, step=0.1)

        with col4:
            cloud = st.number_input("总云量 (0-10)", value=None, min_value=0.0, max_value=10.0, step=0.1)
            vis = st.number_input("能见度 (km)", value=None, step=0.1, format="%.1f")

        col5, col6 = st.columns(2)
        with col5:
            precip = st.number_input("降水量 (mm)", value=None, step=0.1, format="%.1f")
        with col6:
            wcode = st.number_input("天气码 (WMO)", value=None, min_value=0, max_value=99, step=1)
            station = st.text_input("站点ID", placeholder="ST01")

        if st.button("[+] 添加记录", use_container_width=True):
            record = {
                "timestamp": obs_time,
                "temperature": temp,
                "pressure": pres,
                "humidity": humid,
                "wind_speed": ws,
                "wind_direction": wd,
                "cloud_cover": cloud,
                "visibility": vis,
                "precipitation": precip,
                "weather_code": wcode,
                "station_id": station,
            }
            # 过滤None值
            record = {k: v for k, v in record.items() if v is not None and v != ""}
            if "timestamp" not in record:
                st.error("至少需要填写时间字段")
            else:
                if "manual_data" not in st.session_state:
                    st.session_state["manual_data"] = []
                st.session_state["manual_data"].append(record)
                st.success("记录已添加！")

    # 显示已手动添加的记录
    if "manual_data" in st.session_state and st.session_state["manual_data"]:
        st.write(f"已录入 {len(st.session_state['manual_data'])} 条记录")
        manual_df = pd.DataFrame(st.session_state["manual_data"])
        st.dataframe(manual_df, use_container_width=True)

        if st.button("[清空] 清空手动录入", use_container_width=True):
            st.session_state["manual_data"] = []
            st.rerun()

        return manual_df

    return None


def fetch_open_meteo(lat, lon, start_date, end_date):
    """从 Open-Meteo API 获取历史气象数据"""
    import requests

    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": [
            "temperature_2m",
            "relative_humidity_2m",
            "surface_pressure",
            "wind_speed_10m",
            "wind_direction_10m",
            "cloud_cover",
            "precipitation",
            "weather_code",
        ],
        "timezone": "Asia/Shanghai",
    }

    resp = requests.get(url, params=params, timeout=30)
    data = resp.json()

    if "hourly" not in data:
        return None, f"API 返回异常: {data}"

    hourly = data["hourly"]
    df = pd.DataFrame({
        "timestamp": pd.to_datetime(hourly["time"]),
        "temperature": hourly["temperature_2m"],
        "humidity": hourly["relative_humidity_2m"],
        "pressure": hourly["surface_pressure"],
        "wind_speed": hourly["wind_speed_10m"],
        "wind_direction": hourly["wind_direction_10m"],
        "cloud_cover": hourly["cloud_cover"],
        "precipitation": hourly["precipitation"],
        "weather_code": hourly["weather_code"],
        "visibility": [None] * len(hourly["time"]),
    })

    df["station_id"] = f"API({lat:.1f},{lon:.1f})"
    return df, None


def render_api_section():
    """渲染 API 数据获取区域（Open-Meteo + ERA5 引导）"""
    st.subheader("[网络] API 数据获取 (Open-Meteo / ERA5)")

    # ---- 子页签: Open-Meteo / ERA5 引导 ----
    api_tab1, api_tab2 = st.tabs(["Open-Meteo (直接下载)", "ERA5 (CDS 引导下载)"])

    # ===== Tab 1: Open-Meteo =====
    with api_tab1:
        col1, col2, col3 = st.columns(3)
        with col1:
            lat = st.number_input("纬度 (Latitude)", value=39.94, min_value=-90.0, max_value=90.0, step=0.01, key="api_lat")
        with col2:
            lon = st.number_input("经度 (Longitude)", value=116.85, min_value=-180.0, max_value=180.0, step=0.01, key="api_lon")
        with col3:
            date_range = st.date_input(
                "日期范围",
                value=(datetime.now() - timedelta(days=7), datetime.now() - timedelta(days=1)),
                key="api_date",
            )

        if st.button("[搜索] 获取数据", use_container_width=True, key="api_fetch"):
            if len(date_range) == 2:
                start_str = date_range[0].strftime("%Y-%m-%d")
                end_str = date_range[1].strftime("%Y-%m-%d")
                with st.spinner(f"正在从 Open-Meteo 获取 {start_str} ~ {end_str} 数据..."):
                    df, err = fetch_open_meteo(lat, lon, start_str, end_str)
                if err:
                    st.error(err)
                else:
                    st.success(f"[OK] 获取成功: {len(df)} 条逐时记录")
                    with st.expander("[列表] 数据预览"):
                        st.dataframe(df.head(20), use_container_width=True)
                    st.session_state["api_df"] = df
                    st.session_state["api_source"] = f"Open-Meteo ({lat:.2f}N, {lon:.2f}E)"
            else:
                st.warning("请选择起止日期")

    # ===== Tab 2: ERA5 CDS 引导 =====
    with api_tab2:
        _render_era5_guide()

    return st.session_state.get("api_df", None), st.session_state.get("api_source", "")


# ---- ERA5 引导子模块 ----
_ERA5_PRODUCTS = {
    "ERA5-Land (地表小时, 0.1°)": {
        "dataset": "reanalysis-era5-land",
        "url": "https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land",
        "type": "hourly",
        "variables": {
            "2m_temperature": "2m 气温",
            "2m_dewpoint_temperature": "2m 露点温度",
            "skin_temperature": "地表温度",
            "total_precipitation": "总降水",
            "10m_u_component_of_wind": "10m 纬向风",
            "10m_v_component_of_wind": "10m 经向风",
            "surface_pressure": "地面气压",
            "relative_humidity": "相对湿度",
            "cloud_cover": "总云量",
        },
    },
    "ERA5 再分析单层 (0.25°)": {
        "dataset": "reanalysis-era5-single-levels",
        "url": "https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels",
        "type": "hourly",
        "variables": {
            "2m_temperature": "2m 气温",
            "2m_dewpoint_temperature": "2m 露点温度",
            "mean_sea_level_pressure": "平均海平面气压",
            "surface_pressure": "地面气压",
            "total_precipitation": "总降水",
            "10m_u_component_of_wind": "10m 纬向风",
            "10m_v_component_of_wind": "10m 经向风",
            "relative_humidity": "相对湿度",
            "total_cloud_cover": "总云量",
            "snow_depth": "雪深",
        },
    },
    "ERA5 气压层 (0.25°)": {
        "dataset": "reanalysis-era5-pressure-levels",
        "url": "https://cds.climate.copernicus.eu/datasets/reanalysis-era5-pressure-levels",
        "type": "pressure",
        "variables": {
            "geopotential": "位势高度",
            "temperature": "温度",
            "u_component_of_wind": "纬向风",
            "v_component_of_wind": "经向风",
            "relative_humidity": "相对湿度",
            "specific_humidity": "比湿",
            "vertical_velocity": "垂直速度",
        },
    },
    "ERA5-Land 月均值 (0.1°)": {
        "dataset": "reanalysis-era5-land-monthly-means",
        "url": "https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land-monthly-means",
        "type": "monthly",
        "variables": {
            "2m_temperature": "2m 气温",
            "2m_dewpoint_temperature": "2m 露点温度",
            "skin_temperature": "地表温度",
            "total_precipitation": "总降水",
            "10m_u_component_of_wind": "10m 纬向风",
            "10m_v_component_of_wind": "10m 经向风",
            "surface_pressure": "地面气压",
            "relative_humidity": "相对湿度",
            "cloud_cover": "总云量",
        },
    },
}


def _render_era5_guide():
    """ERA5 CDS 数据获取引导页（混合分层：官网为主入口，代码为高级选项）"""
    st.caption("ERA5 数据由 Copernicus Climate Data Store (CDS) 提供。推荐直接前往 CDS 官网下载，也可生成 Python 代码本地运行。")

    # 注册提示
    with st.expander("[说明] 如何获取 ERA5 数据", expanded=False):
        st.markdown("""
### 方式一：CDS 官网下载（推荐）
1. 访问 [Copernicus CDS](https://cds.climate.copernicus.eu/) 注册免费账号
2. 在本页选择数据产品和参数后，点击「去 CDS 官网下载」
3. 在 CDS 官网的 Download 页面配置参数并提交请求
4. CDS 后台处理完成后邮件通知，前往下载 NetCDF 文件
5. 将下载的 `.nc` 文件导入本平台的「数据导入」Tab 即可

> **提示**：CDS 为欧盟服务器，国内直连加载较慢（约 2-5 秒）。如果长时间无响应，建议使用下方「高级选项」生成 Python 代码在本地运行，API 方式通常更稳定。

### 方式二：Python 代码本地运行（高级）
1. 注册 CDS 账号后，在个人资料页获取 API Key
2. 本地终端执行 `pip install cdsapi`
3. 创建 `~/.cdsapirc` 文件，内容为：
   ```
   url: https://cds.climate.copernicus.eu/api
   key: 你的API-Key
   ```
4. 在本页「高级选项」中生成下载代码，复制到本地运行
5. CDS 下载需要排队，请留意邮件通知
""")
        st.link_button("[打开] Copernicus CDS 官网", "https://cds.climate.copernicus.eu/")

    # 参数选择
    st.write("---")
    st.write("#### 参数配置")
    c1, c2, c3 = st.columns(3)
    with c1:
        product = st.selectbox("数据产品", list(_ERA5_PRODUCTS.keys()), key="era5_product")
    with c2:
        years = st.multiselect(
            "年份", options=list(range(1950, 2025)), default=[2023],
            key="era5_years",
        )
    with c3:
        months = st.multiselect(
            "月份", options=list(range(1, 13)), default=[1, 2, 3],
            format_func=lambda m: f"{m}月", key="era5_months",
        )

    # 气压层选择（仅气压层产品显示）
    product_type = _ERA5_PRODUCTS[product].get("type", "hourly")
    pressure_levels = []
    if product_type == "pressure":
        pressure_levels = st.multiselect(
            "气压层 (hPa)",
            options=["1000", "975", "950", "925", "900", "875", "850", "825", "800",
                     "775", "750", "700", "650", "600", "550", "500", "450",
                     "400", "350", "300", "250", "225", "200", "175", "150",
                     "125", "100", "70", "50", "30", "20", "10", "5", "1"],
            default=["500", "850", "200"],
            key="era5_pressure_levels",
        )

    c4, c5 = st.columns(2)
    with c4:
        var_keys = list(_ERA5_PRODUCTS[product]["variables"].keys())
        default_vars = var_keys[:2] if len(var_keys) >= 2 else var_keys
        variables = st.multiselect(
            "变量",
            options=var_keys,
            format_func=lambda v: _ERA5_PRODUCTS[product]["variables"][v],
            default=default_vars,
            key="era5_vars",
        )
    with c5:
        area_n = st.number_input("区域北界 (N)", value=40.0, min_value=-90.0, max_value=90.0, step=0.1, key="era5_n")
        area_s = st.number_input("区域南界 (S)", value=39.0, min_value=-90.0, max_value=90.0, step=0.1, key="era5_s")
        area_w = st.number_input("区域西界 (W)", value=116.0, min_value=-180.0, max_value=180.0, step=0.1, key="era5_w")
        area_e = st.number_input("区域东界 (E)", value=117.0, min_value=-180.0, max_value=180.0, step=0.1, key="era5_e")

    # 主按钮：跳转 CDS 官网下载
    st.write("---")
    cds_url = _ERA5_PRODUCTS[product]["url"] + "?tab=download"
    st.link_button("去 CDS 官网下载", cds_url, use_container_width=True,
                   help=f"在新标签页打开 {product} 的下载页面")
    st.caption("CDS 需要登录（欧盟服务器，首次加载约 2-5 秒）。下载完成后将 NetCDF 文件导入「数据导入」Tab 即可分析。")

    # 高级选项：生成 Python 代码
    with st.expander("高级：生成 Python 下载代码", expanded=False):
        st.caption("适合需要批量下载或自动化处理的用户。生成前请确保已本地安装 cdsapi 并配置好凭证。")
        if st.button("生成代码", key="era5_gen"):
            if not years or not months or not variables:
                st.warning("请至少选择年份、月份和变量")
                return
            if product_type == "pressure" and not pressure_levels:
                st.warning("气压层产品需要至少选择一个气压层")
                return

            ds = _ERA5_PRODUCTS[product]["dataset"]

            # 构建产品特有字段
            extra_fields = ""
            if product_type == "pressure":
                extra_fields = f"        'pressure_level': {pressure_levels},\n"

            # 根据产品类型构建 day/time 字段
            if product_type == "monthly":
                day_time = "        'time': '00:00',\n"
            else:
                day_time = (
                    "        'day': [\n"
                    "            '01', '02', '03', '04', '05', '06', '07', '08', '09', '10',\n"
                    "            '11', '12', '13', '14', '15', '16', '17', '18', '19', '20',\n"
                    "            '21', '22', '23', '24', '25', '26', '27', '28', '29', '30', '31'\n"
                    "        ],\n"
                    "        'time': [\n"
                    "            '00:00', '01:00', '02:00', '03:00', '04:00', '05:00',\n"
                    "            '06:00', '07:00', '08:00', '09:00', '10:00', '11:00',\n"
                    "            '12:00', '13:00', '14:00', '15:00', '16:00', '17:00',\n"
                    "            '18:00', '19:00', '20:00', '21:00', '22:00', '23:00'\n"
                    "        ],\n"
                )

            code = f'''import cdsapi

# 请确保已安装 cdsapi: pip install cdsapi
# 并配置 ~/.cdsapirc (API Key)

c = cdsapi.Client()

c.retrieve(
    '{ds}',
    {{
        'variable': {variables},
        'year': {sorted(years)},
        'month': {[f"{m:02d}" for m in sorted(months)]},
{extra_fields}{day_time}        'area': [{area_n}, {area_w}, {area_s}, {area_e}],
        'format': 'netcdf',
    }},
    'era5_{ds.split("-")[-1]}_download.nc'
)
'''
            st.session_state["era5_code"] = code
            st.rerun()

        # 已生成过代码时持久化展示
        code = st.session_state.get("era5_code", None)
        if code:
            st.text_area("复制代码到本地运行", value=code, height=240, key="era5_code_copy")
            st.caption("本地运行: `python era5_download.py`，CDS 下载需要排队，完成后可用 xarray 读取 NetCDF。")

def render_template_download():
    """渲染模板下载区域"""
    st.subheader("[导入] 模板下载")
    template_path = "templates/data_template.csv"
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            template_content = f.read()
        st.download_button(
            label="[下载] 下载标准数据模板 (CSV)",
            data=template_content,
            file_name="气象数据模板.csv",
            mime="text/csv",
            use_container_width=True,
        )
        st.caption("模板包含 timestamp, temperature, pressure, humidity, wind_speed, wind_direction, cloud_cover, visibility, weather_code, precipitation, station_id 等标准字段（下载文件名仍为「气象数据模板.csv」）")
    except FileNotFoundError:
        st.warning("模板文件未找到")
