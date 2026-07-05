# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Seite → Text-Extraktion → Dokument. Nutzt dieselbe Ingestion wie Uploads."""

import hashlib
import logging
import re
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from govdesk.agents.crawler.fetch import FetchResult
from govdesk.db.models import Document, DocumentSource, DocumentStatus, Project
from govdesk.documents import storage
from govdesk.documents.service import DuplicateDocumentError, create_document

logger = logging.getLogger(__name__)


def extract_markdown(result: FetchResult) -> tuple[str, str] | None:
    """Liefert (titel, markdown) oder None wenn kein verwertbarer Inhalt."""
    if "html" not in result.content_type and not result.content.lstrip().startswith(b"<"):
        return None
    try:
        import trafilatura

        markdown = trafilatura.extract(
            result.content,
            output_format="markdown",
            include_comments=False,
            include_tables=True,
            include_links=False,
        )
        metadata = trafilatura.extract_metadata(result.content)
        title = (metadata.title if metadata else None) or urlsplit(result.url).path
    except ImportError:
        from govdesk.documents.parsers.html import HtmlParser

        parsed = HtmlParser().parse(result.content)
        markdown = "\n\n".join(b.text for b in parsed.blocks)
        title = urlsplit(result.url).path
    if not markdown or len(markdown.strip()) < 50:
        return None
    return title.strip() or result.url, markdown


def content_hash(markdown: str) -> str:
    return hashlib.sha256(markdown.encode()).hexdigest()


def _filename_for(title: str, url: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9äöüÄÖÜß _-]+", "", title)[:120].strip() or "seite"
    return f"{base}.md"


async def upsert_page_document(
    db: AsyncSession,
    project: Project,
    existing_document_id,
    title: str,
    markdown: str,
    url: str,
    collection_id=None,
) -> Document | None:
    """Neues Dokument anlegen oder bestehendes (geänderte Seite) aktualisieren.

    Gibt das zu ingestende Dokument zurück; None wenn Duplikat ohne Änderung.
    """
    payload = f"# {title}\n\nQuelle: {url}\n\n{markdown}".encode()

    if existing_document_id is not None:
        document = await db.get(Document, existing_document_id)
        if document is not None:
            sha256 = hashlib.sha256(payload).hexdigest()
            document.sha256 = sha256
            document.filename = _filename_for(title, url)
            document.status = DocumentStatus.PENDING
            document.error = None
            assert document.file_path is not None
            storage.delete_file(document.file_path)
            document.file_path = storage.store_file(
                project.id, document.id, document.filename, payload
            )
            await db.flush()
            return document

    try:
        return await create_document(
            db,
            project,
            filename=_filename_for(title, url),
            data=payload,
            content_type="text/markdown",
            source_type=DocumentSource.CRAWLER,
            source_url=url,
            collection_id=collection_id,
        )
    except DuplicateDocumentError:
        logger.info("Seite %s ist inhaltsgleich mit vorhandenem Dokument — übersprungen", url)
        return None
