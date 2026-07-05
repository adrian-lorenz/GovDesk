<!--
SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende

SPDX-License-Identifier: EUPL-1.2
-->

# GovDesk

**Souveräne, self-hostbare KI/RAG-Plattform für Behörden.**

GovDesk ermöglicht es Behörden und öffentlichen Einrichtungen, eigene Dokumente und
Online-Quellen (z. B. Gesetze) mit lokalen KI-Modellen zu durchsuchen und in
projektbasierten Chats mit Quellenangaben zu nutzen — vollständig on-premises,
ohne Cloud-Zwang, ohne Telemetrie.

## Funktionsumfang

- 📁 **Projekte** mit Rollen und Berechtigungen (Eigentümer, Admin, Bearbeiter, Betrachter)
- 📄 **Dokument-Ingestion**: PDF, DOCX, ODT, TXT, Markdown, HTML — per UI oder REST-API mit API-Keys
- 🔍 **RAG-Suche** mit Qdrant (Vektordatenbank), bge-m3-Embeddings und Reranker (bge-reranker-v2-m3)
- 💬 **Konfigurierbare Chats** pro Projekt: System-Prompt, Modell, Temperatur, Quellenauswahl — Antworten mit Zitaten
- 🌐 **Internet-Agent**: Webseiten crawlen, extrahieren und einbetten — wahlweise **KI-geführt**: Sie geben eine Start-URL und einen Suchauftrag an, der Agent entscheidet selbst, welchen Links er folgt und welche Inhalte relevant sind. Inkl. periodischem Re-Crawl (robots.txt wird respektiert)
- 🤖 **Ollama** lokal oder Cloud; Provider-Abstraktion für OpenAI-kompatible Endpunkte
- 🔐 **Eigene Nutzerverwaltung** plus optionale **Keycloak/OIDC**-Anbindung
- 🧙 **Einrichtungs-Wizard** beim ersten Start: Verbindungstests, Modellauswahl mit Download-Fortschritt, Admin-Konto
- 🌓 Material-Design-Oberfläche (Beer CSS) mit Hell/Dunkel-Umschaltung, alle Assets lokal (kein CDN)

## Schnellstart

```bash
cp .env.example .env    # Werte anpassen (mindestens GOVDESK_SECRET_KEY)
docker compose up -d --wait
# Erststart: http://localhost:8000 → Einrichtungs-Wizard
```

## Nutzung — in fünf Schritten

Nach dem Start (`http://localhost:8000`) führt Sie der Einrichtungs-Wizard einmalig
durch Verbindungstests, Modellauswahl und das Anlegen des ersten Admin-Kontos.
Danach arbeiten Sie so:

1. **Projekt anlegen.** Ein Projekt bündelt Dokumente, Chats und Zugriffsrechte zu
   einem Thema (z. B. „Vergaberecht" oder „Hausnotruf"). Über *Mitglieder* laden Sie
   Kolleginnen mit passender Rolle ein — **Betrachter** (nur chatten), **Bearbeiter**
   (Dokumente pflegen), **Admin** (Projekt verwalten).

2. **Wissen hinzufügen.** Drei Wege, alle landen in derselben durchsuchbaren
   Wissensbasis:
   - **Hochladen** — PDF, DOCX, ODT, TXT, Markdown oder HTML per Drag-and-drop.
   - **Internet-Agent** (*Verwalten* in der Karte „Internet-Quellen"): Start-URL
     angeben und optional einen **Suchauftrag** formulieren, z. B. „Fristen und
     Zuständigkeiten im Vergaberecht". Mit „Unterseiten einbeziehen" folgt der
     KI-Agent selbstständig relevanten Links und bettet nur passende Seiten ein.
   - **REST-API** — für automatisierte Übernahme aus Fremdsystemen (siehe *API-Keys*).

   Dokumente lassen sich in **Sammlungen** gruppieren; der Fortschritt
   (Parsen → Einbetten → bereit) wird live angezeigt.

3. **Chatten mit Quellen.** Im Chat stellen Sie Fragen in natürlicher Sprache.
   Die Antwort wird aus den eingebetteten Dokumenten belegt — jede Aussage ist mit
   der **Quelle** verknüpft und nachvollziehbar. Nichts verlässt Ihre Instanz.

4. **Chat-Profile zuschneiden.** Pro Projekt konfigurieren Sie unter *Chat-Profile*
   System-Prompt, Modell, Temperatur und die berücksichtigten Sammlungen — etwa ein
   sachlich-knappes Profil für Rechtsauskünfte und ein ausführlicheres für Einarbeitung.

5. **Prüfen & verwalten.** Der **Retrieval-Test** zeigt, welche Textstellen zu einer
   Frage gefunden werden (ideal zum Feinjustieren). Über **API-Keys** binden Sie
   Fremdsysteme an, in den **Admin-Einstellungen** wählen Sie den KI-Provider
   (lokales Ollama oder ein OpenAI-kompatibler Endpunkt), passen das Branding an und
   sehen den Live-Status aller Dienste.

Größere Vorhaben (Massen-Import, Import/Export, Passwort-Richtlinie,
Kubernetes/Podman) stehen in der [ROADMAP.md](ROADMAP.md).

## Entwicklung

Voraussetzungen: [uv](https://docs.astral.sh/uv/), Docker und — auf macOS —
ein natives [Ollama](https://ollama.com) (nutzt die Apple-GPU; unter Linux
tut es auch der Compose-Container).

```bash
make setup    # einmalig: Abhängigkeiten, .env, Dienste, Migrationen
make dev      # App (mit Autoreload) + Worker — http://localhost:8000
```

Alle weiteren Kommandos zeigt `make hilfe` (u. a. `make seed` für Demo-Daten,
`make test`, `make smoke`, `make stop`). Ohne make:

```bash
uv sync
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres qdrant reranker
uv run govdesk migrate
uv run govdesk serve --reload       # App auf http://localhost:8000
uv run govdesk worker               # Job-Worker (zweites Terminal)
```

## Betrieb (Produktion)

### Reverse-Proxy & TLS

GovDesk gehört hinter einen TLS-terminierenden Reverse-Proxy. Für SSE-Streaming
(Chat) muss Response-Buffering aus sein — nginx-Beispiel:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;          # wichtig für SSE
    proxy_read_timeout 300s;
}
```

`GOVDESK_COOKIE_SECURE=true` setzen (Standard) und `GOVDESK_SECRET_KEY`
mit `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` erzeugen.

### Modelle vorab laden / Offline-Betrieb

Beim ersten Start werden Modelle heruntergeladen (bge-m3 ≈ 1,2 GB,
gemma3:4b ≈ 3,3 GB, Reranker ≈ 2,3 GB). Für Air-Gap-Umgebungen:

```bash
docker compose exec ollama ollama pull bge-m3
docker compose exec ollama ollama pull gemma3:4b
# Reranker-Cache liegt im Volume "reranker_cache"; vorbefüllen und
# HF_HUB_OFFLINE=1 setzen, dann findet kein Download mehr statt.
```

Alle Modell-Caches liegen in benannten Docker-Volumes und überleben Updates.

### GPU

Ollama profitiert stark von einer GPU. NVIDIA-Beispiel im Compose-Override:

```yaml
services:
  ollama:
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
```

### Keycloak / SSO

```bash
GOVDESK_OIDC_ENABLED=true
GOVDESK_OIDC_ISSUER=https://keycloak.example.de/realms/behoerde
GOVDESK_OIDC_CLIENT_ID=govdesk
GOVDESK_OIDC_CLIENT_SECRET=…
#GOVDESK_LOCAL_LOGIN_ENABLED=false   # nur SSO zulassen
```

Redirect-URI im Keycloak-Client: `https://govdesk.example.de/auth/oidc/callback`.
Zum Ausprobieren: `docker compose --profile keycloak up -d` startet ein
Keycloak mit Demo-Realm (siehe `deploy/keycloak/`).

### Headless-Administration

```bash
docker compose exec app govdesk createadmin --username admin   # ohne Wizard
./scripts/smoke_test.sh                                        # End-to-End-Check
```

## Technik

Python 3.14 · FastAPI · HTMX · PostgreSQL · Qdrant · Ollama · procrastinate ·
Text-Embeddings-Inference (Reranker) · Docker Compose

## Lizenz

[EUPL-1.2](LICENSE) — Lizenz der Europäischen Union, geeignet für Software der öffentlichen Hand.
