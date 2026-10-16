#!/bin/bash
# Deletes old chats first, so they don't go into the backup, then backs up the database.
set -uo pipefail

dir=/opt/drxl-chatbot
status=0
"$dir/run-job.sh" cleanup "$dir/compose.sh" run --rm --no-deps app python scripts/cleanup_chats.py || status=1
"$dir/run-job.sh" backup "$dir/backup.sh" || status=1
exit "$status"
