#!/bin/bash
# docker compose for the running deployment, for example: compose.sh ps, compose.sh logs app
set -euo pipefail

dir=/opt/drxl-chatbot
set -a
source "$dir/settings.env"
set +a
export ENV_DIR=/etc/drxl-chatbot
tag=$(cat "$dir/current-tag")
export APP_IMAGE="$ECR_REPOSITORY:$tag"
exec docker compose -f "$dir/docker-compose.prod.yml" -f "$dir/docker-compose.aws.yml" "$@"
