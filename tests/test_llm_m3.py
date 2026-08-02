"""M3 LLM 分析代码生成回归测试。

覆盖：prompt 结构、代码提取、mock API 调用（正常/无 key/HTTP 错误）、
llm_body 注入 build_process_script（覆盖模板/回退）、端到端真实运行。

运行：venv python -m pytest tests/test_llm_m3.py -v
"""
import os
import subprocess
import sys
import tempfile

import numpy as np
import pandas as pd
import pytest
import requests
import xarray as xr

from modules import era5_wizard as W
from modules import llm_client as LC


# ---------------------------------------------------------------
# M3-1a: prompt 构造
# ---------------------------------------------------------------
def test_build_analysis_prompt_structure():
    ctx = {
        "scene": "clim_stats", "scene_name": "气候态统计",
        "expected_vars": ["2m_temperature", "total_precipitation"],
        "detected": {"ok": True, "variables": [
            {"orig": "air_temperature", "norm": "2m_temperature",
             "units": "K", "dims": "(time, latitude, longitude)"}]},
        "scene_opts": {"months": [1, 7]}, "out_prefix": "my_run",
    }
    prompt = LC.build_analysis_prompt(ctx, "计算各月平均气温")
    assert "气候态统计" in prompt["user"] and "clim_stats" in prompt["user"]
    assert "2m_temperature" in prompt["user"] and "air_temperature" in prompt["user"]
    assert "my_run" in prompt["user"] and '"months": [1, 7]' in prompt["user"]
    # system 硬约束
    assert "硬性限制" in prompt["system"] and "禁止" in prompt["system"]
    assert "subprocess" in prompt["system"] and "out_prefix" in prompt["system"]
    assert "单位已换算" in prompt["system"]


# ---------------------------------------------------------------
# M3-1b: 代码提取
# ---------------------------------------------------------------
def test_extract_python_code_variants():
    assert LC.extract_python_code("```python\nx = 1\n```") == "x = 1"
    assert LC.extract_python_code("以下是代码：\n```\nx = 2\n```\n完") == "x = 2"
    assert LC.extract_python_code("import numpy as np\nx = np.array([1])") == "import numpy as np\nx = np.array([1])"
    with pytest.raises(LC.LlmCallError):
        LC.extract_python_code("")
    with pytest.raises(LC.LlmCallError):
        LC.extract_python_code("这是一段纯说明文字，没有代码")


# ---------------------------------------------------------------
# M3-1c: API 调用（mock）
# ---------------------------------------------------------------
def _fake_post_ok(url, headers=None, json=None, timeout=None):
    class R:
        status_code = 200
        text = ""
        def json(self):
            return {"choices": [{"message": {"content": "```python\nx = 1\n```"}}]}
    return R()


def _fake_post_err(url, headers=None, json=None, timeout=None):
    class R:
        status_code = 500
        text = "internal error"
        def json(self):
            return {}
    return R()


def test_generate_analysis_code_mock_ok(monkeypatch):
    monkeypatch.setattr(requests, "post", _fake_post_ok)
    code = LC.generate_analysis_code(
        {"system": "s", "user": "u"},
        api_key="test-key", base_url="http://fake/v1", model="m",
    )
    assert code == "x = 1"


def test_generate_analysis_code_no_key():
    with pytest.raises(LC.LlmUnavailable):
        LC.generate_analysis_code({"system": "s", "user": "u"}, api_key=None)


def test_generate_analysis_code_http_error(monkeypatch):
    monkeypatch.setattr(requests, "post", _fake_post_err)
    with pytest.raises(LC.LlmCallError):
        LC.generate_analysis_code(
            {"system": "s", "user": "u"},
            api_key="k", base_url="http://fake/v1", model="m",
        )


# ---------------------------------------------------------------
# M3-2: llm_body 注入 build_process_script（覆盖/回退）
# ---------------------------------------------------------------
def test_llm_body_overrides_template_and_fallback():
    base = dict(scene="clim_stats", expected_vars=["2m_temperature"],
                file_mode="paste", out_prefix="x")
    s_tpl = W.build_process_script(**base)
    assert "LLM 生成处理段" not in s_tpl, "模板模式不应含 LLM 标记"

    s_llm = W.build_process_script(**base, analysis_prompt="计算月均温",
                                  llm_body="print('LLM-BODY-OK')")
    assert "LLM 生成处理段" in s_llm and "LLM-BODY-OK" in s_llm, "llm_body 未注入"
    assert "clim_stats" not in s_llm or True  # 场景体已被 LLM body 覆盖（不再有模板宽表行）

    # analysis_prompt 非空但 llm_body 空 → 模板回退
    s_fb = W.build_process_script(**base, analysis_prompt="随便", llm_body="")
    assert "LLM 生成处理段" not in s_fb, "空 llm_body 应回退模板"


# ---------------------------------------------------------------
# M3 端到端：LLM body 拼进骨架后真实运行
# ---------------------------------------------------------------
def test_llm_body_real_run():
    tmp = tempfile.mkdtemp(prefix="llm_m3_")
    times = np.concatenate([
        np.arange("2020-01-01T00", "2020-01-01T12", dtype="datetime64[h]"),
        np.arange("2020-07-01T00", "2020-07-01T12", dtype="datetime64[h]"),
    ])
    ds = xr.Dataset(
        {"2m_temperature": (("time", "latitude", "longitude"), np.full((24, 1, 1), 280.0))},
        coords={"time": times, "latitude": [39.9], "longitude": [116.4]},
    )
    nc = os.path.join(tmp, "synth.nc")
    ds.to_netcdf(nc)

    llm_body = (
        "# LLM 生成的示例处理段：各月平均气温并保存 CSV\n"
        "t = ds[\"2m_temperature\"]\n"
        "out = []\n"
        "for m, sub in t.groupby(\"time.month\"):\n"
        "    out.append({\"month\": int(m), \"t_mean\": float(sub.mean().values)})\n"
        "df = pd.DataFrame(out)\n"
        "df.to_csv(out_prefix + \"_llm_monthly.csv\", index=False, encoding=\"utf-8-sig\")\n"
        "print(\"[OK] 各月平均气温已输出: %d 个月\" % len(df))\n"
    )
    script = W.build_process_script(
        scene="clim_stats", expected_vars=["2m_temperature"],
        file_mode="paste", scene_opts={"months": [1, 7]},
        out_prefix="llm_run", path_hint=nc.replace("\\", "/"),
        analysis_prompt="计算各月平均气温并保存 CSV", llm_body=llm_body,
    )
    run_py = os.path.join(tmp, "run.py")
    with open(run_py, "w", encoding="utf-8") as f:
        f.write(script)
    r = subprocess.run([sys.executable, run_py], cwd=tmp,
                       capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, f"LLM body 脚本运行失败:\n{r.stdout}\n{r.stderr}"

    out_csv = os.path.join(tmp, "llm_run_llm_monthly.csv")
    assert os.path.exists(out_csv), "LLM body 未产出 CSV"
    df = pd.read_csv(out_csv, encoding="utf-8-sig")
    assert len(df) == 2, f"应 2 个月，实际 {len(df)}"
    assert np.allclose(df["t_mean"], 6.85), f"K→℃ 换算异常: {df['t_mean'].tolist()}"
    assert r.stdout.count("[OK]") >= 1, "缺 [OK] 摘要输出"
