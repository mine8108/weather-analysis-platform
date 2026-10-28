"""Adversarial checks for city identity, request/result isolation and plot semantics."""
import numpy as np
import pandas as pd
import pytest

from modules.forecast_context import make_intent, queue_intent, consume_intent, commit_success, fail_request, restore_previous
from modules.nwp.presentation import precipitation_windows, forecast_summary, forecast_figure
from modules.ui.weather_component import validate_event
from modules.weather_view_model import build_cards, city_id, weather_scene
from modules.app_state import reset_tab, TAB_IMPORT, TAB_CHART, TAB_FORECAST


def frame(n=24):
    return pd.DataFrame({"timestamp": pd.date_range("2026-10-26 01:00", periods=n, freq="h"),
                         "temperature": np.arange(n, dtype=float), "precipitation": np.ones(n),
                         "wind_speed": np.ones(n), "station_id": "fixture"})


def test_same_name_cities_never_share_weather():
    a = {"zh": "同名城", "lat": 28.68, "lon": 115.86}
    b = {"zh": "同名城", "lat": 30.57, "lon": 104.07}
    assert city_id(a) != city_id(b)
    cards = build_cards([a, b], {city_id(a): {"temp": 20, "code": 3}, city_id(b): {"temp": 25, "code": 65}})
    assert [c["temperature"] for c in cards] == ["20°", "25°"]
    assert [c["condition"] for c in cards] == ["阴", "大雨"]
    assert build_cards([a], {})[0]["temperature"] == "—"
    assert weather_scene(0, 0) == "night"
    assert weather_scene(3, 0) == "overcast"


def test_browser_cannot_supply_coordinates_or_an_arbitrary_city():
    c = {"zh": "北京", "lat": 39.9, "lon": 116.4}
    cards = build_cards([c], {})
    raw = {"type": "confirm", "event_id": "abc", "city_id": city_id(c), "days": 7, "lat": 0, "lon": 0}
    event = validate_event(raw, cards)
    assert event["city"]["lat"] == 39.9
    assert validate_event(dict(raw, city_id="not-followed"), cards) is None
    assert validate_event(dict(raw, days=True), cards) is None
    assert validate_event(dict(raw, days=365), cards) is None
    assert validate_event(dict(raw, type="execute"), cards) is None
    assert validate_event(dict(raw, event_id="x" * 100), cards) is None


def test_confirm_is_consumed_once_and_failure_preserves_old_result():
    state = {}
    a = make_intent({"zh": "甲", "lat": 30, "lon": 110}, 7, source_route="visualization")
    queue_intent(state, a)
    assert consume_intent(state) == a
    assert consume_intent(state) is None
    original = commit_success(state, a, frame())
    queue_intent(state, a)
    assert consume_intent(state) is None
    b = make_intent({"zh": "乙", "lat": 31, "lon": 111}, 3)
    queue_intent(state, b)
    assert consume_intent(state) == b
    fail_request(state, b, "offline")
    assert state["fc_result_context"] is original
    assert state["fc_df"] is original["data"]
    assert state["fc_lat"] == 30
    assert state["_forecast_status"]["city"]["name"] == "乙"
    assert original["city"]["name"] == "甲"


def test_invalid_result_never_replaces_success_and_history_is_bounded():
    state = {}
    for i in range(8):
        req = make_intent({"zh": str(i), "lat": 30 + i, "lon": 110}, 7)
        commit_success(state, req, frame())
    assert len(state["_forecast_history"]) == 5
    before = state["fc_result_context"]
    invalid = frame(); invalid.loc[1, "timestamp"] = invalid.loc[0, "timestamp"]
    with pytest.raises(ValueError):
        commit_success(state, req, invalid)
    assert state["fc_result_context"] is before
    assert all("data" not in history for history in state["_forecast_history"])
    assert restore_previous(state)
    assert state["fc_result_context"]["city"]["name"] == "6"
    assert state["fc_df"] is state["fc_result_context"]["data"]


def test_late_result_and_late_error_cannot_overwrite_newer_request():
    state = {}
    a = make_intent({"zh": "甲", "lat": 30, "lon": 110})
    b = make_intent({"zh": "乙", "lat": 31, "lon": 111})
    queue_intent(state, a); consume_intent(state)
    queue_intent(state, b); consume_intent(state)
    current = commit_success(state, b, frame())
    with pytest.raises(ValueError, match="更新的请求"):
        commit_success(state, a, frame())
    fail_request(state, a, "late error")
    assert state["fc_result_context"] is current
    assert state["_forecast_status"]["state"] == "success"
    assert queue_intent(state, b) is False
    assert state["_forecast_status"]["state"] == "success"


def test_precipitation_bins_are_right_closed_and_do_not_fill_missing_with_zero():
    data = frame()
    windows = precipitation_windows(data, 12)
    assert windows["precipitation"].tolist() == [12, 12]
    assert windows.iloc[0]["start"] == pd.Timestamp("2026-10-26 00:00")
    assert windows.iloc[0]["end"] == pd.Timestamp("2026-10-26 12:00")
    data.loc[2, "precipitation"] = np.nan
    windows = precipitation_windows(data, 12)
    assert np.isnan(windows.iloc[0]["precipitation"])
    assert windows.iloc[0]["valid_hours"] == 11
    assert windows.iloc[1]["precipitation"] == 12
    data["precipitation"] = np.nan
    assert precipitation_windows(data, 12)["precipitation"].isna().all()
    assert forecast_summary(data)["precipitation"] is None


def test_missing_hour_and_partial_edge_are_not_full_windows():
    data = frame().drop(index=[5])
    assert np.isnan(precipitation_windows(data, 12).iloc[0]["precipitation"])
    assert not forecast_summary(data)["precipitation_complete"]
    assert forecast_summary(data)["hours"] == 24
    partial = precipitation_windows(frame(4), 12)
    assert not partial.iloc[0]["complete"]
    assert np.isnan(partial.iloc[0]["precipitation"])


def test_probability_is_only_rendered_from_valid_provider_values():
    data = frame()
    data["weather_code"] = 65
    fig = forecast_figure(data, probability=True)
    assert all("概率" not in (trace.name or "") for trace in fig.data)
    data["precipitation_probability"] = 75
    data.loc[2, "precipitation_probability"] = 200
    fig = forecast_figure(data, probability=True)
    prob = [t for t in fig.data if "概率" in (t.name or "")][0]
    assert prob.y[0] == 75
    assert np.isnan(prob.y[2])
    assert fig.layout.yaxis3.range == (0, 100)
    assert not prob.connectgaps


def test_nonfinite_forecast_is_rejected_and_hover_labels_keep_city_identity():
    invalid = frame()
    invalid["temperature"] = np.inf
    invalid["precipitation"] = np.nan
    invalid["wind_speed"] = -np.inf
    intent = make_intent({"zh": "甲城", "lat": 30, "lon": 110})
    with pytest.raises(ValueError, match="有效要素"):
        commit_success({}, intent, invalid)
    figure = forecast_figure(frame(), context={"city": {"name": "甲城"}, "source": "GFS"})
    assert all("甲城" in trace.hovertemplate for trace in figure.data)


def test_resetting_a_module_keeps_global_weather_preferences():
    for tab in [TAB_IMPORT, TAB_CHART, TAB_FORECAST]:
        state = {"wall_cities": [{"zh": "甲", "lat": 30, "lon": 110}], "_weather_expanded": True,
                 "fc_result_context": {"city_id": "a"}, "df": frame()}
        reset_tab(state, tab)
        assert state["wall_cities"][0]["zh"] == "甲"
        assert state["_weather_expanded"] is True
        if tab == TAB_FORECAST:
            assert "fc_result_context" not in state
