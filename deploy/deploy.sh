#!/bin/bash
# Starts the given image tag. If it doesn't come up healthy, starts the previous tag again and fails.
set -euo pipefail

tag="${1:?usage: deploy.sh <image tag>}"
dir=/opt/drxl-chatbot
set -a
source "$dir/settings.env"
set +a
export ENV_DIR=/etc/drxl-chatbot
compose=(docker compose -f "$dir/docker-compose.prod.yml" -f "$dir/docker-compose.aws.yml")

event() { printf '{"event": "deploy", "tag": "%s", "status": "%s"}\n' "$tag" "$1"; }

start() {
  export APP_IMAGE="$ECR_REPOSITORY:$1"
  "${compose[@]}" up -d --wait db
  "${compose[@]}" run --rm --no-deps app python scripts/migrate.py
  "${compose[@]}" up -d --wait --wait-timeout 180 --remove-orphans
}

"$dir/load-secrets.sh"
previous=$(cat "$dir/current-tag" 2> /dev/null || true)

if start "$tag"; then
  echo "$tag" > "$dir/current-tag"
  install -m 644 "$dir"/systemd/* /etc/systemd/system/
  install -m 644 "$dir/logrotate.conf" /etc/logrotate.d/drxl-chatbot
  systemctl daemon-reload
  systemctl enable --now drxl-chatbot-health.timer drxl-chatbot-nightly.timer drxl-chatbot-update.timer
  docker image prune -af --filter "until=168h" > /dev/null || true
  event deployed
else
  event failed
  if [ -n "$previous" ] && [ "$previous" != "$tag" ]; then
    start "$previous" && event "rolled back to $previous"
  fi
  exit 1
fi
