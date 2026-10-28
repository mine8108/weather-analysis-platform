"""Landmark coverage, geographic identity and safe static-asset delivery."""
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urljoin

from PIL import Image

from modules.city_landmarks import landmark_catalog, landmark_for_city
from modules.ui.weather_component import asset_base, validate_event
from modules.weather_view_model import build_cards, city_id

ROOT = Path(__file__).resolve().parents[1]


def test_requested_41_city_coverage_is_complete_and_unique():
    expected = set("北京 天津 石家庄 太原 呼和浩特 沈阳 长春 哈尔滨 大连 上海 南京 杭州 合肥 福州 济南 南昌 苏州 青岛 厦门 台北 郑州 武汉 长沙 广州 南宁 海口 深圳 三亚 桂林 香港 澳门 重庆 成都 贵阳 昆明 拉萨 西安 兰州 西宁 银川 乌鲁木齐".split())
    catalog = landmark_catalog()
    assert len(catalog) == 41
    assert {item["city"] for item in catalog} == expected
    assert len({item["id"] for item in catalog}) == 41


def test_every_catalog_city_resolves_to_its_own_artwork():
    for item in landmark_catalog():
        result = landmark_for_city({"zh": item["city"], "lat": item["lat"], "lon": item["lon"]})
        assert result == {"id": item["id"], "name": item["landmark"], "asset": item["asset"]}


def test_localized_and_english_names_resolve_without_changing_location():
    cases = [("北京市", 39.9, 116.4, "beijing"), ("Hong Kong, China", 22.32, 114.17, "hong-kong"),
             ("中国香港特别行政区", 22.32, 114.17, "hong-kong"), ("澳門", 22.2, 113.55, "macao"),
             ("臺北市", 25.03, 121.57, "taipei"), ("  Xi’An  ", 34.34, 108.94, "xian")]
    for name, lat, lon, expected in cases:
        assert landmark_for_city({"zh": name, "lat": lat, "lon": lon})["id"] == expected


def test_names_alone_cannot_assign_a_landmark_to_a_different_place():
    assert landmark_for_city({"zh": "北京", "lat": 30, "lon": 110}) is None
    assert landmark_for_city({"zh": "苏州", "lat": 33.64, "lon": 116.98}) is None
    assert landmark_for_city({"zh": "上海中心附近", "lat": 31.23, "lon": 121.47}) is None


def test_unknown_invalid_and_untrusted_names_have_no_asset():
    for city in [None, {}, {"zh": "北京"}, {"zh": "北京", "lat": float("nan"), "lon": 116.4},
                 {"zh": "北京", "lat": 100, "lon": 116.4}, {"zh": "../../.env", "lat": 39.9, "lon": 116.4},
                 {"zh": "廊坊", "lat": 39.96, "lon": 116.79}]:
        assert landmark_for_city(city) is None


def test_city_artwork_is_independent_of_weather_and_missing_values():
    city = {"zh": "杭州", "lat": 30.27, "lon": 120.16}
    for weather in [{}, {city_id(city): {"code": 65, "temp": 20}}, {city_id(city): {"code": 0, "temp": 15, "is_day": 0}}]:
        card = build_cards([city], weather)[0]
        assert card["landmark"]["id"] == "hangzhou"
    assert build_cards([city], {})[0]["temperature"] == "—"


def test_all_runtime_artwork_is_local_transparent_and_within_payload_budget():
    metadata = json.loads((ROOT / "assets/landmarks/manifest.json").read_text(encoding="utf-8"))
    assert not metadata["missing"]
    assert metadata["source_count"] == 41
    by_id = {entry["id"]: entry for entry in metadata["assets"]}
    total = 0
    for item in landmark_catalog():
        path = ROOT / "static/weather/landmarks" / item["asset"]
        assert path.parent == ROOT / "static/weather/landmarks"
        data = path.read_bytes()
        assert hashlib.sha256(data).hexdigest() == by_id[item["id"]]["sha256"]
        assert len(data) <= 200_000
        total += len(data)
        with Image.open(path) as image:
            assert image.format == "WEBP" and image.mode == "RGBA"
            assert image.width <= 1024 and image.height <= 448
            assert image.getchannel("A").getextrema() == (0, 255)
    assert total <= 5_000_000


def test_forecast_confirmation_uses_server_landmark_metadata():
    city = {"zh": "上海", "lat": 31.23, "lon": 121.47}
    cards = build_cards([city], {})
    event = validate_event({"type": "confirm", "event_id": "test", "city_id": city_id(city), "days": 7,
                            "landmark": {"asset": "../../secrets.toml"}}, cards)
    assert event["city"]["landmark"]["asset"] == "shanghai.webp"


def test_asset_urls_preserve_hosted_iframe_and_explicit_base_paths():
    import re
    from modules.ui.shell import inject_workbench_style

    with patch("modules.ui.weather_component.st.get_option", return_value=""):
        assert urljoin("https://example.test/~/+/forecast", asset_base() + "/landmarks/beijing.webp") == "https://example.test/~/+/app/static/weather/landmarks/beijing.webp"
        assert urljoin("http://127.0.0.1:8502/forecast", asset_base()) == "http://127.0.0.1:8502/app/static/weather"
        with patch("modules.ui.shell.st.html") as render:
            inject_workbench_style()
            font = re.search(r"src:url\('([^']+)'\)", render.call_args.args[0]).group(1)
            assert urljoin("https://example.test/~/+/forecast", font).startswith("https://example.test/~/+/static/media/")
    with patch("modules.ui.weather_component.st.get_option", return_value="workbench"):
        assert asset_base() == "/workbench/app/static/weather"
        with patch("modules.ui.shell.st.html") as render:
            inject_workbench_style()
            font = re.search(r"src:url\('([^']+)'\)", render.call_args.args[0]).group(1)
            assert font.startswith("/workbench/static/media/")
