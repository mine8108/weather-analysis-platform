"""Supabase 后端契约的纯判定逻辑。

这个模块刻意不导入 streamlit / supabase / pandas，便于在无 UI 依赖的环境里
直接测试。它只回答一个问题：`security_selfcheck()` 返回的线上事实，是否满足
仓库里声明的安全边界。

判定项来自 `sql/schema.sql` 的授权设计：

1. public 下业务表必须启用 RLS；
2. 一组函数绝不能对 anon 开放执行权；
3. 服务端专用函数不能对 authenticated 开放，且必须授予 service_role；
4. 客户端角色不能对业务表持有写权限，anon 不应持有任何业务表权限；
5. 自检报告里**缺少**某一项时按失败处理。缺失意味着无法证明边界成立，
   不能像旧实现那样静默判定为「安全」。
"""

RLS_TABLES = ("datasets", "profiles", "invite_codes", "gfs_cache",
              "vision_usage", "admin_audit_log", "schema_version",
              "outbound_usage", "vision_calls")

# 这些函数一旦对匿名角色开放，未登录访客就能绕过应用直接调后端。
ANON_FORBIDDEN_FUNCTIONS = (
    "settle_vision_call",
    "save_dataset",
    "put_gfs_cache",
    "get_storage_usage",
    "get_storage_quota",
    "get_gfs_cache",
    "get_vision_quota",
    "begin_vision_call",
    "record_vision_usage",
    "begin_outbound_call",
    "consume_invite_code",
    "release_invite_code",
    "security_selfcheck",
    "claim_invite_code",
    "is_invite_code_valid",
)

# 这些函数的信息面或破坏面超出普通登录用户，只允许 service_role。
AUTHENTICATED_FORBIDDEN_FUNCTIONS = (
    "record_vision_usage", "settle_vision_call",
    "put_gfs_cache",
    "release_invite_code",
    "security_selfcheck",
    "consume_invite_code",
    "claim_invite_code",
    "is_invite_code_valid",
    "get_gfs_cache",
)

# 服务端写入/注册函数必须对 service_role 开放，否则注册或缓存写入会静默失败。
SERVICE_REQUIRED_FUNCTIONS = (
    "settle_vision_call",
    "put_gfs_cache",
    "get_gfs_cache",
    "claim_invite_code",
    "consume_invite_code",
    "release_invite_code",
    "security_selfcheck",
)

# 这些函数必须是 SECURITY DEFINER 且 search_path 把 pg_temp 放到最后。
# 缺失、被重建后丢失属性、或 search_path 被改回 public，都会在自检里暴露。
SECURITY_DEFINER_FUNCTIONS = (
    "settle_vision_call",
    "handle_new_user",
    "is_invite_code_valid",
    "claim_invite_code",
    "release_invite_code",
    "consume_invite_code",
    "get_storage_usage",
    "get_storage_quota",
    "put_gfs_cache",
    "get_gfs_cache",
    "save_dataset",
    "get_vision_quota",
    "begin_vision_call",
    "record_vision_usage",
    "begin_outbound_call",
    "security_selfcheck",
)

# schema.sql 创建的 RLS 策略；缺失说明迁移没跑全或被手工删掉。
REQUIRED_POLICIES = (
    "datasets_owner_only",
    "profiles_select_self",
    "profiles_insert_service",
    "vision_usage_select_self",
)

# 客户端角色的表级写权限必须收回，写入一律经 SECURITY DEFINER 函数。
FORBIDDEN_TABLE_PRIVILEGES = {
    "vision_calls": {"authenticated": ("SELECT", "INSERT", "UPDATE", "DELETE")},
    "datasets": {"authenticated": ("INSERT", "UPDATE")},
    "profiles": {"authenticated": ("UPDATE",)},
    "vision_usage": {"authenticated": ("INSERT", "UPDATE", "DELETE")},
    "gfs_cache": {"authenticated": ("SELECT", "INSERT", "UPDATE", "DELETE")},
    "admin_audit_log": {"authenticated": ("SELECT", "INSERT", "UPDATE", "DELETE")},
    "schema_version": {"authenticated": ("SELECT", "INSERT", "UPDATE", "DELETE")},
    "invite_codes": {"authenticated": ("SELECT", "INSERT", "UPDATE", "DELETE")},
}

# anon 不应持有任何业务表权限（RLS 之外的第二道防线）。
FORBIDDEN_ANON_TABLE_PRIVILEGES = {
    table: ("SELECT", "INSERT", "UPDATE", "DELETE") for table in RLS_TABLES
}


def _grant_value(functions, name, role):
    """读 `functions[name][role]`；缺失或非布尔返回 None（不可信）。"""
    entry = functions.get(name)
    if not isinstance(entry, dict):
        return None
    value = entry.get(role)
    return value if isinstance(value, bool) else None


def _privilege_value(privileges, table, role, privilege):
    """读表权限矩阵；缺失返回 None。"""
    value = privileges.get("%s.%s.%s" % (table, role, privilege))
    return value if isinstance(value, bool) else None


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
        value = _grant_value(functions, name, "anon")
        if value is None:
            problems.append("函数 %s 未出现在自检报告中（缺失=不可信）" % name)
        elif value is True:
            problems.append("函数 %s 对 anon 开放执行权" % name)
    for name in AUTHENTICATED_FORBIDDEN_FUNCTIONS:
        value = _grant_value(functions, name, "authenticated")
        if value is None:
            problems.append("函数 %s 未出现在自检报告中（缺失=不可信）" % name)
        elif value is True:
            problems.append("函数 %s 对 authenticated 开放执行权" % name)
    for name in SERVICE_REQUIRED_FUNCTIONS:
        value = _grant_value(functions, name, "service_role")
        if value is not True:
            problems.append("函数 %s 未授予 service_role" % name)

    # SEC-17：策略内容与 SECURITY DEFINER 属性也必须能被证明
    policies = report.get("policies")
    if not isinstance(policies, list):
        problems.append("自检报告缺少 policies 列表（无法证明策略内容）")
    else:
        policy_names = {
            p.get("name") for p in policies if isinstance(p, dict)
        }
        for name in REQUIRED_POLICIES:
            if name not in policy_names:
                problems.append("策略 %s 未出现在自检报告中" % name)
        for policy in policies:
            if not isinstance(policy, dict):
                continue
            roles = policy.get("roles") or []
            if any(str(role).lower() == "anon" for role in roles
                   if role is not None):
                problems.append("策略 %s 对 anon 开放"
                                % policy.get("name", "?"))

    definer = report.get("definer_functions")
    if not isinstance(definer, dict):
        problems.append(
            "自检报告缺少 definer_functions（无法证明 SECURITY DEFINER 属性）"
        )
    else:
        for name in SECURITY_DEFINER_FUNCTIONS:
            entry = definer.get(name)
            if not isinstance(entry, dict):
                problems.append("函数 %s 未出现在 definer_functions 中" % name)
                continue
            if entry.get("security_definer") is not True:
                problems.append("函数 %s 未声明 SECURITY DEFINER" % name)
            search_path = str(entry.get("search_path") or "")
            if "pg_temp" not in search_path:
                problems.append("函数 %s 的 search_path 未包含 pg_temp" % name)

    privileges = report.get("table_privileges") or {}
    for table, roles in FORBIDDEN_TABLE_PRIVILEGES.items():
        for role, privs in roles.items():
            for privilege in privs:
                value = _privilege_value(privileges, table, role, privilege)
                if value is None:
                    problems.append(
                        "权限项 %s.%s.%s 缺失（无法证明已收回）"
                        % (table, role, privilege)
                    )
                elif value is True:
                    problems.append(
                        "表 %s 的 %s 权限仍授予 %s" % (table, privilege, role)
                    )
    for table, privs in FORBIDDEN_ANON_TABLE_PRIVILEGES.items():
        for privilege in privs:
            value = _privilege_value(privileges, table, "anon", privilege)
            if value is None:
                problems.append(
                    "权限项 %s.anon.%s 缺失（无法证明已收回）" % (table, privilege)
                )
            elif value is True:
                problems.append(
                    "表 %s 的 %s 权限仍授予 anon" % (table, privilege)
                )
    return problems
