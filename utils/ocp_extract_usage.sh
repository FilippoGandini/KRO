#!/usr/bin/env bash

set -euo pipefail

# ---------------------------------------------------------------------------
# Interactive input
# ---------------------------------------------------------------------------

read -rp "Namespace: " NAMESPACE
read -rp "Thanos host: " THANOS_HOST
read -rp "Number of observations: " OBSERVATIONS
read -rp "Collection period (e.g. 24h, 7d, 30d): " PERIOD
read -rp "Output directory [metrics]: " OUTPUT_DIR

OUTPUT_DIR=${OUTPUT_DIR:-metrics}
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PYTHON=${PYTHON:-python3}
JSON_DIR="${OUTPUT_DIR}/json"

command -v "$PYTHON" >/dev/null 2>&1 || {
    echo "ERROR: Python 3.12+ is required (set PYTHON to its executable)." >&2
    exit 1
}
# Avoid mixing observations from different extractions.
if [[ -d "$JSON_DIR" ]] && [[ -n "$(find "$JSON_DIR" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
    echo "ERROR: $JSON_DIR is not empty; choose a fresh output directory." >&2
    exit 1
fi

read -rsp "Token: " TOKEN
echo

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

if [[ -z "$NAMESPACE" || -z "$THANOS_HOST" || -z "$TOKEN" ||
      -z "$OBSERVATIONS" || -z "$PERIOD" ]]; then
    echo "ERROR: all required values must be provided." >&2
    exit 1
fi

if ! [[ "$OBSERVATIONS" =~ ^[1-9][0-9]*$ ]]; then
    echo "ERROR: number of observations must be a positive integer." >&2
    exit 1
fi

command -v curl >/dev/null 2>&1 || {
    echo "ERROR: curl is required." >&2
    exit 1
}

command -v jq >/dev/null 2>&1 || {
    echo "ERROR: jq is required." >&2
    exit 1
}


# ---------------------------------------------------------------------------
# Temporary files
# ---------------------------------------------------------------------------

CPU_TMP=$(mktemp)
MEM_TMP=$(mktemp)

trap 'rm -f "$CPU_TMP" "$MEM_TMP"' EXIT
# ---------------------------------------------------------------------------
# Convert period to seconds
#
# Supported formats:
#   30m
#   24h
#   7d
#   30d
# ---------------------------------------------------------------------------

period_to_seconds() {
    local value="$1"

    if [[ "$value" =~ ^([0-9]+)m$ ]]; then
        echo $(( ${BASH_REMATCH[1]} * 60 ))
    elif [[ "$value" =~ ^([0-9]+)h$ ]]; then
        echo $(( ${BASH_REMATCH[1]} * 3600 ))
    elif [[ "$value" =~ ^([0-9]+)d$ ]]; then
        echo $(( ${BASH_REMATCH[1]} * 86400 ))
    else
        echo "ERROR: unsupported period '$value'." >&2
        echo "Use values such as 30m, 24h, 7d or 30d." >&2
        exit 1
    fi
}

PERIOD_SECONDS=$(period_to_seconds "$PERIOD")

if (( PERIOD_SECONDS < OBSERVATIONS )); then
    echo "ERROR: collection period is too short for the requested number of observations." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Calculate sampling interval
#
# Example:
#   period = 24h
#   observations = 24
#
#   step = 3600 seconds
#
# Each returned value will be the average usage over the preceding step.
# ---------------------------------------------------------------------------

STEP=$(( PERIOD_SECONDS / OBSERVATIONS ))

if (( STEP < 1 )); then
    echo "ERROR: calculated step is less than one second." >&2
    exit 1
fi

# Warn if the period cannot be divided exactly by the number of observations.
if (( PERIOD_SECONDS % OBSERVATIONS != 0 )); then
    echo "WARNING: the collection period is not exactly divisible by the number of observations."
    echo "Calculated step: ${STEP}s"
    echo
fi

# ---------------------------------------------------------------------------
# Time range
#
# END is aligned to a STEP boundary.
#
# START is shifted by one step so that the range query returns N evaluation
# points, where every evaluation point represents the average over the
# preceding interval.
# ---------------------------------------------------------------------------

NOW=$(date +%s)

END=$(( NOW / STEP * STEP ))
PERIOD_START=$(( END - PERIOD_SECONDS ))
START=$(( PERIOD_START + STEP ))


mkdir -p "$JSON_DIR"

echo
echo "Configuration"
echo "-------------"
echo "Namespace:          $NAMESPACE"
echo "Thanos host:        $THANOS_HOST"
echo "Collection period:  $PERIOD"
echo "Observations:       $OBSERVATIONS"
echo "Sampling step:      ${STEP}s"
echo "Period start:       $(date -d "@$PERIOD_START" -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "First observation:  $(date -d "@$START" -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "Last observation:   $(date -d "@$END" -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "Output directory:   $OUTPUT_DIR"
echo

# ---------------------------------------------------------------------------
# CPU query
#
# Returns one time series per pod.
#
# The metric is expressed in CPU cores.
#
# Example:
#   0.5  = 500 millicores
#   1.0  = 1 CPU core
# ---------------------------------------------------------------------------

CPU_QUERY=$(cat <<EOF
max_over_time(
  (
    sum(
      node_namespace_pod_container:container_cpu_usage_seconds_total:sum_irate{
        namespace="$NAMESPACE"
      }
    ) by (pod)
  )[${STEP}s:]
)
EOF
)

# ---------------------------------------------------------------------------
# Memory query
#
# Returns one time series per pod.
#
# container_memory_working_set_bytes is expressed in bytes.
# ---------------------------------------------------------------------------

MEM_QUERY=$(cat <<EOF
max_over_time(
  (
    sum(
      container_memory_working_set_bytes{
        namespace="$NAMESPACE",
        container!="",
        container!="POD"
      }
    ) by (pod)
  )[${STEP}s:]
)
EOF
)

# ---------------------------------------------------------------------------
# Execute a Thanos range query
# ---------------------------------------------------------------------------

query_thanos() {
    local query="$1"
    local output_file="$2"

    curl \
        -k \
        -sS \
        --fail-with-body \
        -G \
        -H "Authorization: Bearer $TOKEN" \
        "https://${THANOS_HOST}/api/v1/query_range" \
        --data-urlencode "query=${query}" \
        --data-urlencode "start=${START}" \
        --data-urlencode "end=${END}" \
        --data-urlencode "step=${STEP}" \
        > "$output_file"
}

# ---------------------------------------------------------------------------
# Query CPU and memory metrics
#
# Four sequential read-only GET queries are sent to Thanos:
#   1. one CPU query for the whole namespace
#   2. one memory query for the whole namespace
#   3-4. controller ownership histories (pod and ReplicaSet)
# ---------------------------------------------------------------------------

echo "Querying CPU metrics..."
query_thanos "$CPU_QUERY" "$CPU_TMP"

echo "Querying memory metrics..."
query_thanos "$MEM_QUERY" "$MEM_TMP"

# ---------------------------------------------------------------------------
# Validate Thanos responses
# ---------------------------------------------------------------------------

validate_response() {
    local file="$1"

    local status
    status=$(jq -r '.status // "unknown"' "$file")

    if [[ "$status" != "success" ]]; then
        echo "ERROR: Thanos query failed for $file" >&2
        jq . "$file" >&2
        exit 1
    fi
}

validate_response "$CPU_TMP"
validate_response "$MEM_TMP"

# Windowed owner gauges also capture controllers that disappeared between steps.
# These only read monitoring data; no Kubernetes write API or oc command is used.
echo "Querying pod controller history (read-only)..."
query_thanos \
    "max_over_time(kube_pod_owner{namespace=\"$NAMESPACE\",owner_is_controller=\"true\"}[${STEP}s])" \
    "${JSON_DIR}/pod-owners.json"
validate_response "${JSON_DIR}/pod-owners.json"

echo "Querying ReplicaSet controller history (read-only)..."
query_thanos \
    "max_over_time(kube_replicaset_owner{namespace=\"$NAMESPACE\",owner_is_controller=\"true\"}[${STEP}s])" \
    "${JSON_DIR}/replicaset-owners.json"
validate_response "${JSON_DIR}/replicaset-owners.json"

if [[ "$(jq '.data.result | length' "${JSON_DIR}/pod-owners.json")" == 0 ]]; then
    echo "WARNING: no pod owner metrics returned; service_id will remain empty." >&2
fi

# ---------------------------------------------------------------------------
# Split namespace-level query results into one JSON file per pod
#
# Example:
#
#   pod-a-cpu.json
#   pod-a-mem.json
#   pod-b-cpu.json
#   pod-b-mem.json
# ---------------------------------------------------------------------------

split_results() {
    local input_file="$1"
    local metric_type="$2"

    jq -c '.data.result[]' "$input_file" |
    while IFS= read -r result; do

        pod=$(jq -r '.metric.pod // empty' <<< "$result")

        if [[ -z "$pod" ]]; then
            echo "ERROR: metric series has no pod label." >&2
            exit 1
        fi

        if ! [[ "$pod" =~ ^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$ ]]; then
            echo "ERROR: invalid pod name: $pod" >&2
            exit 1
        fi
        output_file="${JSON_DIR}/${pod}-${metric_type}.json"
        if [[ -e "$output_file" ]]; then
            echo "ERROR: duplicate pod series: $pod ($metric_type)" >&2
            exit 1
        fi

        jq -n \
            --argjson result "$result" \
            '{
                status: "success",
                data: {
                    resultType: "matrix",
                    result: [$result]
                }
            }' > "$output_file"

        count=$(jq '.data.result[0].values | length' "$output_file")

        echo "Created: $output_file ($count observations)"
    done
}

echo
echo "Creating per-pod files..."

split_results "$CPU_TMP" "cpu"
split_results "$MEM_TMP" "mem"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo "Converting JSON exports to KRO inputs..."
PYTHONPATH="${SCRIPT_DIR}/../src${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON" \
    "${SCRIPT_DIR}/ocp_usage_to_csv.py" \
    --input-dir "$JSON_DIR" \
    --output "${OUTPUT_DIR}/usage.csv" \
    --workloads-output "${OUTPUT_DIR}/workload.csv" \
    --pod-owners "${JSON_DIR}/pod-owners.json" \
    --replicaset-owners "${JSON_DIR}/replicaset-owners.json"

CPU_PODS=$(jq '.data.result | length' "$CPU_TMP")
MEM_PODS=$(jq '.data.result | length' "$MEM_TMP")

echo
echo "Extraction completed."
echo "---------------------"
echo "CPU pod series:     $CPU_PODS"
echo "Memory pod series:  $MEM_PODS"
echo "Output directory:   $OUTPUT_DIR"
echo "Usage CSV:          ${OUTPUT_DIR}/usage.csv"
echo "Workload CSV:       ${OUTPUT_DIR}/workload.csv"
