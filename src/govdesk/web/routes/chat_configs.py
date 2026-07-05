# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""CRUD für Chat-Profile (System-Prompt, Modell, Retrieval-Einstellungen)."""

import json
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, update

from govdesk.auth.deps import CurrentUser, Db, ProjectEditor
from govdesk.core.app_settings import get_runtime_config
from govdesk.core.audit import audit
from govdesk.db.models import ChatConfig, Collection, Document
from govdesk.rag.llm import llm_provider_from_config
from govdesk.rag.retrieval import retrieve
from govdesk.web.deps import render

logger = logging.getLogger(__name__)

router = APIRouter()


async def _page_context(request: Request, project, db: Db, edit: ChatConfig | None = None):
    configs = list(
        (
            await db.execute(
                select(ChatConfig)
                .where(ChatConfig.project_id == project.id)
                .order_by(ChatConfig.name)
            )
        ).scalars()
    )
    collections = list(
        (
            await db.execute(
                select(Collection)
                .where(Collection.project_id == project.id)
                .order_by(Collection.name)
            )
        ).scalars()
    )
    cfg = await get_runtime_config(db)
    try:
        models = await llm_provider_from_config(cfg).list_models()
    except Exception:
        models = []
    return {
        "project": project,
        "configs": configs,
        "collections": collections,
        "models": models,
        "default_model": cfg.chat_model,
        "edit": edit,
    }


@router.get("/projects/{project_id}/chat-configs", response_class=HTMLResponse)
async def config_list(request: Request, project: ProjectEditor, db: Db) -> HTMLResponse:
    return render(request, "projects/chat_configs.html", await _page_context(request, project, db))


def _parse_draft(raw: str, project) -> dict:
    """Extrahiert das JSON-Profil aus der LLM-Antwort (tolerant gegen Rahmentext)."""
    text = (raw or "").strip()
    data: dict = {}
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(text[start : end + 1])
        except (json.JSONDecodeError, ValueError):
            data = {}
    try:
        temperature = max(0.0, min(float(data.get("temperature", 0.2)), 2.0))
    except (TypeError, ValueError):
        temperature = 0.2
    try:
        top_k = max(1, min(int(data.get("top_k", 4)), 20))
    except (TypeError, ValueError):
        top_k = 4
    return {
        "name": (str(data.get("name") or f"KI-Profil: {project.name}")).strip()[:150],
        "system_prompt": (data.get("system_prompt") or text or "").strip() or None,
        "temperature": temperature,
        "top_k": top_k,
        "model": None,
        "rerank_enabled": True,
        "is_default": False,
        "collection_ids": None,
    }


@router.post("/projects/{project_id}/chat-configs/generate", response_class=HTMLResponse)
async def config_generate(
    request: Request,
    project: ProjectEditor,
    db: Db,
    ziel: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """Erzeugt per LLM einen Chat-Profil-Vorschlag aus Projektkontext + Chunks.
    Der Vorschlag füllt das Formular vor; gespeichert wird erst nach Prüfung."""
    cfg = await get_runtime_config(db)
    filenames = list(
        (
            await db.execute(
                select(Document.filename).where(Document.project_id == project.id).limit(40)
            )
        ).scalars()
    )
    sample = ""
    try:
        query = ziel.strip() or (
            f"{project.name}. {project.description or ''}. "
            "Worum geht es in diesen Dokumenten und welche Fragen stellen Nutzer?"
        )
        sample = (await retrieve(project, query, cfg, top_n=6)).context[:4000]
    except Exception:
        logger.warning("Kontext-Retrieval für Profilgenerierung fehlgeschlagen", exc_info=True)

    system = (
        "Du konfigurierst Chat-Profile für einen souveränen Behörden-RAG-Assistenten. "
        "Antworte AUSSCHLIESSLICH mit einem einzigen JSON-Objekt, ohne Markdown, ohne Erklärung."
    )
    zweck = ziel.strip() or "allgemeiner Fachassistent für dieses Projekt"
    user = (
        f"Projekt: {project.name}\n"
        f"Beschreibung: {project.description or '—'}\n"
        f"Dokumente: {', '.join(filenames) or '—'}\n"
        f"Ziel/Zweck des Profils: {zweck}\n\n"
        f"Beispiel-Auszüge aus den Dokumenten:\n{sample or '(keine verfügbar)'}\n\n"
        "Erzeuge ein passendes Chat-Profil als JSON mit exakt diesen Feldern: "
        '{"name": "prägnant, max 60 Zeichen", '
        '"system_prompt": "auf Deutsch; definiert Rolle, Tonfall, thematischen Fokus, '
        "den Umgang mit Quellen/Zitaten [1][2] und das Verhalten, wenn keine Quelle passt\", "
        '"temperature": 0.2, "top_k": 4}'
    )
    draft = None
    try:
        raw = await llm_provider_from_config(cfg).complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            model=cfg.chat_model,
            temperature=0.3,
        )
        draft = _parse_draft(raw, project)
    except Exception:
        logger.exception("Profilgenerierung per LLM fehlgeschlagen")

    ctx = await _page_context(request, project, db)
    ctx["draft"] = draft
    ctx["generate_error"] = draft is None
    return render(request, "projects/chat_configs.html", ctx)


@router.get("/projects/{project_id}/chat-configs/{config_id}", response_class=HTMLResponse)
async def config_edit(
    request: Request, project: ProjectEditor, db: Db, config_id: uuid.UUID
) -> HTMLResponse:
    config = await _load_config(db, project, config_id)
    return render(
        request,
        "projects/chat_configs.html",
        await _page_context(request, project, db, edit=config),
    )


async def _load_config(db: Db, project, config_id: uuid.UUID) -> ChatConfig:
    config = await db.get(ChatConfig, config_id)
    if config is None or config.project_id != project.id:
        raise HTTPException(status_code=404, detail="Chat-Profil nicht gefunden")
    return config


def _parse_collection_ids(raw: list[str]) -> list[uuid.UUID] | None:
    ids = [uuid.UUID(value) for value in raw if value]
    return ids or None


@router.post("/projects/{project_id}/chat-configs")
async def config_save(
    request: Request,
    project: ProjectEditor,
    user: CurrentUser,
    db: Db,
    name: Annotated[str, Form()],
    system_prompt: Annotated[str, Form()] = "",
    model: Annotated[str, Form()] = "",
    temperature: Annotated[float, Form()] = 0.2,
    top_k: Annotated[int, Form()] = 4,
    rerank_enabled: Annotated[bool, Form()] = False,
    is_default: Annotated[bool, Form()] = False,
    config_id: Annotated[str, Form()] = "",
) -> RedirectResponse:
    form = await request.form()
    collection_ids = _parse_collection_ids(
        [v for v in form.getlist("collection_ids") if isinstance(v, str)]
    )
    temperature = max(0.0, min(temperature, 2.0))
    top_k = max(1, min(top_k, 20))

    if config_id:
        config = await _load_config(db, project, uuid.UUID(config_id))
        action = "chat_config.update"
    else:
        config = ChatConfig(project_id=project.id)
        db.add(config)
        action = "chat_config.create"

    config.name = name.strip()
    config.system_prompt = system_prompt.strip() or None
    config.model = model.strip() or None
    config.temperature = temperature
    config.top_k = top_k
    config.rerank_enabled = rerank_enabled
    config.collection_ids = collection_ids
    config.is_default = is_default
    await db.flush()
    if is_default:
        await db.execute(
            update(ChatConfig)
            .where(ChatConfig.project_id == project.id, ChatConfig.id != config.id)
            .values(is_default=False)
        )
    await audit(
        db,
        action,
        actor_user_id=user.id,
        project_id=project.id,
        target_type="chat_config",
        target_id=str(config.id),
        meta={"name": config.name},
    )
    await db.commit()
    return RedirectResponse(f"/projects/{project.id}/chat-configs", status_code=303)


@router.post("/projects/{project_id}/chat-configs/{config_id}/loeschen")
async def config_delete(
    project: ProjectEditor, user: CurrentUser, db: Db, config_id: uuid.UUID
) -> RedirectResponse:
    config = await _load_config(db, project, config_id)
    await audit(
        db,
        "chat_config.delete",
        actor_user_id=user.id,
        project_id=project.id,
        target_type="chat_config",
        target_id=str(config.id),
        meta={"name": config.name},
    )
    await db.delete(config)
    await db.commit()
    return RedirectResponse(f"/projects/{project.id}/chat-configs", status_code=303)
