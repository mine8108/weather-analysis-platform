"""Forward time coverage and robust table behavior across real failure cases."""
import numpy as np
import pandas as pd
import pytest

from modules.forecast_context import commit_success, make_intent, restore_previous
from modules.nwp.calc import _calc_life_indices, _get_now_row
from modules.nwp.time_window import calendar_forecast, future_hourly_forecast
from modules.nwp_forecast import _cache_covers_today
from modules.ui.table import table_html
from streamlit.testing.v1 import AppTest


def forecast(days=4):
    timestamps = pd.date_range("2026-11-04", periods=24 * days, freq="h")
    return pd.DataFrame({"timestamp": timestamps, "temperature": 20., "humidity": 60.,
                         "apparent_temperature": 19., "precipitation": 0., "wind_speed": 3.,
                         "weather_code": 2})


@pytest.mark.parametrize("request_time, first, last", [
    ("2026-11-04T09:06:25Z", "2026-11-04 18:00", "2026-11-07 17:00"),
    ("2026-11-04T23:59:59+08:00", "2026-11-05 00:00", "2026-11-07 23:00"),
    ("2026-11-04T00:00:00+08:00", "2026-11-04 00:00", "2026-11-06 23:00"),
])
def test_future_72_excludes_earlier_hours_and_covers_last_hour(request_time, first, last):
    frame, coverage = future_hourly_forecast(forecast(), request_time)
    assert coverage["complete"] and coverage["present"] == len(frame) == 72
    assert frame.timestamp.iloc[0] == pd.Timestamp(first)
    assert frame.timestamp.iloc[-1] == pd.Timestamp(last)


@pytest.mark.parametrize("days", [1, 2, 3, 4])
def test_calendar_export_stays_at_selected_day_count(days):
    selected = calendar_forecast(forecast(), "2026-11-04T17:06:25+08:00", days)
    assert len(selected) == 24 * days
    assert selected.timestamp.iloc[0] == pd.Timestamp("2026-11-04 00:00")
    assert selected.timestamp.iloc[-1] == pd.Timestamp("2026-11-04") + pd.Timedelta(days=days, hours=-1)


def test_future_window_accepts_aware_times_and_marks_gaps():
    data = forecast()
    data["timestamp"] = data.timestamp.dt.tz_localize("Asia/Shanghai").dt.tz_convert("UTC")
    data = data.drop(index=40)
    result, coverage = future_hourly_forecast(data, "2026-11-04T09:06:25Z")
    assert len(result) == coverage["present"] == 71
    assert not coverage["complete"]


def test_indices_ignore_past_and_use_last_future_hour():
    data = forecast()
    data.loc[data.timestamp < "2026-11-04 18:00", "precipitation"] = 50.
    data.loc[data.timestamp == "2026-11-07 17:00", "precipitation"] = 12.
    data.loc[data.timestamp == "2026-11-07 17:00", "temperature"] = 42.
    future, coverage = future_hourly_forecast(data, "2026-11-04T17:06:25+08:00")
    current = {"temperature": 20., "humidity": 60., "wind_speed": 3., "weather_code": 2}
    indices = _calc_life_indices(future, current=current, complete=coverage["complete"])
    assert future.temperature.max() == 42.
    assert future.precipitation.sum() == 12.
    assert indices["umbrella"]["level"] == "必带伞"
    assert indices["carwash"]["level"] == "一般"


def test_missing_precipitation_never_becomes_no_rain_advice():
    future, coverage = future_hourly_forecast(forecast(), "2026-11-04T17:06:25+08:00")
    future.loc[future.index[-1], "precipitation"] = np.nan
    current = {"temperature": 20., "humidity": 60., "wind_speed": 3., "weather_code": 2}
    indices = _calc_life_indices(future, current=current, complete=coverage["complete"])
    for key in ("umbrella", "carwash", "exercise", "drying"):
        assert indices[key]["level"] == "数据不足"
    assert indices["uv"]["level"] != "数据不足"


def test_zero_current_values_are_retained_and_missing_values_fall_back():
    future, coverage = future_hourly_forecast(forecast(), "2026-11-04T17:06:25+08:00")
    current = {"temperature": 20., "humidity": 0., "wind_speed": 0., "weather_code": None}
    indices = _calc_life_indices(future, current=current, as_of="2026-11-04 17:06:25",
                                 complete=coverage["complete"])
    assert indices["comfort"]["score"] == round(20 - 0.55 * 6 - 0.1 ** (1 / 3) * 10 / 20, 1)
    future["weather_code"] = np.nan
    assert _calc_life_indices(future, current=current, complete=True)["uv"]["level"] == "数据不足"


def test_incomplete_window_and_expired_current_fallback():
    future, coverage = future_hourly_forecast(forecast().iloc[:-1], "2026-11-04T23:59:00+08:00")
    current = {"temperature": 20., "humidity": 60., "wind_speed": 3., "weather_code": 2}
    indices = _calc_life_indices(future, current=current, complete=coverage["complete"])
    assert not coverage["complete"]
    assert indices["umbrella"]["level"] == "数据不足"
    assert _get_now_row(future, as_of="2026-11-08 00:00") is None


def test_midnight_cache_rejects_yesterdays_incomplete_horizon():
    assert _cache_covers_today(forecast(), 4, as_of="2026-11-04 23:59")
    assert not _cache_covers_today(forecast(), 4, as_of="2026-11-05 00:01")


def test_previous_result_restores_both_windows_and_history_excludes_frames():
    state = {}
    a = make_intent({"zh": "甲", "lat": 30, "lon": 110}, 3)
    b = make_intent({"zh": "乙", "lat": 31, "lon": 111}, 3)
    full = forecast()
    selected = full.head(72).copy()
    commit_success(state, a, selected, future_frame=full)
    commit_success(state, b, selected, future_frame=full.copy())
    assert "future_data" not in state["_forecast_history"][0]
    assert restore_previous(state)
    assert state["fc_result_context"]["request_id"] == a["request_id"]
    assert len(state["fc_result_context"]["future_data"]) == 96
    assert len(state["fc_df"]) == 72


def test_table_escapes_cells_headers_and_labels_and_limits_rows():
    df = pd.DataFrame({"<script>": ["<img src=x onerror=alert(1)>"] * 3, "value": [1.25, 2.5, 3.]})
    html, total = table_html(df, hide_index=True, labels={"value": "<单位>"}, float_precision=1, max_rows=2)
    assert total == 3 and html.count("&lt;img") == 2
    assert "<script>" not in html and "<img" not in html
    assert "&lt;script&gt;" in html and "&lt;单位&gt;" in html and "1.2" in html
    last_page, _ = table_html(df, hide_index=True, max_rows=2, offset=2)
    assert last_page.count("&lt;img") == 1 and "3.0" in last_page


def test_large_table_pagination_keeps_all_rows_available():
    app = AppTest.from_string("import pandas as pd\nfrom modules.ui.table import render_table\n"
                              "render_table(pd.DataFrame({'x': range(401)}), hide_index=True, key='page')").run()
    assert not app.exception
    assert "第 1–200 条" in app.caption[0].value
    app.number_input(key="page").set_value(3).run()
    assert not app.exception and "第 401–401 条" in app.caption[0].value
    assert ">400<" in app.get("html")[0].value
