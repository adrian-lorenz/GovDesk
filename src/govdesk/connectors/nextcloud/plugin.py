# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Nextcloud-Connector: importiert Dateien aus einem Nextcloud-Ordner über WebDAV.

Authentifizierung per **App-Passwort** (Nextcloud → Einstellungen → Sicherheit →
„App-Passwort erstellen"), nicht mit dem Login-Passwort. Der Ordner wird per
PROPFIND (Tiefe 1, iterativ) durchlaufen — so funktioniert es auch auf Servern,
die PROPFIND mit „Depth: infinity" sperren. Nur vom System unterstützte und per
Allowlist/Blacklist zugelassene Dateien werden geladen.
"""

import hashlib
import logging
import mimetypes
import xml.etree.ElementTree as ET
from collections import deque
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import unquote, urlsplit

import httpx

from govdesk.connectors.base import ConfigField, FetchedItem
from govdesk.connectors.registry import register
from govdesk.documents.parsers.registry import SUPPORTED_EXTENSIONS

logger = logging.getLogger(__name__)

_DAV = "{DAV:}"
_MAX_BYTES = 50 * 1024 * 1024  # einzelne Datei max. 50 MB
_MAX_FILES = 2000  # Sicherheitsnetz gegen sehr große Bäume
_PROPFIND_BODY = (
    '<?xml version="1.0"?>'
    '<d:propfind xmlns:d="DAV:"><d:prop>'
    "<d:resourcetype/><d:getcontenttype/><d:getcontentlength/><d:getetag/>"
    "</d:prop></d:propfind>"
)


def _norm_path(path: str) -> str:
    """Ordnerpfad normalisieren: führender Slash, kein abschließender Slash."""
    path = "/" + (path or "").strip().strip("/")
    return path.rstrip("/") or "/"


def _ext(name: str) -> str:
    dot = name.rfind(".")
    return name[dot:].lower() if dot >= 0 else ""


class NextcloudConnector:
    type_id = "nextcloud"
    label = "Nextcloud"
    description = "Dateien aus einem Nextcloud-Ordner via WebDAV importieren (App-Passwort)."

    def config_fields(self) -> list[ConfigField]:
        return [
            ConfigField(
                "base_url",
                "Server-URL",
                kind="text",
                required=True,
                help="z. B. https://cloud.behoerde.de",
            ),
            ConfigField("user", "Benutzername", kind="text", required=True),
            ConfigField(
                "app_password",
                "App-Passwort",
                kind="password",
                required=True,
                help="In Nextcloud unter Einstellungen → Sicherheit erzeugen (nicht das Login-PW).",
            ),
            ConfigField(
                "path",
                "Ordnerpfad",
                kind="text",
                default="/",
                help="Pfad innerhalb der Dateien, z. B. /Dokumente. „/“ = gesamtes Laufwerk.",
            ),
            ConfigField(
                "include_subfolders",
                "Unterordner einbeziehen",
                kind="bool",
                default=True,
            ),
            ConfigField(
                "file_types",
                "Erlaubte Dateitypen",
                kind="list",
                default=[],
                help="Endungen (z. B. pdf, docx). Leer = alle unterstützten Formate.",
            ),
            ConfigField(
                "blacklist",
                "Ausschlussliste",
                kind="list",
                default=[],
                help="Dateien/Ordner überspringen, deren Pfad einen dieser Begriffe enthält.",
            ),
        ]

    async def fetch_items(self, config: dict[str, Any]) -> AsyncIterator[FetchedItem]:
        base_url = (config.get("base_url") or "").strip().rstrip("/")
        user = (config.get("user") or "").strip()
        app_password = (config.get("app_password") or "").strip()
        start = _norm_path(config.get("path") or "/")
        include_sub = bool(config.get("include_subfolders", True))
        allow = {
            ("." + e.lstrip(".")).lower() for e in (config.get("file_types") or []) if e.strip()
        }
        blacklist = [b.strip().lower() for b in (config.get("blacklist") or []) if b.strip()]

        if not base_url or not user or not app_password:
            raise ValueError("Nextcloud: Server-URL, Benutzername und App-Passwort sind nötig.")

        origin = f"{urlsplit(base_url).scheme}://{urlsplit(base_url).netloc}"
        dav_root = f"{base_url}/remote.php/dav/files/{user}"
        root_path = urlsplit(dav_root).path.rstrip("/")  # z. B. /remote.php/dav/files/user

        yielded = 0
        auth = httpx.BasicAuth(user, app_password)
        async with httpx.AsyncClient(timeout=120.0, auth=auth, follow_redirects=True) as client:
            queue: deque[str] = deque([f"{dav_root}{'' if start == '/' else start}"])
            visited: set[str] = set()

            while queue:
                folder_url = queue.popleft()
                if folder_url in visited:
                    continue
                visited.add(folder_url)

                try:
                    resp = await client.request(
                        "PROPFIND",
                        folder_url,
                        content=_PROPFIND_BODY,
                        headers={"Depth": "1", "Content-Type": "application/xml"},
                    )
                    resp.raise_for_status()
                except httpx.HTTPError as exc:
                    logger.warning("Nextcloud PROPFIND fehlgeschlagen (%s): %s", folder_url, exc)
                    continue

                self_path = urlsplit(folder_url).path.rstrip("/")
                for entry in _parse_propfind(resp.text):
                    href_path = entry["href"].rstrip("/")
                    if href_path == self_path:
                        continue  # der Ordner selbst
                    rel = unquote(href_path[len(root_path) :]) or "/"
                    if any(term in rel.lower() for term in blacklist):
                        continue

                    if entry["is_dir"]:
                        if include_sub:
                            queue.append(f"{origin}{entry['href']}")
                        continue

                    name = unquote(href_path.rsplit("/", 1)[-1])
                    ext = _ext(name)
                    if ext not in SUPPORTED_EXTENSIONS:
                        continue
                    if allow and ext not in allow:
                        continue
                    if entry["size"] is not None and entry["size"] > _MAX_BYTES:
                        logger.info(
                            "Nextcloud: %s zu groß (%d B) — übersprungen", rel, entry["size"]
                        )
                        continue

                    try:
                        dl = await client.get(f"{origin}{entry['href']}")
                        dl.raise_for_status()
                    except httpx.HTTPError as exc:
                        logger.warning("Nextcloud-Download fehlgeschlagen (%s): %s", rel, exc)
                        continue

                    content_type = (
                        entry["content_type"]
                        or mimetypes.guess_type(name)[0]
                        or "application/octet-stream"
                    )
                    external_id = (
                        rel if len(rel) <= 200 else hashlib.sha256(rel.encode()).hexdigest()
                    )
                    yield FetchedItem(
                        external_id=external_id,
                        filename=name,
                        data=dl.content,
                        content_type=content_type,
                        source_url=f"{dav_root}{href_path[len(root_path) :]}",
                        content_hash=entry["etag"] or None,
                    )
                    yielded += 1
                    if yielded >= _MAX_FILES:
                        logger.warning(
                            "Nextcloud: Obergrenze von %d Dateien erreicht — Rest übersprungen.",
                            _MAX_FILES,
                        )
                        return


def _parse_propfind(xml_text: str) -> list[dict[str, Any]]:
    """WebDAV-Multistatus auswerten. Quelle ist der authentifizierte Nextcloud-Server."""
    entries: list[dict[str, Any]] = []
    root = ET.fromstring(xml_text)  # noqa: S314 — Antwort des vertrauenswürdigen NC-Servers
    for resp in root.findall(f"{_DAV}response"):
        href_el = resp.find(f"{_DAV}href")
        if href_el is None or not href_el.text:
            continue
        prop = resp.find(f"{_DAV}propstat/{_DAV}prop")
        is_dir = False
        content_type = etag = None
        size: int | None = None
        if prop is not None:
            rtype = prop.find(f"{_DAV}resourcetype")
            is_dir = rtype is not None and rtype.find(f"{_DAV}collection") is not None
            ct = prop.find(f"{_DAV}getcontenttype")
            content_type = ct.text if ct is not None else None
            et_el = prop.find(f"{_DAV}getetag")
            etag = et_el.text.strip('"') if et_el is not None and et_el.text else None
            len_el = prop.find(f"{_DAV}getcontentlength")
            if len_el is not None and len_el.text and len_el.text.isdigit():
                size = int(len_el.text)
        entries.append(
            {
                "href": href_el.text,
                "is_dir": is_dir,
                "content_type": content_type,
                "etag": etag,
                "size": size,
            }
        )
    return entries


register(NextcloudConnector())
