# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

# GovDesk — lokale Entwicklung (macOS/Linux)
# Einstieg:  make setup  →  make dev

COMPOSE := docker compose -f docker-compose.yml -f docker-compose.dev.yml
DIENSTE := postgres qdrant reranker

.DEFAULT_GOAL := hilfe

.PHONY: hilfe setup dienste ollama-check migrate seed dev app worker \
        test lint smoke stop status logs sauber

hilfe: ## Diese Übersicht anzeigen
	@echo "GovDesk — verfügbare Kommandos:"
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  \033[36mmake %-14s\033[0m %s\n", $$1, $$2}'

setup: ## Erstinstallation: Abhängigkeiten, .env, Dienste, Migrationen, Modelle
	uv sync
	@test -f .env || (cp .env.example .env \
	  && sed -i '' 's|^GOVDESK_DATABASE_URL=.*|GOVDESK_DATABASE_URL=postgresql+psycopg://govdesk:govdesk@localhost:5434/govdesk|' .env \
	  && sed -i '' "s|^GOVDESK_SECRET_KEY=.*|GOVDESK_SECRET_KEY=$$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')|" .env \
	  && echo "→ .env angelegt (Postgres-Port 5434, zufälliger Secret-Key)")
	$(MAKE) dienste
	@sleep 3
	$(MAKE) migrate
	$(MAKE) ollama-check
	@echo "✅ Fertig. Weiter mit:  make dev   →  http://localhost:8000"

dienste: ## Postgres, Qdrant und Reranker starten (Docker)
	GOVDESK_SECRET_KEY=dev $(COMPOSE) up -d $(DIENSTE)

ollama-check: ## Prüfen, ob Ollama läuft und Modelle vorhanden sind
	@curl -sf --max-time 2 http://localhost:11434/api/version >/dev/null \
	  && echo "→ Ollama läuft (nativ, nutzt die Mac-GPU)" \
	  || echo "⚠️  Kein Ollama auf :11434 — bitte installieren (https://ollama.com) und starten"
	@curl -sf http://localhost:11434/api/tags 2>/dev/null | grep -q bge-m3 \
	  || echo "⚠️  Embedding-Modell fehlt:  ollama pull bge-m3"
	@curl -sf http://localhost:11434/api/tags 2>/dev/null | grep -q gemma3 \
	  || echo "⚠️  Sprachmodell fehlt (z. B.):  ollama pull gemma3:4b"

migrate: ## Datenbank-Migrationen anwenden
	uv run govdesk migrate

seed: ## Demo-Daten anlegen (Admin, Projekt, Beispieldokument)
	uv run python scripts/seed.py

dev: dienste ## App + Worker zusammen starten (Strg-C beendet beide)
	@trap 'kill 0' INT TERM; \
	uv run govdesk worker & \
	uv run govdesk serve --reload & \
	wait

app: ## Nur den Webserver starten (mit Autoreload)
	uv run govdesk serve --reload

worker: ## Nur den Job-Worker starten
	uv run govdesk worker

test: ## Ruff, mypy und Unit-Tests
	uv run ruff check src tests scripts
	uv run mypy
	uv run pytest tests/unit -q

lint: ## Nur Linting inkl. REUSE-Lizenzprüfung
	uv run ruff check src tests scripts
	uv run ruff format --check src tests scripts
	uv run reuse lint

smoke: ## End-to-End-Smoke-Test gegen die laufende Instanz
	./scripts/smoke_test.sh

status: ## Status der Docker-Dienste anzeigen
	@$(COMPOSE) ps

logs: ## Logs der Docker-Dienste verfolgen
	$(COMPOSE) logs -f $(DIENSTE)

stop: ## Docker-Dienste stoppen (Daten bleiben erhalten)
	$(COMPOSE) stop

sauber: ## Dienste stoppen und ALLE Daten löschen (Vorsicht!)
	@read -p "Wirklich alle Volumes (Datenbank, Vektoren, Modelle) löschen? [j/N] " antwort; \
	[ "$$antwort" = "j" ] && $(COMPOSE) down -v || echo "Abgebrochen."
