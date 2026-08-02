"""nc_probe_common 跨模块重构回归测试（真实函数调用，非仅 import）。

原则：py_compile / import 通过 ≠ 可用。Python 延迟名字解析会让"漏 import"
在导入时不报错、首次调用时才 NameError。本文件的每个用例都必须真实调用
重构后的函数/类方法，覆盖两条消费链路与共享生成逻辑。

运行：venv python -m pytest tests/test_nc_probe_refactor.py -v
（venv: C:/Users/ASUS/.workbuddy/binaries/python/envs/default/Scripts/python.exe）
"""
import os
import shutil
import tempfile

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from modules import nc_probe_common as C
from modules import era5_wizard as W
from modules import climate_source as CS


def _make_nc(vars_map, path, add_pressure=False, months=None):
    """构造合成 NetCDF。vars_map: {真实变量名: 标量初值}。
    add_pressure: 附加 pressure_level 维度（测 isel 防御）。
    months: 若有则构造 month 维（气候态宽表/气候源测试）。"""
    lat, lon = [39.9], [116.4]
    data = {}
    if months is not None:
        if add_pressure:
            for name, val in vars_map.items():
                data[name] = (("month", "pressure_level", "latitude", "longitude"),
                              np.full((len(months), 2, 1, 1), float(val)))
        else:
            for name, val in vars_map.items():
                data[name] = (("month", "latitude", "longitude"),
                              np.full((len(months), 1, 1), float(val)))
        ds = xr.Dataset(data, coords={"month": months, "latitude": lat, "longitude": lon})
    else:
        for name, val in vars_map.items():
            data[name] = (("time", "latitude", "longitude"),
                          np.full((24, 1, 1), float(val)))
        ds = xr.Dataset(data, coords={"time": np.arange(24), "latitude": lat, "longitude": lon})
    ds.to_netcdf(path)
    return path


def _exec_rows_block(rows_block, clim_ds, ds_month=None):
    """在含 CLIM/ds_month/LAT/LON 的命名空间执行生成的 rows_block。

    注意：rows_block 已按月份展开并含 rows.append(row)，直接 exec（dedent 掉
    生成缩进），不得再包 for m 循环（曾致月份翻倍的双重循环 bug）。
    ds_month 默认从 clim_ds 退化构造：month 坐标 → 2020 年对应日期（极值列
    依赖 time 维；单年数据时极值=该月值本身，年份=2020）。
    """
    import textwrap
    import numpy as np
    if ds_month is None and "time" not in clim_ds.coords:
        time_vals = [np.datetime64(f"2020-{int(m):02d}-01") for m in clim_ds.month.values]
        ds_month = clim_ds.assign_coords(time=time_vals)
    elif ds_month is None:
        ds_month = clim_ds
    ns = {"CLIM": clim_ds, "ds_month": ds_month, "LAT": 39.9, "LON": 116.4,
          "rows": [], "np": np}
    exec(textwrap.dedent(rows_block), ns)  # noqa: S102
    return ns["rows"]


# ---------------------------------------------------------------
# #1 别名漂移：向导探测与平台消费必须指向同一真实变量
# ---------------------------------------------------------------
def test_alias_consistency_wizard_and_platform():
    tmp = tempfile.mkdtemp(prefix="nc_probe_alias_")
    p = _make_nc({"air_temperature": 280.0, "total_precipitation": 0.01,
                  "10m_wind_speed": 3.0}, os.path.join(tmp, "probe.nc"))
    with open(p, "rb") as f:
        blob = f.read()

    info = W.probe_netcdf_file(blob)
    assert info["ok"], f"probe_netcdf_file 失败: {info.get('error')}"
    norms = {v["orig"]: v["norm"] for v in info["variables"]}
    assert norms["air_temperature"] == "2m_temperature", "向导未识别 air_temperature"

    assigned = C.assign_vars(["air_temperature", "total_precipitation", "10m_wind_speed"])
    assert assigned["t_mean"] == "air_temperature", f"平台映射异常: {assigned}"
    assert assigned["precip"] == "total_precipitation"
    assert assigned["wind_max_mean"] == "10m_wind_speed"


# ---------------------------------------------------------------
# 漏 import 回归：climate_source 的 NetCDF 路径必须真实调用成功
# （此用例专门捕获"import 不报错、调用 NameError"类回归）
# ---------------------------------------------------------------
def test_climate_source_nc_path_real_call():
    tmp = tempfile.mkdtemp(prefix="nc_probe_cs_")
    p = os.path.join(tmp, "climate.nc")
    months = list(range(1, 13))
    ds = xr.Dataset(
        {"air_temperature": (("month", "latitude", "longitude"), np.full((12, 1, 1), 293.0))},
        coords={"month": months, "latitude": [39.9], "longitude": [116.4]},
    )
    ds["air_temperature"].attrs["units"] = "K"  # 写盘前先设 attrs（写后改会 PermissionError）
    ds.to_netcdf(p)

    with open(p, "rb") as f:
        blob = f.read()
    stats, extreme = CS.LocalFileSource(nc_bytes=blob).fetch_climate_normal(39.9, 116.4, 7)
    assert stats is not None, "fetch_climate_normal 返回 None（调用路径失败，疑似漏 import）"
    assert stats.t_mean is not None, "t_mean 未识别（别名映射失效）"
    assert abs(stats.t_mean - (293.0 - 273.15)) < 0.01, f"K→℃ 换算异常: {stats.t_mean}"


def test_climate_source_csv_wide_real_call():
    """CSV 宽表消费路径真实调用（含 _load_table 的 session_state 缓存分支）。

    专门捕获"环境装有 streamlit 但模块未局部导入 st → _load_table 内 NameError"
    类回归（2026-08-02 事故：真填极值列后首次走到 CSV 缓存分支暴露）。
    同时验证宽表 extreme 列（t_max_val/t_max_year 等）被消费端正确解析。
    """
    tmp = tempfile.mkdtemp(prefix="nc_probe_csv_")
    p = os.path.join(tmp, "wide.csv")
    rows = [{
        "lat": 39.9, "lon": 116.4, "month": m, "t_mean": 6.85, "t_max": 6.85,
        "t_min": 6.85, "precip": 10.0, "wind_max_mean": 3.0, "base_period": "",
        "t_max_val": 6.85, "t_max_year": 2020, "t_min_val": 6.85, "t_min_year": 2020,
        "precip_max": 10.0, "precip_max_year": 2020, "wind_max": 3.0, "wind_max_year": 2020,
    } for m in (1, 7)]
    pd.DataFrame(rows).to_csv(p, index=False, encoding="utf-8-sig")

    stats, extreme = CS.LocalFileSource(csv_path=p).fetch_climate_normal(39.9, 116.4, 7)
    assert stats is not None and stats.t_mean == 6.85, \
        "CSV 宽表未识别（疑似 _load_table 裸 st NameError 回归）"
    assert extreme is not None and extreme.t_max_record["year"] == 2020, "extreme 年份未解析"
    assert extreme.t_max_record["value"] == 6.85, "extreme 值未解析"
    assert extreme.precip_max_record["year"] == 2020


# ---------------------------------------------------------------
# #6 两模式 clim_stats 列集恒一致（17 列），base_period 随 know_period 区分
# ---------------------------------------------------------------
def test_clim_schema_identity_both_modes():
    months = [1, 7]
    clim = xr.Dataset(
        {"2m_temperature": (("month", "latitude", "longitude"), np.full((2, 1, 1), 280.0)),
         "total_precipitation": (("month", "latitude", "longitude"), np.full((2, 1, 1), 0.01)),
         "10m_wind_speed": (("month", "latitude", "longitude"), np.full((2, 1, 1), 3.0))},
        coords={"month": months, "latitude": [39.9], "longitude": [116.4]},
    )
    fields = [("2m_temperature", "t_mean"), ("total_precipitation", "precip"),
              ("10m_wind_speed", "wind_max_mean")]
    rb_dl = C.clim_rows_block(fields, months, know_period=True,
                              base_period="1991-2020", indent=8)
    rb_proc = C.clim_rows_block(fields, months, know_period=False, indent=4)

    rows_dl, rows_proc = _exec_rows_block(rb_dl, clim), _exec_rows_block(rb_proc, clim)
    expected = {"lat", "lon", "month", "t_mean", "t_max", "t_min", "precip",
                "wind_max_mean", "base_period", "t_max_val", "t_max_year",
                "t_min_val", "t_min_year", "precip_max", "precip_max_year",
                "wind_max", "wind_max_year"}
    assert len(rows_dl) == 2 and len(rows_proc) == 2, \
        f"行数异常（月份重复/缺失）: dl={len(rows_dl)} proc={len(rows_proc)}"
    assert set(rows_dl[0].keys()) == expected
    assert set(rows_proc[0].keys()) == expected
    assert rows_dl[0]["base_period"] == "1991-2020"
    assert rows_proc[0]["base_period"] == ""
    for r in rows_dl:  # 功能性：填充非 None，t_max==t_min==t_mean 简化约定
        assert r["t_mean"] is not None and r["precip"] is not None and r["wind_max_mean"] is not None
        assert r["t_max"] == r["t_min"] == r["t_mean"]
        # 极值列真填：单年数据 → 值=该月值本身，年份=2020
        assert r["t_max_val"] == 280.0 and r["t_max_year"] == 2020, f"t_max 极值异常: {r}"
        assert r["t_min_val"] == 280.0 and r["t_min_year"] == 2020
        assert r["precip_max"] == 0.01 and r["precip_max_year"] == 2020
        assert r["wind_max"] == 3.0 and r["wind_max_year"] == 2020
    for r in rows_proc:  # 处理模式同样真填
        assert r["t_max_val"] == 280.0 and r["t_max_year"] == 2020


# ---------------------------------------------------------------
# 气压层防御：含 pressure_level 维度时安全取最低层，单层产品不崩
# ---------------------------------------------------------------
def test_pressure_level_isec_guard():
    months = [1, 7]
    clim = xr.Dataset(
        {"2m_temperature": (("month", "pressure_level", "latitude", "longitude"),
                            np.full((2, 2, 1, 1), 280.0))},
        coords={"month": months, "pressure_level": [1000, 850],
                "latitude": [39.9], "longitude": [116.4]},
    )
    rb = C.clim_rows_block([("2m_temperature", "t_mean")], months,
                           know_period=True, base_period="x", indent=4)
    rows = _exec_rows_block(rb, clim)
    assert rows[0]["t_mean"] is not None


# ---------------------------------------------------------------
# Windows 非 ASCII 路径：open_nc_safe 复制到 ASCII 临时副本后成功
# ---------------------------------------------------------------
def test_nonascii_path_probe():
    tmp = tempfile.mkdtemp(prefix="nc_probe_ascii_")
    ascii_path = _make_nc({"2m_temperature": 280.0}, os.path.join(tmp, "ascii.nc"))
    cn_dir = tempfile.mkdtemp(prefix="nc_probe_cn_")
    cn_path = os.path.join(cn_dir, "气象数据测试_北京.nc")
    shutil.copy(ascii_path, cn_path)
    info = W.probe_netcdf_file(cn_path)
    assert info["ok"], f"非 ASCII 路径探测失败: {info.get('error')}"
    assert any(v["norm"] == "2m_temperature" for v in info["variables"])


# ---------------------------------------------------------------
# 缺变量路径：不误认领，与生成脚本 _missing 校验一致
# ---------------------------------------------------------------
def test_missing_var_not_assigned():
    assert "t_mean" not in C.assign_vars(["total_precipitation"])
    assert C.probe_var("garbage_var_xyz") is None
