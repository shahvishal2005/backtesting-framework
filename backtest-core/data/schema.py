"""Expected OHLCV column names and case-insensitive matching helpers."""

REQUIRED_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")
NUMERIC_COLUMNS = ("open", "high", "low", "close", "volume")


def normalize_columns(columns):
    """Maps each column's lowercased/stripped name to its original name."""
    return {str(c).strip().lower(): c for c in columns}


def missing_columns(columns):
    """Returns the REQUIRED_COLUMNS not present in columns, case-insensitively."""
    present = normalize_columns(columns)
    return [c for c in REQUIRED_COLUMNS if c not in present]
