<!--
SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende

SPDX-License-Identifier: EUPL-1.2
-->

# Roadmap

Diese Roadmap beschreibt die geplante Weiterentwicklung von GovDesk. Sie ist
richtungsweisend, kein verbindlicher Zeitplan — Prioritäten ergeben sich aus dem
Bedarf der einsetzenden Behörden. Beiträge und Vorschläge sind willkommen
(siehe [CONTRIBUTING.md](CONTRIBUTING.md)).

**Legende:** 🟢 in Arbeit · 🔵 geplant · ⚪ Idee

---

## 🔵 Lokale Passwort-Richtlinie

Für Instanzen mit eigener Nutzerverwaltung (ohne OIDC/SSO) soll eine
konfigurierbare Passwort-Richtlinie durchgesetzt werden — angelehnt an die
Empfehlungen des BSI (IT-Grundschutz).

- Mindestlänge und Komplexität (Zeichenklassen), zentral über Admin-Einstellungen konfigurierbar
- Abgleich gegen eine Liste bekannter/kompromittierter Passwörter
- Optionales Passwort-Ablaufintervall und Sperre nach zu vielen Fehlversuchen (Brute-Force-Schutz)
- Erzwungener Wechsel initialer Admin-Passwörter beim ersten Login
- Greift nur für lokale Konten; bei OIDC bleibt die Richtlinie beim Identity-Provider

## 🔵 Guardrails (Ein- & Ausgabe-Absicherung)

Konfigurierbare Leitplanken für Chat-Ein- und -Ausgaben, damit der Assistent im
behördlichen Einsatz kontrollierbar und rechtssicher bleibt.

- Eingabe-Prüfung: Prompt-Injection- und Jailbreak-Erkennung, Blocklisten, Themen-/Scope-Begrenzung pro Chat-Profil
- Ausgabe-Prüfung: Filter gegen unbelegte Aussagen (nur aus Quellen antworten), Sperrbegriffe, Ton-/Format-Vorgaben
- PII-Erkennung und optionales Schwärzen (Namen, Aktenzeichen, Kontaktdaten) in Ein- und Ausgaben
- Zentrale Konfiguration in den Plattform-Einstellungen, pro Projekt/Chat-Profil überschreibbar; ausgelöste Guardrails landen im Audit-Log
- Lokal/souverän lauffähig (kein externer Moderations-Dienst) — regelbasiert plus optional ein kleines lokales Klassifikationsmodell

## 🔵 Massen-Import & Sync-Agent

Über den bestehenden Internet-Agent hinaus ein Agent, der große Bestände
automatisiert und wiederkehrend in ein Projekt übernimmt.

- Quellen: lokale Verzeichnisse / Netzlaufwerke, S3-kompatibler Objektspeicher, WebDAV/SharePoint
- Geplante Synchronisation (Cron-artig) mit Delta-Erkennung — nur neue/geänderte Dateien werden neu eingebettet
- Deduplizierung und Fortschritts-/Fehlerbericht pro Lauf
- Nutzt dieselbe Ingestion-Pipeline (Parsen → Chunken → Embedden → Qdrant) wie Upload und Crawler
- Verwaltung und Live-Status im Projekt-Dashboard, analog zu den Internet-Quellen

## 🔵 Import / Export

Projekte zwischen Instanzen übertragen und sichern — wichtig für Umzüge,
Backups und Air-Gap-Übergaben.

- Export eines Projekts als in sich geschlossenes Archiv: Dokumente, Sammlungen, Chat-Profile und Metadaten
- Re-Import auf einer anderen Instanz inkl. Neu-Einbettung (vektorunabhängig, damit das Ziel ein anderes Embedding-Modell nutzen kann)
- Selektiver Export (einzelne Sammlungen) und Trockenlauf zur Vorschau
- CLI-Kommandos für automatisierte Backups (`govdesk export` / `govdesk import`)

## 🔵 Kollaborativer Chat- & Dokumenten-Editor

Ein gemeinsamer Arbeitsbereich, in dem mehrere Nutzer zusammen mit dem Chat in
Echtzeit an einem Dokument schreiben — der Chat wird vom reinen Frage-Antwort-
Werkzeug zum Ko-Autor für Vermerke, Bescheide und Vorlagen.

- Echtzeit-Kollaboration mehrerer Nutzer über Socket.IO (Live-Cursor, Präsenz, gemeinsames Bearbeiten)
- Konfliktfreies Zusammenführen paralleler Änderungen (CRDT/OT), damit gleichzeitige Edits nicht verloren gehen
- Der Chat schreibt und überarbeitet direkt im Dokument (Textstellen einfügen/umformulieren) — mit Quellenbezug aus dem RAG
- Export des fertigen Dokuments als **PDF, DOCX und ODF** (behördentaugliche, weiterverarbeitbare Formate)
- Rechte pro Dokument (Lesen/Kommentieren/Bearbeiten); Änderungen fließen ins bestehende Audit-Log

## 🔵 Kubernetes- & Podman-Kompatibilität

Betrieb jenseits von Docker Compose — für Rechenzentren der öffentlichen Hand,
die auf Kubernetes oder rootless Podman setzen.

- **Kubernetes:** Helm-Chart mit getrennten Deployments für App und Worker, Liveness-/Readiness-Probes (`/healthz`), Secrets/ConfigMaps, PVCs für Daten- und Modell-Volumes
- **Podman:** rootless-fähige Images und ein `podman-compose`-taugliches Compose-File; Ablösung von Docker-spezifischen Annahmen
- Container ohne Root laufen lassen (nicht-privilegierter Nutzer, read-only Root-Dateisystem wo möglich)
- Dokumentierte Referenz-Deployments für beide Umgebungen

---

## ⚪ Weitere Ideen

- Feingranulares Audit-Log-Frontend (Ereignisse werden bereits protokolliert)
- Weitere Dateiformate (XLSX, PPTX, gescannte PDFs via OCR)
- Mehrsprachige Oberfläche (i18n-Grundgerüst via Babel ist vorhanden)
- Barrierefreiheit nach BITV 2.0 prüfen und zertifizieren
