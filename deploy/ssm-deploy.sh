#!/usr/bin/env bash
# Deploys an image tag on the server: pulls it, copies its deploy/ files to /opt/drxl-chatbot, runs deploy.sh.
#   AWS_REGION=... INSTANCE_ID=... ECR_REPOSITORY=... deploy/ssm-deploy.sh <image tag>
set -euo pipefail

tag="${1:?usage: ssm-deploy.sh <image tag>}"
: "${AWS_REGION:?}" "${INSTANCE_ID:?}" "${ECR_REPOSITORY:?}"
image="$ECR_REPOSITORY:$tag"

SSM_TIMEOUT=900 SSM_COMMENT="deploy $tag" "$(dirname "$0")/ssm-run.sh" "$(
  cat << SCRIPT
set -euo pipefail
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin ${ECR_REPOSITORY%%/*}
docker pull --quiet $image
container=\$(docker create $image)
docker cp \$container:/app/deploy/. /opt/drxl-chatbot/
docker rm \$container > /dev/null
chmod 755 /opt/drxl-chatbot/*.sh
/opt/drxl-chatbot/deploy.sh $tag
SCRIPT
)"
