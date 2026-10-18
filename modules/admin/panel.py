"""管理员面板：邀请码、用户列表、配额调整与安全自检。

从 auth.py 拆出（批次 4）。依赖 auth 的客户端工厂与邀请码摘要函数，
因此只能在登录会话建立之后惰性导入。
"""

import hashlib
import secrets
import time
from datetime import datetime, timedelta, timezone

import streamlit as st

import auth
from auth import _hash_invite_code, _schema_error_msg, get_supabase_admin
from modules.supabase_backend import selfcheck_problems
from utils import safe_error_text

_LOG = auth._LOG


_ADMIN_MAX_ATTEMPTS = 5          # 连续失败 5 次锁定


_ADMIN_LOCK_SECONDS = 300        # 锁定 5 分钟


_ADMIN_SESSION_SECONDS = 600     # 解锁后 10 分钟自动失效


_ADMIN_FAILS = 0


_ADMIN_LOCKED_UNTIL = 0.0


def _try_admin_unlock(admin_pw: str, pw: str) -> None:
    """校验管理员密码：常量时间比较 + 全局失败计数 + 锁定退避。"""
    global _ADMIN_FAILS, _ADMIN_LOCKED_UNTIL
    import time as _t

    now = _t.time()
    if now < _ADMIN_LOCKED_UNTIL:
        st.error(f"尝试次数过多，请 {int(_ADMIN_LOCKED_UNTIL - now)} 秒后再试。")
        return

    if pw and secrets.compare_digest(pw.encode("utf-8"), admin_pw.encode("utf-8")):
        _ADMIN_FAILS = 0
        _ADMIN_LOCKED_UNTIL = 0.0
        st.session_state["admin_unlocked"] = True
        st.session_state["admin_unlock_time"] = now
        st.rerun()
        return

    _ADMIN_FAILS += 1
    if _ADMIN_FAILS >= _ADMIN_MAX_ATTEMPTS:
        _ADMIN_LOCKED_UNTIL = now + _ADMIN_LOCK_SECONDS
        _ADMIN_FAILS = 0
        st.error(f"密码错误次数过多，已锁定 {_ADMIN_LOCK_SECONDS // 60} 分钟。")
    else:
        st.error(f"密码错误。剩余尝试 {_ADMIN_MAX_ATTEMPTS - _ADMIN_FAILS} 次。")


def _admin_unlock_expired() -> bool:
    """解锁超过 _ADMIN_SESSION_SECONDS 后自动失效。"""
    import time as _t

    t = st.session_state.get("admin_unlock_time", 0)
    return bool(t) and (_t.time() - t) > _ADMIN_SESSION_SECONDS


def render_admin_panel():
    """折叠式管理员入口：生成邀请码、列出用户、设置配额、查看用量。"""
    admin_pw = str(st.secrets.get("ADMIN_PASSWORD", "")).strip()

    with st.expander("🔧 管理员入口", expanded=False):
        if not admin_pw:
            st.warning(
                "未配置 ADMIN_PASSWORD，管理员功能不可用。"
                "请在 Secrets 中添加 ADMIN_PASSWORD。"
            )
            return

        if not st.session_state.get("admin_unlocked"):
            pw = st.text_input("管理员密码", type="password", key="admin_pw")
            if st.button("解锁", key="admin_unlock_btn"):
                _try_admin_unlock(admin_pw, pw)
            return

        # 安全修复（P-05）：解锁超时自动失效
        if _admin_unlock_expired():
            st.session_state["admin_unlocked"] = False
            st.warning("管理员会话已超时，请重新解锁。")
            return

        sb_admin = get_supabase_admin()
        if sb_admin is None:
            st.warning("未配置 SUPABASE_SERVICE_ROLE_KEY，无法执行管理操作。")
            return

        st.success("已解锁。以下操作仅管理员可见。")

        # --- schema 健康检查 ---
        missing = _missing_tables(sb_admin,
                                  ["invite_codes", "profiles", "datasets",
                                   "gfs_cache", "vision_usage"])
        if missing:
            st.error(
                f"⚠️ 数据库表未创建：{', '.join(missing)}\n\n"
                "请前往 **Supabase 控制台 → SQL Editor**，"
                "粘贴并运行 `sql/schema.sql` 中的全部内容，然后刷新本页面。"
            )
            return

        # --- 安全自检（S1）---
        # 表存在不等于安全边界成立：RLS 可能被关、函数执行权可能被重新授给
        # anon、写权限可能被加回来。自检不通过就停止管理操作，避免在边界已破
        # 的情况下继续改配额或生成邀请码。
        report = _run_security_selfcheck(sb_admin)
        if report is None:
            st.error(
                "⚠️ 无法执行数据库安全自检，已停止管理操作。若刚升级代码，"
                "请先重跑 `sql/schema.sql`，然后刷新本页面。"
            )
            return
        problems = selfcheck_problems(report)
        if problems:
            st.error(
                "⚠️ 数据库安全自检未通过，已停止管理操作：\n\n- "
                + "\n- ".join(problems)
                + "\n\n请重跑 `sql/schema.sql` 或到 Supabase 控制台核对策略。"
            )
            return
        _schema_ver = report.get("schema_version")
        st.caption(
            "✅ 数据库安全自检通过（RLS、函数执行权、写权限）。"
            + (f" schema 版本：{_schema_ver}" if _schema_ver else "")
        )

        # --- 5.1 生成邀请码 ---
        st.subheader("生成邀请码")
        col1, col2 = st.columns([1, 2])
        with col1:
            n = st.number_input("数量", min_value=1, max_value=50, value=5, step=1,
                                key="invite_n")
        with col2:
            if st.button("生成并复制", key="invite_gen"):
                codes = [_gen_code() for _ in range(int(n))]
                try:
                    # 安全修复 R-22：库里只写 SHA-256 摘要，明文仅在内存中展示一次
                    sb_admin.table("invite_codes").insert(
                        [{"code": _hash_invite_code(c)} for c in codes]
                    ).execute()
                    st.session_state["invite_codes_out"] = codes
                    _audit_admin(sb_admin, "invite.generate",
                                 detail={"count": int(n)})
                    st.success("已生成，请复制下方邀请码（仅本次显示，之后无法再查看）。")
                except Exception as e:
                    st.error(_schema_error_msg(e))
        codes_out = st.session_state.get("invite_codes_out")
        if codes_out:
            st.code("\n".join(codes_out), language="text")
            st.caption("将上面任一行发给用户即可授权其注册（每码仅用一次，7 天内有效）。")
        st.caption("邀请码默认 7 天有效；作废后未使用的码立即失效。")
        if st.button("作废全部未使用邀请码", key="invite_revoke"):
            try:
                sb_admin.table("invite_codes").update(
                    {"revoked_at": datetime.now(timezone.utc).isoformat()}
                ).is_("used_by", "null").is_("revoked_at", "null").execute()
                _audit_admin(sb_admin, "invite.revoke_all")
                st.success("已作废全部未使用邀请码。")
            except Exception as e:
                st.error(_schema_error_msg(e))

        st.divider()

        # --- 5.2 列出用户 ---
        st.subheader("用户列表")
        try:
            users = _list_users(sb_admin)
        except Exception as e:
            st.error(safe_error_text(e, "获取用户失败。"))
            users = []
        if not users:
            st.caption("暂无用户或获取失败。")
        if users:
            user_opts = {f"{u['email']} ({u['id'][:8]})": u["id"] for u in users}
            sel = st.selectbox("选择用户", list(user_opts.keys()), key="admin_user_sel")
            uid = user_opts[sel]

            # 用量
            try:
                used = sb_admin.rpc("get_storage_usage", {"p_user_id": uid}).execute()
                quota = sb_admin.rpc("get_storage_quota", {"p_user_id": uid}).execute()
                used_b = int(used.data or 0)
                quota_b = int(quota.data or 10485760)
                st.write(
                    f"存储用量：**{_fmt_mb(used_b)} / {_fmt_mb(quota_b)}**"
                )
            except Exception:
                st.write("用量查询失败。")

            # 调整配额
            new_mb = st.number_input(
                "配额（MB）", min_value=1, max_value=102400,
                value=max(1, int(quota_b / 1048576)), step=1, key="quota_mb"
            )
            if st.button("保存配额", key="quota_save"):
                try:
                    sb_admin.table("profiles").update(
                        {"storage_quota_bytes": int(new_mb) * 1048576}
                    ).eq("user_id", uid).execute()
                    _audit_admin(sb_admin, "quota.storage.update", uid,
                                 {"mb": int(new_mb)})
                    st.success("配额已更新。")
                except Exception as e:
                    st.error(safe_error_text(e, "更新失败。"))

            st.divider()

            # --- 5.3 读图配额（sql/schema.sql 第 9 节）---
            # 读图用的是部署方的 API 密钥，任何用户的每次调用都计费在部署方账上，
            # 因此这三项是成本控制的唯一旋钮。每日次数给 0 即等于停用该用户的读图。
            st.subheader("读图配额（每日）")
            prof_row = {}
            try:
                prof = (
                    sb_admin.table("profiles")
                    .select("vision_calls_per_day,vision_tokens_per_day,"
                            "vision_max_tokens_per_call")
                    .eq("user_id", uid)
                    .execute()
                )
                prof_row = (prof.data or [{}])[0] if prof.data else {}
                today = (datetime.now(timezone(timedelta(hours=8)))).date().isoformat()
                usage_rows = (
                    sb_admin.table("vision_usage")
                    .select("calls,total_tokens")
                    .eq("user_id", uid)
                    .eq("day", today)
                    .execute()
                )
                used_row = (usage_rows.data or [{}])[0] if usage_rows.data else {}
                st.caption(
                    "今日已用 %s / %s 次 · token %s / %s（每日 0 点北京时间重置）"
                    % (used_row.get("calls", 0), prof_row.get("vision_calls_per_day", 5),
                       used_row.get("total_tokens", 0),
                       prof_row.get("vision_tokens_per_day", 100000))
                )
            except Exception:
                st.caption("读图用量查询失败。若刚升级代码，请先重跑 sql/schema.sql。")

            vc1, vc2, vc3 = st.columns(3)
            with vc1:
                calls_day = st.number_input(
                    "每日次数", min_value=0, max_value=200, step=1,
                    value=int(prof_row.get("vision_calls_per_day", 5) or 0),
                    key="vq_calls")
            with vc2:
                tokens_day = st.number_input(
                    "每日 token", min_value=0, max_value=100000000, step=10000,
                    value=int(prof_row.get("vision_tokens_per_day", 100000) or 0),
                    key="vq_tokens")
            with vc3:
                max_call = st.number_input(
                    "单次上限 token", min_value=256, max_value=32000, step=1000,
                    value=int(prof_row.get("vision_max_tokens_per_call", 20000) or 20000),
                    key="vq_maxcall")
            if st.button("保存读图配额", key="vq_save"):
                try:
                    sb_admin.table("profiles").update({
                        "vision_calls_per_day": int(calls_day),
                        "vision_tokens_per_day": int(tokens_day),
                        "vision_max_tokens_per_call": int(max_call),
                    }).eq("user_id", uid).execute()
                    _audit_admin(sb_admin, "quota.vision.update", uid, {
                        "calls": int(calls_day),
                        "tokens": int(tokens_day),
                        "max_call": int(max_call),
                    })
                    st.success("读图配额已更新（对该用户的下一次生成生效）。")
                except Exception as e:
                    st.error(safe_error_text(e, "更新失败。"))


def _audit_admin(sb_admin, action, target_user=None, detail=None):
    """写管理员审计日志；失败只记日志，不影响管理操作。"""
    if sb_admin is None:
        return
    try:
        sb_admin.table("admin_audit_log").insert({
            "action": action,
            "target_user": target_user,
            "detail": detail or {},
        }).execute()
    except Exception:
        _LOG.warning("写管理员审计日志失败 action=%s", action, exc_info=True)


def _gen_code() -> str:
    """生成 128 bit 可读大写邀请码（32 个十六进制字符）。"""
    return secrets.token_hex(16).upper()


def _user_dict(u) -> dict:
    """将 gotrue User 对象或字典统一为字典。"""
    if isinstance(u, dict):
        return u
    if hasattr(u, "model_dump"):
        return u.model_dump()
    if hasattr(u, "to_dict"):
        return u.to_dict()
    return {
        "id": getattr(u, "id", ""),
        "email": getattr(u, "email", ""),
        "created_at": getattr(u, "created_at", ""),
    }


_USERS_PER_PAGE = 100


_USERS_MAX_PAGES = 100  # 硬上限，避免异常分页导致死循环


def _users_from_response(res) -> list:
    """兼容 supabase-py 各版本的 list_users 返回结构。"""
    if hasattr(res, "users"):
        return list(res.users or [])
    if isinstance(res, list):
        return res
    if isinstance(res, dict):
        return list(res.get("users", []) or [])
    return []


def _list_users(sb_admin) -> list:
    """返回用户列表（dict），按页拉全，兼容不支持分页参数的老版本。"""
    users = []
    page = 1
    while page <= _USERS_MAX_PAGES:
        try:
            res = sb_admin.auth.admin.list_users(
                page=page, per_page=_USERS_PER_PAGE)
        except TypeError:
            # 老版本没有分页参数，只能拉一页；避免无限重试。
            res = sb_admin.auth.admin.list_users()
            page = _USERS_MAX_PAGES + 1
        batch = _users_from_response(res)
        users.extend(batch)
        if len(batch) < _USERS_PER_PAGE:
            break
        page += 1
    out = []
    for user in users:
        item = _user_dict(user)
        if item:
            out.append(item)
    return out


def _missing_tables(sb_admin, tables: list) -> list:
    """检查 public 下哪些表不存在（通过试读 limit 0）。"""
    missing = []
    for t in tables:
        try:
            sb_admin.table(t).select("*", count="exact").limit(0).execute()
        except Exception:
            missing.append(t)
    return missing


def _run_security_selfcheck(sb_admin):
    """调用数据库自检函数，返回 dict；函数缺失或调用失败时返回 None。

    旧库没有这个函数时，管理面板会提示重跑 schema.sql，而不是把“查不到”
    误判成“自检通过”。
    """
    if sb_admin is None:
        return None
    try:
        res = sb_admin.rpc("security_selfcheck").execute()
        data = res.data if hasattr(res, "data") else res
        if isinstance(data, list):
            data = data[0] if data else None
        return data if isinstance(data, dict) else None
    except Exception:
        _LOG.warning("安全自检 RPC 调用失败", exc_info=True)
        return None


def _fmt_mb(b: int) -> str:
    return f"{b / 1048576:.2f} MB"
