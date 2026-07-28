"""
预报验证模块：GFS 预报 vs 实况 的定量可信度评估

方法学：
- 对齐：观测与预报按整点时间戳内连接（inner join），确保同一时刻配对。
- 指标：MAE / RMSE / Bias(平均误差) / 相关系数 r，纯 numpy 计算，无新依赖。
- 局限：Open-Meteo 对过去窗口返回的「预报」实为同窗口模式最优估计
  （非提前 N 天的业务级预报），属 hindcast 式验证，课程/展示级足够。

设计：本模块只负责计算与绘图（纯函数），UI 交互在 nwp_forecast.py 的
_render_forecast_verification 中完成，便于复用与测试。
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go

# 参与验证的变量（观测与 GFS 字段同名，已统一为标准字段）
VERIFY_VARS = ["temperature", "humidity", "wind_speed", "precipitation"]

VERIFY_VAR_LABELS = {
    "temperature": "气温 (℃)",
    "humidity": "相对湿度 (%)",
    "wind_speed": "风速 (m/s)",
    "precipitation": "降水 (mm)",
}


def align_obs_fc(obs_df, fc_df, freq="1h"):
    """按整点时间戳对齐观测与预报，返回配对 DataFrame。

    处理：
      - 时间戳统一为 datetime
      - 截断到整点（freq）并去重，避免分钟级错位导致匹配失败
      - 内连接合并，列名加 _obs / _fc 后缀

    返回含 timestamp + 各变量对 (temperature_obs/temperature_fc, ...) 的 DataFrame。
    """
    obs = obs_df.copy()
    fc = fc_df.copy()
    obs["timestamp"] = pd.to_datetime(obs["timestamp"])
    fc["timestamp"] = pd.to_datetime(fc["timestamp"])

    obs = obs.assign(_ts=obs["timestamp"].dt.floor(freq)).drop_duplicates("_ts")
    fc = fc.assign(_ts=fc["timestamp"].dt.floor(freq)).drop_duplicates("_ts")

    merged = pd.merge(obs, fc, on="_ts", suffixes=("_obs", "_fc"), how="inner")
    merged = merged.rename(columns={"_ts": "timestamp"})
    return merged


def compute_metrics(merged, var_names=None):
    """对每变量计算 MAE / RMSE / Bias / 相关系数 r。

    merged: align_obs_fc 的输出（含 <var>_obs / <var>_fc 列）。
    var_names: 指定变量；默认取所有含 _obs 后缀且存在对应 _fc 的变量。
    返回 {var: {mae, rmse, bias, r, n}}，样本不足时指标为 NaN。
    """
    if var_names is None:
        var_names = [
            c[:-4] for c in merged.columns
            if c.endswith("_obs") and f"{c[:-4]}_fc" in merged.columns
            and c[:-4] != "timestamp"
        ]

    out = {}
    for v in var_names:
        oc, fc = f"{v}_obs", f"{v}_fc"
        if oc not in merged.columns or fc not in merged.columns:
            continue
        o = merged[oc].to_numpy(dtype=float)
        f = merged[fc].to_numpy(dtype=float)
        mask = np.isfinite(o) & np.isfinite(f)
        n = int(mask.sum())
        if n < 2:
            out[v] = {"mae": float("nan"), "rmse": float("nan"),
                      "bias": float("nan"), "r": float("nan"), "n": n}
            continue
        o, f = o[mask], f[mask]
        err = f - o
        mae = float(np.mean(np.abs(err)))
        rmse = float(np.sqrt(np.mean(err ** 2)))
        bias = float(np.mean(err))
        if np.std(o) > 0 and np.std(f) > 0:
            r = float(np.corrcoef(o, f)[0, 1])
        else:
            r = float("nan")
        out[v] = {"mae": mae, "rmse": rmse, "bias": bias, "r": r, "n": n}
    return out


# ============================================================
# 图表构建（纯函数，返回 go.Figure）
# ============================================================

def make_scatter_1to1(merged, var, label):
    """1:1 散点图：实况 vs 预报 + 理想对角线。"""
    o = merged[f"{var}_obs"].to_numpy(dtype=float)
    f = merged[f"{var}_fc"].to_numpy(dtype=float)
    mask = np.isfinite(o) & np.isfinite(f)
    o, f = o[mask], f[mask]
    if len(o) == 0:
        fig = go.Figure()
        fig.add_annotation(text="无有效配对样本", showarrow=False)
        return fig
    lo = float(min(o.min(), f.min()))
    hi = float(max(o.max(), f.max()))
    pad = (hi - lo) * 0.05 or 1.0
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=o, y=f, mode="markers", name="样本",
        marker=dict(size=6, opacity=0.6, color="#3b82f6"),
        hovertemplate="实况 %{x:.2f}<br>预报 %{y:.2f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=[lo - pad, hi + pad], y=[lo - pad, hi + pad],
        mode="lines", name="1:1 理想线",
        line=dict(color="#ef4444", dash="dash"), hoverinfo="skip",
    ))
    fig.update_layout(
        title=f"{label} 实况 vs 预报 (1:1)",
        xaxis_title=f"实况 {label}",
        yaxis_title=f"预报 {label}",
        height=420, hovermode="closest",
        legend=dict(x=0.01, y=0.99, xanchor="left", yanchor="top"),
    )
    return fig


def make_timeseries_overlay(merged, var, label):
    """时间序列叠加：实况与 GFS 预报两条线。"""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=merged["timestamp"], y=merged[f"{var}_obs"], mode="lines",
        name="实况", line=dict(color="#22c55e", width=2),
        hovertemplate="%{x|%m-%d %H:%M}<br>实况 %{y:.2f}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=merged["timestamp"], y=merged[f"{var}_fc"], mode="lines",
        name="GFS 预报", line=dict(color="#3b82f6", width=2, dash="dot"),
        hovertemplate="%{x|%m-%d %H:%M}<br>预报 %{y:.2f}<extra></extra>",
    ))
    fig.update_layout(
        title=f"{label} 时间序列对比",
        xaxis_title="时间", yaxis_title=label,
        height=420, hovermode="x unified",
        legend=dict(x=0.01, y=0.99, xanchor="left", yanchor="top"),
    )
    return fig


def make_error_hist(merged, var, label):
    """误差直方图：预报 − 实况。"""
    err = (merged[f"{var}_fc"].to_numpy(dtype=float)
           - merged[f"{var}_obs"].to_numpy(dtype=float))
    err = err[np.isfinite(err)]
    fig = go.Figure(go.Histogram(x=err, nbinsx=30, marker_color="#8b5cf6"))
    fig.update_layout(
        title=f"{label} 预报误差分布 (预报 − 实况)",
        xaxis_title="误差", yaxis_title="频数",
        height=420,
    )
    return fig
