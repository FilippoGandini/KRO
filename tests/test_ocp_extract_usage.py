"""Exercise the shell exporter with a fake curl: no network or cluster access."""

import csv
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def test_exporter_uses_only_five_read_queries_and_resolves_service(tmp_path: Path) -> None:
    if shutil.which("jq") is None:
        pytest.skip("shell exporter requires jq")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_curl = bin_dir / "curl"
    fake_curl.write_text(f"#!{sys.executable}\n" + '''
import json
import os
import sys
args = sys.argv[1:]
assert "-G" in args
assert not any(arg in args for arg in ("-X", "--request", "--data", "-d"))
assert any(url in args for url in ("https://thanos.invalid/api/v1/query_range",
                                   "https://thanos.invalid/api/v1/query"))
query = next(arg[6:] for arg in args if arg.startswith("query="))
assert 'namespace="demo"' in query
metric = {"pod": "api-a"}
value = "1"
if "kube_pod_container_(info|resource_requests|resource_limits)" in query:
    assert "https://thanos.invalid/api/v1/query" in args
    assert any(arg.startswith("time=") for arg in args)
    with open(os.environ["QUERY_LOG"], "a") as stream:
        stream.write(json.dumps(query) + "\\n")
    records = []
    for name, resource, unit, value in (
        ("info", None, None, "1"),
        ("resource_requests", "cpu", "core", "0.25"),
        ("resource_limits", "memory", "byte", "536870912"),
    ):
        labels = dict(__name__="kube_pod_container_" + name, namespace="demo",
                      pod="api-a", container="app")
        if resource:
            labels.update(resource=resource, unit=unit)
        records.append({"metric": labels, "value": [1787562000, value]})
    print(json.dumps({"status": "success", "data": {"resultType": "vector", "result": records}}))
    sys.exit(0)
if "kube_pod_owner" in query:
    metric.update(namespace="demo", owner_kind="ReplicaSet",
                  owner_name="api-rs", owner_is_controller="true")
elif "kube_replicaset_owner" in query:
    metric = dict(namespace="demo", replicaset="api-rs", owner_kind="Deployment",
                  owner_name="api", owner_is_controller="true")
elif "container_memory_working_set_bytes" in query:
    value = "1048576"
else:
    assert "container_cpu_usage_seconds_total" in query
with open(os.environ["QUERY_LOG"], "a") as stream:
    stream.write(json.dumps(query) + "\\n")
print(json.dumps({"status": "success", "data": {"resultType": "matrix", "result": [
    {"metric": metric, "values": [[1787562000, value]]}
]}}))
''')
    fake_curl.chmod(0o755)
    fake_date = bin_dir / "date"
    fake_date.write_text('#!/bin/sh\nif [ "$1" = "+%s" ]; then echo 1787562000; '
                         'else echo 2026-08-24T09:00:00Z; fi\n')
    fake_date.chmod(0o755)
    output = tmp_path / "output with spaces"
    log = tmp_path / "queries.jsonl"
    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["bash", str(repo / "utils/ocp_extract_usage.sh")],
        input=f"demo\nthanos.invalid\n1\n1h\n{output}\nfake-token\n",
        text=True, capture_output=True, cwd=tmp_path,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
             "PYTHON": sys.executable, "QUERY_LOG": str(log)},
        timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    queries = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(queries) == 5
    assert "kube_pod_owner" in queries[2]
    assert "kube_replicaset_owner" in queries[3]
    assert {path.name for path in (output / "json").iterdir()} == {
        "api-a-cpu.json", "api-a-mem.json", "pod-owners.json", "replicaset-owners.json",
        "current-resources.json",
    }
    with (output / "pods.csv").open() as stream:
        row = next(csv.DictReader(stream))
    assert row["service_id"] == "Deployment/api"
    assert row["current_cpu_request"] == "0.25"
    assert row["current_memory_limit"] == "512"
    assert row["current_cpu_limit"] == ""
    with (output / "usage.csv").open() as stream:
        row = next(csv.DictReader(stream))
    assert row["memory_usage"] == "1"
