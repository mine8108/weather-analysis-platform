"""
数据导入模块：CSV/Excel 文件上传、NetCDF 解析、手动录入、API 获取、模板下载
"""

import pandas as pd
import numpy as np
import streamlit as st
import re
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


# ---- NetCDF 通用解析器 ----

# 维度名称候选集（小写匹配）
_TIME_DIM_NAMES = {"time", "valid_time", "t", "forecast_time", "step"}
_VERTICAL_DIM_NAMES = {"level", "pressure_level", "isobaricinhpa", "model_level",
                        "hybrid", "depth", "height", "plev", "soil_level"}
_SPATIAL_DIM_NAMES = {"latitude", "longitude", "lat", "lon", "x", "y", "nx", "ny"}


def _classify_dim(dim_name):
    """根据维度名称推断维度类型"""
    key = dim_name.lower().replace(" ", "_")
    if key in _TIME_DIM_NAMES:
        return "time"
    if key in _VERTICAL_DIM_NAMES:
        return "vertical"
    if key in _SPATIAL_DIM_NAMES:
        return "spatial"
    return "other"


def load_netcdf(file):
    """
    解析 NetCDF 文件，返回 (ds, dims_info, variables, error)。

    ds: xarray Dataset
    dims_info: {dim_name: {"type": "time"|"vertical"|"spatial"|"other",
                            "size": N, "label": 中文标签}}
    variables: {var_name: {"dims": [...], "ndim": N, "units": "", "long_name": ""}}
    """
    try:
        import xarray as xr
    except ImportError:
        return None, None, None, "xarray 未安装。请执行: pip install xarray netCDF4"

    try:
        ds = xr.open_dataset(BytesIO(file.read()), engine="netcdf4")
    except Exception:
        try:
            file.seek(0)
            ds = xr.open_dataset(BytesIO(file.read()), engine="h5netcdf")
        except Exception as e:
            return None, None, None, f"无法解析 NetCDF 文件: {e}"

    # 分类所有维度
    dims_info = {}
    time_dims = []
    vertical_dims = []
    spatial_dims = []

    for dim_name, dim_size in ds.sizes.items():
        d_type = _classify_dim(dim_name)
        coord = ds.coords.get(dim_name)
        nvals = len(coord.values) if coord is not None else dim_size

        if d_type == "time":
            label = f"时间维度 ({nvals} 步)"
            time_dims.append(dim_name)
        elif d_type == "vertical":
            label = f"垂直维度: {dim_name} ({nvals} 层)"
            vertical_dims.append(dim_name)
        elif d_type == "spatial":
            label = f"空间维度: {dim_name} ({nvals})"
            spatial_dims.append(dim_name)
        else:
            label = f"其他维度: {dim_name} ({dim_size})"

        dims_info[dim_name] = {"type": d_type, "size": nvals, "label": label}

    # 枚举数据变量
    variables = {}
    for var_name in ds.data_vars:
        var = ds[var_name]
        attrs = dict(var.attrs)
        variables[var_name] = {
            "dims": list(var.dims),
            "ndim": len(var.dims),
            "units": attrs.get("units", ""),
            "long_name": attrs.get("long_name", var_name),
        }

    return ds, dims_info, variables, None


def extract_netcdf_to_df(ds, lat_dim, lon_dim, spatial_mode, lat_val, lon_val,
                         vertical_dim=None, level_val=None, time_dim=None):
    """
    从 xarray Dataset 中提取指定站点/区域的数据转为 DataFrame。

    spatial_mode: "point" (最近邻) 或 "area_mean" (空间平均)
    """
    import xarray as xr

    try:
        if spatial_mode == "point":
            # 最近邻站点提取
            if lat_dim in ds.coords and lon_dim in ds.coords:
                ds_sel = ds.sel({lat_dim: lat_val, lon_dim: lon_val}, method="nearest")
            else:
                # 如果 dim 名就是 coordinate 名
                ds_sel = ds.isel({lat_dim: 0, lon_dim: 0})
        else:
            # 空间平均
            dims_to_mean = [d for d in [lat_dim, lon_dim] if d in ds.dims]
            ds_sel = ds.mean(dim=dims_to_mean)

        # 垂直层切片
        if vertical_dim and level_val is not None:
            if vertical_dim in ds_sel.coords:
                ds_sel = ds_sel.sel({vertical_dim: level_val}, method="nearest")

        # 转为 DataFrame
        df = ds_sel.to_dataframe().reset_index()

        # 清理多级索引
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = ["_".join(str(c) for c in col if c).strip("_") for col in df.columns]

        # 从 attrs 自动给列名加中文备注（不做强制重命名）
        return df, None
    except Exception as e:
        return None, f"提取失败: {e}"



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
    """智能时间列检测与解析（L1-L5 全面方案）
    L1: 扩展名称匹配 (5 级优先级)
    L2: 多列拼接 (year/month/day/hour)
    L3: 内容模式扫描 (不依赖列名)
    L4: 质量报告 (解析后反馈)
    L5: 交互式确认 (找不到时让用户选)
    """
    ts_col = None
    report_method = ""

    # ---- L1: 扩展名称匹配（5 级优先级） ----
    L1_TIERS = [
        ["timestamp", "时间", "日期", "datetime", "date", "time", "datetime_str"],
        ["观测时间", "观测时次", "记录时间", "采集时间", "数据时间", "资料时间",
         "观测日期", "记录日期", "report_time", "forecast_time", "fcst_time",
         "analysis_time", "init_time", "valid_time", "obs_time", "obs_date"],
        ["time_utc", "date_utc", "local_time", "datetime_utc", "utc_time",
         "record_time", "year_month_day", "yyyymmdd", "yyyymmddhh",
         "date_str", "time_str", "TIMESTAMP", "UNIXTIME"],
        ["年月日", "时刻", "开始时间", "结束时间", "起始时间", "终止时间",
         "timestamps", "date_time", "obs_time_utc", "base_time"],
        ["day", "hour", "month", "year"],  # 最低优先级：可能是数值列
    ]
    for tier in L1_TIERS:
        for c in df.columns:
            if c.strip().lower() in [t.lower() for t in tier]:
                ts_col = c
                report_method = f"L1 名称: {c}"
                break
        if ts_col:
            break

    # ---- L2: 多列拼接检测 ----
    if ts_col is None:
        multi = _detect_multi_col_date(df)
        if multi:
            cols, fmt_str = multi
            try:
                df["timestamp"] = pd.to_datetime(
                    df[cols].astype(str).apply(lambda r: fmt_str.format(**r.to_dict()), axis=1),
                    errors="coerce"
                )
                valid = df["timestamp"].notna().sum()
                if valid >= len(df) * 0.5:
                    report_method = f"L2 多列拼接: {cols}"
                    ts_col = "timestamp__generated"
                    df = df.sort_values("timestamp").reset_index(drop=True)
                    _show_time_report(df, report_method, valid, len(df))
                    return df
            except Exception:
                pass

    # ---- L3: 内容模式扫描 ----
    if ts_col is None:
        ts_col, score = _scan_content_pattern(df)
        if ts_col:
            report_method = f"L3 内容模式: {ts_col} ({score:.0%})"

    # ---- L5: 交互式确认 ----
    if ts_col is None:
        ts_col = _interactive_time_picker(df)
        if ts_col:
            report_method = f"L5 手动: {ts_col}"
    if ts_col is None:
        return _fallback_synthetic_time(df)

    # ---- 解析时间列 ----
    df["timestamp"] = _smart_parse_datetime(df[ts_col])
    valid = df["timestamp"].notna().sum()

    # 低质量回退
    if valid < len(df) * 0.3 and ts_col != "timestamp__generated":
        st.warning(f"时间列 `{ts_col}` 仅识别 {valid}/{len(df)} 条有效值，请核对数据格式")
        fallback = _interactive_time_picker(df, default_col=ts_col)
        if fallback and fallback != ts_col:
            df["timestamp"] = _smart_parse_datetime(df[fallback])
            valid = df["timestamp"].notna().sum()
            report_method = f"L5 重选: {fallback}"

    df = df.sort_values("timestamp").reset_index(drop=True)

    # ---- L4: 质量报告 ----
    _show_time_report(df, report_method, valid, len(df))

    return df


# ---- 辅助函数 ----

def _detect_multi_col_date(df):
    """检测是否存在 year/month/day/hour 多列组合，返回 (cols, fmt_str) 或 None"""
    col_map = {}
    for c in df.columns:
        cl = c.strip().lower()
        if cl in ("year", "年", "yyyy"):
            col_map["year"] = c
        elif cl in ("month", "月", "mm"):
            col_map["month"] = c
        elif cl in ("day", "日", "dd"):
            col_map["day"] = c
        elif cl in ("hour", "时", "hh"):
            col_map["hour"] = c

    # 至少需要 year + month
    if "year" not in col_map or "month" not in col_map:
        return None

    cols = [col_map["year"], col_map["month"]]
    fmt = "{year}-{month:0>2}"
    if "day" in col_map:
        cols.append(col_map["day"])
        fmt += "-{day:0>2}"
    if "hour" in col_map:
        cols.append(col_map["hour"])
        fmt += " {hour:0>2}:00"

    return cols, fmt


_DATE_PATTERNS = [
    (re.compile(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}'), "ISO 日期时间"),
    (re.compile(r'^\d{4}-\d{2}-\d{2}$'), "ISO 日期"),
    (re.compile(r'^\d{4}/\d{2}/\d{2}[T ]?\d{2}:\d{2}'), "斜线日期时间"),
    (re.compile(r'^\d{4}/\d{2}/\d{2}$'), "斜线日期"),
    (re.compile(r'^\d{12}$'), "紧凑日期时间 YYYYMMDDHHMM"),
    (re.compile(r'^\d{10}$'), "紧凑日期时间 YYYYMMDDHH"),
    (re.compile(r'^\d{8}$'), "紧凑日期 YYYYMMDD"),
]


def _scan_content_pattern(df):
    """扫描所有列的内容，返回 (col_name, 置信度) 或 (None, 0)"""
    best_col, best_score = None, 0
    sample_size = min(30, len(df))

    for c in df.columns:
        # 跳过已经检测过的
        vals = df[c].dropna().head(sample_size).astype(str)
        if len(vals) == 0:
            continue

        matched = 0
        for v in vals:
            v = v.strip().strip("'\"")
            if any(p.search(v) for p, _ in _DATE_PATTERNS):
                matched += 1

        score = matched / len(vals) if len(vals) > 0 else 0
        if score > best_score and score >= 0.6:
            best_score = score
            best_col = c

    return best_col, best_score


def _interactive_time_picker(df, default_col=None):
    """让用户从列表中选择时间列"""
    # 按「日期可能性」排序候选列
    candidates = _rank_date_columns(df)

    if not candidates:
        st.info("未检测到任何可能的时间列。将使用自动生成的序号作为时间轴。")
        return None

    options = ["（不使用时间轴）"] + candidates
    default_idx = candidates.index(default_col) + 1 if default_col in candidates else 0

    choice = st.radio(
        "请选择包含时间/日期的列：",
        options, index=default_idx, key="ts_picker",
        horizontal=True,
    )
    return None if choice == "（不使用时间轴）" else choice


def _rank_date_columns(df):
    """对列按「看起来像日期」的程度排序"""
    scored = []
    sample_size = min(20, len(df))
    for c in df.columns:
        vals = df[c].dropna().head(sample_size).astype(str)
        if len(vals) == 0:
            continue
        score = 0
        for v in vals:
            v = v.strip()
            if any(p.search(v) for p, _ in _DATE_PATTERNS):
                score += 1
        # 日期列名加额外分
        cl = c.lower()
        if any(kw in cl for kw in ("time", "date", "时间", "日期", "时刻")):
            score += 3
        # datetime64 dtype
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            score += 5
        scored.append((c, score / len(vals)))
    scored.sort(key=lambda x: -x[1])
    return [s[0] for s in scored if s[1] > 0.1]


def _smart_parse_datetime(series):
    """智能解析时间序列：优先自动推断，失败后尝试多种格式"""
    # 先试自动推断
    parsed = pd.to_datetime(series, errors="coerce", infer_datetime_format=True)
    if parsed.notna().sum() >= len(series) * 0.5:
        return parsed

    # 常见格式逐个尝试
    for fmt in [
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M", "%Y%m%d%H%M", "%Y%m%d%H", "%Y-%m-%d", "%Y/%m/%d",
        "%Y年%m月%d日%H时%M分", "%Y年%m月%d日",
        "%m/%d/%Y %H:%M:%S", "%m/%d/%Y", "%d-%m-%Y %H:%M:%S",
        "%d/%m/%Y %H:%M", "%H:%M:%S", "%H:%M",
    ]:
        try:
            p = pd.to_datetime(series, format=fmt, errors="coerce")
            if p.notna().sum() > parsed.notna().sum():
                parsed = p
        except Exception:
            continue
    return parsed


def _fallback_synthetic_time(df):
    """无法找到时间列时，生成序号时间轴并警告"""
    st.warning(
        "未检测到时间列，已用序号生成时间轴。若数据包含时间信息，请在上方选择器中选择对应列。"
    )
    df["timestamp"] = [pd.Timestamp.now().normalize() + pd.Timedelta(hours=i) for i in range(len(df))]
    return df.sort_values("timestamp").reset_index(drop=True)


def _show_time_report(df, method, valid, total):
    """L4: 时间解析质量报告"""
    timestamps = df["timestamp"].dropna()
    if len(timestamps) == 0:
        st.warning(f"时间解析失败（{method}），已降级使用序号")
        return

    gap_str = ""
    if len(timestamps) >= 2:
        diffs = timestamps.diff().dropna()
        most_common = diffs.mode()
        if len(most_common) > 0:
            gap_str = f"，步长 {most_common[0]}"

    missing = total - valid
    missing_str = f"，{missing} 条缺失" if missing > 0 else ""
    span = f"（{timestamps.min().strftime('%Y-%m-%d %H:%M')} ~ {timestamps.max().strftime('%Y-%m-%d %H:%M')}）" if len(timestamps) > 0 else ""

    st.success(
        f"[时间] {method} | {valid}/{total} 条有效{missing_str}{gap_str} {span}"
    )


def render_file_upload_section():
    """渲染文件上传区域（CSV / Excel / NetCDF）"""
    st.subheader("[文件] 文件导入")

    col1, col2, col3 = st.columns(3)

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

    with col3:
        uploaded_nc = st.file_uploader(
            "上传 NetCDF (.nc)",
            type=["nc", "nc4", "cdf"],
            key="nc_upload"
        )

    df = None
    source = ""

    # ---- CSV ----
    if uploaded_csv is not None:
        with st.spinner("正在解析 CSV 文件..."):
            df = load_csv(uploaded_csv)
            source = f"CSV: {uploaded_csv.name}"

    # ---- Excel ----
    elif uploaded_xlsx is not None:
        with st.spinner("正在解析 Excel 文件..."):
            df = load_excel(uploaded_xlsx)
            source = f"Excel: {uploaded_xlsx.name}"

    # ---- NetCDF ----
    elif uploaded_nc is not None:
        nc_key = f"nc_{uploaded_nc.name}"
        # 解析文件（仅首次或文件变化时）
        if nc_key not in st.session_state or st.session_state.get("nc_last_file") != uploaded_nc.name:
            with st.spinner("正在解析 NetCDF 文件..."):
                ds, dims_info, vars_info, err = load_netcdf(uploaded_nc)
            if err:
                st.error(err)
            else:
                st.session_state[nc_key] = {"ds": ds, "dims_info": dims_info, "vars_info": vars_info}
                st.session_state["nc_last_file"] = uploaded_nc.name
                st.session_state["nc_extracted_df"] = None  # 重置提取结果

        # 获取已解析的数据
        nc_data = st.session_state.get(nc_key, {})
        ds = nc_data.get("ds")
        dims_info = nc_data.get("dims_info", {})
        vars_info = nc_data.get("vars_info", {})

        if ds is None:
            return None, ""

        # 显示解析结果
        st.success(f"[OK] NetCDF 文件已解析: {uploaded_nc.name}")

        with st.expander("[维度] 文件结构预览", expanded=True):
            c_dim, c_var = st.columns(2)
            with c_dim:
                st.caption("**检测到的维度**")
                for dn, di in dims_info.items():
                    st.write(f"- {di['label']}")
            with c_var:
                st.caption(f"**数据变量 ({len(vars_info)} 个)**")
                for vn, vi in vars_info.items():
                    unit_str = f" ({vi['units']})" if vi['units'] else ""
                    st.write(f"- `{vn}`{unit_str}: {vi['long_name']} [{vi['ndim']}D]")

        # ---- 提取选项 ----
        st.write("---")
        st.caption("**选择提取方式**（将多维数据转为站点时间序列）")

        # 找空间和垂直维度
        spatial_dims = {k: v for k, v in dims_info.items() if v["type"] == "spatial"}
        vertical_dims = {k: v for k, v in dims_info.items() if v["type"] == "vertical"}
        time_dims = {k: v for k, v in dims_info.items() if v["type"] == "time"}

        lat_dim = None
        lon_dim = None
        for dn in spatial_dims:
            dn_lower = dn.lower()
            if dn_lower in ("latitude", "lat", "y"):
                lat_dim = dn
            elif dn_lower in ("longitude", "lon", "x"):
                lon_dim = dn

        # 如果没有找到明确的 lat/lon，用前两个
        sdim_keys = list(spatial_dims.keys())
        if lat_dim is None and len(sdim_keys) >= 2:
            lat_dim = sdim_keys[0]
            lon_dim = sdim_keys[1]
        elif lat_dim is None and len(sdim_keys) == 1:
            lat_dim = sdim_keys[0]

        # 垂直维度
        vdim_keys = list(vertical_dims.keys())
        vertical_dim = vdim_keys[0] if vdim_keys else None

        ex1, ex2, ex3 = st.columns(3)
        with ex1:
            if spatial_dims:
                spatial_mode = st.radio("空间提取", ["单点（最近邻）", "区域平均"],
                                       key="nc_spatial_mode")
                if spatial_mode == "单点（最近邻）":
                    # 尝试获取坐标范围
                    lat_vals = None
                    lon_vals = None
                    if lat_dim and lon_dim and lat_dim in ds.coords and lon_dim in ds.coords:
                        lat_vals = ds.coords[lat_dim].values
                        lon_vals = ds.coords[lon_dim].values

                    lat_default = float(np.median(lat_vals)) if lat_vals is not None and len(lat_vals) > 0 else 39.9
                    lon_default = float(np.median(lon_vals)) if lon_vals is not None and len(lon_vals) > 0 else 116.4
                    lat_val = st.number_input("纬度", value=lat_default,
                                              min_value=-90.0, max_value=90.0, step=0.01, key="nc_lat")
                    lon_val = st.number_input("经度", value=lon_default,
                                              min_value=-180.0, max_value=180.0, step=0.01, key="nc_lon")
                    if lat_vals is not None:
                        st.caption(f"范围: {lat_vals[0]:.2f}-{lat_vals[-1]:.2f}N, "
                                   f"{float(lon_vals[0]):.2f}-{float(lon_vals[-1]):.2f}E")
                else:
                    lat_val = None
                    lon_val = None
            else:
                st.info("未检测到空间维度")
                spatial_mode = "area_mean"
                lat_val, lon_val = None, None

        with ex2:
            if vertical_dim and vertical_dim in ds.coords:
                level_vals = ds.coords[vertical_dim].values
                level_display = [f"{v} hPa" if float(v) > 50 else f"{v}" for v in level_vals]
                level_sel = st.selectbox("选择层", options=list(range(len(level_vals))),
                                         format_func=lambda i: str(level_display[i]),
                                         key="nc_level")
                level_val = float(level_vals[level_sel])
            elif vertical_dims:
                st.caption(f"垂直维度: {', '.join(vertical_dims.keys())}（默认全层）")
                level_val = None
            else:
                level_val = None

        with ex3:
            tdim_keys = list(time_dims.keys())
            if tdim_keys:
                st.caption(f"时间维度: {tdim_keys[0]} ({dims_info[tdim_keys[0]]['size']} 步)" +
                           " - 完整保留")
            st.metric("原始数据量", f"{np.prod([dim['size'] for dim in dims_info.values()]):,.0f} 格点")

        # 提取按钮
        if st.button("[提取] 提取为站点数据", use_container_width=True, key="nc_extract"):
            if not spatial_dims or (spatial_mode == "单点（最近邻）" and lat_val is None):
                st.warning("请先指定提取方式")
            else:
                with st.spinner("正在提取数据..."):
                    df_extracted, err = extract_netcdf_to_df(
                        ds, lat_dim, lon_dim,
                        "point" if spatial_mode == "单点（最近邻）" else "area_mean",
                        lat_val, lon_val,
                        vertical_dim, level_val,
                        tdim_keys[0] if tdim_keys else None
                    )
                if err:
                    st.error(err)
                else:
                    st.session_state["nc_extracted_df"] = df_extracted
                    st.rerun()

        # 已提取的结果
        extracted = st.session_state.get("nc_extracted_df")
        if extracted is not None:
            df = extracted
            # 列名标准化
            df = normalize_columns(df)
            df = parse_timestamp(df)
            source = f"NetCDF: {uploaded_nc.name}"

            st.success(f"[OK] 提取完成: {len(df)} 条记录 | {len(df.columns)} 个字段")
            with st.expander("[列表] 数据预览"):
                st.dataframe(df.head(20), use_container_width=True)

    # ---- 公共：标准化 + 时间解析 ----
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
