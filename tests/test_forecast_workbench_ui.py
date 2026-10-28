"""Actual Streamlit render checks with isolated weather services (no outbound calls)."""
import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest

from modules.forecast_context import make_intent
from modules import nwp_forecast as nwp


def _forecast(days):
    hours = np.arange(24 * days)
    return pd.DataFrame({"timestamp": pd.date_range("2026-10-26", periods=len(hours), freq="h"),
                         "temperature": 22 + 4 * np.sin(hours / 4), "apparent_temperature": 23 + 4 * np.sin(hours / 4),
                         "humidity": 60., "wind_speed": 2., "wind_direction": 180., "weather_code": 2,
                         "precipitation": 0., "precipitation_probability": np.nan, "station_id": "fixture"})


def test_query_failure_and_control_edits_keep_all_panels_on_successful_city(monkeypatch):
    calls, current_calls, aq_calls = [], [], []
    def fetch(lat, lon, days=7, model="gfs_seamless", **kwargs):
        calls.append((lat, lon, days, model))
        return (_forecast(days), None) if lat == 30 else (None, "测试网络不可用")
    def current(lat, lon, model="gfs_seamless"):
        current_calls.append((lat, lon, model))
        return None
    def aq(lat, lon, days=7):
        aq_calls.append((lat, lon, days))
        return None, None, "测试空气质量缺测"
    monkeypatch.setattr(nwp, "fetch_gfs_forecast", fetch)
    monkeypatch.setattr(nwp, "_fetch_gfs_current", current)
    monkeypatch.setattr(nwp, "fetch_air_quality", aq)
    monkeypatch.setattr(nwp, "_render_forecast_verification", lambda: None)
    at = AppTest.from_string("from modules.nwp_forecast import render_forecast_tab\nrender_forecast_tab()", default_timeout=60)
    at.session_state["_forecast_intent"] = make_intent({"zh": "原城市", "lat": 30, "lon": 110}, 3)
    at.run()
    assert not at.exception
    assert len(calls) == 1
    # Popovers can mount their frontend inputs only after an unrelated rerun.
    # Their serialized defaults must already describe the requested city.
    assert at.number_input(key="_fc_lat_input").proto.default == 30.0
    assert at.number_input(key="_fc_lon_input").proto.default == 110.0
    assert list(at.slider(key="_fc_days_input").proto.default) == [3.0]
    original = at.session_state["fc_result_context"]["request_id"]
    at.number_input(key="_fc_lat_input").set_value(31).run()
    assert len(calls) == 1
    assert at.session_state["fc_result_context"]["request_id"] == original
    at.button(key="fc_fetch").click().run()
    assert not at.exception
    assert len(calls) == 2
    assert at.session_state["fc_result_context"]["city"]["name"] == "原城市"
    assert at.session_state["fc_result_context"]["request_id"] == original
    assert all(c[:2] == (30, 110) for c in current_calls)
    assert all(c[:2] == (30, 110) for c in aq_calls)
    assert any("加载失败" in w.value for w in at.warning)
    at.run()
    assert len(calls) == 2
