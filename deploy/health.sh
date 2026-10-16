#!/bin/bash
# Checks the site through Caddy and its certificate, as a visitor would, and logs the result.
set -uo pipefail

set -a
source /opt/drxl-chatbot/settings.env
set +a

ok=false
if curl -fsS --max-time 10 --resolve "$SITE_ADDRESS:443:127.0.0.1" "https://$SITE_ADDRESS/health" > /dev/null; then
  ok=true
fi
printf '{"event": "health", "ok": %s}\n' "$ok"
