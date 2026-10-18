# 批次 0 止血实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: 用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务执行。步骤用 `- [ ]` 跟踪。每个任务独立提交，任务间跑一次全量测试。

**Goal:** 修掉 7 个会直接产出错误结论、成本失控或点击无效的缺陷，同时把 CI 从「11 个脚本门禁 + 全量测试不阻断」改为「全量测试阻断」。

**Architecture:** 六项改动全部落在边界清晰的小切口上，不引入新架构。唯一新增模块 `modules/app_state.py` 承载纯逻辑，使重置行为可脱离 Streamlit 测试。

**Tech Stack:** Python 3.12 / Streamlit 1.59.1 / pandas 3.0.3 / pytest

**Spec:** `docs/superpowers/plans/2026-10-18-architecture-refactor-roadmap.md` 第二、四节

## Global Constraints

- 技术栈不变。不新增运行时依赖。
- 用户可见行为只允许两处变化，V1 解码按钮恢复可用，V3 重置文案改为「仅清空本地会话」。
- 每个任务结束跑 `python -m pytest tests -q`，必须全绿。
- 新增测试后同步更新 `README.md` 的两处计数，否则 `tests/test_release_surface.py` 会失败。
- 一个小任务一个 commit。

**执行前置，当前机器缺依赖**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests -q
```

---

### Task 1: 会话重置不再破坏登录态，也不再复活云端数据

**Files:**
- Create: `modules/app_state.py`
- Create: `tests/test_app_state.py`
- Modify: `app.py:87-96`

**Interfaces:**
- Produces: `modules.app_state.reset_session(state, *, keep_keys=(), keep_prefixes=()) -> list[str]`
- Produces: `modules.app_state.SESSION_CLIENT_KEYS`、`modules.app_state.NAV_DEFAULTS`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_app_state.py
"""会话重置的作用域契约：保留客户端与登录态，阻断自动载入。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import app_state


class _Client:
    pass


def test_reset_keeps_clients_and_login():
    state = {
        "_sb_client": _Client(),
        "_sb_admin_client": _Client(),
        "auth_user": {"id": "u1"},
        "auth_error": "旧错误",
        "df": object(),
        "warnings_list": [1],
        "active_tab": 4,
    }
    removed = app_state.reset_session(state, keep_prefixes=("auth_",))
    assert state["_sb_client"] is not None
    assert state["_sb_admin_client"] is not None
    assert state["auth_user"] == {"id": "u1"}
    assert "df" not in state and "warnings_list" not in state
    assert state["active_tab"] == 0
    assert set(removed) == {"df", "warnings_list"}


def test_reset_blocks_auto_load():
    state = {"_auto_load_done": False, "df": object()}
    app_state.reset_session(state)
    assert state["_auto_load_done"] is True


def test_reset_on_empty_state_is_safe():
    assert app_state.reset_session({}) == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_app_state.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'modules.app_state'`

- [ ] **Step 3: 实现 `modules/app_state.py`**

```python
"""会话状态的作用域约定与重置策略。

纯逻辑，不依赖 Streamlit 运行时，便于在无依赖环境单元测试。
"""

SESSION_CLIENT_KEYS = ("_sb_client", "_sb_admin_client")
NAV_KEYS = ("active_tab", "import_step", "import_method", "_nav_stack")
NAV_DEFAULTS = {"active_tab": 0, "import_step": 0, "import_method": None}


def reset_session(state, *, keep_keys=(), keep_prefixes=()):
    """清空业务状态，保留导航、登录态与会话级客户端。

    state 既可以是 st.session_state，也可以是普通 dict。
    返回被删除的键列表，供调用方提示与测试断言。
    """
    preserved = set(keep_keys) | set(SESSION_CLIENT_KEYS) | set(NAV_KEYS)
    for prefix in keep_prefixes:
        preserved.update(k for k in state if k.startswith(prefix))
    removed = [k for k in list(state) if k not in preserved]
    for key in removed:
        del state[key]
    state.update(NAV_DEFAULTS)
    state["_auto_load_done"] = True
    return removed
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_app_state.py -q`
Expected: 3 passed

- [ ] **Step 5: 接线 `app.py`**

把 `app.py:87-96` 的 `_safe_reset` 函数体替换为：

```python
def _safe_reset():
    """错误恢复：清空业务数据，保留登录态、导航与会话客户端。

    修复：旧实现删掉了 _sb_client 却保留 auth_user，下一轮新建的客户端没有
    JWT，所有 RLS 读写被拒；同时删掉 _auto_load_done 会让云端数据被自动载回。
    """
    from modules.app_state import reset_session
    reset_session(
        st.session_state,
        keep_prefixes=("auth_", "invite_", "admin_"),
    )
```

- [ ] **Step 6: 全量回归**

Run: `python -m pytest tests -q`
Expected: 全绿。若 `test_release_surface.py::test_readme_pytest_total_matches_collection` 失败，按新增用例数同步 `README.md` 的 `当前共 **N** 项`。

- [ ] **Step 7: 提交**

```powershell
git add modules/app_state.py tests/test_app_state.py app.py README.md
git commit -m "fix(session): 重置保留会话客户端并阻断自动载回数据"
```

---

### Task 2: 自定义阈值移入会话作用域

**Files:**
- Modify: `modules/analyzer.py:24-31`，以及 68、136、187、223、256、301、335、379 八行
- Modify: `app.py:599-601`
- Modify: `tests/test_analyzer.py`

**Interfaces:**
- Produces: `modules.analyzer.current_thresholds() -> dict`
- 保留：`modules.analyzer.set_custom_thresholds(custom)`，供既有测试与无 Streamlit 场景使用

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_analyzer.py`：

```python
def test_current_thresholds_prefers_session_state(monkeypatch):
    import sys
    import types
    fake = types.SimpleNamespace(
        session_state={"_custom_thresholds": {"gale": {"蓝色": 99.0}}})
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    assert analyzer.current_thresholds()["gale"]["蓝色"] == 99.0


def test_current_thresholds_falls_back_to_module_global(monkeypatch):
    import sys
    import types
    monkeypatch.setitem(sys.modules, "streamlit",
                        types.SimpleNamespace(session_state={}))
    analyzer.set_custom_thresholds({"fog": {"黄色": 1.0}})
    try:
        assert analyzer.current_thresholds()["fog"]["黄色"] == 1.0
    finally:
        analyzer.set_custom_thresholds({})
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_analyzer.py -q -k current_thresholds`
Expected: FAIL，`AttributeError: module 'modules.analyzer' has no attribute 'current_thresholds'`

- [ ] **Step 3: 实现取值函数并替换八个读点**

在 `modules/analyzer.py:31` 后追加：

```python
def current_thresholds():
    """当前生效的自定义阈值。

    优先读会话状态，实现多用户隔离；无 Streamlit 上下文或未设置时退回
    模块级 CUSTOM_THRESHOLDS，保持既有测试与脚本的调用方式不变。
    """
    try:
        import streamlit as st
        custom = st.session_state.get("_custom_thresholds")
    except Exception:
        custom = None
    if custom:
        return custom
    return CUSTOM_THRESHOLDS or {}
```

把八处 `CUSTOM_THRESHOLDS.get(` 改为 `current_thresholds().get(`，行号 68、136、187、223、256、301、335、379。

- [ ] **Step 4: 改 `app.py` 的写入点**

```python
        if st.button("[OK] 应用自定义阈值", use_container_width=True):
            st.session_state["_custom_thresholds"] = custom
            st.success("自定义阈值已应用（仅本会话）。")
```

同时删除 `app.py:26` 的 `set_custom_thresholds` 导入，避免未使用符号。

- [ ] **Step 5: 跑测试**

Run: `python -m pytest tests/test_analyzer.py -q`
Expected: 全绿，新增 2 条通过。既有 92 条不受影响，因为 `set_custom_thresholds` 仍写入模块级值。

- [ ] **Step 6: 提交**

```powershell
git add modules/analyzer.py app.py tests/test_analyzer.py
git commit -m "fix(thresholds): 自定义阈值改为会话作用域，消除跨用户串扰"
```

---

### Task 3: 配额服务故障时按进程级临时额度收紧

**Files:**
- Modify: `modules/chart_reader.py:210-224` 与调用点 `:398`
- Modify: `tests/test_vision_quota.py:189-197`

**Interfaces:**
- 变更签名：`quota_allows(state, user_key="") -> (bool, str)`
- 新增：`LOCAL_FALLBACK_CALLS = 3`、`_LOCAL_QUOTA` 字典

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_vision_quota.py`：

```python
def test_quota_fault_falls_back_to_local_budget():
    chart_reader._LOCAL_QUOTA.clear()
    for _ in range(chart_reader.LOCAL_FALLBACK_CALLS):
        allowed, _msg = chart_reader.quota_allows(None, "u1")
        assert allowed is True
    allowed, msg = chart_reader.quota_allows(None, "u1")
    assert allowed is False
    assert "临时额度" in msg


def test_quota_fault_isolates_users():
    chart_reader._LOCAL_QUOTA.clear()
    for _ in range(chart_reader.LOCAL_FALLBACK_CALLS):
        chart_reader.quota_allows(None, "u1")
    assert chart_reader.quota_allows(None, "u2")[0] is True
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_vision_quota.py -q -k local_budget`
Expected: FAIL

- [ ] **Step 3: 实现**

在 `modules/chart_reader.py` 常量区（`:42` 附近）追加：

```python
LOCAL_FALLBACK_CALLS = 3
_LOCAL_QUOTA = {}
```

把 `quota_allows` 替换为：

```python
def _local_quota_take(user_key):
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    entry = _LOCAL_QUOTA.get(user_key)
    if not entry or entry["day"] != today:
        entry = {"day": today, "calls": 0}
        _LOCAL_QUOTA[user_key] = entry
    if entry["calls"] >= LOCAL_FALLBACK_CALLS:
        return False
    entry["calls"] += 1
    return True


def quota_allows(state, user_key=""):
    """(是否放行, 提示文本)。state 为 None 表示配额服务不可用。

    故障时不再无条件放行，改用进程级临时额度。单进程部署下它是全局限流，
    刷新页面无法重置，成本上限从「无限」变为「每人每日 3 次」。
    """
    if state:
        if state.get("allowed"):
            return True, ""
        return False, str(state.get("message") or "今日读图配额已用完。")
    if _local_quota_take(user_key or "anonymous"):
        return True, "⚠️ 配额服务不可用，已启用进程级临时额度（每人每日 3 次）。"
    return False, "配额服务不可用，临时额度已用完，请稍后重试。"
```

调用点 `chart_reader.py:398` 改为：

```python
        _uid = (st.session_state.get("auth_user") or {}).get("id") or "anonymous"
        allowed, notice = quota_allows(quota_state, _uid)
```

- [ ] **Step 4: 改既有契约测试**

`tests/test_vision_quota.py:189-197` 原先断言 `quota_allows(None)[0] is True`。改为断言首次放行且提示包含「临时额度」，第三次之后拒绝。

- [ ] **Step 5: 跑测试**

Run: `python -m pytest tests/test_vision_quota.py -q`
Expected: 全绿

- [ ] **Step 6: 提交**

```powershell
git add modules/chart_reader.py tests/test_vision_quota.py
git commit -m "fix(quota): 配额故障改为进程级临时额度，不再无条件放行"
```

---

### Task 4: 读图输出预算受当日剩余 token 约束

**Files:**
- Modify: `modules/chart_reader.py:227-235`，调用点 `:403`
- Modify: `tests/test_vision_quota.py`

**Interfaces:**
- 新增：`SAFETY_MARGIN_TOKENS = 2000`
- 变更行为：`quota_budget` 返回 0 表示预算不足，调用方必须拒绝本次生成

- [ ] **Step 1: 写失败测试**

```python
def test_budget_capped_by_remaining_tokens():
    state = {"max_tokens_per_call": 20000, "tokens_remaining": 5000}
    assert chart_reader.quota_budget(state, 20000) == 3000


def test_budget_zero_when_remaining_below_margin():
    state = {"max_tokens_per_call": 20000, "tokens_remaining": 1000}
    assert chart_reader.quota_budget(state, 20000) == 0
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_vision_quota.py -q -k budget`
Expected: 第一条 FAIL，实际返回 20000

- [ ] **Step 3: 实现**

```python
SAFETY_MARGIN_TOKENS = 2000


def quota_budget(state, default):
    """本次调用的输出预算。

    取单次上限与当日剩余额度两者较小值，并留 SAFETY_MARGIN_TOKENS 余量。
    返回 0 表示当日剩余不足以再发起一次调用。
    """
    if not state:
        return default
    try:
        per_call = int(state.get("max_tokens_per_call") or 0)
        remaining = int(state.get("tokens_remaining") or 0)
    except (TypeError, ValueError):
        return default
    limit = per_call if per_call > 0 else default
    cap = remaining - SAFETY_MARGIN_TOKENS
    if cap <= 0:
        return 0
    return min(limit, cap)
```

调用点 `:403` 之后追加：

```python
        if budget <= 0:
            st.warning("今日 token 剩余额度不足以再生成一次，请次日再试或请联系管理员调整配额。")
            return
```

- [ ] **Step 4: 跑测试**

Run: `python -m pytest tests/test_vision_quota.py tests/test_chart_reader.py -q`
Expected: 全绿。若 `test_chart_reader.py` 断言了预算等于单次上限，按其真实意图改成「不超过剩余额度」。

- [ ] **Step 5: 提交**

```powershell
git add modules/chart_reader.py tests/test_vision_quota.py tests/test_chart_reader.py
git commit -m "fix(quota): 单次输出预算受当日剩余 token 约束"
```

---

### Task 5: 解码结果落状态，修复点不到的按钮

**Files:**
- Modify: `modules/codec.py:301-347`
- Modify: `app.py:116` 的 `_RESET_KEYS_BY_TAB["报文解码"]`
- Create: `tests/test_codec_render.py`

**Interfaces:**
- 新增会话键：`codec_result`（dict 或 None）、`codec_errors`（list）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_codec_render.py
"""解码结果必须跨 rerun 保留，否则页面上的「添加到手动录入区」永远渲染不出来。"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest  # noqa: E402
from modules.codec import render_codec_tab  # noqa: E402


def test_decoded_result_survives_rerun():
    at = AppTest.from_function(render_codec_tab, default_timeout=30)
    at.session_state["codec_result"] = {"station_id": "54511", "temperature": 25.0}
    at.run()
    assert not at.exception
    labels = [b.label for b in at.button]
    assert any("手动录入" in label for label in labels), labels


def test_decode_click_persists_result():
    at = AppTest.from_function(render_codec_tab, default_timeout=30)
    at.run()
    at.text_area[0].set_value(
        "AAXX 54511 01064 42560 10250 20150 39910 40040 58010 333 91020")
    at.button[0].click().run()
    assert not at.exception
    assert at.session_state["codec_result"] is not None
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_codec_render.py -q`
Expected: FAIL，按钮列表中找不到「手动录入」

- [ ] **Step 3: 改 `render_codec_tab`**

把 `codec.py:301-347` 改为「点击分支只负责解码并写状态，渲染分支每轮都执行」：

```python
    if st.button("[搜索] 解码", use_container_width=True, key="decode_btn"):
        if not report_text.strip():
            st.warning("请输入报文内容")
            return
        if "SYNOP" in codec_type:
            with st.spinner("正在解码 SYNOP 报文..."):
                result, errors = decode_synop(report_text)
        else:
            with st.spinner("正在解码 METAR 报文..."):
                result, errors = decode_metar(report_text)
        st.session_state["codec_result"] = result or None
        st.session_state["codec_errors"] = list(errors or [])

    result = st.session_state.get("codec_result")
    errors = st.session_state.get("codec_errors") or []
    for err in errors:
        st.error(err)
    if not result:
        return
    st.success(f"[OK] 解码成功 | 站点: {result.get('station_id', 'N/A')}")
    # ……原有 cols / field_config / metric 渲染保持不变……
    if st.button("[+] 将此记录添加到手动录入区", key="codec_add_manual"):
        st.session_state.setdefault("manual_data", []).append(result)
        st.success("已添加！请切换到数据导入 Tab 查看")
```

- [ ] **Step 4: 重置清单补键**

`app.py:116`：

```python
    "报文解码": ["manual_data", "codec_result", "codec_errors"],
```

- [ ] **Step 5: 跑测试**

Run: `python -m pytest tests/test_codec.py tests/test_codec_render.py -q`
Expected: 全绿

- [ ] **Step 6: 提交**

```powershell
git add modules/codec.py app.py tests/test_codec_render.py
git commit -m "fix(codec): 解码结果落会话状态，修复永远点不到的添加按钮"
```

---

### Task 6: 手动录入合并幂等

**Files:**
- Modify: `modules/data_loader.py`（新增 `merge_manual_rows`）
- Modify: `app.py:753-766`、`app.py:850-861`
- Modify: `tests/test_data_quality.py` 或新建 `tests/test_import_merge.py`

**Interfaces:**
- Produces: `modules.data_loader.merge_manual_rows(df, manual_df) -> pd.DataFrame`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_import_merge.py
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.data_loader import merge_manual_rows


def _manual():
    return pd.DataFrame([{"timestamp": "2026-07-08 14:00", "temperature": 30.0,
                          "station_id": "ST01"}])


def test_merge_is_idempotent():
    once = merge_manual_rows(None, _manual())
    twice = merge_manual_rows(once, _manual())
    assert len(twice) == len(once) == 1


def test_merge_keeps_new_row():
    existing = pd.DataFrame([{"timestamp": "2026-07-08 14:00", "temperature": 28.0,
                              "station_id": "ST01"}])
    merged = merge_manual_rows(existing, _manual())
    assert len(merged) == 1
    assert float(merged.iloc[0]["temperature"]) == 30.0


def test_merge_without_timestamp_dedupes_whole_row():
    manual = pd.DataFrame([{"temperature": 30.0}])
    assert len(merge_manual_rows(manual, manual)) == 1
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_import_merge.py -q`
Expected: FAIL，`ImportError: cannot import name 'merge_manual_rows'`

- [ ] **Step 3: 实现**

追加到 `modules/data_loader.py`：

```python
def merge_manual_rows(df, manual_df):
    """把手动录入并入现有数据集，按时间与站点去重，可重复调用。

    修复：旧流程每次渲染导入向导都把 session_state 里的全部手动记录重新
    concat 进 df，用户返回上一步再前进就会得到重复行。
    """
    if manual_df is None or manual_df.empty:
        return df
    if df is None or df.empty:
        merged = manual_df.copy()
    else:
        merged = pd.concat([df, manual_df], ignore_index=True)
    if "timestamp" in merged.columns:
        subset = ["timestamp"]
        if "station_id" in merged.columns:
            subset.append("station_id")
        merged = merged.drop_duplicates(subset=subset, keep="last")
    else:
        merged = merged.drop_duplicates(keep="last")
    return merged.sort_values("timestamp").reset_index(drop=True) \
        if "timestamp" in merged.columns else merged.reset_index(drop=True)
```

- [ ] **Step 4: 接线两处**

`app.py:753-766` 与 `app.py:850-861` 的合并段统一替换为：

```python
        elif method == "manual":
            df_manual = _safe_render("导入-手动", render_manual_input_section)
            if df_manual is not None:
                df_manual["timestamp"] = pd.to_datetime(
                    df_manual["timestamp"], errors="coerce")
                st.session_state["df"] = merge_manual_rows(
                    st.session_state.get("df"), df_manual)
                st.session_state["import_step"] = 2
                st.rerun()
```

并在 `app.py` 顶部导入 `merge_manual_rows`。

- [ ] **Step 5: 跑测试**

Run: `python -m pytest tests/test_import_merge.py tests/test_data_quality.py -q`
Expected: 全绿

- [ ] **Step 6: 提交**

```powershell
git add modules/data_loader.py app.py tests/test_import_merge.py
git commit -m "fix(import): 手动录入合并按时间与站点去重，重复进入向导不再翻倍"
```

---

### Task 7: CI 阻断全量测试，修正手册路径

**Files:**
- Modify: `.github/workflows/tests.yml:56-64`
- Modify: `docs/用户使用手册.md:113`
- Modify: `README.md`（测试总数与逐文件计数）

- [ ] **Step 1: 改 CI**

把 `.github/workflows/tests.yml` 末尾的：

```yaml
      # 其余 pytest 用例（含天气墙）作为补充信号，失败不阻断门禁
      - name: pytest 全量收集
        continue-on-error: true
        run: python -m pytest tests -q
```

替换为：

```yaml
      # 全量回归：批次 0 起改为阻断。app 启动冒烟包含在内。
      - name: 全量回归（阻断）
        run: python -m pytest tests -q
```

- [ ] **Step 2: 修手册路径**

`docs/用户使用手册.md:113` 的 `supabase/schema.sql` 改为 `sql/schema.sql`。

- [ ] **Step 3: 本地验证**

Run: `python -m pytest tests -q`
Expected: 全绿。若计数断言失败，按实际值更新 `README.md` 的 `当前共 **N** 项` 与逐文件 `N 条`。

- [ ] **Step 4: 提交**

```powershell
git add .github/workflows/tests.yml docs/用户使用手册.md README.md
git commit -m "ci: 全量回归改为阻断门禁，修正手册中的 schema 路径"
```

---

## 完成判定

- `python -m pytest tests -q` 全绿，且 CI 上「全量回归（阻断）」步骤存在并通过。
- `git log --oneline` 有 7 个批次 0 提交，每个可单独 revert。
- 手动验证两条路径。登录后导入数据，直接切到报告导出，报告仍无预警章节（V2 留给批次 1，本批不改变）。点「重置会话并回到首页」后仍保持登录，且云端数据不会自动复活。
- 报文解码点击后出现「添加到手动录入区」按钮，点击后 `manual_data` 增加一条。
