"""ERA5 catalogue 与脚本包回归测试。

catalogue 的每一个变量标识符都对 research/era5_variable_enums_2026-09-13.json
（CDS constraints 接口实测快照）做离线校验，CI 不访问网络。

无 pytest 时可直接运行（`python -B tests/test_era5_guide.py`）。
"""
import io
import json
import os
import sys

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

_ENUM_PATH = os.path.join(_APP_DIR, "research", "era5_variable_enums_2026-09-13.json")
with io.open(_ENUM_PATH, encoding="utf-8") as _f:
    ENUMS = json.load(_f)["datasets"]


def test_catalogue_has_no_defects():
    from modules.era5_guide import validate_catalogue
    problems = validate_catalogue()
    assert problems == [], "catalogue 存在缺陷：%s" % problems


def test_every_catalogue_variable_exists_in_cds_enum():
    """catalogue 里的每个变量都必须在该数据集的实际枚举中。"""
    from modules.era5_guide import ERA5_PRODUCTS
    bad = []
    for product, meta in ERA5_PRODUCTS.items():
        allowed = set(ENUMS[meta["dataset"]]["variables"])
        for name in meta["variables"]:
            if name not in allowed:
                bad.append("%s / %s" % (product, name))
    assert bad == [], "以下变量在 CDS 枚举中不存在：%s" % bad


def test_unsupported_variables_are_really_unsupported():
    """标为「不支持」的变量，必须确实不在该数据集的枚举里。"""
    from modules.era5_guide import ERA5_PRODUCTS
    wrong = []
    for product, meta in ERA5_PRODUCTS.items():
        allowed = set(ENUMS[meta["dataset"]]["variables"])
        for name in meta.get("unsupported", {}):
            if name in allowed:
                wrong.append("%s / %s 实际可用，不应标为不支持" % (product, name))
    assert wrong == [], wrong


def test_relative_humidity_absent_from_land_and_single():
    """相对湿度只在气压层提供，这是原实现最主要的错误。"""
    from modules.era5_guide import ERA5_PRODUCTS
    for product, meta in ERA5_PRODUCTS.items():
        if meta["dataset"] in ("reanalysis-era5-land",
                               "reanalysis-era5-single-levels",
                               "reanalysis-era5-land-monthly-means"):
            assert "relative_humidity" not in meta["variables"], product
            assert "relative_humidity" in meta.get("unsupported", {}), product


def test_geopotential_height_is_rejected_with_mapping():
    """位势高度不是 API 变量，必须给出改用位势的说明。"""
    from modules.era5_guide import ERA5_PRODUCTS
    meta = ERA5_PRODUCTS["ERA5 气压层 (0.25°)"]
    assert "geopotential_height" not in meta["variables"]
    assert "geopotential" in meta["variables"]
    info = meta["unsupported"]["geopotential_height"]
    assert "9.80665" in info["reason"]


def test_metadata_completeness():
    """每个变量的标签、单位、分组、换算说明齐备，分组在 GROUP_ORDER 内。"""
    from modules.era5_guide import ERA5_PRODUCTS, GROUP_ORDER, SCALES
    for product, meta in ERA5_PRODUCTS.items():
        for name, info in meta["variables"].items():
            for field in ("label", "unit", "group", "scale", "note"):
                assert field in info, "%s / %s 缺 %s" % (product, name, field)
            assert info["group"] in GROUP_ORDER, (product, name, info["group"])
            assert info["scale"] is None or info["scale"] in SCALES, (product, name)


# ============================================================
# 二、payload 构建、键集白名单与规模估算
# ============================================================

def test_payload_keys_within_allowed_set():
    """每个产品的 payload 键集必须是该数据集允许键的子集。"""
    from modules.era5_guide import (ERA5_PRODUCTS, build_payload,
                                    KEYS_ALLOWED_BY_DATASET)
    for product, meta in ERA5_PRODUCTS.items():
        variables = list(meta["variables"])[:2]
        levels = ["500"] if meta["type"] == "pressure" else None
        payload = build_payload(product, [2024], [1], variables, levels,
                                [41.0, 115.0, 39.0, 118.0])
        allowed = set(KEYS_ALLOWED_BY_DATASET[meta["dataset"]])
        assert set(payload) <= allowed, (product, sorted(set(payload) - allowed))


def test_payload_keys_match_recorded_enum_snapshot():
    """键集白名单必须与快照记录的 allowed_keys 逐数据集一致。"""
    from modules.era5_guide import ERA5_PRODUCTS, KEYS_ALLOWED_BY_DATASET
    for product, meta in ERA5_PRODUCTS.items():
        recorded = set(ENUMS[meta["dataset"]]["allowed_keys"])
        assert set(KEYS_ALLOWED_BY_DATASET[meta["dataset"]]) == recorded, product


def test_land_and_single_levels_differ_in_product_type_key():
    """同属小时数据的两个数据集键集不同，白名单不得按类型合并。"""
    from modules.era5_guide import KEYS_ALLOWED_BY_DATASET
    land = set(KEYS_ALLOWED_BY_DATASET["reanalysis-era5-land"])
    single = set(KEYS_ALLOWED_BY_DATASET["reanalysis-era5-single-levels"])
    assert "product_type" not in land
    assert "product_type" in single


def test_payload_uses_data_format_and_download_format():
    """必须使用 data_format + download_format，且不得出现已废弃的 format。"""
    from modules.era5_guide import build_payload
    payload = build_payload("ERA5-Land (地表小时, 0.1°)", [2024], [1],
                            ["2m_temperature"], None, [41.0, 115.0, 39.0, 118.0])
    assert payload["data_format"] == "netcdf"
    assert payload["download_format"] == "unarchived"
    assert "format" not in payload


def test_land_payload_has_no_product_type_and_monthly_has_no_day():
    from modules.era5_guide import build_payload
    land = build_payload("ERA5-Land (地表小时, 0.1°)", [2024], [1],
                         ["2m_temperature"], None, None)
    assert "product_type" not in land
    assert "day" in land

    monthly = build_payload("ERA5-Land 月均值 (0.1°)", [2024], [1],
                            ["2m_temperature"], None, None)
    assert "day" not in monthly
    assert monthly["product_type"] == ["monthly_averaged_reanalysis"]
    assert monthly["time"] == ["00:00"]


def test_single_and_pressure_payloads_carry_product_type():
    from modules.era5_guide import build_payload
    single = build_payload("ERA5 再分析单层 (0.25°)", [2024], [1],
                           ["2m_temperature"], None, None)
    assert single["product_type"] == ["reanalysis"]
    pressure = build_payload("ERA5 气压层 (0.25°)", [2024], [1],
                             ["temperature"], ["500", "850"], None)
    assert pressure["product_type"] == ["reanalysis"]
    assert pressure["pressure_level"] == ["500", "850"]


def test_payload_values_are_strings_and_lists():
    """与 CDS 官网表单一致：年/月/日/时全部以零填充字符串列表提交。"""
    from modules.era5_guide import build_payload
    payload = build_payload("ERA5-Land (地表小时, 0.1°)", [2024, 2023], [1, 12],
                            ["2m_temperature"], None, None)
    assert payload["year"] == ["2023", "2024"]
    assert payload["month"] == ["01", "12"]
    assert payload["day"][0] == "01"
    assert len(payload["day"]) == 31
    assert len(payload["time"]) == 24
    assert payload["time"][0] == "00:00"


def test_pressure_levels_are_all_valid():
    """37 个气压层与快照记录一致。"""
    from modules.era5_guide import PRESSURE_LEVELS
    recorded = ENUMS["reanalysis-era5-pressure-levels"]["pressure_levels"]
    assert list(PRESSURE_LEVELS) == sorted(recorded, key=lambda x: int(x))
    assert len(PRESSURE_LEVELS) == 37


def test_validate_payload_rejects_unknown_keys_and_variables():
    from modules.era5_guide import validate_payload
    problems = validate_payload("ERA5-Land (地表小时, 0.1°)",
                                {"format": "netcdf", "variable": ["nope"],
                                 "year": ["2024"], "month": ["01"], "day": ["01"],
                                 "time": ["00:00"], "data_format": "netcdf",
                                 "download_format": "unarchived"})
    joined = " | ".join(problems)
    assert "format" in joined
    assert "nope" in joined


def test_validate_payload_rejects_product_type_on_land():
    """ERA5-Land 不接受 product_type，带上必须报错。"""
    from modules.era5_guide import build_payload, validate_payload
    payload = build_payload("ERA5-Land (地表小时, 0.1°)", [2024], [1],
                            ["2m_temperature"], None, None)
    payload["product_type"] = ["reanalysis"]
    problems = validate_payload("ERA5-Land (地表小时, 0.1°)", payload)
    assert any("product_type" in p for p in problems), problems


def test_field_count_estimator():
    """字段数 = 变量 × 年 × Σ各月天数 × 时次 × 层数。"""
    from modules.era5_guide import estimate_field_count
    # 1 变量 × 2024 年 1 月（31 天）× 24 时次 = 744
    assert estimate_field_count("ERA5-Land (地表小时, 0.1°)", [2024], [1],
                                ["2m_temperature"]) == 744
    # 月均值只有 1 个时次且不带 day：1 变量 × 1 年 × 1 月 = 1
    assert estimate_field_count("ERA5-Land 月均值 (0.1°)", [2024], [1],
                                ["2m_temperature"]) == 1
    # 气压层带层数：1 变量 × 31 天 × 24 时次 × 2 层 = 1488
    assert estimate_field_count("ERA5 气压层 (0.25°)", [2024], [1],
                                ["temperature"], ["500", "850"]) == 1488


def test_field_count_exceeds_land_limit_for_typical_request():
    """单变量全年并未超限（8784），两个变量才超过 ERA5-Land 的 12000 上限。"""
    from modules.era5_guide import ERA5_PRODUCTS, estimate_field_count
    meta = ERA5_PRODUCTS["ERA5-Land (地表小时, 0.1°)"]
    one = estimate_field_count("ERA5-Land (地表小时, 0.1°)", [2024],
                               list(range(1, 13)), ["2m_temperature"])
    assert one == 8784
    assert one < meta["field_limit"]
    two = estimate_field_count("ERA5-Land (地表小时, 0.1°)", [2024],
                               list(range(1, 13)),
                               ["2m_temperature", "total_precipitation"])
    assert two == 17568
    assert two > meta["field_limit"]


def test_available_years_starts_at_1950_and_excludes_current_year():
    from datetime import datetime
    from modules.era5_guide import available_years
    years = available_years()
    assert years[0] == 1950
    assert years[-1] == datetime.now().year - 1


# ============================================================
# 三、data_loader 接线与引导文案
# ============================================================

def test_data_loader_no_longer_holds_era5_tables():
    """旧的扁平变量字典与旧引导函数必须已从 data_loader 移除。"""
    from modules import data_loader
    assert not hasattr(data_loader, "_ERA5_PRODUCTS")
    assert not hasattr(data_loader, "_render_era5_guide")


def test_data_loader_exposes_era5_entry_point():
    """data_loader 必须能从新模块取到引导入口。"""
    from modules import data_loader
    assert callable(data_loader.render_era5_guide)


def test_era5_guide_exposes_renderer():
    from modules import era5_guide
    assert callable(era5_guide.render_era5_guide)


def test_stale_tab_reference_removed():
    """引导文案不得再引用不存在的「再分析数据处理」Tab。"""
    for path in ("modules/data_loader.py", "modules/era5_guide.py"):
        with io.open(os.path.join(_APP_DIR, path), encoding="utf-8") as f:
            assert "再分析数据处理" not in f.read(), path


def test_no_deprecated_cds_endpoints_are_used():
    """不得把已停用的端点当作可用地址（文案中的提醒不算，实际地址才算）。"""
    for path in ("modules/era5_guide.py", "modules/data_loader.py"):
        with io.open(os.path.join(_APP_DIR, path), encoding="utf-8") as f:
            source = f.read()
        assert "climate.copernicus.eu/api/v2" not in source, path
        assert "cds-beta.climate.copernicus.eu" not in source, path


def test_era5_help_mentions_licence_and_terminal():
    """引导文案必须写明许可证需网页手工接受，以及终端运行路径。"""
    from modules.era5_guide import _HELP_GET_DATA
    assert "terms and conditions" in _HELP_GET_DATA
    assert "手工接受" in _HELP_GET_DATA
    assert "终端" in _HELP_GET_DATA
    assert "cdsapi>=0.7.7" in _HELP_GET_DATA
    assert "data_format" in _HELP_GET_DATA


def test_app_side_never_imports_heavy_cds_stack():
    """应用侧不得真正 import cdsapi / xarray / netCDF4。

    只检查真实 import 节点（AST），不做文本匹配：脚本包模块的模板字符串里
    必然含有 ``import cdsapi`` 这段生成脚本正文，那不是应用侧的导入。
    """
    import ast
    banned = ("cdsapi", "xarray", "netCDF4")
    for path in ("modules/era5_guide.py", "modules/data_loader.py",
                 "modules/era5_script_pack.py"):
        full = os.path.join(_APP_DIR, path)
        if not os.path.exists(full):
            continue
        with io.open(full, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=path)
        modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.append(node.module or "")
        for name in modules:
            root = name.split(".")[0]
            assert root not in banned, "%s 真正导入了 %s" % (path, name)


if __name__ == "__main__":
    import traceback

    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception:
                failed += 1
                print(f"[FAIL] {name}")
                traceback.print_exc()
            else:
                print(f"[PASS] {name}")
    print(f"\n{'FAILED' if failed else 'ALL PASSED'} ({failed} failures)")
    sys.exit(1 if failed else 0)
