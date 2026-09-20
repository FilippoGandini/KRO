"""Convert OCP/Prometheus matrix exports to the optimizer usage CSV.

This module deliberately remains separate from the optimizer CLI: it prepares
local input data but does not connect to OpenShift or build the MILP model.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class ConversionError(ValueError):
    """Raised when an export cannot be converted without losing information."""


@dataclass(frozen=True, slots=True, order=True)
class ObservationKey:
    """Identity of one pod observation."""

    timestamp: float
    pod_id: str


CPU_CONVERTERS: dict[str, Callable[[float], float]] = {
    "cores": lambda value: value,
    "millicores": lambda value: value / 1_000,
    "nanocores": lambda value: value / 1_000_000_000,
}
MEMORY_CONVERTERS: dict[str, Callable[[float], float]] = {
    "mib": lambda value: value,
    "bytes": lambda value: value / (1024 * 1024),
    "kib": lambda value: value / 1024,
    "gib": lambda value: value * 1024,
}


def _load_json(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as stream:
            return json.load(stream)
    except OSError as error:
        raise ConversionError(f"cannot read {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise ConversionError(f"invalid JSON in {path}: {error}") from error


def parse_matrix_export(
    document: Any,
    *,
    source: str,
    metric_label: str = "pod",
) -> dict[ObservationKey, float]:
    """Parse a successful Prometheus matrix response into finite observations."""

    if not isinstance(document, dict) or document.get("status") != "success":
        raise ConversionError(f"{source}: expected a response with status='success'")
    data = document.get("data")
    if not isinstance(data, dict) or data.get("resultType") != "matrix":
        raise ConversionError(f"{source}: expected data.resultType='matrix'")
    results = data.get("result")
    if not isinstance(results, list):
        raise ConversionError(f"{source}: data.result must be a list")

    observations: dict[ObservationKey, float] = {}
    for result_index, series in enumerate(results):
        location = f"{source}: result[{result_index}]"
        if not isinstance(series, dict):
            raise ConversionError(f"{location} must be an object")
        metric = series.get("metric")
        values = series.get("values")
        if not isinstance(metric, dict) or not isinstance(metric.get(metric_label), str):
            raise ConversionError(f"{location} has no string metric.{metric_label}")
        pod_id = metric[metric_label].strip()
        if not pod_id:
            raise ConversionError(f"{location} has an empty metric.{metric_label}")
        if not isinstance(values, list):
            raise ConversionError(f"{location}.values must be a list")

        for value_index, sample in enumerate(values):
            sample_location = f"{location}.values[{value_index}]"
            if not isinstance(sample, list) or len(sample) != 2:
                raise ConversionError(f"{sample_location} must be [timestamp, value]")
            try:
                timestamp = float(sample[0])
                value = float(sample[1])
            except (TypeError, ValueError) as error:
                raise ConversionError(
                    f"{sample_location} contains a non-numeric timestamp or value"
                ) from error
            if not math.isfinite(timestamp) or not math.isfinite(value):
                raise ConversionError(f"{sample_location} contains a non-finite number")
            if value < 0:
                raise ConversionError(f"{sample_location} contains a negative value")
            key = ObservationKey(timestamp=timestamp, pod_id=pod_id)
            if key in observations:
                raise ConversionError(
                    f"{source}: duplicate observation for {pod_id!r} at {timestamp}"
                )
            observations[key] = value
    if not observations:
        raise ConversionError(f"{source}: matrix contains no observations")
    return observations


def _format_timestamp(timestamp: float) -> str:
    try:
        value = datetime.fromtimestamp(timestamp, tz=UTC)
    except (OverflowError, OSError, ValueError) as error:
        raise ConversionError(f"timestamp {timestamp!r} is outside the supported range") from error
    return value.isoformat().replace("+00:00", "Z")


def _format_number(value: float) -> str:
    return format(value, ".15g")


def convert_exports(
    cpu_json: Path,
    memory_json: Path,
    output_csv: Path,
    *,
    cpu_unit: str = "cores",
    memory_unit: str = "bytes",
    metric_label: str = "pod",
) -> int:
    """Convert two aligned matrix exports and return the written row count."""

    cpu = parse_matrix_export(
        _load_json(cpu_json), source=str(cpu_json), metric_label=metric_label
    )
    memory = parse_matrix_export(
        _load_json(memory_json), source=str(memory_json), metric_label=metric_label
    )
    cpu_keys = set(cpu)
    memory_keys = set(memory)
    if cpu_keys != memory_keys:
        cpu_only = sorted(cpu_keys - memory_keys)[:3]
        memory_only = sorted(memory_keys - cpu_keys)[:3]
        details = []
        if cpu_only:
            details.append(f"CPU-only examples: {cpu_only}")
        if memory_only:
            details.append(f"memory-only examples: {memory_only}")
        raise ConversionError(
            "CPU and memory exports are not aligned; " + "; ".join(details)
        )

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output_csv.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(("timestamp", "pod_id", "cpu_usage", "memory_usage"))
            for key in sorted(cpu):
                writer.writerow(
                    (
                        _format_timestamp(key.timestamp),
                        key.pod_id,
                        _format_number(CPU_CONVERTERS[cpu_unit](cpu[key])),
                        _format_number(MEMORY_CONVERTERS[memory_unit](memory[key])),
                    )
                )
    except OSError as error:
        raise ConversionError(f"cannot write {output_csv}: {error}") from error
    return len(cpu)


def _discover_export_pairs(input_dir: Path) -> list[tuple[Path, Path]]:
    """Return deterministic ``-cpu.json``/``-mem.json`` pairs."""

    if not input_dir.is_dir():
        raise ConversionError(f"input directory does not exist: {input_dir}")
    cpu_files = {
        path.name.removesuffix("-cpu.json"): path
        for path in input_dir.glob("*-cpu.json")
    }
    memory_files = {
        path.name.removesuffix("-mem.json"): path
        for path in input_dir.glob("*-mem.json")
    }
    names = set(cpu_files) | set(memory_files)
    if not names:
        raise ConversionError(
            f"{input_dir}: no <name>-cpu.json / <name>-mem.json files found"
        )
    missing_cpu = sorted(set(memory_files) - set(cpu_files))
    missing_memory = sorted(set(cpu_files) - set(memory_files))
    if missing_cpu or missing_memory:
        details = []
        if missing_cpu:
            details.append(f"missing CPU files for: {', '.join(missing_cpu)}")
        if missing_memory:
            details.append(f"missing memory files for: {', '.join(missing_memory)}")
        raise ConversionError("missing JSON pairs; " + "; ".join(details))
    return [(cpu_files[name], memory_files[name]) for name in sorted(names)]


def convert_directory(
    input_dir: Path,
    output_csv: Path,
    *,
    pods_output: Path | None = None,
    current_resources: Path | None = None,
    pod_owners: Path | None = None,
    replicaset_owners: Path | None = None,
    cpu_unit: str = "cores",
    memory_unit: str = "bytes",
    metric_label: str = "pod",
) -> int:
    """Combine every named CPU/memory JSON pair into one canonical usage CSV."""

    combined_cpu: dict[ObservationKey, float] = {}
    combined_memory: dict[ObservationKey, float] = {}
    for cpu_path, memory_path in _discover_export_pairs(input_dir):
        cpu = parse_matrix_export(
            _load_json(cpu_path), source=str(cpu_path), metric_label=metric_label
        )
        memory = parse_matrix_export(
            _load_json(memory_path), source=str(memory_path), metric_label=metric_label
        )
        if set(cpu) != set(memory):
            raise ConversionError(
                f"JSON pair {cpu_path.name} / {memory_path.name} is not aligned"
            )
        duplicate_keys = (set(combined_cpu) | set(combined_memory)) & set(cpu)
        if duplicate_keys:
            examples = sorted(duplicate_keys)[:3]
            raise ConversionError(
                f"duplicate observations across JSON pairs; examples: {examples}"
            )
        combined_cpu.update(cpu)
        combined_memory.update(memory)

    current: dict[str, dict[str, float]] = {}
    if current_resources is not None:
        from kubernetes_resource_optimizer.utils.ocp_current import (
            load_current_resources,
        )

        current = load_current_resources(current_resources)
    services: dict[str, str] = {}
    if (pod_owners is None) != (replicaset_owners is None):
        raise ConversionError("provide both pod and ReplicaSet owner exports")
    if pod_owners is not None and replicaset_owners is not None:
        from kubernetes_resource_optimizer.utils.ocp_owners import resolve_services

        services = resolve_services(pod_owners, replicaset_owners)

    histories: dict[str, set[float]] = {}
    for key in combined_cpu:
        histories.setdefault(key.pod_id, set()).add(key.timestamp)
    expected = next(iter(histories.values()))
    if any(timestamps != expected for timestamps in histories.values()):
        raise ConversionError("pod histories are not aligned across all pods")
    if pods_output is not None and pods_output.resolve() == output_csv.resolve():
        raise ConversionError("usage and pod output paths must differ")
    # Validate timestamp formatting before writing any output.
    for timestamp in expected:
        _format_timestamp(timestamp)

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output_csv.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(("timestamp", "pod_id", "cpu_usage", "memory_usage"))
            for key in sorted(combined_cpu):
                writer.writerow(
                    (
                        _format_timestamp(key.timestamp),
                        key.pod_id,
                        _format_number(CPU_CONVERTERS[cpu_unit](combined_cpu[key])),
                        _format_number(
                            MEMORY_CONVERTERS[memory_unit](combined_memory[key])
                        ),
                    )
                )
    except OSError as error:
        raise ConversionError(f"cannot write {output_csv}: {error}") from error
    if pods_output is not None:
        fields = (
            "pod_id", "service_id", "current_cpu_request", "current_memory_request",
            "current_cpu_limit", "current_memory_limit", "cpu_request_max",
            "memory_request_max", "cpu_limit_max", "memory_limit_max",
        )
        try:
            pods_output.parent.mkdir(parents=True, exist_ok=True)
            with pods_output.open("w", encoding="utf-8", newline="") as stream:
                pod_writer = csv.DictWriter(stream, fieldnames=fields)
                pod_writer.writeheader()
                for pod_id in sorted(histories):
                    pod_writer.writerow({
                        "pod_id": pod_id,
                        "service_id": services.get(pod_id, ""),
                        **{field: _format_number(value)
                           for field, value in current.get(pod_id, {}).items()},
                    })
        except OSError as error:
            raise ConversionError(f"cannot write {pods_output}: {error}") from error
    return len(combined_cpu)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Combine OCP/Prometheus CPU and memory matrix JSON pairs into usage.csv."
        )
    )
    parser.add_argument(
        "--input-dir", type=Path, default=Path("data/private/json")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("data/private/usage.csv")
    )
    parser.add_argument(
        "--pods-output", type=Path,
        help="also write a KRO pod CSV for exactly the observed pods",
    )
    parser.add_argument(
        "--current-resources", type=Path,
        help="instant vector of container info, resource requests and limits",
    )
    parser.add_argument("--pod-owners", type=Path, help="kube_pod_owner matrix JSON")
    parser.add_argument(
        "--replicaset-owners", type=Path, help="kube_replicaset_owner matrix JSON"
    )
    parser.add_argument(
        "--cpu-unit", choices=tuple(CPU_CONVERTERS), default="cores"
    )
    parser.add_argument(
        "--memory-unit", choices=tuple(MEMORY_CONVERTERS), default="bytes"
    )
    parser.add_argument(
        "--metric-label",
        default="pod",
        help="metric label containing the pod identifier (default: pod)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        count = convert_directory(
            args.input_dir,
            args.output,
            pods_output=args.pods_output,
            current_resources=args.current_resources,
            pod_owners=args.pod_owners,
            replicaset_owners=args.replicaset_owners,
            cpu_unit=args.cpu_unit,
            memory_unit=args.memory_unit,
            metric_label=args.metric_label,
        )
    except ConversionError as error:
        build_parser().exit(2, f"error: {error}\n")
    print(f"Wrote {count} aligned observations to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
