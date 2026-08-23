import pytest

from kubernetes_resource_optimizer.data.units import parse_cpu_cores, parse_memory_mib


@pytest.mark.parametrize(
    ("raw", "expected"), [("1", 1.0), ("500m", 0.5), ("1.5 cores", 1.5)]
)
def test_parse_cpu_cores(raw: str, expected: float) -> None:
    assert parse_cpu_cores(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("512", 512.0), ("512MiB", 512.0), ("1GiB", 1024.0), ("1048576B", 1.0)],
)
def test_parse_memory_mib(raw: str, expected: float) -> None:
    assert parse_memory_mib(raw) == expected


@pytest.mark.parametrize("raw", ["one", "1GB", "NaN"])
def test_rejects_invalid_or_unsupported_units(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_memory_mib(raw)
