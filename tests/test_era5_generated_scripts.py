"""era5_wizard 生成脚本的真实执行回归测试（两模式产出 CSV 一致性）。

原则升级：不只断言生成代码的字符串或列集，而是把生成脚本真的跑起来：
- 处理模式：整脚本 subprocess 运行（FILE_PATH 指向合成 NetCDF），产出 clim_stats CSV。
- 下载模式：跳过外部副作用段（CDS 认证检查/网络下载），从「读取与单位换算」段起
  exec 真实执行（TARGET 指向合成 NetCDF），同样产出 clim_stats CSV。
- 终断言：两份真实产出的 CSV 列集/列序/数值完全一致，仅 base_period 随 know_period 区分。

运行：venv python -m pytest tests/test_era5_generated_scripts.py -v
"""
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np
import pandas as pd
import xarray as xr

from modules import era5_wizard as W

EXPECTED_COLS = ["lat", "lon", "month", "t_mean", "t_max", "t_min", "precip",
                 "wind_max_mean", "base_period", "t_max_val", "t_max_year",
                 "t_min_val", "t_min_year", "precip_max", "precip_max_year",
                 "wind_max", "wind_max_year"]


def _make_hourly_nc(path, vars_map=None):
    """合成逐小时 NetCDF：24 时次覆盖 1 月与 7 月（含 6 个月空档，验证 NaN 桶无害），
    单格点（39.9°N, 116.4°E）。K 温度 / m 降水，测单位换算链。

    vars_map: {变量名: 标量初值}。下载模式需给 U/V 分量（脚本合成风速），
    处理模式直接给 10m_wind_speed（候选名绑定，无合成逻辑）。
    """
    vars_map = vars_map or {"2m_temperature": 280.0, "total_precipitation": 0.01,
                            "10m_wind_speed": 3.0}
    times = np.concatenate([
        np.arange("2020-01-01T00", "2020-01-01T12", dtype="datetime64[h]"),
        np.arange("2020-07-01T00", "2020-07-01T12", dtype="datetime64[h]"),
    ])
    data = {}
    for name, val in vars_map.items():
        data[name] = (("time", "latitude", "longitude"), np.full((24, 1, 1), float(val)))
    ds = xr.Dataset(data, coords={"time": times, "latitude": [39.9], "longitude": [116.4]})
    ds.to_netcdf(path)
    return path


def test_process_script_clim_stats_real_run():
    """处理模式：整脚本真实运行，产出的 clim_stats CSV 列序/取值正确。"""
    tmp = tempfile.mkdtemp(prefix="era5_proc_")
    nc = _make_hourly_nc(os.path.join(tmp, "synth.nc"))
    script = W.build_process_script(
        scene="clim_stats",
        expected_vars=["2m_temperature", "total_precipitation", "10m_wind_speed"],
        file_mode="paste",
        scene_opts={"months": [1, 7]},
        out_prefix="proc_real",
        path_hint=nc.replace("\\", "/"),
    )
    run_py = os.path.join(tmp, "run_proc.py")
    with open(run_py, "w", encoding="utf-8") as f:
        f.write(script)

    r = subprocess.run([sys.executable, run_py], cwd=tmp,
                       capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, f"处理脚本运行失败:\n{r.stdout}\n{r.stderr}"

    out_csv = os.path.join(tmp, "proc_real_climate_stats.csv")
    assert os.path.exists(out_csv), "处理模式未产出气候态 CSV"
    df = pd.read_csv(out_csv, encoding="utf-8-sig")
    assert list(df.columns) == EXPECTED_COLS, f"列序异常: {list(df.columns)}"
    assert len(df) == 2  # 1 月与 7 月
    # 处理模式 base_period 应为空串（CSV 往返后空串变 NaN，fillna 归一比较）
    assert (df["base_period"].fillna("") == "").all(), "处理模式 base_period 应为空串"
    # 取值：K→℃（280-273.15=6.85）、m→mm（0.01*1000=10.0）、风速原值 3.0
    assert np.allclose(df["t_mean"], 6.85)
    assert np.allclose(df["precip"], 10.0)
    assert np.allclose(df["wind_max_mean"], 3.0)
    assert (df["t_max"] == df["t_min"]).all() and (df["t_max"] == df["t_mean"]).all()
    # 极值列真填：单年（2020）数据 → 极值=该月值本身（换算后），年份=2020
    assert np.allclose(df["t_max_val"], 6.85) and (df["t_max_year"] == 2020).all(), \
        f"t_max 极值异常: {df[['month','t_max_val','t_max_year']].to_dict('records')}"
    assert np.allclose(df["t_min_val"], 6.85) and (df["t_min_year"] == 2020).all()
    assert np.allclose(df["precip_max"], 10.0) and (df["precip_max_year"] == 2020).all()
    assert np.allclose(df["wind_max"], 3.0) and (df["wind_max_year"] == 2020).all()
    return df


def test_download_script_clim_part_matches_process():
    """下载模式：跳过网络下载段，从读取段起真实执行，产出 CSV 与处理模式完全一致（仅 base_period 区分）。"""
    tmp = tempfile.mkdtemp(prefix="era5_dl_")
    # TARGET 是相对路径 {prefix}_download.nc，把合成文件放到 cwd 即命中。
    # 下载模式 10m_wind_speed 是虚拟变量：脚本从 U/V 分量合成（u=3.0, v=0.0 → 3.0）
    _make_hourly_nc(os.path.join(tmp, "dl_real_download.nc"),
                    {"2m_temperature": 280.0, "total_precipitation": 0.01,
                     "10m_u_component_of_wind": 3.0, "10m_v_component_of_wind": 0.0})

    script = W.build_era5_script(
        product="single_hourly",
        variables=["2m_temperature", "total_precipitation", "10m_wind_speed"],
        year_start=1991, year_end=2020,
        months=[1, 7], climate_months=[1, 7],
        time_res="clim", output_climate_csv=True,
        out_prefix="dl_real",
    )
    # 从「读取与单位换算」段开始执行（段 1 是 CDS 认证+网络下载，外部副作用）。
    # exec 在 pytest 进程内运行，相对路径 TARGET/CSV 依赖 cwd，故 chdir 到临时目录。
    lines = script.splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("# ---- 2."))
    body = "\n".join(lines[start:])
    ns = {"TARGET": "dl_real_download.nc"}
    old_cwd = os.getcwd()
    os.chdir(tmp)
    try:
        exec(body, ns)  # noqa: S102
    finally:
        os.chdir(old_cwd)

    dl_csv = os.path.join(tmp, "dl_real_climate_stats.csv")
    assert os.path.exists(dl_csv), "下载模式 clim 段未产出 CSV"
    df_dl = pd.read_csv(dl_csv, encoding="utf-8-sig")
    assert list(df_dl.columns) == EXPECTED_COLS

    # 与处理模式真实产出的 CSV 对比：数值列完全一致，base_period 不同
    df_proc = test_process_script_clim_stats_real_run()
    assert (df_dl["base_period"] == "1991-2020").all(), "下载模式 base_period 应为实值"
    common = [c for c in EXPECTED_COLS if c != "base_period"]
    pd.testing.assert_frame_equal(
        df_dl[common].reset_index(drop=True),
        df_proc[common].reset_index(drop=True),
        check_exact=False, rtol=1e-9,
    )


def test_batch_mode_script_structure():
    """P2.1: 批量 glob 模式生成的脚本包含关键结构。"""
    import ast
    s = W.build_process_script(
        scene="clim_stats",
        expected_vars=["2m_temperature", "total_precipitation"],
        file_mode="batch", glob_pattern=r"C:\era5\*.nc",
        out_prefix="batch_test",
    )
    ast.parse(s)  # 语法合法
    assert "import glob" in s
    assert "set(os.path.abspath(" in s, "批处理脚本缺去重逻辑"
    assert "def _process_one(" in s, "批处理脚本缺处理函数"
    assert "批量摘要" in s or "总文件" in s, "批处理脚本缺摘要"


def test_batch_mode_real_run():
    """P2.1+M3: 批量脚本真实运行（双文件 glob → 逐文件 clim_stats → 分目录产物）。

    专门捕获"结构断言测不出"的运行时 bug（2026-08-02 事故：batch 脚本
    _res_dir 用 f"{out_prefix}_batch..." 但 out_prefix 从未定义 → NameError）。
    """
    tmp = tempfile.mkdtemp(prefix="era5_batch_")
    for i in (1, 2):
        _make_hourly_nc(os.path.join(tmp, f"synth_{i}.nc"))
    pattern = os.path.join(tmp, "*.nc").replace("\\", "/")

    script = W.build_process_script(
        scene="clim_stats",
        expected_vars=["2m_temperature", "total_precipitation"],
        file_mode="batch", glob_pattern=pattern,
        scene_opts={"months": [1, 7]},
        out_prefix="bt",
    )
    run_py = os.path.join(tmp, "run_batch.py")
    with open(run_py, "w", encoding="utf-8") as f:
        f.write(script)
    r = subprocess.run([sys.executable, run_py], cwd=tmp,
                       capture_output=True, text=True, encoding="utf-8", timeout=90)
    assert r.returncode == 0, f"批量脚本运行失败:\n{r.stdout}\n{r.stderr}"
    assert "[摘要] 批量处理完成" in r.stdout, "缺批量摘要"
    assert "总文件" in r.stdout and "成功" in r.stdout, "摘要缺统计"

    for i in (0, 1):
        out_dir = os.path.join(tmp, f"bt_batch{i:03d}")
        csv = os.path.join(out_dir, "bt_climate_stats.csv")
        assert os.path.exists(csv), f"缺少产物: {csv}"
        df = pd.read_csv(csv, encoding="utf-8-sig")
        assert len(df) == 2, f"应 2 个月，实际 {len(df)}（双重循环回归？）"
        assert np.allclose(df["t_mean"], 6.85)
        assert (df["t_max_year"] == 2020).all(), "batch 模式极值列异常"


def test_llm_validator_all_paths():
    """P2.2: LLM 校验器各路径。"""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "modules"))
    from llm_validator import validate_llm_output, validate_safe_for_scene

    # 语法错误
    r = validate_llm_output("for i in range(10)")
    assert not r["ok"] and "语法" in r["errors"][0]

    # 禁止导入
    r = validate_llm_output("import flask\nx=1")
    assert not r["ok"] and any("flask" in e for e in r["errors"])

    # 禁止调用
    r = validate_llm_output("import os\nos.system('ls')")
    assert not r["ok"] and any("system" in e for e in r["errors"])

    # 合法代码
    r = validate_llm_output("import numpy as np\nimport xarray as xr\nx=np.array([1,2])\nprint(x.mean())")
    assert r["ok"], f"合法代码不应报错: {r}"
    assert not r["errors"]

    # 场景检查：无数据输出的 clim_stats 代码会警告
    r = validate_safe_for_scene("import numpy as np\nx=np.array([1,2])\nprint(x.mean())", "clim_stats")
    assert r["ok"]
    assert any("rows.append" in w.lower() or "pd.DataFrame" in w.lower() for w in r["warnings"])


def test_p2_result_summary_in_scripts():
    """P2.3: 下载/处理/批处理脚本均含结果摘要。"""
    dl = W.build_era5_script(
        product="single_hourly",
        variables=["2m_temperature"],
        year_start=1991, year_end=2020,
        months=[1], time_res="clim", output_climate_csv=True,
        out_prefix="summ_test",
    )
    assert "[摘要]" in dl and "产物" in dl, "下载脚本缺摘要"

    proc = W.build_process_script(
        scene="clim_stats",
        expected_vars=["2m_temperature"],
        file_mode="paste", out_prefix="summ_proc",
    )
    assert "[摘要]" in proc and "场景" in proc, "处理脚本缺摘要"

    batch = W.build_process_script(
        scene="clim_stats",
        expected_vars=["2m_temperature"],
        file_mode="batch", glob_pattern=r"C:\test\*.nc",
        out_prefix="summ_batch",
    )
    assert "摘要" in batch, "批处理脚本缺摘要"
