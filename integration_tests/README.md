# Supabase RPC 集成测试（staging）

这里的三条用例验证**数据库侧**安全契约，单测无法覆盖：

1. `test_save_dataset_concurrent_quota` — SEC-01：并发 `save_dataset` 不得突破存储配额。
2. `test_outbound_quota_concurrency` — SEC-02：并发 `begin_outbound_call` 只能放行配额内次数（需要 service key）。
3. `test_invite_functions_require_service_role` — SEC-08：验码/认领不再对 anon / authenticated 开放。

## 准备

**不要使用生产项目。** 新建一个独立的 Supabase 项目用于测试：

1. 在新项目的 SQL Editor 执行仓库里的 `sql/schema.sql`。
2. Authentication → Users → Add user，创建一个测试账号（勾选 auto-confirm）。
3. 设置环境变量（只写在当前 shell，不要提交）：

```powershell
$env:SUPABASE_TEST_URL = "https://<staging-ref>.supabase.co"
$env:SUPABASE_TEST_ANON_KEY = "<staging anon key>"
$env:SUPABASE_TEST_EMAIL = "itest@example.com"
$env:SUPABASE_TEST_PASSWORD = "<test user password>"
# 仅第 2 条用例需要；没有就自动 skip
$env:SUPABASE_TEST_SERVICE_KEY = "<staging service_role key>"
```

4. 运行：

```powershell
.venv\Scripts\python.exe -m pytest integration_tests -q
```

## 注意

- `pip install -r requirements.txt` 已包含 `supabase`，`requirements-dev.txt` 包含 `pytest`。
- 用例会创建并清理测试数据集/用量记录；第 2 条会临时把测试用户的出站配额改成 3，结束后恢复 200。
- service_role key 只在 staging 使用，绝不进入 CI Secrets 之外的任何地方。
- 默认 `pytest tests` 不会收集本目录，因此不影响线上回归套件。
