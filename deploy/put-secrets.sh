#!/usr/bin/env bash
# Saves the production secrets in AWS Parameter Store (encrypted). Run it on your own computer:
#   AWS_PROFILE=<your profile> deploy/put-secrets.sh
# API keys are typed in hidden; the random secrets are created once and never changed afterwards,
# because changing them would log everyone out (JWT_SECRET) or lock the app out of its database.
set -euo pipefail

: "${AWS_PROFILE:?Set AWS_PROFILE to your AWS CLI profile, for example AWS_PROFILE=myprofile}"
region="${AWS_REGION:-us-east-1}"
prefix=/drxl-chatbot
export AWS_PAGER=""

exists() { aws ssm get-parameter --region "$region" --name "$prefix/$1" > /dev/null 2>&1; }
put() {
  aws ssm put-parameter --region "$region" --name "$prefix/$1" --type SecureString --overwrite --value "$2" > /dev/null
  echo "  saved $1"
}

for name in ANTHROPIC_API_KEY VOYAGE_API_KEY; do
  if exists "$name"; then
    read -rsp "$name (press Enter to keep the saved one): " value
  else
    read -rsp "$name: " value
  fi
  echo
  if [ -n "$value" ]; then
    put "$name" "$value"
  elif ! exists "$name"; then
    echo "  $name is required" >&2
    exit 1
  fi
done

for name in JWT_SECRET IP_HASH_SECRET POSTGRES_PASSWORD; do
  if exists "$name"; then
    echo "  kept $name"
  else
    put "$name" "$(openssl rand -hex 32)"
  fi
done
