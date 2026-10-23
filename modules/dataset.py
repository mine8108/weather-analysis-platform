"""数据集契约：归一化、版本化序列化与云端往返。

项目此前把 DataFrame 直接当会话数据，列名、时间类型、来源与质量评分各自
散落；云端保存的是裸 CSV，读回后无法知道按哪一版规则归一。本模块给出
唯一入口：

- :func:`prepare_import`  导入端唯一的归一入口，返回 ``Dataset``
- :func:`to_text`         写入云端前的版本化序列化
- :func:`from_text`       读回时识别版本并按需迁移

序列化格式为一行注释头加 CSV 正文。注释头缺失视为 v1（历史数据），
读取后自动迁移到当前版本。
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd

from config import FIELD_ALIASES, FIELD_LABELS

SCHEMA_VERSION = 2
LEGACY_VERSION = 1
HEADER_PREFIX = "#weather_dataset;schema_version="

# 历史版本迁移时补齐的规范列名。FIELD_ALIASES 已覆盖大部分输入，
# 这里兜住大小写与下划线变体，以及归一后可能残留的重复列。
RESIDUAL_ALIASES = {
    "pm2_5": "pm25", "pm2.5": "pm25", "pm_25": "pm25", "pm2": "pm25",
    "pm_10": "pm10", "pm1": "pm1",
    "temp": "temperature", "temp_c": "temperature",
    "rh": "humidity", "wind": "wind_speed", "ws": "wind_speed",
    "wd": "wind_direction", "precip": "precipitation", "rain": "precipitation",
    "time": "timestamp", "datetime": "timestamp", "date": "timestamp",
}


def _unit_of(label: str) -> str:
    """从「气温 (℃)」这类标签里取出单位；没有单位时返回空串。"""
    if "(" not in label or ")" not in label:
        return ""
    return label[label.rindex("(") + 1:label.rindex(")")].strip()


def units_for(columns):
    """列名到单位的映射，单位来自 config.FIELD_LABELS 的单一真相源。"""
    return {col: _unit_of(FIELD_LABELS.get(col, "")) for col in columns
            if _unit_of(FIELD_LABELS.get(col, ""))}


def station_dtypes(columns):
    """读取时保留站号，避免类型推断先丢失前导零。"""
    aliases = {str(k).strip().lower() for k, v in FIELD_ALIASES.items() if v == "station_id"}
    aliases.add("station_id")
    return {c: "string" for c in columns if str(c).strip().lower() in aliases}


def canonicalize(df: pd.DataFrame) -> pd.DataFrame:
    """列名与时间类型的归一，幂等。

    1. 去列名首尾空白
    2. 按 FIELD_ALIASES 与 RESIDUAL_ALIASES 映射到标准名
    3. 消除归一后产生的重复列（保留首次出现的列）
    4. timestamp 转北京时间无时区 datetime；无时区输入视为北京时间
    """
    if df is None or not isinstance(df, pd.DataFrame):
        raise TypeError("canonicalize 需要 pandas.DataFrame")
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]

    mapping = {}
    for col in out.columns:
        key = col.lower()
        if key in {k.lower() for k in RESIDUAL_ALIASES}:
            for alias, std in RESIDUAL_ALIASES.items():
                if key == alias.lower():
                    mapping[col] = std
                    break
            continue
        for alias, std in FIELD_ALIASES.items():
            if key == alias.lower():
                mapping[col] = std
                break
    if mapping:
        out = out.rename(columns=mapping)
    out = out.loc[:, ~out.columns.duplicated()]
    if "station_id" in out:
        out["station_id"] = out["station_id"].astype("string")

    if "timestamp" in out.columns:
        try:
            parsed = pd.to_datetime(out["timestamp"], errors="coerce", format="mixed")
            if isinstance(parsed.dtype, pd.DatetimeTZDtype):
                parsed = parsed.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
            elif not pd.api.types.is_datetime64_any_dtype(parsed.dtype):
                raise ValueError("mixed time zones")
        except (ValueError, TypeError):
            # 手工追加报文时可能同时含本地无时区值与带 UTC/偏移量的值。
            def local_time(value):
                try:
                    ts = pd.Timestamp(value)
                    if pd.isna(ts):
                        return pd.NaT
                    return ts.tz_convert("Asia/Shanghai").tz_localize(None) if ts.tzinfo else ts
                except (ValueError, TypeError):
                    return pd.NaT
            parsed = pd.to_datetime(out["timestamp"].map(local_time))
        # 全空结果说明这一列不是时间，保留原值交给下游报错
        if parsed.notna().any():
            out["timestamp"] = parsed
    return out.reset_index(drop=True)


@dataclass
class Dataset:
    """导入完成后的唯一数据对象。"""

    df: pd.DataFrame
    source: str = ""
    quality_score: float = 0.0
    warnings: list = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat(timespec="seconds")

    @property
    def n_rows(self) -> int:
        return 0 if self.df is None else int(len(self.df))

    @property
    def columns(self) -> list:
        return [] if self.df is None else list(self.df.columns)

    @property
    def units(self) -> dict:
        return units_for(self.columns)


def prepare_import(df, source="", quality_score=0.0, warnings=None) -> Dataset:
    """导入端唯一归一入口。"""
    return Dataset(
        df=canonicalize(df),
        source=str(source or ""),
        quality_score=float(quality_score or 0.0),
        warnings=list(warnings or []),
    )


def to_text(dataset) -> str:
    """版本化序列化，供云端单字段存储。"""
    if isinstance(dataset, Dataset):
        df = dataset.df
        version = dataset.schema_version
    else:
        df = canonicalize(dataset)
        version = SCHEMA_VERSION
    body = "" if df is None or df.empty else df.to_csv(index=False)
    return "%s%d\n%s" % (HEADER_PREFIX, int(version), body)


def _split_header(text: str):
    """返回 (版本号, 正文)。注释头缺失视为 v1。"""
    text = text or ""
    first_line, _, rest = text.partition("\n")
    if first_line.startswith(HEADER_PREFIX):
        try:
            return int(first_line[len(HEADER_PREFIX):].strip() or LEGACY_VERSION), rest
        except ValueError:
            return LEGACY_VERSION, rest
    return LEGACY_VERSION, text


def migrate(df: pd.DataFrame, version: int, source="") -> Dataset:
    """把旧版本数据迁移到当前契约。"""
    if version > SCHEMA_VERSION:
        raise ValueError(
            "数据 schema 版本 %d 高于当前代码支持的 %d，请先升级应用"
            % (version, SCHEMA_VERSION))
    return prepare_import(df, source=source)


def from_text(text: str, source="") -> Dataset:
    """读回云端文本，识别版本并迁移。"""
    version, body = _split_header(text)
    if not body.strip():
        return Dataset(df=pd.DataFrame(), source=source, schema_version=SCHEMA_VERSION)
    columns = pd.read_csv(io.StringIO(body), nrows=0).columns
    df = pd.read_csv(io.StringIO(body), dtype=station_dtypes(columns))
    dataset = migrate(df, version, source=source)
    dataset.schema_version = SCHEMA_VERSION
    return dataset
