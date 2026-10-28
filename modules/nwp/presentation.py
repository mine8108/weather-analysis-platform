"""Forecast plot semantics: aligned axes, explicit accumulation, honest missing data."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from modules.chart_theme import apply as apply_theme
from modules.design_tokens import tokens_for


def numeric_series(frame, field):
    value = frame[field] if field in frame else pd.Series(np.nan, index=frame.index)
    return pd.to_numeric(value, errors="coerce").replace([np.inf, -np.inf], np.nan)


def precipitation_windows(frame, hours=12):
    """Open-Meteo timestamps mark the END of the preceding one-hour interval.

    Right-closed bins contain (end-hours, end]. Partial/missing bins remain NaN.
    A missing or invalid value must never become a dry interval.
    """
    if hours not in (1, 3, 6, 12, 24):
        raise ValueError("不支持的降水累计窗口")
    series = pd.Series(numeric_series(frame, "precipitation").to_numpy(),
                       index=pd.DatetimeIndex(pd.to_datetime(frame["timestamp"])))
    series = series.where(series >= 0).sort_index()
    if series.index.has_duplicates:
        raise ValueError("降水时间轴包含重复时次")
    if series.empty:
        return pd.DataFrame(columns=["end", "start", "precipitation", "valid_hours", "complete"])
    grid = pd.date_range(series.index.min(), series.index.max(), freq="h")
    series = series.reindex(grid)
    grouped = series.resample(f"{hours}h", closed="right", label="right", origin="start_day")
    count = grouped.count()
    total = grouped.sum(min_count=hours).where(count == hours)
    result = pd.DataFrame({"end": total.index, "start": total.index - pd.Timedelta(hours=hours),
                           "precipitation": total.to_numpy(), "valid_hours": count.to_numpy(),
                           "complete": (count == hours).to_numpy()})
    return result


def forecast_summary(frame):
    temp = numeric_series(frame, "temperature")
    wind = numeric_series(frame, "wind_speed")
    rain = numeric_series(frame, "precipitation").where(lambda s: s >= 0)
    def extremum(series, high):
        if not series.notna().any():
            return {"value": None, "time": None}
        idx = series.idxmax() if high else series.idxmin()
        return {"value": float(series.loc[idx]), "time": str(frame.loc[idx, "timestamp"])}
    times = pd.DatetimeIndex(pd.to_datetime(frame["timestamp"]))
    expected = len(pd.date_range(times.min(), times.max(), freq="h")) if len(times) else 0
    return {"maximum": extremum(temp, True), "minimum": extremum(temp, False),
            "wind_maximum": extremum(wind, True), "precipitation": float(rain.sum()) if rain.notna().any() else None,
            "precipitation_complete": bool(expected and len(times.unique()) == expected and rain.notna().all()),
            "valid_rain_hours": int(rain.notna().sum()), "hours": expected}


def forecast_figure(frame, *, apparent=True, precipitation_hours=12, probability=False, dark=False, context=None):
    from html import escape
    t = tokens_for(dark)
    context = context or {}
    label = escape(str(context.get("city", {}).get("name", "")))
    source = escape(str(context.get("source", "Open-Meteo")))
    hover_context = f"{label} · {source}<br>有效时间 %{{x|%m/%d %H:%M}}（UTC+8）<br>"
    times = pd.to_datetime(frame["timestamp"])
    temp = numeric_series(frame, "temperature")
    prob = numeric_series(frame, "precipitation_probability").where(lambda s: s.between(0, 100))
    show_probability = probability and prob.notna().any()
    rows = 3 if show_probability else 2
    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True,
                        row_heights=[.58, .25, .17] if show_probability else [.66, .34], vertical_spacing=.09)
    fig.add_trace(go.Scatter(x=times, y=temp, mode="lines", name="2 m 气温", connectgaps=False,
                            line=dict(color=t["temp"], width=2.4), hovertemplate=hover_context + "%{y:.1f} °C<extra>气温</extra>"), row=1, col=1)
    if apparent and "apparent_temperature" in frame:
        fig.add_trace(go.Scatter(x=times, y=numeric_series(frame, "apparent_temperature"), mode="lines",
                                name="体感温度", connectgaps=False, line=dict(color=t["wind"], width=1.8, dash="dash"),
                                hovertemplate=hover_context + "%{y:.1f} °C<extra>体感温度</extra>"), row=1, col=1)
    if temp.notna().any():
        for i, extrema_label, color in [(temp.idxmax(), "最高", t["temp"]), (temp.idxmin(), "最低", t["humid"])]:
            fig.add_trace(go.Scatter(x=[times.loc[i]], y=[temp.loc[i]], mode="markers+text",
                                    text=[f"{temp.loc[i]:.1f}°C"], textposition="top center", cliponaxis=False, showlegend=False,
                                    marker=dict(size=8, color=color), textfont=dict(color=color, size=12),
                                    hovertemplate=hover_context + f"{extrema_label}气温 %{{y:.1f}} °C<extra></extra>"), row=1, col=1)
    rain = precipitation_windows(frame, precipitation_hours)
    centers = rain["start"] + pd.Timedelta(hours=precipitation_hours / 2)
    custom = [[a.strftime("%m/%d %H:%M"), b.strftime("%m/%d %H:%M"), int(n)]
              for a, b, n in zip(rain["start"], rain["end"], rain["valid_hours"])]
    fig.add_trace(go.Bar(x=centers, y=rain["precipitation"], name=f"{precipitation_hours} 小时累计降水",
                        width=precipitation_hours * 3600000 * .72, marker_color=t["rain"], customdata=custom,
                        hovertemplate=f"{label} · {source}<br>" + "%{customdata[0]} 至 %{customdata[1]}（UTC+8）<br>%{y:.1f} mm<extra>累计降水</extra>"), row=2, col=1)
    if show_probability:
        fig.add_trace(go.Scatter(x=times, y=prob, name="降水概率（接口原值）", connectgaps=False,
                                line=dict(color=t["humid"], width=1.6, dash="dot"), hovertemplate="%{y:.0f}%<extra>降水概率</extra>"), row=3, col=1)
        fig.update_yaxes(title_text="概率 / %", range=[0, 100], row=3, col=1)
    fig.update_yaxes(title_text="气温 / °C", row=1, col=1)
    fig.update_yaxes(title_text=f"{precipitation_hours}h 降水 / mm", rangemode="tozero", row=2, col=1)
    fig.update_xaxes(tickformat="%m/%d\n%H:%M", showgrid=True, matches="x", row=rows, col=1,
                     title_text="有效时间 · 北京时间（UTC+8）")
    fig.update_layout(height=430 if show_probability else 310,
                      margin=dict(l=38, r=18, t=35, b=34), hovermode="x unified", hoversubplots="axis",
                      legend=dict(orientation="h", x=0, y=1.15, font=dict(size=12)),
                      uirevision=f"{times.min()}|{times.max()}|{frame.get('station_id', pd.Series([''])) .iloc[0]}")
    apply_theme(fig, dark)
    return fig
