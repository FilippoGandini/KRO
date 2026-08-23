"""Conversions into canonical CPU cores and memory MiB."""

import math
import re

_QUANTITY = re.compile(
    r"^\s*(?P<value>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
    r"\s*(?P<unit>[A-Za-z]*)\s*$"
)


def _parts(raw: str, *, field: str) -> tuple[float, str]:
    match = _QUANTITY.fullmatch(raw)
    if match is None:
        raise ValueError(f"{field} must be a numeric quantity")
    value = float(match.group("value"))
    if not math.isfinite(value):
        raise ValueError(f"{field} must be finite")
    return value, match.group("unit")


def parse_cpu_cores(raw: str, *, field: str = "CPU") -> float:
    """Parse cores (unitless or ``core(s)``) or Kubernetes millicores (``m``)."""

    value, unit = _parts(raw, field=field)
    factors = {"": 1.0, "core": 1.0, "cores": 1.0, "m": 0.001}
    if unit not in factors:
        raise ValueError(f"{field} has unsupported CPU unit {unit!r}")
    return value * factors[unit]


def parse_memory_mib(raw: str, *, field: str = "memory") -> float:
    """Parse memory into MiB, accepting binary and common byte units."""

    value, unit = _parts(raw, field=field)
    factors = {
        "": 1.0,
        "MiB": 1.0,
        "Mi": 1.0,
        "GiB": 1024.0,
        "Gi": 1024.0,
        "KiB": 1.0 / 1024.0,
        "Ki": 1.0 / 1024.0,
        "B": 1.0 / (1024.0 * 1024.0),
    }
    if unit not in factors:
        raise ValueError(f"{field} has unsupported memory unit {unit!r}")
    return value * factors[unit]
