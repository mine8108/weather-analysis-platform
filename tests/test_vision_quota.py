"""读图配额回归测试：schema 安全契约、数据访问层、页面侧纯函数。

为什么要有 schema 契约测试：配额是**安全边界**，它的正确性不在 Python 里，
而在 supabase/schema.sql 的 SQL 里。改错一个 revoke，登录用户就能自己清空计数，
而所有 Python 测试依然全绿。因此这里直接对 SQL 文本做断言，把三条底线锁住：

1. 函数内部以 auth.uid() 判定身份，**不得接受调用方传入的 user_id**；
2. token 增量钳到非负，否则传负数即可反向冲销用量；
3. 默认的 PUBLIC 执行权收回，仅授予 authenticated 与 service_role。

无 pytest 时可直接运行（`python -B tests/test_vision_quota.py`）。
"""
import os
import sys

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from modules import chart_reader  # noqa: E402
import db  # noqa: E402


def _read(rel):
    import io
    with io.open(os.path.join(_APP_DIR, rel), encoding="utf-8") as handle:
        return handle.read()


def _quota_section():
    """schema.sql 里读图配额那一节（避免断言误命中其他章节的同名字样）。"""
    sql = _read("supabase/schema.sql")
    marker = "8. 读图配额"
    assert marker in sql, "schema.sql 缺少读图配额章节"
    return sql.split(marker, 1)[1]


# ============================================================
# 一、schema 安全契约
# ============================================================

def test_schema_defines_per_user_vision_quota():
    section = _quota_section()
    for needle in ("vision_calls_per_day", "vision_tokens_per_day",
                   "vision_max_tokens_per_call", "public.vision_usage",
                   "public.get_vision_quota", "public.begin_vision_call",
                   "public.record_vision_usage"):
        assert needle in section, needle


def test_schema_revokes_public_execute_and_grants_authenticated():
    """默认 PUBLIC 执行权必须收回，否则匿名角色也能调用这些函数。"""
    section = _quota_section()
    for fn in ("get_vision_quota()", "begin_vision_call()",
               "record_vision_usage(bigint, bigint, bigint, bigint)"):
        assert "revoke execute on function public.%s from public;" % fn in section, fn
        assert "grant execute on function public.%s" % fn in section, fn
    assert "to authenticated, service_role" in section


def test_schema_vision_functions_never_take_caller_supplied_user_id():
    """身份只能来自 auth.uid()。若函数接受 p_user_id，登录用户就能伪造或清空
    他人的用量，配额形同虚设。"""
    section = _quota_section()
    assert "p_user_id" not in section, "读图配额函数不得接受调用方传入的 user_id"
    assert "auth.uid()" in section
    assert section.count("security definer") >= 3


def test_schema_clamps_negative_token_usage():
    """token 增量必须钳到非负：传负数即可把已用用量改小，从而绕过每日上限。"""
    section = _quota_section()
    for field in ("p_prompt", "p_completion", "p_reasoning", "p_total"):
        assert "greatest(coalesce(%s, 0), 0)" % field in section, field


def test_schema_vision_usage_is_read_only_for_clients():
    """计数只能经函数改动，表的直插/直改权限对客户端全部撤销。"""
    section = _quota_section()
    assert "alter table public.vision_usage enable row level security" in section
    assert "revoke insert, update, delete on public.vision_usage" in section
    assert "auth.uid() = user_id" in section


def test_schema_daily_counter_is_occupied_before_the_call():
    """先占后用：begin_vision_call 必须在同一事务里检查并自增次数。"""
    section = _quota_section()
    assert "on conflict (user_id, day) do update" in section
    assert "set calls = public.vision_usage.calls + 1" in section
    assert "for update" in section  # 行锁，防并发穿透


# ============================================================
# 二、数据访问层：服务不可用必须与配额用完区分开
# ============================================================

class _Exec:
    def __init__(self, data):
        self._data = data

    def execute(self):
        return type("_Res", (), {"data": self._data})()


class _FakeClient:
    def __init__(self, data=None, error=None):
        self._data = data
        self._error = error
        self.calls = []

    def rpc(self, name, params=None):
        self.calls.append((name, params))
        if self._error:
            raise self._error
        return _Exec(self._data)


class _patched_db:
    """替换 db.get_supabase / db._user_id，并暴露假客户端以便断言入参。"""

    def __init__(self, data, error=None, uid="u-1"):
        self.client = _FakeClient(data, error)
        self.uid = uid
        self._orig = (db.get_supabase, db._user_id)

    def __enter__(self):
        db.get_supabase = lambda: self.client
        db._user_id = lambda: self.uid
        return self.client

    def __exit__(self, *exc):
        db.get_supabase, db._user_id = self._orig
        return False


def test_get_vision_quota_returns_state_dict():
    with _patched_db({"ok": True, "calls_limit": 5, "calls_used": 2}):
        state = db.get_vision_quota()
    assert state["calls_used"] == 2


def test_vision_rpc_returns_none_when_not_logged_in():
    with _patched_db({"ok": True}, uid=None):
        assert db.get_vision_quota() is None


def test_vision_rpc_returns_none_on_exception():
    """服务不可用返回 None，与「配额用完」区分开，调用方需分别处置。"""
    with _patched_db(None, error=RuntimeError("boom")):
        assert db.begin_vision_call() is None


def test_vision_rpc_returns_none_on_non_ok_payload():
    with _patched_db({"ok": False, "error": "未登录"}):
        assert db.get_vision_quota() is None


def test_vision_rpc_accepts_single_row_wrapped_in_list():
    """某些 supabase-py 版本把单行结果包成列表。"""
    with _patched_db([{"ok": True, "calls_used": 1}]):
        assert db.get_vision_quota()["calls_used"] == 1


def test_record_vision_usage_sends_normalized_int_params():
    with _patched_db({"ok": True}) as client:
        db.record_vision_usage({"prompt": "10", "completion": 20,
                                "reasoning": None, "total": 30})
    name, params = client.calls[-1]
    assert name == "record_vision_usage"
    assert params == {"p_prompt": 10, "p_completion": 20,
                      "p_reasoning": 0, "p_total": 30}


def test_record_vision_usage_tolerates_empty_usage():
    with _patched_db({"ok": True}) as client:
        db.record_vision_usage(None)
    assert client.calls[-1][1] == {"p_prompt": 0, "p_completion": 0,
                                   "p_reasoning": 0, "p_total": 0}


# ============================================================
# 三、页面侧纯函数：故障放行、正常拒绝
# ============================================================

def test_quota_allows_fails_open_with_explicit_notice():
    """配额服务不可用时放行，但必须明确提示。

    静默放行等于绕过配额；而因为一次数据库抖动就把功能整体锁死也不合理。
    """
    allowed, notice = chart_reader.quota_allows(None)
    assert allowed is True
    assert notice and "不可用" in notice


def test_quota_allows_blocks_when_server_says_no():
    allowed, notice = chart_reader.quota_allows(
        {"allowed": False, "message": "今日读图次数已用完（5 次）。"})
    assert allowed is False
    assert "用完" in notice


def test_quota_allows_is_silent_when_allowed():
    allowed, notice = chart_reader.quota_allows({"allowed": True})
    assert allowed is True
    assert notice == ""


def test_quota_budget_prefers_server_value_then_falls_back():
    assert chart_reader.quota_budget({"max_tokens_per_call": 8000}, 20000) == 8000
    assert chart_reader.quota_budget(None, 20000) == 20000
    assert chart_reader.quota_budget({"max_tokens_per_call": "x"}, 20000) == 20000
    assert chart_reader.quota_budget({"max_tokens_per_call": 0}, 20000) == 20000
    assert chart_reader.quota_budget({"max_tokens_per_call": None}, 20000) == 20000


def test_daily_quota_text_and_exhaustion():
    state = {"calls_limit": 5, "calls_used": 5, "calls_remaining": 0,
             "tokens_limit": 100000, "tokens_used": 12345, "tokens_remaining": 87655}
    text = chart_reader.format_daily_quota(state)
    assert "5/5" in text
    assert "12,345" in text
    assert chart_reader.daily_quota_exhausted(state) is True


def test_daily_quota_exhausted_handles_partial_and_missing_state():
    assert chart_reader.daily_quota_exhausted(None) is False
    assert chart_reader.daily_quota_exhausted({"calls_remaining": 1,
                                               "tokens_remaining": 10}) is False
    assert chart_reader.daily_quota_exhausted({"calls_remaining": 1,
                                               "tokens_remaining": 0}) is True
    assert chart_reader.format_daily_quota(None) == ""


# ============================================================
# 四、报告与图片的对应关系（导出不得静默丢图）
# ============================================================

def test_cached_report_images_keeps_only_export_fields():
    """生成成功时把当时那批图固化下来，只留导出需要的三个字段。"""
    cached = chart_reader.cached_report_images([
        {"name": "a.png", "data_bytes": b"AA", "mime": "image/png",
         "orig_kb": 64, "width": 600},
        {"name": "bad.png", "data_bytes": None, "mime": None},
    ])
    assert cached == [{"name": "a.png", "data_bytes": b"AA", "mime": "image/png"}]


def test_cached_report_images_tolerates_empty():
    assert chart_reader.cached_report_images(None) == []
    assert chart_reader.cached_report_images([]) == []


def test_report_images_prefers_generation_time_cache():
    """报告与图片的对应关系在生成那刻就固定了。

    上传区会被任意一次重跑清空（换标签、点别的控件），若导出时读当前上传区，
    docx 会静默丢掉原图，与手册承诺的「导出 Word（含原图）」不符。
    """
    cached = [{"name": "a.png", "data_bytes": b"AA", "mime": "image/png"}]
    assert chart_reader.report_images_for_export(cached, []) == cached
    # 没有缓存（刚上传、还没生成）时退回当前上传区
    assert chart_reader.report_images_for_export(None, cached) == cached
    assert chart_reader.report_images_for_export([], cached) == cached
    assert chart_reader.report_images_for_export(None, None) == []


def test_report_image_cache_is_wired_into_render_and_reset():
    """缓存必须被写入（生成时）、被读取（导出时）、被清理（重置时）。"""
    reader = _read("modules/chart_reader.py")
    assert reader.count("chart_reader_report_images") >= 2
    assert "report_images_for_export" in reader
    app = _read("app.py")
    assert "chart_reader_report_images" in app, "重置键需覆盖报告图片缓存"


if __name__ == "__main__":
    import traceback

    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception:
                failed += 1
                print(f"[FAIL] {name}")
                traceback.print_exc()
            else:
                print(f"[PASS] {name}")
    print(f"\n{'FAILED' if failed else 'ALL PASSED'} ({failed} failures)")
    sys.exit(1 if failed else 0)
