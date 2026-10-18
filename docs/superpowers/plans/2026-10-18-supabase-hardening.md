# Supabase 后端加固（批次 1：S1-S4）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让线上安全边界可自证，让 GFS 二级缓存恢复跨用户、跨重启可用，堵住存储配额绕过。

**Architecture:** `supabase/schema.sql` 仍是唯一部署脚本，新增 `security_selfcheck()` 与 `put_gfs_cache()` 两个 `SECURITY DEFINER` RPC，客户端对 `gfs_cache` 的直写权限全部收回。缓存读写下沉到不依赖 Streamlit 的纯模块，管理面板每次解锁先跑自检，自检不通过就停止管理操作。

**Tech Stack:** PostgreSQL / Supabase、Python 3.14（本机测试解释器）、Streamlit、supabase-py。

**Spec:** [research/supabase-体检-2026-10-18.md](../../../research/supabase-体检-2026-10-18.md)

## Global Constraints

- `supabase/schema.sql` 必须可重复执行，新增对象一律用 `if not exists` 或 `create or replace`。
- `APP_VERSION` 保持 `2.3.8`，发布时统一升版；本批次不碰版本声明。
- 不新增运行时依赖，不引入 `pytest` 之外的开发依赖。
- 所有测试文件必须能 `python -B tests/<file>.py` 直跑。
- 客户端写路径一律经 `SECURITY DEFINER` 函数，表级 `insert/update/delete` 对 `anon` 与 `authenticated` 收回。
- 本机测试解释器：`C:\Users\ASUS\AppData\Local\Programs\Python\Python314\python.exe`。

---

### Task 1: 安全自检的纯判定函数

**Files:**
- Create: `modules/supabase_backend.py`
- Test: `tests/test_supabase_backend.py`

**Interfaces:**
- Produces: `selfcheck_problems(report: dict) -> list[str]`，输入是 `security_selfcheck()` 返回的 jsonb 解析结果，返回人类可读的问题列表，空列表表示通过。
- Produces: 常量 `RLS_TABLES`、`ANON_FORBIDDEN_FUNCTIONS`、`AUTHENTICATED_FORBIDDEN_FUNCTIONS`、`FORBIDDEN_TABLE_PRIVILEGES`。

- [ ] **Step 1: 写失败测试**

```python
def test_selfcheck_passes_on_expected_report():
    report = {
        "rls": {t: True for t in backend.RLS_TABLES},
        "functions": {
            "save_dataset": {"anon": False, "authenticated": True},
            "security_selfcheck": {"anon": False, "authenticated": False},
            "release_invite_code": {"anon": False, "authenticated": False},
        },
        "table_privileges": {
            "datasets.authenticated.INSERT": False,
            "datasets.authenticated.UPDATE": False,
            "profiles.authenticated.UPDATE": False,
            "vision_usage.authenticated.INSERT": False,
            "gfs_cache.authenticated.INSERT": False,
        },
    }
    assert backend.selfcheck_problems(report) == []
```

- [ ] **Step 2: 运行并确认失败**

Run: `python -B tests/test_supabase_backend.py`
Expected: `ModuleNotFoundError: modules.supabase_backend`

- [ ] **Step 3: 实现**

按测试里的报告结构实现 `selfcheck_problems`，检查五张表的 RLS、`anon` 禁止函数、`authenticated` 禁止函数、四张表的写权限。

- [ ] **Step 4: 运行通过**

Run: `python -B tests/test_supabase_backend.py`
Expected: PASS

### Task 2: GFS 缓存读写纯模块

**Files:**
- Create: `modules/gfs_cache.py`
- Test: `tests/test_supabase_backend.py`

**Interfaces:**
- Produces: `write_params(cache_key, lat, lon, days, model, records) -> dict`，键名与 `put_gfs_cache` 参数一一对应。
- Produces: `read_from(client, cache_key, ttl_hours=1, now=None) -> list | None`，只选 `data_json`，按 `updated_at` 过滤。
- Produces: `save_to(client, cache_key, lat, lon, days, model, records) -> bool`，调用 `put_gfs_cache` RPC。

- [ ] **Step 1: 写失败测试**

```python
def test_read_from_filters_on_updated_at_and_returns_records():
    client = _FakeClient([{"data_json": [{"timestamp": "2026-10-18T00:00"}]}])
    rows = cache.read_from(client, "k", now=datetime(2026, 10, 18, tzinfo=timezone.utc))
    assert rows == [{"timestamp": "2026-10-18T00:00"}]
    assert client.calls[0] == ("select", "data_json")
    assert client.calls[2][0] == "gte" and client.calls[2][1] == "updated_at"

def test_save_to_uses_put_rpc():
    client = _FakeClient(True)
    assert cache.save_to(client, "k", 1.0, 2.0, 7, "blend", [{"timestamp": "x"}]) is True
    name, params = client.calls[0]
    assert name == "put_gfs_cache"
    assert params["p_days"] == 7 and params["p_model"] == "blend"
```

- [ ] **Step 2: 运行并确认失败**

Run: `python -B tests/test_supabase_backend.py`
Expected: `ModuleNotFoundError: modules.gfs_cache`

- [ ] **Step 3: 实现**

模块只导入 `logging` 与 `datetime`，不导入 Streamlit。`read_from` 用 `select("data_json").eq("cache_key", key).gte("updated_at", cutoff)`；`save_to` 调 `rpc("put_gfs_cache", write_params(...))`，失败只记日志。

- [ ] **Step 4: 运行通过**

Expected: PASS

### Task 3: schema.sql 的四组改动

**Files:**
- Modify: `supabase/schema.sql`

**Interfaces:**
- Produces: `gfs_cache.updated_at`、`gfs_cache_updated_idx`、`put_gfs_cache(...) returns boolean`、`security_selfcheck() returns jsonb`、`datasets_name_len_check`。
- Consumes: 无。

- [ ] **Step 1: 写 schema 契约失败测试**

```python
def test_schema_defines_cache_rpc_and_updated_at():
    sql = _read("supabase/schema.sql")
    for needle in ("updated_at timestamptz", "gfs_cache_updated_idx",
                   "create or replace function public.put_gfs_cache",
                   "revoke insert, update, delete on public.gfs_cache",
                   "create or replace function public.security_selfcheck",
                   "datasets_name_len_check"):
        assert needle in sql, needle
```

- [ ] **Step 2: 运行并确认失败**

Expected: FAIL，缺第一个 needle

- [ ] **Step 3: 改 schema**

1. `datasets` 建表后加名称长度约束，`not valid` 后尝试 `validate`，失败只 warning。
2. `save_dataset` 增加 `char_length(p_name) > 200`、插入时 200 条上限、`v_new_bytes` 计入 `octet_length(p_name)`；`get_storage_usage` 同步计入名称字节。
3. `gfs_cache` 增加 `updated_at` 与索引，删除旧写/更新/清理策略，收回 `insert/update/delete`。
4. 新增 `put_gfs_cache`，校验 key 前缀、经纬度与 key 自洽、days、model、数组形状、每项 timestamp、100KB 上限，写入前清理 6 小时前旧行。
5. 新增 `security_selfcheck`，返回 `rls`、`functions`、`table_privileges` 三段 jsonb，只授予 `service_role`。

- [ ] **Step 4: 运行通过**

Expected: PASS

### Task 4: nwp_forecast 接入新 RPC

**Files:**
- Modify: `modules/nwp_forecast.py`

**Interfaces:**
- Consumes: `modules.gfs_cache.read_from`、`modules.gfs_cache.save_to`。
- Produces: `_load_gfs_from_cache` 与 `_save_gfs_to_cache` 行为不变，底层改走 `updated_at` 与 `put_gfs_cache`。

- [ ] **Step 1: 写失败测试**

```python
def test_nwp_cache_write_uses_rpc():
    # patch nwp_forecast.st 与 auth.get_supabase，调用 _save_gfs_to_cache
    assert fake.calls[0][0] == "put_gfs_cache"
```

- [ ] **Step 2: 运行并确认失败**

Expected: 断言失败，当前是 `table("gfs_cache").upsert`

- [ ] **Step 3: 改实现**

删除表直写，改调 `gfs_cache.save_to`；读取改调 `gfs_cache.read_from`；补 `logging`，异常不再完全静默。

- [ ] **Step 4: 运行通过**

Expected: PASS

### Task 5: db.py 错误文案

**Files:**
- Modify: `db.py`
- Test: `tests/test_supabase_backend.py`

**Interfaces:**
- Produces: `save_error_message(error: str) -> str`，映射 `配额不足`、`名称过长`、`数据集数量已达上限`。

- [ ] **Step 1-4:** 先写 `test_save_error_message_maps_new_codes`，确认失败，再实现并跑通。

### Task 6: 管理面板接入自检

**Files:**
- Modify: `auth.py`

**Interfaces:**
- Consumes: `modules.supabase_backend.selfcheck_problems`。
- Produces: `_run_security_selfcheck(sb_admin) -> dict | None`；`_render_admin_panel` 在 `_missing_tables` 之后调用，自检不通过就报错并 `return`。

- [ ] **Step 1: 写失败测试**

```python
def test_admin_selfcheck_reads_rpc():
    report = auth._run_security_selfcheck(_FakeAdminWithSelfcheck())
    assert report["rls"]["datasets"] is True

def test_admin_selfcheck_returns_none_on_error():
    assert auth._run_security_selfcheck(_FakeBoom()) is None
```

- [ ] **Step 2: 运行并确认失败**

Expected: `AttributeError: module 'auth' has no attribute '_run_security_selfcheck'`

- [ ] **Step 3: 实现并接入**

`_run_security_selfcheck` 兼容 dict 与单元素 list；`_missing_tables` 列表加入 `gfs_cache`；自检问题非空时 `st.error` 并 `return`。

- [ ] **Step 4: 运行通过**

Expected: PASS

### Task 7: 文档、CI、README 计数

**Files:**
- Modify: `.github/workflows/tests.yml`
- Modify: `README.md`
- Modify: `SECURITY.md`

- [ ] CI 增加 `Supabase 后端契约` 一步，直跑新测试文件。
- [ ] README 测试树与直跑命令加入新文件，更新 pytest 总数。
- [ ] SECURITY.md 补 `security_selfcheck`、`put_gfs_cache`、`updated_at` 与升级重跑说明。

### Task 8: 全量验证与提交

- [ ] 运行新测试文件、CI 门禁脚本、pytest 全量。
- [ ] 检查 `git diff`，确认没有版本号漂移、没有未跟踪的临时文件。
- [ ] 提交到 `fix/supabase-hardening`。

## 实施记录（2026-10-18）

- Task 1-8 全部完成，代码在 `fix/supabase-hardening` 分支。
- 新增文件：`modules/supabase_backend.py`、`modules/gfs_cache.py`、`tests/test_supabase_backend.py`。
- 修改文件：`supabase/schema.sql`、`modules/nwp_forecast.py`、`db.py`、`auth.py`、`README.md`、`SECURITY.md`、`.github/workflows/tests.yml`。
- 本机测试解释器：Python 3.14。十一个 CI 门禁脚本全部通过；新测试 18 条全绿。
- `pytest tests` 共收集 421 项，410 通过、11 失败。11 条失败在修改前就存在，全部由本机沙箱的临时目录权限导致（7 条 `test_auth_session` 的 AppTest 临时目录、4 条 `test_weather_wall` 的本地偏好文件），已在 `main` 基线上复现，与本批次改动无关。
- 线上执行（2026-10-18）：`supabase/schema.sql` 已在 Supabase SQL Editor 执行成功；`security_selfcheck()`、`put_gfs_cache` 的权限与写入行为已通过 SQL 核验。
- 执行中发现并修复：`security_selfcheck` 的 `bool_or` 嵌套聚合（42803）；Supabase 默认函数权限需要显式 revoke anon/authenticated。
- 线上 Streamlit 应用仍是旧部署，新代码尚未推送；管理员面板自检需发布后验证。

### 批次 2（2026-10-18）：写入收口与冗余清理

- `put_gfs_cache` 放行 service_role、收回 authenticated 执行权；`nwp_forecast._save_gfs_to_cache` 改用 `get_supabase_admin()`。登录用户不再有缓存写入入口。
- HMAC 暂缓：签名者与写库者同为 Streamlit 进程，HMAC 对该威胁模型没有额外收益。
- 冗余清理：`auth._session_client`、`db._scalar_rpc`、`utils.supabase_secrets_ready` 三处合并；删除 `gfs_cache.PRUNE_HOURS`；schema 读图配额章节由 8 改为 9、自检章节由 9 改为 10，并同步所有引用。
- 测试保持 18 条，修改既有断言覆盖 service_role 写入与 authenticated 收回；本地门禁需重新跑一遍。

### 批次 2 后端项（S5/S6/S14/S15）

- S5：`app.py` 在登录门禁后调用 `ensure_session()`；`auth.py` 新增 `is_session_error` / `expire_session` / `ensure_session`；`db.py` 在 RPC 异常中识别会话失效并回登录页。
- S6：`db.py` 与 `auth.py` 补 `logging`，关键失败路径不再静默。
- S14：`auth._list_users` 按 100 条/页翻页，老版本 API 回退单页。
- S15：两个 `SECURITY DEFINER` 函数在 `for update` 前幂等补 `profiles` 行，schema 增加历史用户补行。
- 测试：`test_supabase_backend.py` 新增会话错误、分页、日志三条，总数 424；全量通过。
