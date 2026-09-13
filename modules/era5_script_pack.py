"""ERA5 脚本包交付：把合法请求体渲染成可离线运行的六文件 ZIP。

设计依据：`docs/superpowers/specs/2026-09-13-chart-reader-and-era5-delivery-design.md`
第 5.4.2 / 5.4.3 节与附录 A（对 Copernicus CDS API 的在线实测结论）。

本模块只依赖标准库（`io` / `zipfile` / `textwrap` / `json` / `datetime`），
永不 import `cdsapi` / `xarray` / `netCDF4` / `streamlit` / `pandas`：
生成的脚本正文以字符串模板存放，重依赖只在用户本机运行时才需要。

对外接口：

- :func:`render_script` — 生成 `era5_download.py`
- :func:`render_readme` — 生成 `README.txt`
- :func:`render_cdsapirc_example` — 生成 `.cdsapirc.example`
- :func:`render_requirements` — 生成 `requirements.txt`
- :func:`render_bat` / :func:`render_sh` — 生成可选的批处理加速器
- :func:`build_era5_zip` — 打包为 ZIP 字节串
"""

import io
import json
import textwrap
import zipfile
from datetime import datetime

__all__ = [
    "render_script",
    "render_readme",
    "render_cdsapirc_example",
    "render_requirements",
    "render_bat",
    "render_sh",
    "build_era5_zip",
]


# --------------------------------------------------------------------------
# 请求体归一化
# --------------------------------------------------------------------------

def _clean_payload(payload):
    """校验并归一化请求体，返回新字典。

    - `format` 键在 2024-09 迁移后已废弃（四个数据集均返回 HTTP 422），
      出现即视为调用方违约，直接报错而不是静默丢弃；
    - 缺少 `data_format` 时服务端会**静默返回 GRIB**，故补齐默认值；
    - 缺少 `download_format` 时服务端默认 `unarchived`，同样补齐。
    """
    if not isinstance(payload, dict):
        raise TypeError("payload 必须是 dict，实际为 %s" % type(payload).__name__)
    if "format" in payload:
        raise ValueError("payload 含已废弃的 format 键；"
                         "请改用 data_format（grib/netcdf）与 download_format"
                         "（zip/unarchived）")
    clean = dict(payload)
    clean.setdefault("data_format", "netcdf")
    clean.setdefault("download_format", "unarchived")
    return clean


def _py_literal(value, level=0):
    """把请求体渲染成合法、可读、缩进良好的 Python 字面量。

    不使用 JSON 是因为 JSON 的 true/false/null 不是合法的 Python 字面量；
    字符串一律用 `json.dumps` 转义，保证中文与引号安全。
    """
    pad = "    " * level
    inner = "    " * (level + 1)
    if isinstance(value, dict):
        if not value:
            return "{}"
        items = [
            "%s%s: %s" % (inner, json.dumps(key, ensure_ascii=False),
                          _py_literal(item, level + 1))
            for key, item in value.items()
        ]
        return "{\n" + ",\n".join(items) + "\n" + pad + "}"
    if isinstance(value, (list, tuple)):
        if not value:
            return "[]"
        scalar = all(isinstance(item, (str, int, float, bool)) or item is None
                     for item in value)
        if scalar and len(value) <= 6:
            return "[" + ", ".join(_py_literal(item, level) for item in value) + "]"
        items = ["%s%s" % (inner, _py_literal(item, level + 1)) for item in value]
        return "[\n" + ",\n".join(items) + "\n" + pad + "]"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "True" if value else "False"
    if value is None:
        return "None"
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, int):
        return repr(value)
    return json.dumps(str(value), ensure_ascii=False)


# --------------------------------------------------------------------------
# 生成脚本正文
# --------------------------------------------------------------------------

_SCRIPT_TEMPLATE = textwrap.dedent('''\
    #!/usr/bin/env python3
    """ERA5 数据下载脚本（由气象网站 ERA5 引导页生成）。

    用法：先手工打开终端，然后执行

        python era5_download.py

    凭证只从本机 ~/.cdsapirc 读取，本脚本不接受任何命令行密钥参数。
    请求参数已烘焙在下方 PARAMS 中，与网站上生成的请求完全一致，无需手工编辑。
    """

    import math
    import os
    import zipfile

    PARAMS = @@PARAMS@@

    DATASET = @@DATASET@@
    CDS_API_URL = "https://cds.climate.copernicus.eu/api"
    DATASET_PAGE = "https://cds.climate.copernicus.eu/datasets/" + DATASET
    CDS_RC_PATH = os.path.join(os.path.expanduser("~"), ".cdsapirc")

    # =====================================================================
    # 单位换算（纯函数，可离线校验）
    # =====================================================================

    def k_to_c(v):
        """开尔文 → 摄氏度。"""
        return v - 273.15


    def m_to_mm(v):
        """米 → 毫米（降水等累计量）。"""
        return v * 1000.0


    def pa_to_hpa(v):
        """帕 → 百帕。"""
        return v / 100.0


    def frac_to_pct(v):
        """0–1 比例 → 百分数。"""
        return v * 100.0


    def geopotential_to_height(v):
        """位势 → 位势高度（标准重力加速度 9.80665 m/s²）。"""
        return v / 9.80665


    def uv_to_speed_dir(u, v):
        """u/v 分量 → (风速, 气象风向)。

        气象风向指风**来自**的方位：正北为 0°，顺时针增大。
        """
        speed = math.hypot(u, v)
        direction = (270.0 - math.degrees(math.atan2(v, u))) % 360.0
        return speed, direction


    # =====================================================================
    # CSV 列名映射与换算表（与气象网站「数据导入」Tab 的字段一致）
    # =====================================================================

    CSV_COLUMN_NAMES = {
        "2m_temperature": "temperature",
        "2m_dewpoint_temperature": "dewpoint",
        "skin_temperature": "skin_temperature",
        "surface_pressure": "pressure",
        "mean_sea_level_pressure": "mslp",
        "total_precipitation": "precipitation",
        "total_cloud_cover": "cloud_cover",
        "cloud_cover": "cloud_cover",
        "snow_depth": "snow_depth",
        "relative_humidity": "humidity",
        "geopotential": "geopotential_height",
    }

    SCALE_BY_VARIABLE = {
        "2m_temperature": "K2C",
        "2m_dewpoint_temperature": "K2C",
        "skin_temperature": "K2C",
        "soil_temperature_level_1": "K2C",
        "temperature": "K2C",
        "surface_pressure": "PA2HPA",
        "mean_sea_level_pressure": "PA2HPA",
        "total_precipitation": "M2MM",
        "potential_evaporation": "M2MM",
        "total_cloud_cover": "FRAC2PCT",
        "cloud_cover": "FRAC2PCT",
        "geopotential": "GEOPOT2HEIGHT",
    }

    WIND_PAIRS = (
        ("10m_u_component_of_wind", "10m_v_component_of_wind"),
        ("u_component_of_wind", "v_component_of_wind"),
    )

    PREFERRED_COLUMNS = (
        "timestamp", "temperature", "dewpoint", "skin_temperature",
        "pressure", "mslp", "precipitation", "humidity", "cloud_cover",
        "snow_depth", "wind_speed", "wind_direction", "geopotential_height",
    )


    def csv_column_name(variable):
        """ERA5 变量名 → CSV 列名；未列入映射表的变量保留原名。"""
        return CSV_COLUMN_NAMES.get(variable, variable)


    def convert_value(variable, value):
        """按变量名应用单位换算；无换算的变量原样返回。"""
        if value is None:
            return value
        scale = SCALE_BY_VARIABLE.get(variable)
        if scale == "K2C":
            return k_to_c(value)
        if scale == "M2MM":
            return m_to_mm(value)
        if scale == "PA2HPA":
            return pa_to_hpa(value)
        if scale == "FRAC2PCT":
            return frac_to_pct(value)
        if scale == "GEOPOT2HEIGHT":
            return geopotential_to_height(value)
        return value


    def column_order(variables):
        """变量名列表 → CSV 列顺序；u/v 分量合成 wind_speed 与 wind_direction。"""
        components = [item for pair in WIND_PAIRS for item in pair]
        names = []
        for variable in variables:
            if variable in components:
                continue
            column = csv_column_name(variable)
            if column not in names:
                names.append(column)
        present = set(variables)
        for u_name, v_name in WIND_PAIRS:
            if u_name in present and v_name in present:
                for extra in ("wind_speed", "wind_direction"):
                    if extra not in names:
                        names.append(extra)
                break

        def sort_key(name):
            if name in PREFERRED_COLUMNS:
                return (0, PREFERRED_COLUMNS.index(name), name)
            return (1, 0, name)

        return sorted(names, key=sort_key)


    def format_timestamp(value):
        """datetime / numpy.datetime64 / 字符串 → ISO 8601 字符串。"""
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1]
        text = text.replace(" ", "T")
        if "." in text:
            text = text.split(".", 1)[0]
        if "+" in text[10:]:
            text = text[:text.index("+", 10)]
        return text


    # =====================================================================
    # 可读报错
    # =====================================================================

    def classify_error(text):
        """把 CDS / HTTP 错误文本归类，返回 (类别, 中文处置提示)。"""
        low = (text or "").lower()
        if ("terms and conditions" in low or "not agreed" in low
                or "licence" in low or "license" in low):
            return "licence", (
                "数据集许可尚未接受。请登录 CDS 后打开 %s ，"
                "在该数据集下载页手工勾选并接受许可（API 无法代办，"
                "可在个人资料页确认已接受的许可清单），然后重新运行本脚本。"
                % DATASET_PAGE
            )
        if "422" in low or "unprocessable" in low:
            return "http_422", (
                "请求参数不被该数据集接受（HTTP 422）。"
                "本脚本提交的键集为：%s 。请登录 CDS 下载表单核对；"
                "注意已废弃的 format 键必须换成 data_format 与 download_format，"
                "且变量名必须在该数据集的可用枚举内。" % ", ".join(sorted(PARAMS))
            )
        if "cost limits exceeded" in low or ("403" in low and "cost" in low):
            return "cost_limit", (
                "已触发 CDS 的 netCDF 成本限额（HTTP 403，cost limits exceeded）。"
                "请缩小请求范围：减少变量、缩短时段或缩小区域后再试。"
            )
        if "queued requests" in low or "temporarily limited" in low:
            return "queue_limit", (
                "该数据集的排队请求数已达上限"
                "（Number of API queued requests for this dataset is temporarily "
                "limited）。请等待已有请求完成，或减少请求规模后稍后重试。"
            )
        if "401" in low or "unauthorized" in low or "invalid key" in low:
            return "auth", (
                "凭证无效或缺失。请检查 %s 中的 url 与 key"
                "（新版 API 没有 uid 字段）。" % CDS_RC_PATH
            )
        return "other", "未分类的错误，请把下面的原文反馈给站点维护者。"


    def check_config():
        """检查本机 ~/.cdsapirc；返回 (是否可用, 提示文本)。"""
        if os.path.exists(CDS_RC_PATH):
            return True, ""
        lines = [
            "未找到配置文件：%s" % CDS_RC_PATH,
            "请在用户主目录新建 .cdsapirc，内容为两行（新版 API 没有 uid 字段）：",
            "  url: %s" % CDS_API_URL,
            "  key: <你的 API Key>",
            "提示：旧式「uid:key」会走已废弃的 LegacyClient 分支而失败。",
            "可参考脚本包内的 .cdsapirc.example。",
        ]
        return False, "\\n".join(lines)


    # =====================================================================
    # 下载与解包
    # =====================================================================

    def script_dir():
        """脚本所在目录；被 exec 加载（没有 __file__）时退回当前工作目录。"""
        path = globals().get("__file__")
        return os.path.dirname(os.path.abspath(path)) if path else os.getcwd()


    def download(target):
        """调用 CDS 客户端下载；cdsapi 延迟导入，保证加载脚本时零副作用。"""
        available, hint = check_config()
        if not available:
            raise RuntimeError(hint)
        import cdsapi

        client = cdsapi.Client(progress=True)
        return client.retrieve(DATASET, PARAMS, target)


    def safe_extract(archive, out_dir):
        """解包 ZIP，拒绝绝对路径与 ../ 穿越（Zip Slip）。"""
        root = os.path.abspath(out_dir)
        for member in archive.namelist():
            name = member.replace("\\\\", "/")
            if name.startswith("/") or ".." in name.split("/"):
                raise RuntimeError("压缩包内含不安全路径：%s" % member)
            archive.extract(member, out_dir)
        return root


    def unpack_if_zip(path):
        """多变量或多文件请求可能返回 ZIP；解包出全部 .nc 并返回文件清单。"""
        if not zipfile.is_zipfile(path):
            return [path]
        out_dir = os.path.join(script_dir(), "era5_nc")
        os.makedirs(out_dir, exist_ok=True)
        with zipfile.ZipFile(path) as archive:
            safe_extract(archive, out_dir)
        names = sorted(
            os.path.join(out_dir, name)
            for name in os.listdir(out_dir) if name.endswith(".nc")
        )
        print("下载结果是 ZIP，已解包 %d 个 netCDF 文件到 %s" % (len(names), out_dir))
        return names


    # =====================================================================
    # NetCDF → CSV
    # =====================================================================

    def time_dim_name(dataset):
        """兼容新版 netCDF 的 valid_time 与旧版的 time 时间维。"""
        for candidate in ("time", "valid_time"):
            if candidate in dataset.dims:
                return candidate
        raise KeyError("netCDF 中既没有 time 维也没有 valid_time 维")


    def merge_expver(dataset):
        """ERA5T 与最终产品并存：沿 expver 维合并（最终产品优先，其后回填）。"""
        if "expver" not in dataset.dims:
            if "expver" in dataset.variables:
                return dataset.drop_vars("expver", errors="ignore")
            return dataset
        if dataset.sizes.get("expver", 1) <= 1:
            return dataset.isel(expver=0).drop_vars("expver", errors="ignore")
        labels = [str(value) for value in dataset["expver"].values.ravel().tolist()]
        order = sorted(range(len(labels)), key=lambda i: (labels[i] != "0001", i))
        merged = None
        for index in order:
            part = dataset.isel(expver=index).drop_vars("expver", errors="ignore")
            merged = part if merged is None else merged.combine_first(part)
        return merged


    def reduce_to_series(dataset, variable):
        """取变量并沿空间维（及气压层）求平均，得到只含时间维的一维序列。

        请求带区域时一个时次会有多个格点，这里取区域平均；
        如需单点原值，请把区域收缩到单个格点后重新生成脚本。
        """
        data = dataset[variable]
        spatial = [name for name in ("latitude", "longitude", "lat", "lon")
                   if name in data.dims]
        if spatial:
            data = data.mean(dim=spatial, skipna=True)
        extra = [name for name in data.dims if name != "time"]
        if extra:
            data = data.mean(dim=extra, skipna=True)
        return data


    def dataset_frame(dataset):
        """单个 netCDF 数据集 → 宽表 DataFrame（timestamp 列为 ISO 字符串）。"""
        import pandas as pd

        dataset = merge_expver(dataset)
        time_name = time_dim_name(dataset)
        if time_name != "time":
            dataset = dataset.rename({time_name: "time"})

        series = {}
        for variable in dataset.data_vars:
            value = reduce_to_series(dataset, variable)
            if "time" in value.dims:
                series[variable] = value
        if not series:
            raise RuntimeError("该 netCDF 中没有带时间维的变量")

        frame = pd.DataFrame(
            {name: value.to_pandas() for name, value in series.items()})
        components = [item for pair in WIND_PAIRS for item in pair]
        out = pd.DataFrame(index=frame.index)
        for name in frame.columns:
            if name in components:
                continue
            out[csv_column_name(name)] = [
                convert_value(name, value) for value in frame[name].tolist()]
        for u_name, v_name in WIND_PAIRS:
            if u_name in frame.columns and v_name in frame.columns:
                pairs = [
                    uv_to_speed_dir(u, v)
                    for u, v in zip(frame[u_name].tolist(), frame[v_name].tolist())
                ]
                out["wind_speed"] = [item[0] for item in pairs]
                out["wind_direction"] = [item[1] for item in pairs]
                break
        out.insert(0, "timestamp",
                   [format_timestamp(value) for value in frame.index])
        ordered = [name for name in column_order(list(frame.columns))
                   if name in out.columns]
        return out[["timestamp"] + ordered]


    def export_csv(paths, csv_path):
        """把下载到的 netCDF 转成「数据导入」Tab 可识别的宽表 CSV，返回行数。"""
        import pandas as pd
        import xarray as xr

        frames = []
        for path in paths:
            with xr.open_dataset(path) as dataset:
                frames.append(dataset_frame(dataset))
        if not frames:
            raise RuntimeError("没有可转换的 netCDF 文件")
        frame = pd.concat(frames, axis=0)
        frame = frame[~frame.index.duplicated(keep="last")].sort_index()
        frame = frame.reset_index(drop=True)
        frame.to_csv(csv_path, index=False, encoding="utf-8-sig")
        return len(frame)


    # =====================================================================
    # 主流程
    # =====================================================================

    def main():
        print("=" * 64)
        print("ERA5 数据下载")
        print("数据集：%s" % DATASET)
        print("数据集下载页：%s" % DATASET_PAGE)
        print("变量：%s" % ", ".join(PARAMS.get("variable", [])))
        print("范围：%s" % (PARAMS.get("area") or "整幅（未限定区域）"))
        print("格式：%s / %s"
              % (PARAMS.get("data_format"), PARAMS.get("download_format")))
        print("=" * 64)

        available, hint = check_config()
        if not available:
            print(hint)
            return 2

        target = os.path.join(script_dir(), "era5_download.nc")
        print("正在提交请求。状态从 queued 变为 running 可能需要数十分钟到数小时；")
        print("终端可以关闭，请求 ID 会打印在下方，之后可凭它在 CDS 网页取回结果。")
        try:
            download(target)
        except Exception as exc:
            kind, hint = classify_error(str(exc))
            print("[错误 %s] %s" % (kind, exc))
            print(hint)
            return 1

        files = unpack_if_zip(target)
        csv_path = os.path.join(script_dir(), "era5_export.csv")
        try:
            rows = export_csv(files, csv_path)
        except Exception as exc:
            print("[警告] 自动转换 CSV 失败：%s" % exc)
            print("请确认已执行 python -m pip install -r requirements.txt 。")
            print("netCDF 文件仍在：%s" % files)
            return 3
        print("已生成 CSV：%s（%d 行）" % (csv_path, rows))
        print("把该 CSV 拖回气象网站的「数据导入」Tab 即可继续分析。")
        return 0


    if __name__ == "__main__":
        raise SystemExit(main())
    ''')


def render_script(payload, dataset):
    """渲染 `era5_download.py` 源码（不含任何下载副作用，可安全 exec）。"""
    clean = _clean_payload(payload)
    source = _SCRIPT_TEMPLATE
    for token, value in (("@@PARAMS@@", _py_literal(clean)),
                         ("@@DATASET@@", json.dumps(dataset, ensure_ascii=False))):
        if token not in source:
            raise ValueError("模板缺少占位符 %s" % token)
        source = source.replace(token, value)
    return source


# --------------------------------------------------------------------------
# README
# --------------------------------------------------------------------------

def _payload_lines(payload):
    """请求摘要，供 README 与用户核对 CDS 表单。"""
    variables = payload.get("variable") or []
    years = payload.get("year") or []
    months = payload.get("month") or []
    days = payload.get("day")
    times = payload.get("time") or []
    lines = [
        "  变量（%d 个）：%s" % (len(variables), ", ".join(variables)),
        "  年：%s" % ", ".join(years),
        "  月：%s" % ", ".join(months),
        "  日：%s" % ("全部" if days is None else "%d 天" % len(days)),
        "  时次：%s" % ("全部" if not times else ", ".join(times)),
        "  区域 [北, 西, 南, 东]：%s" % (payload.get("area") or "未限定（整幅）"),
        "  格式：data_format=%s，download_format=%s"
        % (payload.get("data_format"), payload.get("download_format")),
    ]
    if payload.get("pressure_level"):
        lines.insert(4, "  气压层：%s" % ", ".join(payload["pressure_level"]))
    return lines


def render_readme(payload, dataset, product_label):
    """渲染 `README.txt`：以手动打开终端为主路径。"""
    clean = _clean_payload(payload)
    page = "https://cds.climate.copernicus.eu/datasets/" + dataset
    lines = [
        "=" * 68,
        "ERA5 数据下载脚本包",
        "生成时间：%s" % datetime.now().strftime("%Y-%m-%d %H:%M"),
        "数据集：%s" % dataset,
        "产品：%s" % product_label,
        "=" * 68,
        "",
        "【怎么用】主路径是手动打开终端敲三条命令，不需要双击任何脚本。",
        "",
        "第 0 步（最容易失败，务必先做）：在本数据集下载页手工接受许可",
        "  1. 登录 https://cds.climate.copernicus.eu/",
        "  2. 打开该数据集下载页：%s" % page,
        "  3. 在页面上手工勾选并接受许可条款（API 无法代办）。",
        "  未接受时报错原文：Client has not agreed to the required terms and conditions",
        "  已接受的许可清单可在 CDS 个人资料页查看。",
        "",
        "第 1 步：打开终端",
        "  Windows：",
        "    - 按 Win + R，输入 cmd 后回车；或",
        "    - 点开始菜单，搜索 PowerShell 并打开。",
        "  macOS：",
        "    - 打开「访达」→ 应用程序 → 实用工具 → 终端。",
        "",
        "第 2 步：在终端里依次执行三条命令（把第一行换成解压后的目录）",
        "  cd 解压后的目录路径",
        "  python -m pip install -r requirements.txt",
        "  python era5_download.py",
        "",
        "【.cdsapirc 放在哪里】",
        "  Windows：C:\\Users\\<你的用户名>\\.cdsapirc",
        "  macOS：/Users/<你的用户名>/.cdsapirc",
        "  Linux：/home/<你的用户名>/.cdsapirc",
        "  内容为两行，注意没有 uid 字段：",
        "    url: https://cds.climate.copernicus.eu/api",
        "    key: <你的 API Key>",
        "  旧式「uid:key」写法会走已废弃的 LegacyClient 分支而失败。",
        "  同目录下的 .cdsapirc.example 可直接复制参考。",
        "",
        "【可选加速器】",
        "  一键运行.bat（Windows）与 运行.sh（macOS / Linux）只是把上面第 2 步的",
        "  三条命令合并执行，属于可选加速器。命令行不熟时可以双击 / 执行它们；",
        "  不安装、不使用它们也完全可以，按第 2 步手工敲命令同样跑通全流程。",
        "",
        "【脚本会做什么】",
        "  1. 读取本机 ~/.cdsapirc（脚本不接受任何命令行密钥参数）；",
        "  2. 按下方烘焙好的参数向 CDS 提交请求并等待；",
        "  3. 若下载结果是 ZIP（多变量或多文件请求可能如此）则自动解包；",
        "  4. 把 netCDF 转为宽表 CSV，列名为 timestamp 加气象要素名，",
        "     其中 temperature / dewpoint / pressure / mslp / precipitation /",
        "     cloud_cover / humidity / snow_depth / wind_speed / wind_direction /",
        "     geopotential_height 已完成单位换算；",
        "  5. 时间列统一写成 ISO 8601 字符串，时间维名为 time 或 valid_time 均可，",
        "     存在 expver 维（ERA5T 与最终产品并存）时会自动合并；",
        "  6. 区域请求的多个格点会做区域平均，需要单点原值请把区域缩到单个格点。",
        "",
        "【输出文件】",
        "  era5_download.nc        下载的原始 netCDF（返回 ZIP 时为其本身）",
        "  era5_nc/*.nc            ZIP 解包出的 netCDF",
        "  era5_export.csv         宽表 CSV，可直接拖回气象网站的「数据导入」Tab",
        "",
        "【本次请求摘要】",
    ]
    lines.extend(_payload_lines(clean))
    lines.extend([
        "",
        "【常见错误对照表】",
        "  1. Client has not agreed to the required terms and conditions",
        "     → 回第 0 步，在该数据集下载页手工接受许可后重试。",
        "  2. HTTP 422（请求参数不被该数据集接受）",
        "     → 核对变量名与键集；注意已废弃的 format 键已换成",
        "       data_format（grib/netcdf）与 download_format（zip/unarchived）。",
        "  3. HTTP 403，cost limits exceeded",
        "     → 触发了 netCDF 成本限额，减少变量、缩短时段或缩小区域。",
        "  4. Number of API queued requests for this dataset is temporarily limited",
        "     → 排队请求数达上限，等待已有请求完成或减小请求规模后重试。",
        "  5. 下载得到 ZIP",
        "     → 正常现象，脚本会自动解包出全部 .nc 文件。",
        "  6. 时间维叫 valid_time 而不是 time",
        "     → 新版 netCDF 的正常命名，脚本两种都兼容。",
        "  7. 缺少 .cdsapirc",
        "     → 按上面的位置与内容创建配置文件后重试。",
        "",
        "【数据集规模提示】",
        "  单个请求的字段数存在上限，超限不会报错而是长期排队；",
        "  同一个数据集同时排队的请求数也有上限。请求过大时请分批下载。",
        "",
    ])
    return "\n".join(lines)


# --------------------------------------------------------------------------
# 其余文件
# --------------------------------------------------------------------------

def render_cdsapirc_example():
    """渲染 `.cdsapirc.example`。"""
    return textwrap.dedent('''\
        # Copernicus CDS 凭证示例（新版 API）
        #
        # 用法：
        #   1. 登录 https://cds.climate.copernicus.eu/ ，在个人资料页复制 API Key；
        #   2. 把本文件复制到用户主目录并改名为 .cdsapirc
        #      Windows：C:\\Users\\<你的用户名>\\.cdsapirc
        #      macOS / Linux：~/.cdsapirc
        #   3. 把下面的 <你的 API Key> 换成你自己的 Key。
        #
        # 注意：新版 API 只有 url 与 key 两行，没有 uid 字段；
        #       写成旧式「uid:key」会走已废弃的 LegacyClient 分支而失败。
        url: https://cds.climate.copernicus.eu/api
        key: <你的 API Key>
        ''')


def render_requirements():
    """渲染 `requirements.txt`：这些库只在用户本机运行脚本时需要。"""
    return textwrap.dedent('''\
        # ERA5 下载脚本的依赖（只在你的本机运行，气象网站本身不安装它们）
        cdsapi>=0.7.7
        xarray
        netCDF4
        pandas
        ''')


def render_bat():
    """渲染 `一键运行.bat`：可选加速器，非主路径。"""
    return textwrap.dedent('''\
        @echo off
        chcp 65001 >nul
        cd /d "%~dp0"
        echo [可选加速器] 本文件只是把 README 里的三条命令合并执行。
        echo 不用它也可以：手动打开终端后自行敲命令即可。
        echo.
        echo [1/2] 安装依赖...
        python -m pip install -r requirements.txt
        if errorlevel 1 (
            echo 依赖安装失败，请检查 Python 与网络后重试。
            pause
            exit /b 1
        )
        echo [2/2] 开始下载 ERA5 数据...
        python era5_download.py
        echo.
        echo 运行结束。若需重新下载，可直接再次双击本文件。
        pause
        ''')


def render_sh():
    """渲染 `运行.sh`：可选加速器，非主路径，带 set -e。"""
    return textwrap.dedent('''\
        #!/usr/bin/env bash
        # [可选加速器] 本文件只是把 README 里的三条命令合并执行。
        # 不用它也可以：手动打开终端后自行敲命令即可。
        set -e
        cd "$(dirname "$0")"
        echo "[可选加速器] 安装依赖..."
        python3 -m pip install -r requirements.txt
        echo "开始下载 ERA5 数据..."
        python3 era5_download.py
        echo "运行结束。"
        ''')


# --------------------------------------------------------------------------
# ZIP 打包
# --------------------------------------------------------------------------

def _zip_date_time():
    """ZIP 条目时间戳（DOS 格式需要 6 元组，年份下限 1980）。"""
    now = datetime.now()
    return (now.year, now.month, now.day, now.hour, now.minute, now.second)


def build_era5_zip(payload, dataset, product_label):
    """把六个文件打包成 ZIP，返回字节串（供 `st.download_button` 使用）。"""
    entries = (
        ("era5_download.py", render_script(payload, dataset), 0o644),
        (".cdsapirc.example", render_cdsapirc_example(), 0o644),
        ("README.txt", render_readme(payload, dataset, product_label), 0o644),
        ("requirements.txt", render_requirements(), 0o644),
        ("一键运行.bat", render_bat(), 0o644),
        ("运行.sh", render_sh(), 0o755),
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text, mode in entries:
            info = zipfile.ZipInfo(name, date_time=_zip_date_time())
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (mode & 0xFFFF) << 16
            archive.writestr(info, text.encode("utf-8"))
    return buffer.getvalue()
