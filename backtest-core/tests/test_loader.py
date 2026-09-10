# Tests for data/loader.py — ticket 3
from datetime import datetime
from pathlib import Path

import pytest

from data.loader import load_ohlcv

FIXTURE = Path(__file__).parent / "fixtures" / "sample_20bars.csv"


def write_csv(tmp_path, content, name="data.csv"):
    path = tmp_path / name
    path.write_text(content)
    return path


def test_loads_full_fixture():
    bars = load_ohlcv(str(FIXTURE), symbol="EURUSD")
    assert len(bars) == 20
    assert bars[0].timestamp == datetime(2024, 1, 1)
    assert bars[0].open == 10
    assert bars[-1].timestamp == datetime(2024, 1, 20)
    assert bars[-1].close == 13
    assert all(bar.symbol == "EURUSD" for bar in bars)


def test_bars_sorted_even_if_input_out_of_order(tmp_path):
    content = (
        "timestamp,open,high,low,close,volume\n"
        "2024-01-02,11,11,11,11,1000\n"
        "2024-01-01,10,10,10,10,1000\n"
    )
    path = write_csv(tmp_path, content)
    bars = load_ohlcv(str(path), symbol="EURUSD")
    assert [b.timestamp for b in bars] == [datetime(2024, 1, 1), datetime(2024, 1, 2)]


def test_columns_case_insensitive_and_reorderable(tmp_path):
    content = "Volume,Close,High,Low,Open,Timestamp\n1000,10,10,10,10,2024-01-01\n"
    path = write_csv(tmp_path, content)
    bars = load_ohlcv(str(path), symbol="EURUSD")
    assert len(bars) == 1
    assert bars[0].open == 10
    assert bars[0].volume == 1000


def test_missing_column_raises_value_error(tmp_path):
    content = "timestamp,open,high,low,close\n2024-01-01,10,10,10,10\n"
    path = write_csv(tmp_path, content)
    with pytest.raises(ValueError, match="missing required column"):
        load_ohlcv(str(path), symbol="EURUSD")


def test_nan_in_required_field_raises_value_error(tmp_path):
    content = (
        "timestamp,open,high,low,close,volume\n"
        "2024-01-01,10,10,10,10,1000\n"
        "2024-01-02,,10,10,10,1000\n"
    )
    path = write_csv(tmp_path, content)
    with pytest.raises(ValueError, match="NaN"):
        load_ohlcv(str(path), symbol="EURUSD")


def test_non_numeric_field_raises_value_error(tmp_path):
    content = (
        "timestamp,open,high,low,close,volume\n"
        "2024-01-01,not-a-number,10,10,10,1000\n"
    )
    path = write_csv(tmp_path, content)
    with pytest.raises(ValueError, match="non-numeric"):
        load_ohlcv(str(path), symbol="EURUSD")


def test_duplicate_timestamps_raise_value_error(tmp_path):
    content = (
        "timestamp,open,high,low,close,volume\n"
        "2024-01-01,10,10,10,10,1000\n"
        "2024-01-01,11,11,11,11,1000\n"
    )
    path = write_csv(tmp_path, content)
    with pytest.raises(ValueError, match="duplicate|non-monotonic"):
        load_ohlcv(str(path), symbol="EURUSD")


def test_unsupported_extension_raises_value_error(tmp_path):
    path = write_csv(tmp_path, "not,a,real,csv\n", name="data.txt")
    with pytest.raises(ValueError, match="unsupported file extension"):
        load_ohlcv(str(path), symbol="EURUSD")
