<!--
SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende

SPDX-License-Identifier: EUPL-1.2
-->

# Sicherheitshinweise

## Schwachstellen melden

Bitte melden Sie Sicherheitslücken **nicht** über öffentliche Issues, sondern
vertraulich über die Funktion „Vertrauliches Issue“ des Repositories auf
Open CoDE. Wir bestätigen den Eingang innerhalb von 5 Werktagen.

## Sicherheitsarchitektur (Überblick)

- **Keine externen Verbindungen**: keine CDNs, keine Telemetrie, kein
  Phone-Home. Alle Assets werden lokal ausgeliefert. Die einzigen ausgehenden
  Verbindungen gehen an die selbst konfigurierten Dienste (Ollama, Qdrant,
  Reranker, OIDC-Provider) und — nur bei aktiver Nutzung des Internet-Agenten —
  an die vom Nutzer angegebenen URLs.
- **Passwörter**: argon2id (64 MiB, t=3). **Sessions**: serverseitig, Token nur
  als SHA-256-Hash gespeichert, sofortiger Widerruf möglich, Idle- und
  Absolut-Ablauf, Rotation beim Login.
- **API-Keys**: projektgebunden, Scopes, Ablauf/Widerruf, nur Hash gespeichert,
  Klartext einmalige Anzeige.
- **CSRF**: sessiongebundener Token, von HTMX als Header an alle Requests
  vererbt; unsichere Methoden ohne gültigen Header werden abgelehnt.
- **Mandantentrennung**: eine Qdrant-Collection pro Projekt plus zusätzlicher
  project_id-Filter in jeder Suche (Defense in Depth).
- **Audit-Log**: append-only Protokoll sicherheitsrelevanter Aktionen
  (Logins inkl. Fehlversuche, Rechteänderungen, Schlüssel, Dokumente, Crawls).
- **Rate-Limiting**: Brute-Force-Schutz auf dem Login-Endpunkt.
- **HTML-Ausgabe**: Markdown der Sprachmodelle wird mit nh3 sanitisiert;
  Streaming-Token werden HTML-escaped.

## Bekannte Einschränkungen

- Die Content-Security-Policy erlaubt derzeit `unsafe-inline` für Skripte und
  Styles (Inline-Handler der HTMX-Templates). Umstellung auf Nonces ist geplant.
- Das In-Memory-Rate-Limiting wirkt pro App-Instanz (Zielbild: eine Instanz).

## Betriebsempfehlungen

- GovDesk hinter einem TLS-terminierenden Reverse-Proxy betreiben und
  `GOVDESK_COOKIE_SECURE=true` setzen (Standard).
- `GOVDESK_SECRET_KEY` mit mindestens 48 zufälligen Zeichen erzeugen.
- Datenbank- und Dienst-Ports nicht öffentlich exponieren (Compose-Standard).
