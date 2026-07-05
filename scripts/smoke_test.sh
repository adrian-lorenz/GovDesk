#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2
#
# End-to-End-Smoke-Test gegen eine laufende GovDesk-Instanz.
# Voraussetzungen: App + Worker + Dienste laufen, Setup ist abgeschlossen,
# Admin-Zugangsdaten unten stimmen (Default: scripts/seed.py).
#
# Nutzung: BASE_URL=http://localhost:8000 ./scripts/smoke_test.sh

set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_PASS="${ADMIN_PASS:-GovDesk-Demo-2026!}"
JAR="$(mktemp)"
trap 'rm -f "$JAR"' EXIT

fehler() { echo "❌ $1" >&2; exit 1; }
ok() { echo "✅ $1"; }

# 1) Health
curl -sf "$BASE_URL/healthz" | grep -q '"status":"ok"' || fehler "healthz"
ok "healthz"

# 2) Login
curl -sf -c "$JAR" -o /dev/null -X POST "$BASE_URL/login" \
  -d "username=$ADMIN_USER&password=$ADMIN_PASS" || fehler "Login"
CSRF=$(curl -sf -b "$JAR" "$BASE_URL/projects" \
  | grep -o '"X-CSRF-Token": "[^"]*"' | sed 's/.*: "//;s/"//')
[ -n "$CSRF" ] || fehler "CSRF-Token nicht gefunden — Login fehlgeschlagen?"
ok "Login + CSRF"

# 3) Projekt anlegen
PROJEKT=$(curl -sf -b "$JAR" -H "X-CSRF-Token: $CSRF" -o /dev/null -w '%{redirect_url}' \
  -X POST "$BASE_URL/projects" -d "name=Smoke-Test $(date +%s)&description=automatisch")
[ -n "$PROJEKT" ] || fehler "Projekt anlegen"
ok "Projekt: $PROJEKT"

# 4) API-Key erstellen
KEY=$(curl -sf -b "$JAR" -H "X-CSRF-Token: $CSRF" -X POST "$PROJEKT/api-keys" \
  -d "name=smoke&gueltig_tage=0&scopes=documents:read&scopes=documents:write&scopes=search:read" \
  | grep -o 'id="neuer-key">[^<]*' | sed 's/.*>//')
[ -n "$KEY" ] || fehler "API-Key erstellen"
ok "API-Key erstellt"

# 5) Dokument per API hochladen
DOKUMENT=$(mktemp -t smoke.XXXXXX).txt
printf '§ 1 Smoke-Test\nDie Antwortzeit des Systems beträgt höchstens dreißig Sekunden.\n' > "$DOKUMENT"
DOC_ID=$(curl -sf -H "Authorization: Bearer $KEY" -F "datei=@$DOKUMENT" \
  "$BASE_URL/api/v1/documents" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
rm -f "$DOKUMENT"
ok "Upload: $DOC_ID"

# 6) Auf Ingestion warten
for i in $(seq 1 60); do
  STATUS=$(curl -sf -H "Authorization: Bearer $KEY" "$BASE_URL/api/v1/documents/$DOC_ID" \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['status'])")
  [ "$STATUS" = "ready" ] && break
  [ "$STATUS" = "failed" ] && fehler "Ingestion fehlgeschlagen"
  sleep 2
done
[ "$STATUS" = "ready" ] || fehler "Ingestion-Timeout (Status: $STATUS) — läuft der Worker?"
ok "Ingestion: ready"

# 7) Suche findet den Inhalt
curl -sf -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -X POST "$BASE_URL/api/v1/search" -d '{"query":"Wie schnell antwortet das System?","top_k":3}' \
  | grep -q "dreißig Sekunden" || fehler "Suche findet Inhalt nicht"
ok "Suche"

# 8) Chat mit SSE-Antwort
CHAT=$(curl -sf -b "$JAR" -H "X-CSRF-Token: $CSRF" -o /dev/null -w '%{redirect_url}' \
  -X POST "$PROJEKT/chats" -d "chat_config_id=")
curl -sf -b "$JAR" -H "X-CSRF-Token: $CSRF" -o /dev/null -X POST "$CHAT/messages" \
  --data-urlencode "frage=Wie schnell antwortet das System laut Dokument?"
STREAM=$(curl -sf -N -b "$JAR" --max-time 180 "$CHAT/stream")
echo "$STREAM" | grep -q "event: token" || fehler "Chat streamt keine Token"
echo "$STREAM" | grep -q "event: done" || fehler "Chat sendet kein done-Event"
ok "Chat-Streaming inkl. Abschluss-Event"

echo
echo "🎉 Smoke-Test erfolgreich."
