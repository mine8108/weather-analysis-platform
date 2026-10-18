"""Supabase 后端契约的纯判定逻辑。

这个模块刻意不导入 streamlit / supabase / pandas，便于在无 UI 依赖的环境里
直接测试。它只回答一个问题：`security_selfcheck()` 返回的线上事实，是否满足
仓库里声明的安全边界。

判定项来自 `sql/schema.sql` 的授权设计：

1. public 下五张业务表必须启用 RLS；
2. 一组函数绝不能对 anon 开放执行权；
3. `put_gfs_cache`、`release_invite_code` 与 `security_selfcheck` 不能对 authenticated 开放；
4. 客户端角色不能对业务表持有 insert/update/delete 权限。
"""

RLS_TABLES = ("datasets", "profiles", "invite_codes", "gfs_cache",
              "vision_usage", "admin_audit_log", "schema_version")

# 这些函数一旦对匿名角色开放，未登录访客就能绕过应用直接调后端。
ANON_FORBIDDEN_FUNCTIONS = (
    "save_dataset",
    "put_gfs_cache",
    "get_storage_usage",
    "get_storage_quota",
    "get_gfs_cache",
    "begin_vision_call",
    "record_vision_usage",
    "consume_invite_code",
    "release_invite_code",
    "security_selfcheck",
)

# 这些函数的信息面或破坏面超出普通登录用户，只允许 service_role。
AUTHENTICATED_FORBIDDEN_FUNCTIONS = (
    "put_gfs_cache",
    "release_invite_code",
    "security_selfcheck",
)

# 服务端写入函数必须对 service_role 开放，否则缓存写入会静默失败。
SERVICE_REQUIRED_FUNCTIONS = ("put_gfs_cache",)

# 客户端角色的表级写权限必须收回，写入一律经 SECURITY DEFINER 函数。
FORBIDDEN_TABLE_PRIVILEGES = {
    "datasets": {"authenticated": ("INSERT", "UPDATE")},
    "profiles": {"authenticated": ("UPDATE",)},
    "vision_usage": {"authenticated": ("INSERT", "UPDATE", "DELETE")},
    "gfs_cache": {"authenticated": ("SELECT", "INSERT", "UPDATE", "DELETE")},
    "admin_audit_log": {"authenticated": ("SELECT", "INSERT", "UPDATE", "DELETE")},
    "schema_version": {"authenticated": ("SELECT", "INSERT", "UPDATE", "DELETE")},
}


def _function_grant(functions, name, role):
    """读 `functions[name][role]`，缺失一律视为未授权。"""
    entry = functions.get(name) or {}
    return entry.get(role) is True


def selfcheck_problems(report):
    """把自检报告转成人类可读的问题列表，空列表表示通过。"""
    if not isinstance(report, dict):
        return ["安全自检返回值不是对象"]

    problems = []
    rls = report.get("rls") or {}
    for table in RLS_TABLES:
        if rls.get(table) is not True:
            problems.append("表 %s 未启用 RLS" % table)

    functions = report.get("functions") or {}
    for name in ANON_FORBIDDEN_FUNCTIONS:
        if _function_grant(functions, name, "anon"):
            problems.append("函数 %s 对 anon 开放执行权" % name)
    for name in AUTHENTICATED_FORBIDDEN_FUNCTIONS:
        if _function_grant(functions, name, "authenticated"):
            problems.append("函数 %s 对 authenticated 开放执行权" % name)
    for name in SERVICE_REQUIRED_FUNCTIONS:
        if not _function_grant(functions, name, "service_role"):
            problems.append("函数 %s 未授予 service_role" % name)

    privileges = report.get("table_privileges") or {}
    for table, roles in FORBIDDEN_TABLE_PRIVILEGES.items():
        for role, privs in roles.items():
            for privilege in privs:
                key = "%s.%s.%s" % (table, role, privilege)
                if privileges.get(key) is True:
                    problems.append(
                        "表 %s 的 %s 权限仍授予 %s" % (table, privilege, role)
                    )
    return problems
