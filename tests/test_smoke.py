"""weather_app 冒烟测试：防回归。

- test_app_boots: 用 Streamlit AppTest 真实启动 app.py，断言无未捕获异常
  （验证顶层错误边界、导入链路、tab 分发在默认会话下可跑通）。
- test_modules_import: 确认各业务模块可被 import（顶层无 import 崩溃）。
"""
import importlib
import os

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_app_boots_without_exception():
    from streamlit.testing.v1 import AppTest

    # 注入测试用假密钥：app 启动即渲染登录 UI 并读取 ADMIN_PASSWORD，
    # Supabase 密钥为懒加载（登录时才用），一并注入以防回归。
    at = AppTest.from_file(os.path.join(APP_DIR, "app.py"), default_timeout=60)
    at.secrets["ADMIN_PASSWORD"] = "test-admin"
    at.secrets["SUPABASE_URL"] = "https://example.supabase.co"
    at.secrets["SUPABASE_ANON_KEY"] = "test-anon-key"
    at.secrets["SUPABASE_SERVICE_ROLE_KEY"] = "test-service-key"
    at.run()
    assert not at.exception, f"app.py 启动抛异常: {at.exception}"


def test_modules_import():
    modules = [
        "utils",
        "config",
        "auth",
        "db",
        "modules.data_loader",
        "modules.data_quality",
        "modules.visualizer",
        "modules.analyzer",
        "modules.codec",
        "modules.reporter",
        "modules.nwp_forecast",
    ]
    for name in modules:
        importlib.import_module(name)
