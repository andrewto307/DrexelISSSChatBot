#!/bin/bash
# restore.sh [backup key]           restores a backup into a scratch database and compares row counts
# restore.sh <backup key> --replace replaces the live database with the backup (asks first)
set -euo pipefail

dir=/opt/drxl-chatbot
set -a
source "$dir/settings.env"
set +a

key="${1:-}"
if [ -z "$key" ]; then
  key=$(aws s3api list-objects-v2 --bucket "$BACKUP_BUCKET" --prefix postgres/ \
    --query 'sort_by(Contents, &LastModified)[-1].Key' --output text)
fi
file=$(mktemp /var/tmp/restore.XXXXXX)
trap 'rm -f "$file"' EXIT
aws s3 cp "s3://$BACKUP_BUCKET/$key" "$file" --only-show-errors

psql() { "$dir/compose.sh" exec -T db psql -U isss -v ON_ERROR_STOP=1 "$@"; }
restore_into() { "$dir/compose.sh" exec -T db pg_restore -U isss -d "$1" --no-owner < "$file"; }

if [ "${2:-}" = "--replace" ]; then
  read -rp "This replaces the live database with $key. Type REPLACE to continue: " answer
  [ "$answer" = REPLACE ] || exit 1
  "$dir/compose.sh" stop app
  psql -d postgres -c "DROP DATABASE isss WITH (FORCE)" -c "CREATE DATABASE isss OWNER isss"
  restore_into isss
  "$dir/compose.sh" start app
  echo "Restored $key into the live database."
else
  psql -d postgres -c "DROP DATABASE IF EXISTS restore_check" -c "CREATE DATABASE restore_check OWNER isss"
  restore_into restore_check
  echo "Backup $key, row counts (live / backup):"
  for table in pages chunks users conversations messages feedback; do
    printf '  %-14s %8s / %s\n' "$table" "$(psql -d isss -Atc "SELECT count(*) FROM $table")" \
      "$(psql -d restore_check -Atc "SELECT count(*) FROM $table")"
  done
  psql -d postgres -c "DROP DATABASE restore_check"
fi
