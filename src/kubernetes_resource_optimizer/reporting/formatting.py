"""Locale-independent numbers: decimal dot, narrow no-break grouping spaces."""


def format_number(value: float, precision: int = 3) -> str:
    """Keep decimal and thousands separators visually unambiguous."""
    text = f"{value:,.{precision}f}".replace(",", "\u202f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def format_percent(value: float, precision: int = 2, *, signed: bool = False) -> str:
    """Format a percentage without insignificant trailing decimal zeros."""
    prefix = "+" if signed and value >= 0 else ""
    return f"{prefix}{format_number(value * 100, precision)}%"
