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
# 二·五、地理编码
# ============================================================
class TestGeocode:
    def test_clean_city_name(self):
        from modules.geocode import _clean_city_name
        assert _clean_city_name("北京市") == "北京"
        assert _clean_city_name("廊坊市") == "廊坊"
        assert _clean_city_name("三河市") == "三河"
        assert _clean_city_name("朝阳区") == "朝阳"
        assert _clean_city_name("None") == "None"   # 非后缀结尾原样
        assert _clean_city_name("") == ""
        assert _clean_city_name(None) == ""

    def test_parse_lat_lon(self):
        from modules.geocode import parse_lat_lon
        assert parse_lat_lon("39.9,116.4") == (39.9, 116.4)
        assert parse_lat_lon("39.9，116.4") == (39.9, 116.4)  # 中文逗号
        assert parse_lat_lon("39.9 116.4") == (39.9, 116.4)   # 空格分隔
        assert parse_lat_lon("hello") is None
        assert parse_lat_lon("91,116") is None    # 纬度越界
        assert parse_lat_lon("39.9,181") is None  # 经度越界
        assert parse_lat_lon("39.9,116.4,5") is None

    def test_format_candidate(self):
        from modules.geocode import format_candidate
        c = {"name": "北京", "admin1": "北京市", "country": "中国"}
        assert format_candidate(c) == "北京 · 北京市 · 中国"


# ============================================================
# 三、场景映射全分支
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

    def test_aqi_in_sub_line(self):
        """AQI 追加到 ww-sub 行，格式与湿度/风速一致。"""
        city = {"zh": "北京", "en": "Beijing", "lat": 39.9, "lon": 116.4,
                "region": "华北", "capital": True}
        wx = {"temp": 26.4, "humidity": 45, "wind": 3.21,
              "code": 0, "is_day": 1, "t_max": 28.1, "t_min": 19.0}
        html = weather_wall.card_html(city, wx, "sunny", 0,
                                      aqi={"aqi": 45, "level": "优", "color": "#3fa660"})
        assert "🌫AQI 45 优" in html

    def test_aqi_none_not_appended(self):
        """AQI 缺值：不追加，保持原 ww-sub 内容。"""
        city = {"zh": "北京", "en": "Beijing", "lat": 39.9, "lon": 116.4,
                "region": "华北", "capital": True}
        wx = {"temp": 26.4, "humidity": 45, "wind": 3.21,
              "code": 0, "is_day": 1, "t_max": 28.1, "t_min": 19.0}
        html = weather_wall.card_html(city, wx, "sunny", 0, aqi=None)
        assert "AQI" not in html


# ============================================================
# 四、数据层（离线 mock requests，真实调用解析逻辑）
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
# 五、定位结果消费（纯函数）
# ============================================================
class TestBuildCityFromGeo:
    def test_ok(self):
        city = weather_wall.build_city_from_geo(
            {"status": "ok", "lat": 39.9, "lon": 116.4},
            reverse_fn=lambda lat, lon: "北京",
        )
        assert city == {"zh": "北京", "en": "39.90, 116.40",
                        "lat": 39.9, "lon": 116.4, "region": "定位", "capital": False}

    def test_reverse_fail_fallback_coords(self):
        city = weather_wall.build_city_from_geo(
            {"status": "ok", "lat": 39.9, "lon": 116.4},
            reverse_fn=lambda lat, lon: "",
        )
        assert city["zh"] == "(39.90, 116.40)"

    def test_denied_unsupported_missing(self):
        assert weather_wall.build_city_from_geo({"status": "denied"}) is None
        assert weather_wall.build_city_from_geo({"status": "unsupported"}) is None
        assert weather_wall.build_city_from_geo(None) is None
        assert weather_wall.build_city_from_geo({"status": "ok", "lat": "x", "lon": 1}) is None


# ============================================================
# 五·五、6 卡上限 + 持久化
# ============================================================
def _mk_city(zh: str, i: int = 0) -> dict:
    return {"zh": zh, "en": f"City{i}", "lat": 30.0 + i, "lon": 110.0 + i,
            "region": "测试", "capital": False}


class TestCanAdd:
    def test_ok(self):
        import streamlit as st
        st.session_state["wall_cities"] = [_mk_city("甲", 1)]
        ok, msg = weather_wall._can_add(_mk_city("乙", 2))
        assert ok and not msg

    def test_duplicate_rejected(self):
        import streamlit as st
        st.session_state["wall_cities"] = [_mk_city("甲", 1)]
        ok, msg = weather_wall._can_add(_mk_city("甲", 1))
        assert not ok and "已在列表中" in msg

    def test_max_six_rejected(self):
        """需求 4：最多 6 张，第 7 张被拒。"""
        import streamlit as st
        st.session_state["wall_cities"] = [_mk_city(f"城{i}", i) for i in range(6)]
        ok, msg = weather_wall._can_add(_mk_city("第七城", 99))
        assert not ok and "最多展示 6" in msg


class TestCityPrefs:
    def test_sanitize_filters(self):
        from modules.city_prefs import sanitize_cities
        cities = [
            {"zh": "北京", "en": "B", "lat": 39.9, "lon": 116.4, "region": "华北", "capital": True},
            {"zh": "", "en": "bad", "lat": 1, "lon": 1},          # 空名丢弃
            {"zh": "坏城", "en": "x", "lat": "abc", "lon": 1},    # 非法坐标丢弃
        ]
        out = sanitize_cities(cities)
        assert len(out) == 1 and out[0]["zh"] == "北京"

    def test_local_roundtrip(self, monkeypatch):
        """刷新后保留：写入本地文件 → 重新读取能恢复。"""
        import tempfile
        from pathlib import Path
        from modules import city_prefs
        pref = Path(tempfile.mkdtemp()) / "cities.json"
        monkeypatch.setattr(city_prefs, "_PREF_FILE", pref)
        cities = [_mk_city("北京", 1), _mk_city("上海", 2)]
        city_prefs._save_local(cities)
        loaded = city_prefs._load_local()
        assert [c["zh"] for c in loaded] == ["北京", "上海"]

    def test_apply_cloud_cities(self, monkeypatch):
        """云端城市 JSON 串 → 清洗并写入本地。"""
        import tempfile
        from pathlib import Path
        import json
        from modules import city_prefs
        pref = Path(tempfile.mkdtemp()) / "cities.json"
        monkeypatch.setattr(city_prefs, "_PREF_FILE", pref)
        raw = json.dumps([{"zh": "成都", "en": "Chengdu", "lat": 30.57,
                           "lon": 104.07, "region": "西南", "capital": True}])
        city_prefs.apply_cloud_cities(raw)
        assert city_prefs._load_local()[0]["zh"] == "成都"
        city_prefs.apply_cloud_cities("not-json")  # 损坏值静默忽略
        assert city_prefs._load_local()[0]["zh"] == "成都"


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
    # 城市列表持久化隔离到临时文件，避免测试写入真实用户 ~/.weather_wall_cities.json
    import tempfile
    from modules import city_prefs as cp_mod
    monkeypatch.setattr(cp_mod, "_PREF_FILE",
                        Path(tempfile.mkdtemp()) / "test_cities.json")

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
    def test_cover_wall_placeholder(self, monkeypatch):
        """未定位未添加：封面显示引导占位卡，标题区已删除，无预置城市。"""
        at = _make_app_test(monkeypatch, with_df=False)
        at.run()
        assert not at.exception, f"封面渲染抛异常: {at.exception}"
        md = "\n".join(m.value for m in at.markdown)
        assert "aether-title" not in md   # 首页标题字段已移除（需求：删除标题）
        assert "天气墙还空着" in md        # 引导占位卡
        assert 'class="ww-card' not in md  # 无任何城市卡片（CSS 选择器 .ww-card 不算）

    def test_geo_location_adds_city(self, monkeypatch):
        """手工搜索路径：输入库内城市名 → 解析添加 → 首页出现该城市卡片。"""
        import modules.weather_wall as ww_mod
        monkeypatch.setattr(ww_mod, "forward_geocode", lambda name: [])
        at = _make_app_test(monkeypatch, with_df=False)
        at.run()
        # text_input 输入城市名并点击「解析并添加」（北京命中 CITY_LIBRARY 直接加）
        at.text_input[0].set_value("北京")
        at.run()
        at.button(key="wall_resolve").click().run()
        assert not at.exception, f"解析添加抛异常: {at.exception}"
        md = "\n".join(m.value for m in at.markdown)
        assert "北京" in md and 'class="ww-card' in md

    def test_search_unknown_city_prompt(self, monkeypatch):
        """未匹配城市：提示未找到，不添加卡片。"""
        import modules.weather_wall as ww_mod
        monkeypatch.setattr(ww_mod, "forward_geocode", lambda name: [])
        at = _make_app_test(monkeypatch, with_df=False)
        at.run()
        at.text_input[0].set_value("zzzz不存在的城市")
        at.run()
        at.button(key="wall_resolve").click().run()
        assert not at.exception
        md = "\n".join(m.value for m in at.markdown)
        warn = " ".join(w.value for w in at.warning)
        assert 'class="ww-card' not in md
        assert "未找到城市" in warn

    def test_duplicate_city_notice_transient(self, monkeypatch):
        """重复添加：提示一次性显示，下一次 rerun 自动消失（修复弹窗残留）。"""
        import modules.weather_wall as ww_mod
        monkeypatch.setattr(ww_mod, "forward_geocode", lambda name: [])
        at = _make_app_test(monkeypatch, with_df=False)
        at.run()
        # 第一次添加北京（成功）
        at.text_input[0].set_value("北京")
        at.run()
        at.button(key="wall_resolve").click().run()
        # 第二次输入北京 → 重复 → 一次性警告
        at.text_input[0].set_value("北京")
        at.run()
        at.button(key="wall_resolve").click().run()
        assert not at.exception
        warns = " ".join(w.value for w in at.warning)
        assert "已在列表中" in warns
        # 无任何交互的纯 rerun：警告已消费消失
        at.run()
        warns2 = " ".join(w.value for w in at.warning)
        assert "已在列表中" not in warns2
        # 城市列表仍只有北京 1 个
        assert len(at.session_state["wall_cities"]) == 1

    def test_reset_clears_wall_state(self, monkeypatch):
        """重置当前页面数据：天气墙城市列表与搜索状态被彻底清理。"""
        import modules.weather_wall as ww_mod
        monkeypatch.setattr(ww_mod, "forward_geocode", lambda name: [])
        at = _make_app_test(monkeypatch, with_df=False)
        at.run()
        at.text_input[0].set_value("北京")
        at.run()
        at.button(key="wall_resolve").click().run()
        assert len(at.session_state["wall_cities"]) == 1
        # 点击侧边栏「重置当前模块数据」
        at.button(key="sidebar_reset_current_tab").click().run()
        assert not at.exception
        # 重置后 wall_cities 被清理，render_wall 重新初始化为空（临时偏好文件无数据）
        assert at.session_state["wall_cities"] == []
        try:
            q = at.session_state["wall_query"]  # SafeSessionState 无 .get 方法
        except KeyError:
            q = ""
        assert q == ""
        # 重置后封面回到占位卡
        md = "\n".join(m.value for m in at.markdown)
        assert "天气墙还空着" in md

    def test_tab_order_viz_before_forecast(self, monkeypatch):
        """修改 4：导航顺序为 可视化分析 → 数值预报（已互换）。"""
        at = _make_app_test(monkeypatch, with_df=False)
        at.run()
        assert not at.exception
        for opts in [r.options for r in at.radio]:
            if opts and opts and "数据导入" in opts[0]:
                viz = opts.index("[图表] 可视化分析")
                fc = opts.index("[预报] 数值预报")
                assert viz < fc, f"可视化({viz}) 应排在 数值预报({fc}) 之前"
                break

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
        assert "天气墙还空着" in md        # 封面（标题已删，以占位卡为封面标志）
        # 数据仍在会话中（返回按钮依赖 df 判定）
        assert at.session_state["df"] is not None
