#!/usr/bin/env bash
# Runs shell commands on the server through SSM Run Command (no SSH) and prints their output.
#   AWS_REGION=... INSTANCE_ID=... deploy/ssm-run.sh '<commands>'
# Set SSM_TIMEOUT (seconds, default 600) for long jobs.
set -euo pipefail

: "${AWS_REGION:?}" "${INSTANCE_ID:?}"
commands="${1:?usage: ssm-run.sh '<commands>'}"
export AWS_PAGER=""

parameters=$(SSM_TIMEOUT="${SSM_TIMEOUT:-600}" python3 -c '
import json, os, sys
lines = ["export HOME=/root"] + sys.stdin.read().splitlines()
print(json.dumps({"commands": lines, "executionTimeout": [os.environ["SSM_TIMEOUT"]]}))
' <<< "$commands")

command_id=$(aws ssm send-command --region "$AWS_REGION" --instance-ids "$INSTANCE_ID" \
  --document-name AWS-RunShellScript --comment "${SSM_COMMENT:-ssm-run}" --parameters "$parameters" \
  --query Command.CommandId --output text)
echo "SSM command $command_id" >&2

invocation() {
  aws ssm get-command-invocation --region "$AWS_REGION" --command-id "$command_id" --instance-id "$INSTANCE_ID" "$@"
}
status=Pending
while :; do
  sleep 3
  status=$(invocation --query Status --output text 2> /dev/null || echo Pending)
  case "$status" in Pending | InProgress | Delayed) ;; *) break ;; esac
done

invocation --query StandardOutputContent --output text
errors=$(invocation --query StandardErrorContent --output text)
[ -n "$errors" ] && [ "$errors" != "None" ] && echo "$errors" >&2
echo "Status: $status" >&2
[ "$status" = Success ]
