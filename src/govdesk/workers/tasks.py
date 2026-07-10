# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Hintergrund-Tasks: Dokument-Ingestion (Parsen → Chunken → Embedden → Qdrant)."""

import logging
import uuid

from sqlalchemy import delete

from govdesk.core.app_settings import get_runtime_config
from govdesk.db.models import Document, DocumentChunk, DocumentStatus, Project
from govdesk.db.session import get_session_factory
from govdesk.documents import storage
from govdesk.documents.parsers.registry import parser_for
from govdesk.rag.chunking import chunk_blocks
from govdesk.rag.embeddings import embedding_provider_from_config
from govdesk.rag.vectorstore import ChunkPayload, VectorStore
from govdesk.workers.app import queue

logger = logging.getLogger(__name__)


@queue.task(name="govdesk.ping")
async def ping() -> str:
    """Smoke-Test-Task: beweist, dass Queue und Worker laufen."""
    return "pong"


async def _set_status(document_id: uuid.UUID, status: DocumentStatus, error: str | None = None):
    async with get_session_factory()() as db:
        document = await db.get(Document, document_id)
        if document is not None:
            document.status = status
            document.error = error
            await db.commit()


@queue.task(name="govdesk.ingest_document", retry=2)
async def ingest_document(document_id: str) -> None:
    doc_id = uuid.UUID(document_id)

    async with get_session_factory()() as db:
        document = await db.get(Document, doc_id)
        if document is None:
            logger.warning("Dokument %s existiert nicht mehr — Ingest übersprungen", document_id)
            return
        project = await db.get(Project, document.project_id)
        assert project is not None
        cfg = await get_runtime_config(db)
        filename = document.filename
        file_path = document.file_path
        project_id = project.id
        collection = project.qdrant_collection
        collection_id = document.collection_id
        embedding_model = project.embedding_model
        source_url = document.source_url

    try:
        # 1) Parsen — Bilddateien laufen komplett über OCR (Vision-Modell);
        #    bei PDFs werden Seiten ohne Textebene (Scans) per OCR ergänzt.
        from pathlib import PurePosixPath

        from govdesk.documents.ocr import (
            IMAGE_EXTENSIONS,
            ocr_image_to_blocks,
            ocr_missing_pdf_pages,
        )
        from govdesk.documents.parsers.base import ParsedDocument

        await _set_status(doc_id, DocumentStatus.PARSING)
        assert file_path is not None
        data = storage.read_file(file_path)
        suffix = PurePosixPath(filename.lower()).suffix
        if suffix in IMAGE_EXTENSIONS:
            if not cfg.ocr_enabled:
                raise ValueError(
                    "Bilddatei — der OCR-Modus ist deaktiviert "
                    "(Einstellungen → KI & Modelle → OCR)."
                )
            parsed = ParsedDocument(blocks=await ocr_image_to_blocks(cfg, data))
        else:
            parsed = parser_for(filename).parse(data)
            if suffix == ".pdf" and cfg.ocr_enabled:
                parsed = ParsedDocument(
                    blocks=await ocr_missing_pdf_pages(cfg, data, list(parsed.blocks))
                )

        # 2) Chunken
        await _set_status(doc_id, DocumentStatus.CHUNKING)
        chunks = chunk_blocks(parsed.blocks)
        if not chunks:
            hinweis = (
                "" if cfg.ocr_enabled else " Für Scans/Bilder den OCR-Modus aktivieren "
                "(Einstellungen → KI & Modelle)."
            )
            raise ValueError(f"Kein Textinhalt gefunden — ist das Dokument leer?{hinweis}")

        # 3) Embedden
        await _set_status(doc_id, DocumentStatus.EMBEDDING)
        embedder = embedding_provider_from_config(cfg)
        vectors = await embedder.embed([c.text for c in chunks], model=embedding_model)

        # 4) Qdrant + Chunk-Metadaten (Re-Ingest: alte Chunks ersetzen)
        store = VectorStore()
        try:
            await store.delete_document(collection, doc_id)
            payloads = []
            point_ids = []
            for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
                point_id = uuid.uuid4()
                point_ids.append(point_id)
                payloads.append(
                    ChunkPayload(
                        point_id=point_id,
                        vector=vector,
                        project_id=project_id,
                        document_id=doc_id,
                        chunk_index=index,
                        filename=filename,
                        text=chunk.text,
                        heading_path=chunk.heading_path,
                        page_no=chunk.page_no,
                        source_url=source_url,
                        collection_id=collection_id,
                    )
                )
            await store.upsert_chunks(collection, payloads)
        finally:
            await store.close()

        async with get_session_factory()() as db:
            await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc_id))
            for index, (chunk, point_id) in enumerate(zip(chunks, point_ids, strict=True)):
                db.add(
                    DocumentChunk(
                        document_id=doc_id,
                        chunk_index=index,
                        text=chunk.text,
                        token_count=chunk.token_count,
                        heading_path=chunk.heading_path,
                        page_no=chunk.page_no,
                        qdrant_point_id=point_id,
                    )
                )
            document = await db.get(Document, doc_id)
            assert document is not None
            document.chunk_count = len(chunks)
            document.status = DocumentStatus.READY
            document.error = None
            await db.commit()
        logger.info("Dokument %s eingebettet (%d Chunks)", filename, len(chunks))

    except Exception as exc:
        logger.exception("Ingest von %s fehlgeschlagen", filename)
        # str() mancher Exceptions (z. B. httpx.ReadTimeout) ist leer — dann
        # wenigstens den Typ nennen, sonst steht in der UI „kein Fehler".
        grund = str(exc).strip() or f"{type(exc).__name__} (z. B. Zeitüberschreitung/Verbindung)"
        await _set_status(doc_id, DocumentStatus.FAILED, error=grund[:2000])
        raise


@queue.task(name="govdesk.crawl_source")
async def crawl_source(job_id: str) -> None:
    """Crawlt eine Web-Quelle: Frontier → robots.txt → Extraktion → Ingestion."""
    import asyncio
    from datetime import UTC, datetime

    from sqlalchemy import select

    from govdesk.agents.crawler.agent import evaluate_page
    from govdesk.agents.crawler.fetch import fetch_page, new_client
    from govdesk.agents.crawler.frontier import (
        Frontier,
        extract_links,
        extract_links_with_text,
        url_hash,
    )
    from govdesk.agents.crawler.ingest import (
        content_hash,
        extract_markdown,
        upsert_page_document,
    )
    from govdesk.agents.crawler.robots import RobotsCache
    from govdesk.db.models import CrawlJob, CrawlJobStatus, CrawlMode, CrawlPage, CrawlSource
    from govdesk.rag.llm import llm_provider_from_config

    def now():
        return datetime.now(UTC).replace(tzinfo=None)

    async with get_session_factory()() as db:
        job = await db.get(CrawlJob, uuid.UUID(job_id))
        if job is None or job.status != CrawlJobStatus.QUEUED:
            return
        source = await db.get(CrawlSource, job.crawl_source_id)
        assert source is not None
        project = await db.get(Project, source.project_id)
        assert project is not None
        job.status = CrawlJobStatus.RUNNING
        job.started_at = now()
        source_id, project_id = source.id, project.id
        mode, topic = source.mode, (source.topic or "").strip()
        # LLM-Provider nur im Agent-Modus (mit Suchauftrag) vorbereiten.
        llm = llm_model = None
        if mode == CrawlMode.AGENT and topic:
            cfg = await get_runtime_config(db)
            llm = llm_provider_from_config(cfg)
            llm_model = cfg.chat_model
        await db.commit()

    frontier = Frontier(
        start_url=source.start_url,
        max_depth=0 if mode == CrawlMode.SINGLE else source.max_depth,
        max_pages=1 if mode == CrawlMode.SINGLE else source.max_pages,
        allowed_domains=source.allowed_domains,
        include_pattern=source.url_include_pattern,
        exclude_pattern=source.url_exclude_pattern,
    )
    fetched = ingested = skipped = 0
    error: str | None = None

    async with new_client() as client:
        robots = RobotsCache(client)
        try:
            while (item := frontier.pop()) is not None and fetched < frontier.max_pages:
                url, depth = item

                # Abbruch-Flag aus der UI prüfen
                async with get_session_factory()() as db:
                    current = await db.get(CrawlJob, uuid.UUID(job_id))
                    if current is None or current.status == CrawlJobStatus.CANCELLED:
                        return

                if not await robots.allowed(url):
                    skipped += 1
                    continue
                await asyncio.sleep(await robots.crawl_delay(url))

                try:
                    result = await fetch_page(client, url)
                except Exception as exc:
                    logger.warning("Abruf fehlgeschlagen: %s (%s)", url, exc)
                    skipped += 1
                    continue
                fetched += 1

                # Im Agent-Modus wählt das LLM die zu folgenden Links aus (None =
                # noch keine Entscheidung getroffen → im recursive-Modus allen folgen).
                agent_follow: list[str] | None = None
                async with get_session_factory()() as db:
                    page = (
                        await db.execute(
                            select(CrawlPage).where(
                                CrawlPage.crawl_source_id == source_id,
                                CrawlPage.url_hash == url_hash(url),
                            )
                        )
                    ).scalar_one_or_none()
                    if page is None:
                        page = CrawlPage(crawl_source_id=source_id, url=url, url_hash=url_hash(url))
                        db.add(page)
                    page.last_fetched_at = now()
                    page.http_status = result.status_code

                    document_to_ingest = None
                    if result.status_code == 200:
                        extracted = extract_markdown(result)
                        if extracted is not None:
                            title, markdown = extracted

                            # Agent-Modus: LLM entscheidet über Relevanz + Linkauswahl.
                            relevant = True
                            if llm is not None:
                                candidates = (
                                    extract_links_with_text(result.url, result.content)
                                    if depth < frontier.max_depth
                                    else []
                                )
                                decision = await evaluate_page(
                                    llm, llm_model, topic, url, title, markdown, candidates
                                )
                                relevant = decision.relevant
                                agent_follow = [candidates[i][0] for i in decision.follow]

                            if not relevant:
                                skipped += 1  # themenfremd — nicht einbetten
                            else:
                                new_hash = content_hash(markdown)
                                if page.content_hash == new_hash and page.document_id:
                                    skipped += 1  # unverändert
                                else:
                                    fresh_project = await db.get(Project, project_id)
                                    assert fresh_project is not None
                                    document_to_ingest = await upsert_page_document(
                                        db,
                                        fresh_project,
                                        page.document_id,
                                        title,
                                        markdown,
                                        url,
                                        collection_id=source.collection_id,
                                    )
                                    if document_to_ingest is not None:
                                        page.content_hash = new_hash
                                        page.document_id = document_to_ingest.id
                                        ingested += 1
                                    else:
                                        skipped += 1
                        else:
                            skipped += 1
                    else:
                        skipped += 1

                    job_row = await db.get(CrawlJob, uuid.UUID(job_id))
                    if job_row is not None:
                        job_row.pages_fetched = fetched
                        job_row.pages_ingested = ingested
                        job_row.pages_skipped = skipped
                    await db.commit()
                    if document_to_ingest is not None:
                        await ingest_document.defer_async(document_id=str(document_to_ingest.id))

                if depth < frontier.max_depth and result.status_code == 200:
                    if agent_follow is not None:
                        for link in agent_follow:
                            frontier.add(link, depth + 1)
                    elif mode != CrawlMode.AGENT:
                        for link in extract_links(result.url, result.content):
                            frontier.add(link, depth + 1)
        except Exception as exc:
            logger.exception("Crawl-Job %s fehlgeschlagen", job_id)
            error = str(exc)[:2000]

    async with get_session_factory()() as db:
        job_row = await db.get(CrawlJob, uuid.UUID(job_id))
        if job_row is not None and job_row.status != CrawlJobStatus.CANCELLED:
            job_row.status = CrawlJobStatus.FAILED if error else CrawlJobStatus.DONE
            job_row.error = error
            job_row.finished_at = now()
            job_row.pages_fetched = fetched
            job_row.pages_ingested = ingested
            job_row.pages_skipped = skipped
            await db.commit()


@queue.task(name="govdesk.run_connector_job")
async def run_connector_job(job_id: str) -> None:
    """Führt einen Connector-Lauf aus: Plugin.fetch_items → Delta-Check → Ingestion."""
    import hashlib
    from datetime import UTC, datetime

    from sqlalchemy import select

    from govdesk.connectors.registry import UnknownConnectorError, get_connector
    from govdesk.connectors.service import resolve_config_secrets, upsert_item_document
    from govdesk.db.models import (
        ConnectorItem,
        ConnectorJob,
        ConnectorJobStatus,
        ConnectorSource,
    )

    def now():
        return datetime.now(UTC).replace(tzinfo=None)

    async with get_session_factory()() as db:
        job = await db.get(ConnectorJob, uuid.UUID(job_id))
        if job is None or job.status != ConnectorJobStatus.QUEUED:
            return
        source = await db.get(ConnectorSource, job.connector_source_id)
        assert source is not None
        job.status = ConnectorJobStatus.RUNNING
        job.started_at = now()
        source_id = source.id
        project_id = source.project_id
        connector_type = source.connector_type
        config = resolve_config_secrets(source.config)
        collection_id = source.collection_id
        await db.commit()

    found = ingested = skipped = 0
    error: str | None = None

    try:
        plugin = get_connector(connector_type)
        async for item in plugin.fetch_items(config):
            found += 1

            # Abbruch-Flag aus der UI prüfen
            async with get_session_factory()() as db:
                current = await db.get(ConnectorJob, uuid.UUID(job_id))
                if current is None or current.status == ConnectorJobStatus.CANCELLED:
                    return

            new_hash = item.content_hash or hashlib.sha256(item.data).hexdigest()
            async with get_session_factory()() as db:
                existing = (
                    await db.execute(
                        select(ConnectorItem).where(
                            ConnectorItem.connector_source_id == source_id,
                            ConnectorItem.external_id == item.external_id,
                        )
                    )
                ).scalar_one_or_none()
                if existing is None:
                    existing = ConnectorItem(
                        connector_source_id=source_id, external_id=item.external_id
                    )
                    db.add(existing)
                existing.last_seen_at = now()

                document_to_ingest = None
                if existing.content_hash == new_hash and existing.document_id:
                    skipped += 1  # unverändert
                else:
                    project = await db.get(Project, project_id)
                    assert project is not None
                    document_to_ingest = await upsert_item_document(
                        db, project, item, existing.document_id, collection_id
                    )
                    if document_to_ingest is not None:
                        existing.content_hash = new_hash
                        existing.document_id = document_to_ingest.id
                        ingested += 1
                    else:
                        skipped += 1

                job_row = await db.get(ConnectorJob, uuid.UUID(job_id))
                if job_row is not None:
                    job_row.items_found = found
                    job_row.items_ingested = ingested
                    job_row.items_skipped = skipped
                await db.commit()
                if document_to_ingest is not None:
                    await ingest_document.defer_async(document_id=str(document_to_ingest.id))
    except UnknownConnectorError as exc:
        error = str(exc)
    except Exception as exc:
        logger.exception("Connector-Job %s fehlgeschlagen", job_id)
        error = str(exc)[:2000]

    async with get_session_factory()() as db:
        job_row = await db.get(ConnectorJob, uuid.UUID(job_id))
        if job_row is not None and job_row.status != ConnectorJobStatus.CANCELLED:
            job_row.status = ConnectorJobStatus.FAILED if error else ConnectorJobStatus.DONE
            job_row.error = error
            job_row.finished_at = now()
            job_row.items_found = found
            job_row.items_ingested = ingested
            job_row.items_skipped = skipped
            await db.commit()


@queue.periodic(cron="*/15 * * * *")
@queue.task(name="govdesk.schedule_connector_syncs")
async def schedule_connector_syncs(timestamp: int) -> None:
    """Alle 15 Minuten: fällige Connector-Quellen mit Sync-Intervall neu einplanen."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from govdesk.db.models import ConnectorJob, ConnectorJobStatus, ConnectorSource

    now = datetime.now(UTC).replace(tzinfo=None)
    async with get_session_factory()() as db:
        sources = (
            (
                await db.execute(
                    select(ConnectorSource).where(
                        ConnectorSource.enabled,
                        ConnectorSource.sync_interval_hours.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        for source in sources:
            last_job = (
                await db.execute(
                    select(ConnectorJob)
                    .where(ConnectorJob.connector_source_id == source.id)
                    .order_by(ConnectorJob.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if last_job is not None and last_job.status in (
                ConnectorJobStatus.QUEUED,
                ConnectorJobStatus.RUNNING,
            ):
                continue
            due = last_job is None or (
                last_job.finished_at is not None
                and now - last_job.finished_at
                > timedelta(hours=source.sync_interval_hours or 24)
            )
            if due:
                job = ConnectorJob(connector_source_id=source.id)
                db.add(job)
                await db.flush()
                await run_connector_job.defer_async(job_id=str(job.id))
                logger.info("Connector-Sync eingeplant: %s", source.name)
        await db.commit()


@queue.periodic(cron="*/15 * * * *")
@queue.task(name="govdesk.schedule_recrawls")
async def schedule_recrawls(timestamp: int) -> None:
    """Alle 15 Minuten: fällige Quellen mit Re-Crawl-Intervall neu einplanen."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from govdesk.db.models import CrawlJob, CrawlJobStatus, CrawlSource

    now = datetime.now(UTC).replace(tzinfo=None)
    async with get_session_factory()() as db:
        sources = (
            (
                await db.execute(
                    select(CrawlSource).where(
                        CrawlSource.enabled,
                        CrawlSource.recrawl_interval_hours.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        for source in sources:
            last_job = (
                await db.execute(
                    select(CrawlJob)
                    .where(CrawlJob.crawl_source_id == source.id)
                    .order_by(CrawlJob.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if last_job is not None and last_job.status in (
                CrawlJobStatus.QUEUED,
                CrawlJobStatus.RUNNING,
            ):
                continue
            due = last_job is None or (
                last_job.finished_at is not None
                and now - last_job.finished_at
                > timedelta(hours=source.recrawl_interval_hours or 24)
            )
            if due:
                job = CrawlJob(crawl_source_id=source.id)
                db.add(job)
                await db.flush()
                await crawl_source.defer_async(job_id=str(job.id))
                logger.info("Re-Crawl eingeplant: %s", source.name)
        await db.commit()


@queue.task(name="govdesk.summarize_chat", retry=1)
async def summarize_chat(chat_id: str, document_id: str, user_id: str) -> None:
    """Fasst einen Chat im Hintergrund zusammen und füllt das (bereits angelegte)
    Editor-Dokument. Der Editor aktualisiert sich über den Long-Poll von selbst,
    sobald die Version steigt — der Nutzer sieht die Zusammenfassung „eintreffen"."""
    from govdesk.chat.service import get_chat_session
    from govdesk.chat.streaming import render_markdown
    from govdesk.chat.zusammenfassung import (
        strip_code_fence,
        summarize_transcript,
        transcript_for,
    )
    from govdesk.db.models import EditorDocument, User
    from govdesk.editor.service import save_document

    async with get_session_factory()() as db:
        session = await get_chat_session(db, uuid.UUID(chat_id), with_messages=True)
        doc = await db.get(EditorDocument, uuid.UUID(document_id))
        user = await db.get(User, uuid.UUID(user_id))
        if doc is None or user is None:
            logger.warning("summarize_chat: Dokument/Nutzer fehlt — übersprungen")
            return
        cfg = await get_runtime_config(db)
        transcript = transcript_for(session) if session is not None else ""

        try:
            if not transcript.strip():
                raise ValueError("Der Chat enthält keine Nachrichten.")
            summary = await summarize_transcript(cfg, transcript)
            html = render_markdown(strip_code_fence(summary))
        except Exception as exc:
            logger.exception("Chat-Zusammenfassung fehlgeschlagen (Chat %s)", chat_id)
            html = (
                "<p><strong>Die Zusammenfassung ist fehlgeschlagen.</strong> "
                f"Grund: {str(exc)[:300]} — Sie können dieses Dokument löschen "
                "und es erneut versuchen.</p>"
            )

        # Immer auf die aktuelle Version speichern: der Platzhalter darf auch
        # dann ersetzt werden, wenn zwischenzeitlich jemand tippte.
        await save_document(db, doc, user, html, doc.version)
        await db.commit()
