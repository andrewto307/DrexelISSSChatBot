#!/bin/bash
# Dumps the database and uploads it to the backup bucket, which deletes backups after 5 days.
set -euo pipefail

dir=/opt/drxl-chatbot
set -a
source "$dir/settings.env"
set +a

stamp=$(date -u +%Y-%m-%dT%H-%M-%SZ)
file=$(mktemp /var/tmp/backup.XXXXXX)
trap 'rm -f "$file"' EXIT

"$dir/compose.sh" exec -T db pg_dump -U isss -d isss --format=custom > "$file"
aws s3 cp "$file" "s3://$BACKUP_BUCKET/postgres/$stamp.dump" --only-show-errors
printf '{"event": "backup", "key": "postgres/%s.dump", "bytes": %d}\n' "$stamp" "$(stat -c %s "$file")"
