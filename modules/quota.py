"""出站请求配额的轻量封装（SEC-02）。

背景：本应用所有用户共享部署方的一个出口 IP，Open-Meteo 免费层配额按来源
共享。旧实现里，任意登录用户只要反复改 0.01° 坐标触发 rerun，就能把全站
日配额打光。服务端配额由 ``begin_outbound_call()`` 在数据库内原子占用，
本模块只负责把「服务不可用」与「额度用完」翻译成调用方好处理的结果。

约定：
- 返回 ``(True, "")``：放行（含配额服务不可用的降级路径）。
- 返回 ``(False, message)``：今日额度用完，调用方必须直接拒绝发起请求。
"""


def take_outbound():
    """占用一次外部请求额度，返回 (allowed, message)。"""
    try:
        from db import begin_outbound_call

        state = begin_outbound_call()
    except Exception:
        return True, ""
    if not state:
        # 配额服务不可用：不让一次数据库抖动把功能整体锁死；
        # 但也不会给出「无限」——服务恢复后立刻重新受控。
        return True, ""
    if state.get("allowed"):
        return True, ""
    return False, str(
        state.get("message")
        or "今日外部数据请求次数已用完，次日 0 点重置。"
    )
