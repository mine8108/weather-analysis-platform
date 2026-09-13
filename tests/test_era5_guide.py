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
