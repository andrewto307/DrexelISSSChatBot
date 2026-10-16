#!/bin/bash
# run-job.sh <name> <command...>: runs a scheduled job and logs one JSON line with the result.
set -uo pipefail

name="$1"
shift
started=$(date +%s)
if "$@"; then
  printf '{"event": "job_done", "job": "%s", "seconds": %d}\n' "$name" "$(($(date +%s) - started))"
else
  code=$?
  printf '{"event": "job_failed", "job": "%s", "exit_code": %d}\n' "$name" "$code"
  exit "$code"
fi
