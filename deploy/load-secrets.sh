#!/bin/bash
# Writes /etc/drxl-chatbot/app.env and db.env (root only) from Parameter Store and app.env.defaults.
set -euo pipefail

dir=/opt/drxl-chatbot
set -a
source "$dir/settings.env"
set +a
umask 077

params=$(mktemp)
trap 'rm -f "$params" "$params.app" "$params.db"' EXIT
aws ssm get-parameters-by-path --region "$AWS_REGION" --path /drxl-chatbot --with-decryption \
  --query 'Parameters[].[Name,Value]' --output text > "$params"

value() { awk -F '\t' -v name="/drxl-chatbot/$1" '$1 == name { print $2 }' "$params"; }

for name in ANTHROPIC_API_KEY VOYAGE_API_KEY JWT_SECRET IP_HASH_SECRET POSTGRES_PASSWORD; do
  if [ -z "$(value "$name")" ]; then
    echo "Parameter /drxl-chatbot/$name is missing; run deploy/put-secrets.sh first." >&2
    exit 1
  fi
done

{
  cat "$dir/app.env.defaults"
  for name in ANTHROPIC_API_KEY VOYAGE_API_KEY JWT_SECRET IP_HASH_SECRET; do
    echo "$name=$(value "$name")"
  done
  echo "DATABASE_URL=postgresql://isss:$(value POSTGRES_PASSWORD)@db:5432/isss"
} > "$params.app"
echo "POSTGRES_PASSWORD=$(value POSTGRES_PASSWORD)" > "$params.db"

install -d -m 700 /etc/drxl-chatbot
install -m 600 "$params.app" /etc/drxl-chatbot/app.env
install -m 600 "$params.db" /etc/drxl-chatbot/db.env
