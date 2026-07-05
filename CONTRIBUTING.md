<!--
SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende

SPDX-License-Identifier: EUPL-1.2
-->

# Mitwirken an GovDesk

Beiträge sind willkommen — von Fehlerberichten über Doku bis zu Code.

## Entwicklungsumgebung

```bash
make setup     # einmalig: uv sync, .env, Docker-Dienste, Migrationen
make dev       # App (Autoreload) + Worker in einem Terminal
make hilfe     # alle Kommandos
```

Hinweis macOS: Ollama nativ installieren (Metal-GPU); `make ollama-check`
prüft Erreichbarkeit und Modelle. Der Dev-Postgres lauscht auf **5434**,
um Kollisionen mit lokalen Installationen zu vermeiden.

Erster Aufruf von http://localhost:8000 startet den Einrichtungs-Wizard.
Alternativ: `uv run python scripts/seed.py` legt Demo-Daten an.

## Qualitätssicherung

```bash
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy
uv run pytest tests/unit -q          # schnell, ohne Dienste
uv run pytest tests -q               # inkl. Integration (Dienste nötig)
./scripts/smoke_test.sh              # End-to-End gegen laufende Instanz
uv run reuse lint                    # Lizenz-Compliance (REUSE)
```

Jeder Merge Request muss die Lint- und Unit-Stufen der CI bestehen.

## Konventionen

- **Sprache**: UI-Texte, Doku und Commit-Messages auf Deutsch; Bezeichner im
  Code auf Englisch.
- **Lizenz**: EUPL-1.2. Jede neue Datei erhält einen SPDX-Header
  (`reuse lint` prüft das).
- **Migrationen**: `uv run alembic revision --autogenerate -m "…"` — bitte das
  generierte Skript prüfen; fremde Tabellen (procrastinate_*) werden gefiltert.
- **Vertikale Slices**: Features möglichst end-to-end (Modell → Service →
  Route → Template → Test) in einem MR.

## Manuelle Prüf-Checkliste vor Releases

- [ ] Einrichtungs-Wizard auf leerer Datenbank durchlaufen
- [ ] OIDC-Flow gegen Compose-Keycloak (`--profile keycloak`)
- [ ] `.doc`-Konvertierung mit `GOVDESK_ENABLE_DOC_CONVERT=true`
- [ ] Crawler gegen eine gesetze-im-internet.de-Seite, Re-Crawl-Intervall
- [ ] `./scripts/smoke_test.sh` gegen den vollen Compose-Stack
