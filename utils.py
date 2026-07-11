"""工具模块：DataFrame 指纹、API 重试、预加载缓存"""

import functools
import hashlib
import time
import streamlit as st
import pandas as pd


# ============================================================
# 一、DataFrame 指纹
# ============================================================

def df_fingerprint(df):
    """计算 DataFrame 轻量指纹（行数+列名+首尾3行 MD5）"""
    if df is None or df.empty:
        return "empty"
    head_tail = pd.concat([df.head(3), df.tail(3)])
    raw = f"{len(df)}_{','.join(df.columns)}_{head_tail.to_csv(index=False)}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def tab_fingerprint_match(tab_name, df):
    """检查 Tab 的 DataFrame 是否与上次相同（用于避免重复渲染）"""
    fp = df_fingerprint(df)
    key = f"_tab_fp_{tab_name}"
    last = st.session_state.get(key, "")
    if last == fp:
        return False  # 相同，不需要重绘
    st.session_state[key] = fp
    return True  # 不同，需要重绘


# ============================================================
# 二、API 重试 + 降级
# ============================================================

def retry_with_backoff(max_retries=3, base_delay=2, backoff_factor=2):
    """带指数退避的重试装饰器"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt < max_retries:
                        delay = base_delay * (backoff_factor ** (attempt - 1))
                        st.warning(
                            f"请求失败（{attempt}/{max_retries}），{delay}s 后重试… "
                            f"({str(e)[:80]})"
                        )
                        time.sleep(delay)
                    else:
                        st.error(
                            f"请求失败，已达最大重试（{max_retries} 次）: "
                            f"{str(e)[:200]}"
                        )
            # 全部重试失败，降级
            cache_key = f"_api_cache_{func.__name__}"
            cached = st.session_state.get(cache_key)
            if cached is not None:
                st.warning("请求失败，使用上次缓存数据（可能过期）。")
                return cached
            return None, f"API 不可用: {str(last_error)[:200]}"
        return wrapper
    return decorator
