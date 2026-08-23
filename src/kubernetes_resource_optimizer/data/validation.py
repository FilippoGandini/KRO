"""Cross-record and semantic input validation."""

import math
from collections import Counter, defaultdict
from datetime import datetime

from kubernetes_resource_optimizer.data.models import InputData


class InputValidationError(ValueError):
    """Raised with all input validation failures discovered in one pass."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("Input validation failed:\n- " + "\n- ".join(errors))


def _duplicates(values: list[str]) -> list[str]:
    return sorted(value for value, count in Counter(values).items() if count > 1)


def validate_input_data(data: InputData) -> None:
    """Validate identifiers, values, references, and aligned scenarios."""

    errors: list[str] = []
    node_duplicates = _duplicates([node.node_id for node in data.nodes])
    pod_duplicates = _duplicates([pod.pod_id for pod in data.pods])
    if node_duplicates:
        errors.append(f"duplicate node_id values: {', '.join(node_duplicates)}")
    if pod_duplicates:
        errors.append(f"duplicate pod_id values: {', '.join(pod_duplicates)}")

    if not data.nodes:
        errors.append("nodes.csv must contain at least one node")
    if not data.pods:
        errors.append("pods.csv must contain at least one pod")
    if not data.usage_samples:
        errors.append("usage.csv must contain at least one usage sample")

    for node in data.nodes:
        for field, value in (
            ("cpu_capacity", node.cpu_capacity),
            ("memory_capacity", node.memory_capacity),
        ):
            if not math.isfinite(value) or value <= 0:
                errors.append(
                    f"node {node.node_id!r} {field} must be finite and positive"
                )

    for pod in data.pods:
        optional_values = {
            "current_cpu_request": pod.current_cpu_request,
            "current_memory_request": pod.current_memory_request,
            "current_cpu_limit": pod.current_cpu_limit,
            "current_memory_limit": pod.current_memory_limit,
            "cpu_request_max": pod.cpu_request_max,
            "memory_request_max": pod.memory_request_max,
            "cpu_limit_max": pod.cpu_limit_max,
            "memory_limit_max": pod.memory_limit_max,
        }
        for field, value in optional_values.items():
            if value is not None and (not math.isfinite(value) or value < 0):
                errors.append(
                    f"pod {pod.pod_id!r} {field} must be finite and non-negative"
                )

    known_pods = {pod.pod_id for pod in data.pods}
    sample_keys = [(sample.timestamp, sample.pod_id) for sample in data.usage_samples]
    duplicate_samples = [
        key for key, count in Counter(sample_keys).items() if count > 1
    ]
    for timestamp, pod_id in sorted(duplicate_samples):
        errors.append(
            f"duplicate usage sample for pod {pod_id!r} at {timestamp.isoformat()}"
        )

    scenarios: defaultdict[str, set[datetime]] = defaultdict(set)
    for sample in data.usage_samples:
        if sample.pod_id not in known_pods:
            errors.append(f"usage references unknown pod_id {sample.pod_id!r}")
        if sample.cpu_usage < 0 or not math.isfinite(sample.cpu_usage):
            errors.append(
                f"usage for {sample.pod_id!r} at {sample.timestamp.isoformat()} "
                "has invalid cpu_usage"
            )
        if sample.memory_usage < 0 or not math.isfinite(sample.memory_usage):
            errors.append(
                f"usage for {sample.pod_id!r} at {sample.timestamp.isoformat()} "
                "has invalid memory_usage"
            )
        if sample.pod_id in known_pods:
            scenarios[sample.pod_id].add(sample.timestamp)

    expected: set[datetime] | None = None
    expected_pod = ""
    for pod_id in sorted(known_pods):
        timestamps = scenarios[pod_id]
        if not timestamps:
            errors.append(f"pod {pod_id!r} has no usage samples")
        elif expected is None:
            expected = timestamps
            expected_pod = pod_id
        elif timestamps != expected:
            errors.append(
                f"pod {pod_id!r} has inconsistent scenario timestamps "
                f"compared with pod {expected_pod!r}"
            )

    if errors:
        raise InputValidationError(errors)
