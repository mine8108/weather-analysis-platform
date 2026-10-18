"""会话状态的作用域约定、注册表与重置策略。

纯逻辑，不依赖 Streamlit 运行时，便于在无依赖环境单元测试。

作用域约定：
- ``keep``   登录态、会话客户端、主题与用户偏好。错误恢复与登出之外的任何重置都不得清除。
- ``global`` 只在整会话重置时清除，例如导入历史与自动载入哨兵。
- ``tab``    归属某个 Tab 的业务数据，重置该 Tab 时清除。

注册表是唯一清单。``app.py`` 不再手写 keep / reset 键集合，
``research/check_state_registry.py`` 在 CI 中校验源码里的字面量键是否全部登记。
"""

SESSION_CLIENT_KEYS = ("_sb_client", "_sb_admin_client")
NAV_KEYS = ("active_tab", "import_step", "import_method", "_nav_stack")
NAV_DEFAULTS = {"active_tab": 0, "import_step": 0, "import_method": None}
AUTO_LOAD_KEY = "_auto_load_done"

TAB_IMPORT = "导入"
TAB_VISUAL = "可视化"
TAB_FORECAST = "数值预报"
TAB_CHART = "读图解析"
TAB_EXPORT = "报告导出"
TAB_CODEC = "报文解码"

# Tab 顺序的单一真相源，app.py 用它派生 _TAB_NAMES
TAB_NAMES = (TAB_IMPORT, TAB_VISUAL, TAB_FORECAST, TAB_CHART, TAB_EXPORT, TAB_CODEC)


def _register(names, reset, tab=None):
    for name in names:
        KEYS[name] = {"scope": "session", "reset": reset, "tab": tab}


KEYS = {}

# 登录态与会话客户端（登出流程单独处理，不在这份策略内）
_register((
    "auth_user", "auth_error", "admin_unlocked", "admin_unlock_time",
    "invite_codes_out", "dark_mode", "_theme_cloud", "debug_mode",
    "_custom_thresholds", "_nav_stack", "_admin_sid",
), "keep")

_register(("active_tab", "import_step", "import_method"), "keep")

_register((
    "_auto_load_done", "_import_history", "_wall_show", "_manual_open",
    "_warn_fp",
), "global")

_register((
    # 数据导入
    "df", "source", "quality_score", "warnings_list", "manual_data",
    "_dataset_schema_version", "_dataset_created_at",
    "api_df", "api_source", "api_fetched_weather", "api_fetched_pollution",
    "api_weather_source", "api_aq_source",
    "era5_product", "era5_preset_pick", "_era5_preset_applied",
    "_template_cache",
    "climate_data", "climate_extreme", "_date_is_synthetic", "_filter_date_range",
    # 首页天气墙（随导入 Tab 渲染）
    "wall_cities", "wall_query", "wall_candidate_pick", "_resolve_candidates",
    "_wall_notice", "_geo_consumed", "_relocate", "_wall_cover",
    "_wall_fallback", "_wall_aqi_fallback",
), "tab", tab=TAB_IMPORT)

_register((
    "fc_df", "fc_analysis", "fc_lat", "fc_lon", "fc_model", "life_indices",
    "nwp_forecast_for_analysis", "nwp_air_quality_for_analysis",
), "tab", tab=TAB_FORECAST)

_register((
    "chart_reader_images", "chart_reader_text", "chart_reader_meta",
    "chart_reader_report_images", "chart_reader_last_gen",
    "chart_reader_gen_count", "chart_reader_usage_last",
    "chart_reader_usage_total",
), "tab", tab=TAB_CHART)

_register(("report_data",), "tab", tab=TAB_EXPORT)
_register(("codec_result", "codec_errors"), "tab", tab=TAB_CODEC)
_register(("multi_station_selected",), "tab", tab=TAB_VISUAL)

# 动态键前缀：以变量拼出的会话键，注册表用前缀覆盖
KNOWN_PREFIXES = (
    "aq_cache_",       # nwp_forecast 空气质量会话缓存
    "_tab_fp_",        # utils.tab_fingerprint_match
    "_api_cache_",     # utils.retry_with_backoff 降级缓存
    "load_",           # app.py 数据集载入按钮
    "del_",            # app.py 数据集删除按钮
    "ww_del_",         # weather_wall 城市删除按钮
)

# widget key 注册表：只用于 CI 校验，不参与重置（Streamlit 会自行重建）
WIDGET_KEYS = {
    name: {"owner": "ui"}
    for name in (
        "_filter_date_range_input", "admin_pw", "admin_unlock_btn",
        "admin_user_sel", "api_aq_date", "api_aq_fetch", "api_aq_lat",
        "api_aq_lon", "api_date", "api_fetch", "api_lat", "api_lon",
        "api_merge", "api_merge_solo_a", "api_merge_solo_w", "api_use_aq_merged",
        "api_use_aq_solo", "api_use_weather_merged", "api_use_weather_solo",
        "auth_email", "auth_invite", "auth_mode", "auth_password",
        "back_to_wizard", "chart_reader_generate", "chart_reader_note",
        "chart_reader_uploader", "codec_add_manual", "codec_input", "codec_type",
        "csv_upload", "dark_toggle", "debug_mode", "decode_btn", "dual_agg",
        "dual_left", "dual_right", "era5_e", "era5_months", "era5_n",
        "era5_preset_pick", "era5_pressure_levels", "era5_product", "era5_s",
        "era5_w", "era5_years", "fc_days", "fc_fetch", "fc_lat", "fc_lon",
        "fc_model", "fg_o", "fg_r", "fg_y", "fr_b", "fr_o", "fr_y",
        "gen_report", "gw_b", "gw_o", "gw_r", "gw_y", "hist_fields", "ht_o",
        "ht_r", "ht_y", "hz_o", "hz_y", "invite_gen", "invite_n",
        "invite_revoke", "jump_alert", "jump_export", "jump_viz", "logout_btn",
        "manual_back", "manual_chapter_pick", "manual_download",
        "manual_open_btn", "ms_all", "ms_invert", "ms_none", "ms_select",
        "multi_station_field", "onboard_quick", "oq_calls", "oq_save",
        "quota_mb", "quota_save",
        "report_download_docx", "report_download_md", "report_style", "rs_b",
        "rs_o", "rs_r", "rs_y", "save_cloud", "sb_wall_cover",
        "sidebar_reset_current_tab", "skip_wizard", "th_h", "ts_picker",
        "ts_select", "verify_end", "verify_obs_src", "verify_run",
        "verify_start", "verify_upload", "verify_var", "viz_back",
        "viz_subtab", "vq_calls", "vq_maxcall", "vq_save", "vq_tokens",
        "wall_back_to_data", "wall_candidate_pick", "wall_locate", "wall_query",
        "wall_refresh", "wall_resolve", "wall_show_toggle", "wiz_api",
        "wiz_back", "wiz_back_step0", "wiz_back_step1", "wiz_confirm",
        "wiz_file", "wiz_manual", "wiz_retry", "xlsx_upload",
    )
}


def preserved_keys():
    """整会话重置时必须保留的键。"""
    return (set(SESSION_CLIENT_KEYS) | set(NAV_KEYS)
            | {k for k, spec in KEYS.items() if spec["reset"] == "keep"})


# 登出时保留的键。登出必须丢弃客户端与登录态，只留导航栈，
# 与 reset_session 的保留集合刻意不同。
LOGOUT_KEEP = {"_nav_stack"}


def keys_for_tab(tab):
    """某个 Tab 重置时清除的显式键。"""
    return {k for k, spec in KEYS.items()
            if spec["reset"] == "tab" and spec["tab"] == tab}


def prefixes_for_tab(tab):
    """某个 Tab 的显式键前缀；当前没有按 Tab 区分的前缀规则。"""
    return ()


def reset_session(state, *, keep_keys=(), keep_prefixes=()):
    """清空业务状态，保留导航、登录态与会话级客户端。

    state 既可以是 ``st.session_state``，也可以是普通 dict，因此本函数
    不依赖 Streamlit，可直接单测。

    返回被删除的键列表，供调用方提示与测试断言。
    """
    preserved = preserved_keys() | set(keep_keys)
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


def reset_tab(state, tab):
    """清空某个 Tab 的业务状态，保留登录态、导航与偏好。

    返回被删除的键列表。
    """
    names = keys_for_tab(tab)
    prefixes = prefixes_for_tab(tab)
    removed = []
    for key in list(state):
        if key in names or any(key.startswith(p) for p in prefixes):
            del state[key]
            removed.append(key)
    return removed
