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

    # ---- 第4级：尝试逐列解析为 datetime（取第一个能成功转为 datetime 的列）----
    if ts_col is None and len(df.columns) > 0:
        for c in df.columns:
            try:
                parsed = pd.to_datetime(df[c], errors="coerce")
                if parsed.notna().sum() >= len(df) * 0.5:  # 至少50%能解析为有效时间
                    ts_col = c
                    break
            except Exception:
                continue

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
    st.subheader("📂 文件导入")

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

        st.success(f"✅ 成功导入: {source} | {len(df)} 条记录 | 识别字段: {len(recognized)} 个")

        with st.expander("📋 数据预览（前20行）"):
            st.dataframe(df.head(20), use_container_width=True)

        with st.expander("🔍 字段识别详情"):
            st.write("**已识别标准字段**:", recognized if recognized else "无")
            st.write("**未识别字段**:", unrecognized if unrecognized else "无")
            if unrecognized:
                st.info("未识别字段不会参与分析和预警，可在手动录入区补充。")

    return df, source


def render_manual_input_section(existing_df=None):
    """渲染手动录入区域"""
    st.subheader("✏️ 手动录入")

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

        if st.button("➕ 添加记录", use_container_width=True):
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

        if st.button("🗑️ 清空手动录入", use_container_width=True):
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
    """渲染 API 数据获取区域"""
    st.subheader("🌐 API 数据获取 (Open-Meteo / ERA5)")

    col1, col2, col3 = st.columns(3)

    with col1:
        lat = st.number_input("纬度 (Latitude)", value=39.94, min_value=-90.0, max_value=90.0, step=0.01)
    with col2:
        lon = st.number_input("经度 (Longitude)", value=116.85, min_value=-180.0, max_value=180.0, step=0.01)
    with col3:
        date_range = st.date_input(
            "日期范围",
            value=(datetime.now() - timedelta(days=7), datetime.now() - timedelta(days=1)),
        )

    if st.button("🔍 获取数据", use_container_width=True):
        if len(date_range) == 2:
            start_str = date_range[0].strftime("%Y-%m-%d")
            end_str = date_range[1].strftime("%Y-%m-%d")

            with st.spinner(f"正在从 Open-Meteo 获取 {start_str} ~ {end_str} 数据..."):
                df, err = fetch_open_meteo(lat, lon, start_str, end_str)

            if err:
                st.error(err)
                return None, ""
            else:
                st.success(f"✅ 获取成功: {len(df)} 条逐时记录")
                with st.expander("📋 数据预览"):
                    st.dataframe(df.head(20), use_container_width=True)
                return df, f"Open-Meteo ({lat:.2f}N, {lon:.2f}E)"
        else:
            st.warning("请选择起止日期")
    return None, ""


def render_template_download():
    """渲染模板下载区域"""
    st.subheader("📥 模板下载")
    template_path = "templates/data_template.csv"
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            template_content = f.read()
        st.download_button(
            label="⬇️ 下载标准数据模板 (CSV)",
            data=template_content,
            file_name="气象数据模板.csv",
            mime="text/csv",
            use_container_width=True,
        )
        st.caption("模板包含 timestamp, temperature, pressure, humidity, wind_speed, wind_direction, cloud_cover, visibility, weather_code, precipitation, station_id 等标准字段（下载文件名仍为「气象数据模板.csv」）")
    except FileNotFoundError:
        st.warning("模板文件未找到")
