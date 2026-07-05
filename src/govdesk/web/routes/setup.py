# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Einrichtungs-Wizard (First-Run). Nur erreichbar, solange kein Admin existiert —
die WebSessionMiddleware sperrt /setup danach automatisch."""

import html
import json
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy import text as sql_text

from govdesk.auth.deps import Db
from govdesk.core.app_settings import get_runtime_config, set_setting
from govdesk.core.config import get_settings
from govdesk.rag.llm import OllamaLLMProvider
from govdesk.rag.reranker import RerankerClient
from govdesk.rag.vectorstore import VectorStore
from govdesk.users.service import create_user
from govdesk.web.deps import render

router = APIRouter(prefix="/setup")

# Kuratierte Modell-Empfehlungen für Behörden-Hardware (im Wizard erweiterbar)
CURATED_MODELS = [
    ("gemma3:4b", "Google Gemma 3 (4B) — schnell, gutes Deutsch, läuft auf CPU/kleiner GPU"),
    ("gemma3:12b", "Google Gemma 3 (12B) — deutlich bessere Antworten, braucht ~8 GB VRAM"),
    ("gemma3:27b", "Google Gemma 3 (27B) — höchste Qualität, braucht ~20 GB VRAM"),
    ("mistral:7b", "Mistral 7B — bewährter Allrounder mit solidem Deutsch"),
    ("qwen3:8b", "Qwen 3 (8B) — sehr gutes Deutsch und starkes Reasoning"),
    ("llama3.2:3b", "Meta Llama 3.2 (3B) — sehr leichtgewichtig für schwache Hardware"),
]


@router.get("", response_class=HTMLResponse)
async def wizard(request: Request, db: Db, schritt: int = 1) -> HTMLResponse:
    cfg = await get_runtime_config(db)
    context: dict = {"schritt": schritt, "cfg": cfg}

    if schritt == 1:
        context["checks"] = await _system_checks(db, cfg)
    elif schritt == 3:
        provider = OllamaLLMProvider(cfg.ollama_base_url, cfg.ollama_api_key)
        try:
            installed = set(await provider.list_models())
        except Exception:
            installed = set()
        context["installed"] = installed
        context["curated"] = CURATED_MODELS
        context["embedding_installed"] = any(m.startswith(cfg.embedding_model) for m in installed)
        reranker = RerankerClient(cfg.reranker_url)
        context["reranker_ok"] = await reranker.is_available()

    return render(request, f"setup/schritt{min(schritt, 4)}.html", context)


async def _system_checks(db, cfg) -> list[dict]:
    checks = []
    try:
        await db.execute(sql_text("SELECT 1"))
        checks.append({"name": "PostgreSQL", "ok": True, "detail": "Verbindung hergestellt"})
    except Exception as exc:
        checks.append({"name": "PostgreSQL", "ok": False, "detail": str(exc)[:200]})
    store = VectorStore()
    try:
        qdrant_ok = await store.is_available()
    finally:
        await store.close()
    checks.append(
        {
            "name": "Qdrant (Vektordatenbank)",
            "ok": qdrant_ok,
            "detail": get_settings().qdrant_url if qdrant_ok else "Nicht erreichbar",
        }
    )
    return checks


@router.post("/ollama/test", response_class=HTMLResponse)
async def ollama_test(
    request: Request,
    base_url: Annotated[str, Form()],
    api_key: Annotated[str, Form()] = "",
) -> HTMLResponse:
    provider = OllamaLLMProvider(base_url.strip(), api_key.strip() or None)
    try:
        models = await provider.list_models()
        ok, detail = True, f"Verbunden — {len(models)} Modell(e) installiert"
    except Exception as exc:
        ok, detail = False, f"Keine Verbindung: {str(exc)[:200]}"
    return render(request, "setup/_testergebnis.html", {"ok": ok, "detail": detail})


@router.post("/ollama")
async def save_ollama(
    db: Db,
    base_url: Annotated[str, Form()],
    api_key: Annotated[str, Form()] = "",
) -> RedirectResponse:
    await set_setting(db, "ollama_base_url", base_url.strip())
    await set_setting(db, "ollama_api_key", api_key.strip() or None)
    await db.commit()
    return RedirectResponse("/setup?schritt=3", status_code=303)


@router.get("/modelle/pull")
async def pull_model(db: Db, model: str) -> StreamingResponse:
    """SSE-Stream: Modell-Download mit Fortschritt."""
    cfg = await get_runtime_config(db)
    provider = OllamaLLMProvider(cfg.ollama_base_url, cfg.ollama_api_key)

    async def event_stream():
        try:
            async for status, completed, total in provider.pull_stream(model):
                percent = int(completed * 100 / total) if total else 0
                bar = (
                    f'<progress class="max" value="{percent}" max="100"></progress>'
                    f"<span>{html.escape(status)} {percent}%</span>"
                    if total
                    else f"<span>{html.escape(status)}</span>"
                )
                yield f"event: progress\ndata: {bar}\n\n"
            yield (
                "event: done\ndata: "
                '<span class="green-text"><i>check_circle</i> Modell installiert</span>\n\n'
            )
        except Exception as exc:
            detail = html.escape(str(exc)[:200])
            yield (
                "event: done\ndata: "
                f'<span class="error-text"><i>error</i> Download fehlgeschlagen: '
                f"{detail}</span>\n\n"
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/modelle")
async def save_models(db: Db, default_llm_model: Annotated[str, Form()]) -> RedirectResponse:
    await set_setting(db, "default_llm_model", default_llm_model.strip())
    await set_setting(db, "embedding_model", get_settings().embedding_model)
    reranker = RerankerClient((await get_runtime_config(db)).reranker_url)
    await set_setting(db, "reranker_enabled", await reranker.is_available())
    await db.commit()
    return RedirectResponse("/setup?schritt=4", status_code=303)


@router.post("/admin")
async def create_admin(
    request: Request,
    db: Db,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    password2: Annotated[str, Form()],
    email: Annotated[str, Form()] = "",
):
    if password != password2:
        return render(
            request,
            "setup/schritt4.html",
            {"schritt": 4, "error": "Die Passwörter stimmen nicht überein."},
            status_code=400,
        )
    if len(password) < 12:
        return render(
            request,
            "setup/schritt4.html",
            {"schritt": 4, "error": "Das Passwort muss mindestens 12 Zeichen lang sein."},
            status_code=400,
        )
    await create_user(db, username, password, email.strip() or None, is_platform_admin=True)
    await set_setting(db, "setup_completed", True)
    await db.commit()
    return RedirectResponse("/login", status_code=303)


@router.get("/modelle/status", response_class=HTMLResponse)
async def models_status(request: Request, db: Db) -> HTMLResponse:
    """HTMX-Partial: installierte Modelle neu prüfen (nach einem Pull)."""
    cfg = await get_runtime_config(db)
    provider = OllamaLLMProvider(cfg.ollama_base_url, cfg.ollama_api_key)
    try:
        installed = set(await provider.list_models())
    except Exception:
        installed = set()
    return HTMLResponse(json.dumps(sorted(installed)))
