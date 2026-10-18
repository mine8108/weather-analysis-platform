"""会话状态的作用域约定与重置策略。

纯逻辑，不依赖 Streamlit 运行时，便于在无依赖环境单元测试。

作用域约定（批次 1 会把这里扩展成完整注册表）：
- 会话级数据：``df`` / ``source`` / ``warnings_list`` 等，重置时清空。
- 会话级客户端：``_sb_client`` / ``_sb_admin_client``，重置时必须保留，
  否则下一轮新建的客户端没有 JWT，所有 RLS 读写都会被拒。
- 登录态：``auth_user`` 与 ``auth_`` / ``invite_`` / ``admin_`` 前缀键，
  重置与错误恢复都不得清除。
- 导航：``active_tab`` / ``import_step`` / ``import_method`` / ``_nav_stack``，
  重置时回到默认值，但保留栈对象本身以免按钮 key 失效。
"""

SESSION_CLIENT_KEYS = ("_sb_client", "_sb_admin_client")
NAV_KEYS = ("active_tab", "import_step", "import_method", "_nav_stack")
NAV_DEFAULTS = {"active_tab": 0, "import_step": 0, "import_method": None}
AUTO_LOAD_KEY = "_auto_load_done"


def reset_session(state, *, keep_keys=(), keep_prefixes=()):
    """清空业务状态，保留导航、登录态与会话级客户端。

    state 既可以是 ``st.session_state``，也可以是普通 dict，因此本函数
    不依赖 Streamlit，可直接单测。

    返回被删除的键列表，供调用方提示与测试断言。
    """
    preserved = set(keep_keys) | set(SESSION_CLIENT_KEYS) | set(NAV_KEYS)
    for prefix in keep_prefixes:
        preserved.update(k for k in state if k.startswith(prefix))
    removed = [k for k in list(state) if k not in preserved]
    for key in removed:
        del state[key]
    state.update(NAV_DEFAULTS)
    # 阻断 app.py 启动段的「登录后自动载入最近一次云端数据」，
    # 否则重置后数据会被自动载回，用户看到的是「重置没生效」。
    state[AUTO_LOAD_KEY] = True
    return removed
