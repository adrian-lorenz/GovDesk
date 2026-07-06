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

## 🟢 Lokale Passwort-Richtlinie

Für Instanzen mit eigener Nutzerverwaltung (ohne OIDC/SSO) eine konfigurierbare
Passwort-Richtlinie — angelehnt an die Empfehlungen des BSI (IT-Grundschutz).

- ✅ Mindestlänge und Komplexität (Zeichenklassen), zentral über Admin-Einstellungen konfigurierbar
- ✅ Abgleich gegen eine (eingebaute) Liste offensichtlich schwacher Passwörter
- ✅ Durchgesetzt bei Ersteinrichtung und Nutzeranlage; greift nur für lokale Konten (bei OIDC beim IdP)
- Offen: Abgleich gegen große Leak-Listen (z. B. HIBP-Range-API, offline)
- Offen: Passwort-Ablaufintervall + Sperre nach zu vielen Fehlversuchen (braucht Schema-Erweiterung)
- Offen: erzwungener Wechsel initialer Admin-Passwörter beim ersten Login

## 🟢 Guardrails (Ein- & Ausgabe-Absicherung)

Konfigurierbare Leitplanken für Chat-Ein- und -Ausgaben, damit der Assistent im
behördlichen Einsatz kontrollierbar und rechtssicher bleibt.

- ✅ Eingabe-Prüfung vor dem LLM: Sperrbegriffe, Längenlimit, Prompt-Injection-/Jailbreak-Heuristik (regelbasiert, lokal)
- ✅ Themen-/Scope-Grenzen: konfigurierbare Verbotskategorien (Politik, Code, Medizin, Recht, Meinung) + Freitext, als Vorgabe im System-Prompt → Assistent lehnt ab
- ✅ Zentrale Konfiguration in den Plattform-Einstellungen; blockierte Anfragen landen im Audit-Log
- Offen: Übersteuerung pro Projekt/Chat-Profil; optional kleines lokales Klassifikationsmodell

## 🔵 Massen-Import & Sync-Agent

Über den bestehenden Internet-Agent hinaus ein Agent, der große Bestände
automatisiert und wiederkehrend in ein Projekt übernimmt.

> ✅ Grundlage vorhanden: Connector-Quellen mit **`sync_interval_hours`** werden
> über den periodischen Task `schedule_connector_syncs` (alle 15 min, Delta über
> `content_hash`) automatisch neu synchronisiert. Offen sind die weiteren Quellen unten.

- Quellen: lokale Verzeichnisse / Netzlaufwerke, S3-kompatibler Objektspeicher, WebDAV/SharePoint
- Geplante Synchronisation (Cron-artig) mit Delta-Erkennung — nur neue/geänderte Dateien werden neu eingebettet
- Deduplizierung und Fortschritts-/Fehlerbericht pro Lauf
- Nutzt dieselbe Ingestion-Pipeline (Parsen → Chunken → Embedden → Qdrant) wie Upload und Crawler
- Verwaltung und Live-Status im Projekt-Dashboard, analog zu den Internet-Quellen

## 🟢 Import / Export

Projekte zwischen Instanzen übertragen und sichern — wichtig für Umzüge,
Backups und Air-Gap-Übergaben.

- ✅ Export eines Projekts als in sich geschlossenes ZIP-Archiv: Dokumente, Sammlungen, Chat-Profile und Metadaten
- ✅ Re-Import auf einer anderen Instanz inkl. Neu-Einbettung (vektorunabhängig)
- ✅ CLI-Kommandos (`govdesk export` / `govdesk import`) und Web-UI (Export/Import in der Projektliste)
- Offen: selektiver Export (einzelne Sammlungen) und Trockenlauf zur Vorschau

## 🟢 Kollaborativer Chat- & Dokumenten-Editor

Ein gemeinsamer Arbeitsbereich, in dem mehrere Nutzer zusammen mit dem Chat in
Echtzeit an einem Dokument schreiben — der Chat wird vom reinen Frage-Antwort-
Werkzeug zum Ko-Autor für Vermerke, Bescheide und Vorlagen.

**Bereits umgesetzt:** WYSIWYG-Editor pro Projekt (Plain JS, Word-Look mit Formatierungsleiste),
Echtzeit-Sync über **Long-Polling** (statt Socket.IO), Versionshistorie (wer/wann),
privat/geteilt, optimistische Konfliktauflösung, Umbenennen, **Chat-Zusammenfassung → Dokument**
(KI), **Export nach PDF, DOCX & ODF**. **Offen:** CRDT-Merge für gleichzeitiges Tippen.

- Echtzeit-Kollaboration mehrerer Nutzer über Socket.IO (Live-Cursor, Präsenz, gemeinsames Bearbeiten)
- Konfliktfreies Zusammenführen paralleler Änderungen (CRDT/OT), damit gleichzeitige Edits nicht verloren gehen
- Editor bewusst in **schlankem Plain JS** (kein schweres Frontend-Framework) — passt zum souveränen, wartungsarmen Stack
- **Dokumente sind für alle Projekt-Mitglieder sichtbar**, mit **Versionshistorie** (wer hat wann was geändert) — Ausnahme: als **privat** markierte Dokumente bleiben dem Ersteller vorbehalten
- Der Chat schreibt und überarbeitet direkt im Dokument (Textstellen einfügen/umformulieren) — mit Quellenbezug aus dem RAG
- **Chat per KI zusammenfassen und als Dokument speichern** — der zusammengefasste Verlauf landet als bearbeitbares Dokument im Editor und kann dort manuell weitergeschrieben werden
- Export des fertigen Dokuments als **PDF, DOCX und ODF** (behördentaugliche, weiterverarbeitbare Formate)
- Rechte pro Dokument (Lesen/Kommentieren/Bearbeiten, privat/geteilt); Änderungen fließen ins bestehende Audit-Log

---

## ⚪ Weitere Ideen

- ✅ Feingranulares Audit-Log-Frontend (`/admin/audit`, gefiltert + paginiert)
- ✅ Weitere Dateiformate: XLSX & PPTX umgesetzt — offen: gescannte PDFs via OCR
- Barrierefreiheit nach BITV 2.0 prüfen und zertifizieren
