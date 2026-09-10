"""CSV/Parquet -> list[Bar] loader."""

from pathlib import Path

import pandas as pd

from data.schema import NUMERIC_COLUMNS, REQUIRED_COLUMNS, missing_columns, normalize_columns
from engine.types import Bar


def load_ohlcv(path: str, symbol: str) -> list[Bar]:
    """Reads a CSV/Parquet file, validates columns/dtypes, sorts by timestamp,
    and returns a list of Bar objects. Raises ValueError on missing columns,
    non-monotonic timestamps, or NaN values in required fields."""
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        df = pd.read_csv(file_path)
    elif suffix == ".parquet":
        df = pd.read_parquet(file_path)
    else:
        raise ValueError(f"unsupported file extension {suffix!r}; expected .csv or .parquet")

    missing = missing_columns(df.columns)
    if missing:
        raise ValueError(f"{file_path}: missing required column(s): {', '.join(missing)}")

    column_map = normalize_columns(df.columns)
    df = df.rename(columns={column_map[c]: c for c in REQUIRED_COLUMNS})[list(REQUIRED_COLUMNS)]

    for column in NUMERIC_COLUMNS:
        try:
            df[column] = pd.to_numeric(df[column], errors="raise")
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{file_path}: column {column!r} contains non-numeric data") from exc

    if df.isna().any().any():
        raise ValueError(f"{file_path}: NaN values found in required column(s)")

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp")

    if df["timestamp"].duplicated().any():
        raise ValueError(f"{file_path}: duplicate/non-monotonic timestamps found")

    return [
        Bar(
            timestamp=row.timestamp.to_pydatetime(),
            symbol=symbol,
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=float(row.volume),
        )
        for row in df.itertuples(index=False)
    ]
