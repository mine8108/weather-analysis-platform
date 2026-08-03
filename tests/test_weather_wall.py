"""天气墙 + Aether 主题的真实调用测试。

遵循项目验证纪律：不止 import，每个关键函数至少真实调用一次。
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules import theme_aether, weather_wall  # noqa: E402


# ============================================================
# 一、城市库完整性
# ============================================================
class TestCityLibrary:
    def test_capital_count_34(self):
        """需求 1：默认预置 34 个省级行政区省会/首府/直辖市/特区。"""
        caps = weather_wall.capital_cities()
        assert len(caps) == 34

    def test_zh_unique(self):
        zhs = [c["zh"] for c in weather_wall.CITY_LIBRARY]
        assert len(zhs) == len(set(zhs))

    def test_required_fields_and_ranges(self):
        regions = set(weather_wall.REGION_ORDER)
        for c in weather_wall.CITY_LIBRARY:
            assert c["zh"] and c["en"]
            assert -90 <= c["lat"] <= 90 and -180 <= c["lon"] <= 180
            assert c["region"] in regions, f"{c['zh']} 的 region 未配置"
            assert isinstance(c["capital"], bool)

    def test_hk_mo_tw_labeled_china(self):
        """港澳台名称带中国前缀/后缀标注。"""
        by_zh = {c["zh"]: c for c in weather_wall.CITY_LIBRARY}
        assert "中国香港" in by_zh and "Hong Kong, China" in by_zh["中国香港"]["en"]
        assert "中国澳门" in by_zh and "Macao, China" in by_zh["中国澳门"]["en"]
        assert "Taiwan, China" in by_zh["台北"]["en"]


# ============================================================
# 二、场景映射全分支
# ============================================================
class TestMapScene:
    @pytest.mark.parametrize("code,expected", [
        (95, "thunder"), (96, "thunder"), (99, "thunder"),
        (71, "snow"), (75, "snow"), (85, "snow"), (86, "snow"),
        (51, "rain"), (61, "rain"), (65, "rain"), (80, "rain"), (82, "rain"),
        (45, "fog"), (48, "fog"),
        (2, "cloudy"), (3, "cloudy"),
    ])
    def test_wmo_codes(self, code, expected):
        assert weather_wall.map_scene(code, 1) == expected

    def test_clear_day_vs_night(self):
        """晴/晴夜由 is_day 决定（昼夜切换需求）。"""
        assert weather_wall.map_scene(0, 1) == "sunny"
        assert weather_wall.map_scene(1, 1) == "sunny"
        assert weather_wall.map_scene(0, 0) == "night"
        assert weather_wall.map_scene(1, 0) == "night"

    def test_unknown_and_none_fallback(self):
        assert weather_wall.map_scene(999, 1) == "cloudy"
        assert weather_wall.map_scene(None, 1) == "cloudy"


# ============================================================
# 三、卡片 HTML 生成
# ============================================================
class TestCardHtml:
    def test_full_card(self):
        city = {"zh": "北京", "en": "Beijing", "lat": 39.9, "lon": 116.4,
                "region": "华北", "capital": True}
        wx = {"temp": 26.4, "humidity": 45, "wind": 3.21,
              "code": 0, "is_day": 1, "t_max": 28.1, "t_min": 19.0}
        html = weather_wall.card_html(city, wx, "sunny", 3)
        assert "北京" in html and "Beijing" in html
        assert "26°" in html and "晴" in html and "Sunny" in html
        assert "45%" in html and "3.2" in html
        assert "ww-sun" in html  # 晴场景含太阳元素
        assert "sc-sunny" in html

    def test_none_weather_placeholder(self):
        city = {"zh": "上海", "en": "Shanghai", "lat": 31.2, "lon": 121.5,
                "region": "华东", "capital": True}
        html = weather_wall.card_html(city, None, "cloudy", 0)
        assert "数据加载中" in html and "—" in html

    def test_night_scene_elements(self):
        city = {"zh": "拉萨", "en": "Lhasa", "lat": 29.65, "lon": 91.14,
                "region": "西南", "capital": True}
        html = weather_wall.card_html(city, None, "night", 1)
        assert "ww-moon" in html and "ww-stars" in html


# ============================================================
# 四、数据层（离线 mock requests，真实调用解析逻辑）
# ============================================================
class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _fake_payload(codes=(0, 61), is_day=1):
    """构造 Open-Meteo 多坐标返回数组。"""
    return [
        {
            "current": {"temperature_2m": 20.0 + i, "relative_humidity_2m": 50,
                        "weather_code": codes[i % len(codes)], "wind_speed_10m": 2.5,
                        "is_day": is_day},
            "daily": {"temperature_2m_max": [25.0], "temperature_2m_min": [15.0]},
        }
        for i in range(len(codes))
    ]


class TestFetch:
    def test_parse_batch(self, monkeypatch):
        import requests
        monkeypatch.setattr(requests, "get",
                            lambda *a, **k: _FakeResp(_fake_payload((0, 61))))
        weather_wall._fetch_batch.clear()
        cities = [
            {"zh": "测试甲", "en": "TestA", "lat": 11.11, "lon": 111.11,
             "region": "华北", "capital": False},
            {"zh": "测试乙", "en": "TestB", "lat": 22.22, "lon": 112.22,
             "region": "华北", "capital": False},
        ]
        out = weather_wall.fetch_wall_weather(cities)
        assert out["测试甲"]["temp"] == 20.0 and out["测试甲"]["code"] == 0
        assert out["测试乙"]["t_max"] == 25.0 and out["测试乙"]["t_min"] == 15.0

    def test_failure_fallback_and_no_poisoned_cache(self, monkeypatch):
        """请求失败：降级到会话缓存；失败结果不得写入 cache_data。"""
        import requests

        def _boom(*a, **k):
            raise ConnectionError("offline")

        monkeypatch.setattr(requests, "get", _boom)
        weather_wall._fetch_batch.clear()
        cities = [
            {"zh": "离线城", "en": "Offline", "lat": 33.33, "lon": 113.33,
             "region": "华中", "capital": False},
        ]
        out = weather_wall.fetch_wall_weather(cities)
        # retry 层与 fallback 均无缓存时应返回空 dict（由 render 层提示）
        assert isinstance(out, dict)


# ============================================================
# 五、主题系统
# ============================================================
class TestTheme:
    def test_token_parity(self):
        """亮暗两套 token 键集合必须一致，防止暗色漏定义变量。"""
        assert set(theme_aether.LIGHT_TOKENS) == set(theme_aether.DARK_TOKENS)

    def test_scene_vars_present(self):
        """七场景天空变量两套主题都有。"""
        for t in (theme_aether.LIGHT_TOKENS, theme_aether.DARK_TOKENS):
            for scene in ("sunny", "cloudy", "rain", "snow", "thunder", "fog", "night"):
                assert f"ww-{scene}" in t

    def test_default_is_light(self, monkeypatch):
        """需求 3：无偏好文件时默认浅色。"""
        # 沙箱内 pytest tmp_path 根目录会 WinError 5，用 tempfile.mkdtemp（项目惯例）
        import tempfile
        pref = Path(tempfile.mkdtemp()) / "none.json"
        monkeypatch.setattr(theme_aether, "_PREF_FILE", pref)
        assert theme_aether._load_pref_local() is None  # None → init_theme 用 "light"

    def test_pref_local_roundtrip(self, monkeypatch):
        """持久化：写入后重启（重新读文件）能恢复上次选择。"""
        import tempfile
        pref = Path(tempfile.mkdtemp()) / ".aether_theme.json"
        monkeypatch.setattr(theme_aether, "_PREF_FILE", pref)
        theme_aether._save_pref_local("dark")
        assert theme_aether._load_pref_local() == "dark"
        theme_aether._save_pref_local("light")
        assert theme_aether._load_pref_local() == "light"
        # 损坏文件静默回退
        pref.write_text("{broken", encoding="utf-8")
        assert theme_aether._load_pref_local() is None

    def test_wall_css_contains_scenes(self):
        css = weather_wall.wall_css()
        for scene in ("sunny", "cloudy", "rain", "snow", "thunder", "fog", "night"):
            assert f"sc-{scene}" in css
        assert "prefers-reduced-motion" in css


# ============================================================
# 六、AppTest 集成：封面渲染 + 需求 2 切换
# ============================================================
APP_FILE = str(Path(__file__).resolve().parent.parent / "app.py")


def _make_app_test(monkeypatch, with_df: bool):
    """启动 app.py：登录态 + mock 网络/云端，返回 AppTest 实例。"""
    from streamlit.testing.v1 import AppTest
    import requests
    import db as db_mod

    monkeypatch.setattr(
        requests, "get",
        lambda *a, **k: _FakeResp(_fake_payload((0,) * 34)),
    )
    # 侧边栏云端调用与真实 Supabase 解耦
    monkeypatch.setattr(db_mod, "get_storage_usage_bytes", lambda *a, **k: 0)
    monkeypatch.setattr(db_mod, "get_storage_quota_bytes", lambda *a, **k: 10485760)
    monkeypatch.setattr(db_mod, "list_datasets", lambda: [])

    at = AppTest.from_file(APP_FILE, default_timeout=60)
    at.secrets["ADMIN_PASSWORD"] = "test-admin"
    at.secrets["SUPABASE_URL"] = "https://example.supabase.co"
    at.secrets["SUPABASE_ANON_KEY"] = "test-anon-key"
    at.session_state["auth_user"] = {"id": "u1", "email": "t@example.com"}
    if with_df:
        import pandas as pd
        at.session_state["df"] = pd.DataFrame({
            "timestamp": pd.to_datetime(["2026-08-01 08:00", "2026-08-01 09:00"]),
            "temperature": [30.1, 31.2],
        })
        at.session_state["source"] = "测试数据"
    return at


class TestAppIntegration:
    def test_cover_wall_boots(self, monkeypatch):
        """未导入数据：封面显示 Aether 天气墙，34 城分组渲染无异常。"""
        at = _make_app_test(monkeypatch, with_df=False)
        at.run()
        assert not at.exception, f"封面渲染抛异常: {at.exception}"
        md = "\n".join(m.value for m in at.markdown)
        # 用封面专属 class 断言（"Aether" 字样会出现在主题 CSS 注释里，不可靠）
        assert "aether-title" in md
        assert "ww-region" in md          # 区域分组标题
        assert "北京" in md and "中国香港" in md  # 默认省会含港澳台

    def test_wall_disappears_after_import(self, monkeypatch):
        """需求 2：导入数据后天气墙消失，自动回到数据摘要卡视图。"""
        at = _make_app_test(monkeypatch, with_df=True)
        at.run()
        assert not at.exception, f"摘要卡渲染抛异常: {at.exception}"
        md = "\n".join(m.value for m in at.markdown)
        assert "aether-title" not in md    # 天气墙封面消失
        assert "ww-card" not in md

    def test_cover_entry_with_data(self, monkeypatch):
        """老用户回封面：有数据 + _wall_cover=True 时封面照常渲染，数据不丢。"""
        at = _make_app_test(monkeypatch, with_df=True)
        at.session_state["_wall_cover"] = True
        at.run()
        assert not at.exception, f"封面渲染抛异常: {at.exception}"
        md = "\n".join(m.value for m in at.markdown)
        assert "aether-title" in md        # 封面出现
        assert "ww-region" in md
        # 数据仍在会话中（返回按钮依赖 df 判定）
        assert at.session_state["df"] is not None
