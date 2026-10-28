"""2026-10-23 审查案例，期望值来自量纲、时间与业务契约。"""
import io
from datetime import datetime, timezone
from types import SimpleNamespace
import zipfile

import pandas as pd
import pytest

from modules import analyzer, data_loader, dataset, codec, aqi, analysis_service
from modules.nwp.calc import _analyze_forecast
from utils import df_fingerprint


def observations(n=24):
    return pd.DataFrame({"timestamp": pd.date_range("2026-07-01", periods=n, freq="h"),
                         "temperature": [25.] * n, "humidity": [60.] * n,
                         "precipitation": [0.] * n, "wind_speed": [2.] * n})


@pytest.mark.parametrize("unit,wind", [("km/h", 36), ("m/s", 10)])
def test_historical_api_normalizes_units(monkeypatch, unit, wind):
    captured = {}
    hourly = {"time": ["2026-07-01T00:00"], "temperature_2m": [25],
              "relative_humidity_2m": [60], "surface_pressure": [1000],
              "wind_speed_10m": [wind], "wind_direction_10m": [90],
              "cloud_cover": [80], "precipitation": [0], "weather_code": [3]}
    def get(url, **kwargs):
        captured.update(kwargs["params"])
        return SimpleNamespace(raise_for_status=lambda: None, headers={},
            json=lambda: {"hourly": hourly, "hourly_units": {"wind_speed_10m": unit, "cloud_cover": "%"}})
    monkeypatch.setattr("requests.get", get)
    monkeypatch.setattr(data_loader, "take_outbound", lambda: (True, ""))
    frame, err = data_loader.fetch_open_meteo.__wrapped__(30, 115, "2026-07-01", "2026-07-01")
    assert err is None and captured["wind_speed_unit"] == "ms"
    assert frame.wind_speed.iloc[0] == 10 and frame.cloud_cover.iloc[0] == 8


def test_rain_windows_do_not_mix_stations_days_or_gaps():
    multi = pd.DataFrame({"timestamp": pd.to_datetime(["2026-07-01 12:00"] * 3),
                          "station_id": ["A", "B", "C"], "precipitation": [40.] * 3})
    assert analyzer.check_rainstorm(multi) == []
    daily = multi.assign(station_id="A", timestamp=pd.date_range("2026-07-01", periods=3, freq="D"))
    assert analyzer.check_rainstorm(daily) == []
    hourly = multi.assign(station_id="A", timestamp=pd.date_range("2026-07-01", periods=3, freq="h"))
    assert analyzer.check_rainstorm(hourly)[0]["level"] == "红色"
    assert analyzer.check_rainstorm(hourly.iloc[[0, 2]]) == []
    assert analyzer.check_rainstorm(pd.concat([hourly, hourly.iloc[[1]]])) == []
    shuffled = hourly.iloc[::-1]
    assert analyzer.check_rainstorm(shuffled) == analyzer.check_rainstorm(hourly)


def test_nonconsecutive_days_do_not_form_heat_streak():
    df = pd.concat([observations(8).assign(temperature=35, timestamp=pd.date_range(d, periods=8, freq="h"))
                    for d in ("2026-07-01", "2026-07-03", "2026-07-05")])
    assert analyzer.check_high_temperature(df) == []


def test_analysis_cache_changes_with_middle_row_and_threshold(monkeypatch):
    df = observations()
    hot = df.copy()
    hot.loc[12, "temperature"] = 41
    assert df_fingerprint(df) != df_fingerprint(hot)
    state = {}
    analysis_service.ensure_analysis(state, df)
    assert state["warnings_list"] == []
    state["report_data"] = b"obsolete"
    analysis_service.ensure_analysis(state, hot)
    assert any(w["level"] == "红色" for w in state["warnings_list"])
    assert "report_data" not in state
    monkeypatch.setattr(analyzer, "current_thresholds", lambda: {"high_temp": {"红色": 50, "橙色": 49}})
    analysis_service.ensure_analysis(state, hot)
    assert state["warnings_list"] == []


def test_forecast_rain_uses_short_windows_including_midnight():
    slow = observations().assign(precipitation=5)
    assert not any(w["level"] == "红色" and w["type"] == "暴雨" for w in _analyze_forecast(slow)["warnings"])
    peak = observations(48)
    peak.loc[23:25, "precipitation"] = 40
    warnings = _analyze_forecast(peak)["warnings"]
    assert any(w["level"] == "红色" and "3h" in w["detail"] for w in warnings)
    assert not any(w["type"] == "暴雨" for w in _analyze_forecast(peak.drop(index=24))["warnings"])


def test_forecast_red_wind_matches_observations():
    df = observations().assign(wind_speed=35)
    assert analyzer.check_gale(df)[0]["level"] == "红色"
    assert any(w["type"] == "大风" and w["level"] == "红色" for w in _analyze_forecast(df)["warnings"])


def test_invalid_numbers_are_not_high_quality_or_safe():
    result = analysis_service.analyze_observations(observations().assign(temperature="bad"))
    assert result["score"] < 100
    assert result["status"] == "partial"
    assert any("有限数值" in n for n in result["notes"])
    assert analysis_service.analyze_observations(pd.DataFrame({"temperature": [41] * 24}))["status"] == "unavailable"


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "gbk", "gb18030"])
def test_csv_encodings_preserve_fields_and_station_ids(encoding):
    content = "站号,时间,气温\n001,2026-07-01 00:00,30\n01,2026-07-01 01:00,31\n".encode(encoding)
    df = dataset.canonicalize(data_loader._read_csv_content(content))
    assert "temperature" in df and df.station_id.tolist() == ["001", "01"]
    assert dataset.from_text(dataset.to_text(df)).df.station_id.tolist() == ["001", "01"]


@pytest.mark.parametrize("day", [28, 29, 30, 31])
def test_month_end_is_not_clamped(day):
    ref = datetime(2026, 10, 23, tzinfo=timezone.utc)
    metar, _ = codec.decode_metar(f"METAR ZBAA {day:02d}1200Z 09005MPS 9999 25/10 Q1013", ref)
    synop, _ = codec.decode_synop(f"AAXX {day:02d}121 54511 11298 80905 10250", ref)
    assert metar["timestamp"].day == synop["timestamp"].day == day
    assert synop["timestamp"].tzinfo == timezone.utc


def test_report_timestamp_handles_leap_year_and_month_rollover():
    assert codec._report_time(29, 12, reference_time=datetime(2024, 3, 1)).date().isoformat() == "2024-02-29"
    assert codec._report_time(31, 23, reference_time=datetime(2026, 11, 1)).date().isoformat() == "2026-10-31"
    with pytest.raises(ValueError):
        codec._report_time(32, 12)


def test_utc_report_and_local_observations_share_one_time_axis():
    report, _ = codec.decode_metar("METAR ZBAA 231200Z 09005MPS 9999 25/10 Q1013",
                                  datetime(2026, 10, 23, tzinfo=timezone.utc))
    df = dataset.canonicalize(pd.DataFrame({"timestamp": ["2026-10-23 19:00", report["timestamp"]]}))
    assert df.timestamp.tolist() == [pd.Timestamp("2026-10-23 19:00"), pd.Timestamp("2026-10-23 20:00")]
    pd.testing.assert_frame_equal(dataset.from_text(dataset.to_text(df)).df, df)
    aware = dataset.canonicalize(pd.DataFrame({"timestamp": [report["timestamp"]]}))
    assert aware.timestamp.iloc[0] == pd.Timestamp("2026-10-23 20:00")


def test_manual_merge_normalizes_time_before_sorting_and_deduplication():
    local = pd.DataFrame({"station_id": ["001"], "timestamp": [pd.Timestamp("2026-10-23 20:00")], "temperature": [20]})
    utc = local.assign(timestamp=datetime(2026, 10, 23, 12, tzinfo=timezone.utc), temperature=25)
    merged = data_loader.merge_manual_rows(local, utc)
    assert len(merged) == 1 and merged.temperature.iloc[0] == 25
    assert merged.timestamp.iloc[0] == pd.Timestamp("2026-10-23 20:00")
    pd.testing.assert_frame_equal(data_loader.merge_manual_rows(merged, utc), merged)


@pytest.mark.parametrize("reported", [{}, {"prompt_tokens": 10}, {"total_tokens": "bad"}, {"total_tokens": -1}])
def test_malformed_provider_usage_remains_unknown(monkeypatch, reported):
    from modules import ai_narrative
    monkeypatch.setattr(ai_narrative.requests, "post", lambda *a, **kw: SimpleNamespace(
        status_code=200, headers={}, raise_for_status=lambda: None,
        json=lambda: {"choices": [{"message": {"content": "解读"}}], "usage": reported}))
    usage = {}
    assert ai_narrative.call_vision_llm("p", [], "test", model="test", max_tokens=100, usage_out=usage) == "解读"
    assert usage == {}


@pytest.mark.parametrize("quota", [None, {"allowed": True, "tokens_remaining": 80000}])
def test_generate_never_calls_provider_without_reservation(monkeypatch, quota):
    import db
    from modules import chart_reader, ai_narrative
    monkeypatch.setattr(chart_reader, "st", SimpleNamespace(session_state={}, error=lambda *a: None))
    monkeypatch.setattr(db, "begin_vision_call", lambda: quota)
    def unexpected(*a, **kw):
        raise AssertionError("No provider call without a reservation")
    monkeypatch.setattr(ai_narrative, "call_vision_llm", unexpected)
    chart_reader._generate({}, [], "")


@pytest.mark.parametrize("outcome", ["success", "timeout", "empty"])
def test_generate_bounds_request_and_settles_success_and_failure(monkeypatch, outcome):
    import db
    import requests
    from contextlib import nullcontext
    from modules import chart_reader, ai_narrative
    state, requests_sent, settlements = {}, [], []
    monkeypatch.setattr(chart_reader, "st", SimpleNamespace(session_state=state,
        error=lambda *a: None, caption=lambda *a: None, spinner=lambda *a: nullcontext()))
    monkeypatch.setattr(db, "begin_vision_call", lambda: {
        "allowed": True, "call_id": "test-call", "reserved_tokens": 80000})
    def settle(usage, call_id):
        settlements.append((dict(usage), call_id))
        return True
    monkeypatch.setattr(db, "record_vision_usage", settle)
    def post(url, **kwargs):
        requests_sent.append(kwargs["json"])
        if outcome == "timeout":
            raise requests.Timeout("test timeout")
        return SimpleNamespace(status_code=200, headers={}, raise_for_status=lambda: None,
            json=lambda: {"choices": [{"message": {"content": "正文" if outcome == "success" else ""},
                                       "finish_reason": "stop" if outcome == "success" else "length"}],
                          "usage": {"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200}})
    monkeypatch.setattr(ai_narrative.requests, "post", post)
    images = [{"name": "test.png", "ok": True, "data_bytes": b"test", "mime": "image/png",
               "width": 300, "height": 300}]
    chart_reader._generate({"api_key": "test", "base_url": "https://example.invalid/v1", "model": "test"}, images, "")
    assert len(requests_sent) == len(settlements) == 1
    assert 0 < requests_sent[0]["max_tokens"] < 78000
    assert settlements[0][1] == "test-call"
    assert settlements[0][0] == ({} if outcome == "timeout" else {"prompt": 100, "completion": 100, "reasoning": 0, "total": 200})
    assert state["chart_reader_gen_count"] == 1
    if outcome == "success":
        assert state["chart_reader_text"] == "正文"
        assert state["chart_reader_report_images"][0]["data_bytes"] == b"test"
    else:
        assert "chart_reader_text" not in state


@pytest.mark.parametrize("vv,expected", [("00", .05), ("01", .1), ("50", 5), ("60", 10), ("80", 30), ("89", 75), ("98", 20), ("//", None)])
def test_synop_full_visibility_code(vv, expected):
    result, _ = codec.decode_synop(f"AAXX 23121 54511 112{vv} 80905 10250")
    assert result.get("visibility") == expected


@pytest.mark.parametrize("pollutant,points", [("o3", [(400,200),(800,300),(1000,400),(1200,500)]),
                                               ("no2", [(1200,200),(2340,300),(3090,400),(3840,500)])])
def test_aqi_high_concentration_breakpoints(pollutant, points):
    for concentration, expected in points:
        assert aqi.comprehensive_aqi({pollutant: concentration})["aqi"] == expected


def test_direct_report_export_includes_warnings_and_invalidates_when_data_changes(monkeypatch):
    import auth
    import db
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    monkeypatch.setattr(auth, "ensure_session", lambda: None)
    monkeypatch.setattr(db, "get_storage_usage_bytes", lambda *a, **kw: 0)
    monkeypatch.setattr(db, "get_storage_quota_bytes", lambda *a, **kw: 10485760)
    monkeypatch.setattr(db, "list_datasets_result", lambda *a, **kw: ([], None))
    monkeypatch.setattr(db, "list_datasets", lambda *a, **kw: [])
    def offline(*args, **kwargs):
        raise AssertionError("Regression test must stay offline")
    monkeypatch.setattr("requests.get", offline)
    monkeypatch.setattr("requests.post", offline)
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=60)
    at.secrets["ADMIN_PASSWORD"] = "test-only"
    at.session_state["auth_user"] = {"id": "review-user", "email": "test@example.invalid"}
    at.session_state["_wall_show"] = False
    at.session_state["dark_mode"] = False
    hot = observations()
    hot.loc[12, "temperature"] = 41
    at.session_state["df"] = hot
    at.session_state["source"] = "synthetic"
    at.session_state["_route_request"] = 4
    at.run()
    assert not at.exception
    at.button(key="gen_report").click().run()
    assert not at.exception
    with zipfile.ZipFile(io.BytesIO(at.session_state["report_data"])) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    assert "最高气温达 41.0" in xml
    assert "观测分析范围与数据限制" in xml
    at.session_state["df"] = observations()
    at.run()
    assert not at.exception and at.session_state["warnings_list"] == []
    assert "report_data" not in at.session_state
    # 核验 Streamlit/Pillow 升级后，既有六个入口仍能渲染。
    for tab_id in (0, 1, 2, 3, 5):
        at.session_state["active_tab"] = tab_id
        at.run()
        assert not at.exception, (tab_id, at.exception)
        assert not at.error, (tab_id, at.error)
