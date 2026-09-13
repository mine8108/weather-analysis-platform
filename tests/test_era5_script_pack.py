"""ERA5 脚本包 ZIP 交付回归测试。

契约来自 `docs/superpowers/specs/2026-09-13-chart-reader-and-era5-delivery-design.md`
第 5.4.2 / 5.4.3 节与附录 A（CDS API 在线实测结论）：

- ZIP 恰好六个条目；
- 请求体使用 `data_format` + `download_format`，绝不出现已废弃的 `format` 键；
- 生成脚本兼容 `valid_time` 时间维与 `expver`（ERA5T）合并；
- 许可证未接受 / 422 / 403 成本限额 / 队列受限 / `.cdsapirc` 缺失均有可读报错；
- 生成脚本以 `exec` 独立加载后，六个换算纯函数取值正确（离线可验证的最强证据）；
- README 以手动打开终端为主路径，`.bat` / `.sh` 仅作可选加速器；
- 脚本只读本机 `~/.cdsapirc`，不经手任何命令行密钥。

payload 采用本文件内的字面量，测试自包含，不依赖并行开发的 `modules.era5_guide`。

无 pytest 时可直接运行（`python -B tests/test_era5_script_pack.py`）。
"""
import io
import os
import sys
import zipfile

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from modules.era5_script_pack import (  # noqa: E402
    build_era5_zip,
    render_bat,
    render_cdsapirc_example,
    render_readme,
    render_requirements,
    render_script,
    render_sh,
)

ENTRY_NAMES = {
    "era5_download.py",
    ".cdsapirc.example",
    "README.txt",
    "requirements.txt",
    "一键运行.bat",
    "运行.sh",
}

DATASET = "reanalysis-era5-land"
PRODUCT_LABEL = "ERA5-Land (地表小时, 0.1°)"

# 与 modules.era5_guide.build_payload 的产物同构的合法请求体
PAYLOAD = {
    "variable": ["2m_temperature", "10m_u_component_of_wind",
                 "10m_v_component_of_wind"],
    "year": ["2024"],
    "month": ["01"],
    "day": ["%02d" % d for d in range(1, 32)],
    "time": ["%02d:00" % h for h in range(24)],
    "area": [41.0, 115.0, 39.0, 118.0],
    "data_format": "netcdf",
    "download_format": "unarchived",
}


def _script_source():
    return render_script(PAYLOAD, DATASET)


def _script_namespace():
    """在独立命名空间加载生成的脚本；不得触发任何下载或第三方导入。"""
    source = _script_source()
    ns = {"__name__": "_era5_generated"}
    exec(compile(source, "era5_download.py", "exec"), ns)
    return ns


# ---------------------------------------------------------------- ZIP 结构

def test_zip_entries_are_exactly_the_six_contracted_files():
    data = build_era5_zip(PAYLOAD, DATASET, PRODUCT_LABEL)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
    assert set(names) == ENTRY_NAMES, sorted(names)
    assert len(names) == 6, names


def test_build_era5_zip_returns_bytes_with_readable_members():
    data = build_era5_zip(PAYLOAD, DATASET, PRODUCT_LABEL)
    assert isinstance(data, bytes), type(data)
    assert data[:2] == b"PK", data[:4]
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert zf.testzip() is None
        script = zf.read("era5_download.py").decode("utf-8")
        readme = zf.read("README.txt").decode("utf-8")
        example = zf.read(".cdsapirc.example").decode("utf-8")
    assert script == _script_source()
    assert PRODUCT_LABEL in readme
    assert readme.startswith("=" * 68)
    assert "url: https://cds.climate.copernicus.eu/api" in example


def test_render_script_rejects_legacy_format_key():
    """已废弃的 format 键必须显式报错，而不是静默透传进请求体。"""
    bad = dict(PAYLOAD)
    bad["format"] = "netcdf"
    try:
        render_script(bad, DATASET)
    except ValueError as exc:
        assert "format" in str(exc), str(exc)
    else:
        raise AssertionError("含 format 键的 payload 必须被拒绝")


def test_render_script_fills_missing_format_keys():
    """缺 data_format 时服务端会静默返回 GRIB，因此必须补齐两个格式键。"""
    lean = {"variable": ["2m_temperature"], "year": ["2024"], "month": ["01"],
            "day": ["01"], "time": ["00:00"]}
    ns = {"__name__": "_era5_generated"}
    exec(compile(render_script(lean, DATASET), "era5_download.py", "exec"), ns)
    assert ns["PARAMS"]["data_format"] == "netcdf"
    assert ns["PARAMS"]["download_format"] == "unarchived"


# ------------------------------------------------------- 请求关键字与兼容性

def test_script_uses_data_format_and_download_format_and_never_format():
    source = _script_source()
    assert "data_format" in source, "缺少 data_format"
    assert "download_format" in source, "缺少 download_format"
    assert "'format'" not in source, "生成脚本不得把 format 作为请求键"
    assert '"format"' not in source, "生成脚本不得把 format 作为请求键"


def test_script_payload_has_no_legacy_format_key():
    ns = _script_namespace()
    params = ns["PARAMS"]
    assert "format" not in params, sorted(params)
    assert params["data_format"] == "netcdf"
    assert params["download_format"] == "unarchived"


def test_script_supports_valid_time_and_expver():
    source = _script_source()
    assert "valid_time" in source, "必须兼容新版 netCDF 的 valid_time 时间维"
    assert "expver" in source, "必须处理 ERA5T 合并产生的 expver 维"


# ------------------------------------------------------------ 可读报错覆盖

def test_script_error_keywords_cover_licence_422_cost_queue_and_cdsapirc():
    source = _script_source()
    for keyword in ("terms and conditions", "422", "403", "cost limits exceeded",
                    "queued requests", ".cdsapirc"):
        assert keyword in source, "生成脚本缺少错误关键字：%s" % keyword


def test_script_classifies_real_cds_errors():
    ns = _script_namespace()
    classify = ns["classify_error"]
    cases = {
        "Client has not agreed to the required terms and conditions.": "licence",
        "HTTP 422 Unprocessable Entity: the request is not valid": "http_422",
        "403 Client Error: cost limits exceeded for this request": "cost_limit",
        "Number of API queued requests for this dataset is temporarily "
        "limited": "queue_limit",
    }
    for message, expected in cases.items():
        kind, hint = classify(message)
        assert kind == expected, (message, kind)
        assert hint, "分类必须带中文处置提示：%s" % message


# ---------------------------------------------------------- 凭证不经命令行

def test_script_has_no_argv_or_env_api_key_handling():
    source = _script_source()
    assert "sys.argv" not in source, "脚本不得解析命令行参数"
    assert "CDSAPI_KEY" not in source, "脚本不得读取密钥环境变量"
    assert "CDSAPI_URL" not in source, "脚本不得读取地址环境变量"
    assert "getenv" not in source, "脚本不得读取环境变量中的密钥"
    assert ".cdsapirc" in source, "脚本必须只从本机 .cdsapirc 读取凭证"


# ------------------------------------------------------------- README 主路径

def test_readme_teaches_manual_terminal_use():
    readme = render_readme(PAYLOAD, DATASET, PRODUCT_LABEL)
    for keyword in ("Win + R", "cmd", "PowerShell", "应用程序", "实用工具", "终端"):
        assert keyword in readme, "README 缺少打开终端说明：%s" % keyword
    assert "pip install -r requirements.txt" in readme
    assert "python era5_download.py" in readme


def test_readme_states_manual_licence_acceptance_and_optional_accelerators():
    readme = render_readme(PAYLOAD, DATASET, PRODUCT_LABEL)
    assert "terms and conditions" in readme
    assert "手工接受" in readme, "必须说明许可证只能在该数据集下载页手工接受"
    assert DATASET in readme, "README 必须给出该数据集的下载页链接"
    assert "一键运行.bat" in readme and "运行.sh" in readme
    assert "可选" in readme, "bat/sh 必须标注为可选加速器"
    assert "不需要" in readme or "可以不用" in readme, \
        "README 必须说明不用 bat/sh 也能跑通"


def test_readme_describes_outputs_and_error_table():
    readme = render_readme(PAYLOAD, DATASET, PRODUCT_LABEL)
    assert "CSV" in readme and "数据导入" in readme
    assert "422" in readme and "403" in readme
    assert "cost limits exceeded" in readme
    assert "queued requests" in readme


# --------------------------------------------------------- 无废弃地址与依赖

def test_generated_files_avoid_deprecated_cds_hosts():
    blobs = [
        _script_source(),
        render_readme(PAYLOAD, DATASET, PRODUCT_LABEL),
        render_cdsapirc_example(),
    ]
    for blob in blobs:
        assert "/api/v2" not in blob, "不得出现已停用的 /api/v2 地址"
        assert "cds-beta" not in blob, "不得出现已停用的 cds-beta 主机"


def test_cdsapirc_example_points_at_current_api_without_uid():
    example = render_cdsapirc_example()
    assert "url: https://cds.climate.copernicus.eu/api" in example
    assert "key:" in example
    assert "uid" in example, "必须说明旧式 uid:key 已废弃"
    assert ".cdsapirc" in example


def test_requirements_lists_the_four_runtime_libraries():
    req = render_requirements()
    assert "cdsapi>=0.7.7" in req
    for name in ("xarray", "netCDF4", "pandas"):
        assert name in req, name


def test_bat_and_sh_are_optional_accelerators():
    bat = render_bat()
    assert "pip install -r requirements.txt" in bat
    assert "era5_download.py" in bat
    assert "pause" in bat, "bat 结束时必须暂停以便阅读输出"
    assert "可选" in bat

    sh = render_sh()
    assert "set -e" in sh
    assert "pip install -r requirements.txt" in sh
    assert "era5_download.py" in sh
    assert "可选" in sh


# ----------------------------------------------------- 生成脚本的实跑校验

def test_generated_script_embeds_payload_verbatim():
    ns = _script_namespace()
    assert ns["PARAMS"] == PAYLOAD, ns["PARAMS"]
    source = _script_source()
    assert "PARAMS = {" in source, "参数必须以 PARAMS = {...} 形式内嵌"
    assert "reanalysis-era5-land" in source
    assert "2m_temperature" in source


def test_exec_does_not_run_any_download():
    ns = _script_namespace()
    assert callable(ns["main"]), "脚本必须提供 main()"
    assert "_era5_generated" == ns["__name__"]
    # 未调用 main 时，命名空间中不得出现任何客户端对象
    assert "client" not in ns, sorted(k for k in ns if not k.startswith("__"))


def test_loaded_script_defines_expected_pure_functions():
    ns = _script_namespace()
    for name in ("k_to_c", "m_to_mm", "pa_to_hpa", "frac_to_pct",
                 "geopotential_to_height", "uv_to_speed_dir"):
        assert callable(ns.get(name)), "生成脚本缺少纯函数 %s" % name


def test_temperature_conversions():
    ns = _script_namespace()
    k_to_c = ns["k_to_c"]
    assert k_to_c(273.15) == 0.0, k_to_c(273.15)
    assert abs(k_to_c(300.0) - 26.85) < 1e-9
    assert k_to_c(0.0) == -273.15


def test_precipitation_and_pressure_conversions():
    ns = _script_namespace()
    assert ns["m_to_mm"](0.001) == 1.0
    assert ns["m_to_mm"](1.0) == 1000.0
    assert ns["pa_to_hpa"](101325.0) == 1013.25
    assert ns["frac_to_pct"](0.42) == 42.00000000000001 or \
        abs(ns["frac_to_pct"](0.42) - 42.0) < 1e-9


def test_geopotential_conversion():
    ns = _script_namespace()
    height = ns["geopotential_to_height"](9.80665 * 5000.0)
    assert abs(height - 5000.0) < 1e-9, height


def test_uv_to_speed_dir_compass_checkpoints():
    ns = _script_namespace()
    uv = ns["uv_to_speed_dir"]
    assert uv(0.0, -1.0) == (1.0, 0.0), uv(0.0, -1.0)      # 北风
    assert uv(-1.0, 0.0) == (1.0, 90.0), uv(-1.0, 0.0)     # 东风
    assert uv(1.0, 0.0) == (1.0, 270.0), uv(1.0, 0.0)      # 西风
    assert uv(0.0, 1.0) == (1.0, 180.0), uv(0.0, 1.0)      # 南风
    import math
    speed, direction = uv(3.0, 4.0)
    assert speed == 5.0, speed
    expected = (270.0 - math.degrees(math.atan2(4.0, 3.0))) % 360.0
    assert abs(direction - expected) < 1e-9, direction


def test_csv_column_mapping_matches_import_schema():
    ns = _script_namespace()
    column = ns["csv_column_name"]
    expected = {
        "2m_temperature": "temperature",
        "2m_dewpoint_temperature": "dewpoint",
        "skin_temperature": "skin_temperature",
        "surface_pressure": "pressure",
        "mean_sea_level_pressure": "mslp",
        "total_precipitation": "precipitation",
        "total_cloud_cover": "cloud_cover",
        "snow_depth": "snow_depth",
        "relative_humidity": "humidity",
        "geopotential": "geopotential_height",
    }
    for variable, name in expected.items():
        assert column(variable) == name, (variable, column(variable))
    assert column("boundary_layer_height") == "boundary_layer_height", \
        "未映射的变量必须保留原名"


def test_convert_value_applies_unit_conversion():
    ns = _script_namespace()
    convert = ns["convert_value"]
    assert convert("2m_temperature", 273.15) == 0.0
    assert convert("2m_dewpoint_temperature", 263.15) == -10.0
    assert convert("skin_temperature", 280.0) == 6.850000000000023 or \
        abs(convert("skin_temperature", 280.0) - 6.85) < 1e-9
    assert convert("surface_pressure", 100000.0) == 1000.0
    assert convert("mean_sea_level_pressure", 101325.0) == 1013.25
    assert convert("total_precipitation", 0.002) == 2.0
    assert convert("total_cloud_cover", 0.5) == 50.0
    assert convert("relative_humidity", 63.0) == 63.0
    assert convert("snow_depth", 0.12) == 0.12
    assert abs(convert("geopotential", 9.80665 * 850.0) - 850.0) < 1e-9


def test_format_timestamp_produces_iso_string():
    ns = _script_namespace()
    import datetime as _dt
    iso = ns["format_timestamp"]
    assert iso(_dt.datetime(2024, 1, 1, 0, 0)) == "2024-01-01T00:00:00", \
        iso(_dt.datetime(2024, 1, 1, 0, 0))
    assert iso("2024-01-01 06:00:00").startswith("2024-01-01")


def test_column_order_puts_import_columns_first():
    ns = _script_namespace()
    order = ns["column_order"](["snow_depth", "2m_temperature",
                                "10m_u_component_of_wind",
                                "10m_v_component_of_wind"])
    assert order == ["temperature", "snow_depth", "wind_speed",
                     "wind_direction"], order
    assert len(order) == len(set(order)), order


def test_module_imports_only_the_stdlib_whitelist():
    import ast

    path = os.path.join(_APP_DIR, "modules", "era5_script_pack.py")
    with io.open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    allowed = {"io", "zipfile", "textwrap", "json", "datetime"}
    assert imported <= allowed, sorted(imported - allowed)
    for banned in ("cdsapi", "xarray", "netCDF4", "streamlit", "pandas"):
        assert banned not in imported, banned


if __name__ == "__main__":
    import traceback

    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception:
                failed += 1
                print("[FAIL] %s" % name)
                traceback.print_exc()
            else:
                print("[PASS] %s" % name)
    print("\n%s (%d failures)" % ("FAILED" if failed else "ALL PASSED", failed))
    sys.exit(1 if failed else 0)
