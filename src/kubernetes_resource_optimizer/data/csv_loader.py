"""Strict CSV loading, independent from optimization logic."""

import csv
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from kubernetes_resource_optimizer.data.models import (
    InputData,
    Node,
    Pod,
    UsageSample,
)
from kubernetes_resource_optimizer.data.units import parse_cpu_cores, parse_memory_mib
from kubernetes_resource_optimizer.data.validation import (
    InputValidationError,
    validate_input_data,
)

Parser = Callable[[str], float]


def _rows(
    path: Path,
    required: set[str],
    any_identifier: set[str] | None = None,
) -> list[tuple[int, dict[str, str | None]]]:
    try:
        with path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            headers = set(reader.fieldnames or ())
            missing = sorted(required - headers)
            if missing:
                raise InputValidationError(
                    [f"{path.name} is missing required columns: {', '.join(missing)}"]
                )
            if any_identifier is not None and headers.isdisjoint(any_identifier):
                choices = " or ".join(sorted(any_identifier))
                raise InputValidationError(
                    [f"{path.name} is missing required column: {choices}"]
                )
            return [(line, row) for line, row in enumerate(reader, start=2)]
    except OSError as error:
        raise InputValidationError([f"cannot read {path}: {error}"]) from error


def _required(row: dict[str, str | None], field: str, source: str) -> str:
    value = row.get(field)
    if value is None or not value.strip():
        raise InputValidationError([f"{source}: missing value for {field}"])
    return value.strip()


def _workload_id(row: dict[str, str | None], source: str) -> str:
    """Read the public workload identifier, accepting the legacy pod_id alias."""

    field = "workload_id" if "workload_id" in row else "pod_id"
    return _required(row, field, source)


def _quantity(
    row: dict[str, str | None], field: str, source: str, parser: Parser
) -> float:
    raw = _required(row, field, source)
    try:
        return parser(raw)
    except ValueError as error:
        raise InputValidationError([f"{source}: {error}"]) from error


def _optional_quantity(
    row: dict[str, str | None], field: str, source: str, parser: Parser
) -> float | None:
    raw = row.get(field)
    if raw is None or not raw.strip():
        return None
    try:
        return parser(raw.strip())
    except ValueError as error:
        raise InputValidationError([f"{source}: {error}"]) from error


def load_nodes_csv(path: Path) -> tuple[Node, ...]:
    """Load candidate nodes; resource values are converted to canonical units."""

    nodes: list[Node] = []
    for line, row in _rows(path, {"node_id", "cpu_capacity", "memory_capacity"}):
        source = f"{path.name} line {line}"
        cost = _optional_quantity(row, "cost", source, float)
        nodes.append(
            Node(
                node_id=_required(row, "node_id", source),
                cpu_capacity=_quantity(
                    row,
                    "cpu_capacity",
                    source,
                    lambda value: parse_cpu_cores(value, field="cpu_capacity"),
                ),
                memory_capacity=_quantity(
                    row,
                    "memory_capacity",
                    source,
                    lambda value: parse_memory_mib(value, field="memory_capacity"),
                ),
                cost=1.0 if cost is None else cost,
            )
        )
    return tuple(nodes)


def load_pods_csv(path: Path) -> tuple[Pod, ...]:
    """Load pods, their service membership, and optional resource values."""

    pods: list[Pod] = []
    cpu_fields = (
        "current_cpu_request",
        "current_cpu_limit",
        "cpu_request_max",
        "cpu_limit_max",
    )
    memory_fields = (
        "current_memory_request",
        "current_memory_limit",
        "memory_request_max",
        "memory_limit_max",
    )
    for line, row in _rows(path, set(), {"workload_id", "pod_id"}):
        source = f"{path.name} line {line}"
        values = {
            field: _optional_quantity(
                row,
                field,
                source,
                lambda value, field=field: parse_cpu_cores(value, field=field),
            )
            for field in cpu_fields
        }
        values.update(
            {
                field: _optional_quantity(
                    row,
                    field,
                    source,
                    lambda value, field=field: parse_memory_mib(value, field=field),
                )
                for field in memory_fields
            }
        )
        raw_service_id = row.get("service_id")
        service_id = (
            raw_service_id.strip()
            if raw_service_id is not None and raw_service_id.strip()
            else None
        )
        pods.append(
            Pod(
                pod_id=_workload_id(row, source),
                service_id=service_id,
                **values,
            )
        )
    return tuple(pods)


def _timestamp(raw: str, source: str) -> datetime:
    try:
        timestamp = datetime.fromisoformat(raw)
    except ValueError as error:
        raise InputValidationError([f"{source}: invalid timestamp {raw!r}"]) from error
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise InputValidationError([f"{source}: timestamp must include a UTC offset"])
    return timestamp


def load_usage_csv(path: Path) -> tuple[UsageSample, ...]:
    """Load historical pod observations in canonical units."""

    samples: list[UsageSample] = []
    required = {"timestamp", "cpu_usage", "memory_usage"}
    for line, row in _rows(path, required, {"workload_id", "pod_id"}):
        source = f"{path.name} line {line}"
        samples.append(
            UsageSample(
                timestamp=_timestamp(_required(row, "timestamp", source), source),
                pod_id=_workload_id(row, source),
                cpu_usage=_quantity(
                    row,
                    "cpu_usage",
                    source,
                    lambda value: parse_cpu_cores(value, field="cpu_usage"),
                ),
                memory_usage=_quantity(
                    row,
                    "memory_usage",
                    source,
                    lambda value: parse_memory_mib(value, field="memory_usage"),
                ),
            )
        )
    return tuple(samples)


def load_input_data(nodes_path: Path, pods_path: Path, usage_path: Path) -> InputData:
    """Load all CSV inputs and perform complete semantic validation."""

    data = InputData(
        nodes=load_nodes_csv(nodes_path),
        pods=load_pods_csv(pods_path),
        usage_samples=load_usage_csv(usage_path),
    )
    validate_input_data(data)
    return data
