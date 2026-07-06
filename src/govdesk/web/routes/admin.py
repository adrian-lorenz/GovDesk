# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Admin-Bereich: Nutzerverwaltung und Plattform-Einstellungen."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, text

from govdesk.auth.deps import Db, PlatformAdmin
from govdesk.connectors.registry import all_connectors
from govdesk.connectors.service import ENABLED_SETTING_KEY, enabled_type_ids
from govdesk.core.app_settings import RuntimeConfig, get_runtime_config, set_setting
from govdesk.core.audit import audit
from govdesk.core.config import get_settings
from govdesk.db.models import User
from govdesk.rag.llm import OllamaLLMProvider, OpenAICompatProvider
from govdesk.rag.reranker import RerankerClient
from govdesk.rag.vectorstore import VectorStore
from govdesk.users.service import create_user
from govdesk.web.deps import render

router = APIRouter(prefix="/admin")


async def _service_status(db: Db, cfg: RuntimeConfig) -> list[dict]:
    """Health-Übersicht der abhängigen Dienste für die Admin-Ansicht."""
    status: list[dict] = []

    try:
        await db.execute(text("SELECT 1"))
        status.append({"name": "PostgreSQL", "ok": True, "detail": "verbunden"})
    except Exception as exc:
        status.append({"name": "PostgreSQL", "ok": False, "detail": str(exc)[:120]})

    store = VectorStore()
    try:
        qdrant_ok = await store.is_available()
    finally:
        await store.close()
    status.append(
        {"name": "Qdrant (Vektor-DB)", "ok": qdrant_ok,
         "detail": "erreichbar" if qdrant_ok else "nicht erreichbar"}
    )

    try:
        models = await OllamaLLMProvider(cfg.ollama_base_url, cfg.ollama_api_key).list_models()
        status.append({"name": "Ollama", "ok": True, "detail": f"{len(models)} Modell(e)"})
    except Exception as exc:
        status.append({"name": "Ollama", "ok": False, "detail": str(exc)[:120]})

    rr_ok = await RerankerClient(cfg.reranker_url).is_available()
    status.append(
        {"name": "Reranker", "ok": rr_ok,
         "detail": ("erreichbar" if rr_ok else "nicht erreichbar")
         + ("" if cfg.reranker_enabled else " (deaktiviert)")}
    )

    if cfg.llm_provider == "openai" and cfg.openai_base_url:
        try:
            ext = await OpenAICompatProvider(cfg.openai_base_url, cfg.openai_api_key).list_models()
            status.append(
                {"name": "Externer LLM (OpenAI-kompatibel)", "ok": True,
                 "detail": f"{len(ext)} Modell(e)"}
            )
        except Exception as exc:
            status.append(
                {"name": "Externer LLM (OpenAI-kompatibel)", "ok": False, "detail": str(exc)[:120]}
            )

    return status


@router.get("/users", response_class=HTMLResponse)
async def user_list(request: Request, admin: PlatformAdmin, db: Db) -> HTMLResponse:
    result = await db.execute(select(User).order_by(User.username))
    return render(request, "admin/users.html", {"users": list(result.scalars())})


@router.post("/users")
async def user_create(
    request: Request,
    admin: PlatformAdmin,
    db: Db,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    email: Annotated[str, Form()] = "",
    display_name: Annotated[str, Form()] = "",
    is_platform_admin: Annotated[bool, Form()] = False,
):
    if len(password) < 12:
        result = await db.execute(select(User).order_by(User.username))
        return render(
            request,
            "admin/users.html",
            {
                "users": list(result.scalars()),
                "error": "Das Passwort muss mindestens 12 Zeichen lang sein.",
            },
            status_code=400,
        )
    existing = await db.execute(select(User.id).where(User.username == username.strip()))
    if existing.scalar_one_or_none() is not None:
        result = await db.execute(select(User).order_by(User.username))
        return render(
            request,
            "admin/users.html",
            {
                "users": list(result.scalars()),
                "error": f"Benutzername „{username}“ ist bereits vergeben.",
            },
            status_code=400,
        )
    user = await create_user(
        db,
        username,
        password,
        email.strip() or None,
        display_name.strip() or None,
        is_platform_admin=is_platform_admin,
    )
    await audit(
        db,
        "user.create",
        actor_user_id=admin.id,
        target_type="user",
        target_id=str(user.id),
        meta={"username": user.username, "is_platform_admin": is_platform_admin},
    )
    await db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/users/{user_id}/aktiv")
async def user_toggle_active(admin: PlatformAdmin, db: Db, user_id: uuid.UUID) -> RedirectResponse:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404)
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Eigenes Konto kann nicht deaktiviert werden")
    user.is_active = not user.is_active
    await audit(
        db,
        "user.activate" if user.is_active else "user.deactivate",
        actor_user_id=admin.id,
        target_type="user",
        target_id=str(user.id),
    )
    await db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/users/{user_id}/adminrolle")
async def user_toggle_admin(admin: PlatformAdmin, db: Db, user_id: uuid.UUID) -> RedirectResponse:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404)
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Eigene Admin-Rolle kann nicht entzogen werden")
    user.is_platform_admin = not user.is_platform_admin
    await audit(
        db,
        "user.grant_admin" if user.is_platform_admin else "user.revoke_admin",
        actor_user_id=admin.id,
        target_type="user",
        target_id=str(user.id),
    )
    await db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@router.get("/settings")
async def settings_index(admin: PlatformAdmin) -> RedirectResponse:
    return RedirectResponse("/admin/settings/branding", status_code=307)


@router.get("/settings/branding", response_class=HTMLResponse)
async def settings_branding(request: Request, admin: PlatformAdmin) -> HTMLResponse:
    # platform_name / platform_subtitle liefert render() global aus request.state.
    return render(request, "admin/settings/branding.html")


@router.get("/settings/ki", response_class=HTMLResponse)
async def settings_ki(request: Request, admin: PlatformAdmin, db: Db) -> HTMLResponse:
    cfg = await get_runtime_config(db)
    try:
        installed = await OllamaLLMProvider(cfg.ollama_base_url, cfg.ollama_api_key).list_models()
    except Exception:
        installed = []
    external_models: list[str] = []
    if cfg.openai_base_url:
        try:
            external_models = await OpenAICompatProvider(
                cfg.openai_base_url, cfg.openai_api_key
            ).list_models()
        except Exception:
            external_models = []
    return render(
        request,
        "admin/settings/ki.html",
        {"cfg": cfg, "installed": installed, "external_models": external_models},
    )


@router.get("/settings/reranking", response_class=HTMLResponse)
async def settings_reranking(request: Request, admin: PlatformAdmin, db: Db) -> HTMLResponse:
    cfg = await get_runtime_config(db)
    reranker_ok = await RerankerClient(cfg.reranker_url).is_available()
    return render(
        request, "admin/settings/reranking.html", {"cfg": cfg, "reranker_ok": reranker_ok}
    )


@router.get("/settings/connectoren", response_class=HTMLResponse)
async def settings_connectoren(request: Request, admin: PlatformAdmin, db: Db) -> HTMLResponse:
    return render(
        request,
        "admin/settings/connectoren.html",
        {"connectors": all_connectors(), "enabled": set(await enabled_type_ids(db))},
    )


@router.get("/settings/anmeldung", response_class=HTMLResponse)
async def settings_anmeldung(request: Request, admin: PlatformAdmin) -> HTMLResponse:
    env = get_settings()
    try:
        redirect_uri = str(request.url_for("oidc_callback"))
    except Exception:
        redirect_uri = "—"
    oidc_info = {
        "enabled": env.oidc_enabled,
        "local_login": env.local_login_enabled,
        "issuer": env.oidc_issuer or "—",
        "client_id": env.oidc_client_id or "—",
        "redirect_uri": redirect_uri,
    }
    return render(request, "admin/settings/anmeldung.html", {"oidc_info": oidc_info})


@router.get("/settings/system", response_class=HTMLResponse)
async def settings_system(request: Request, admin: PlatformAdmin, db: Db) -> HTMLResponse:
    cfg = await get_runtime_config(db)
    services = await _service_status(db, cfg)
    env = get_settings()
    env_info = [
        {"label": "Sichere Cookies", "value": "ja" if env.cookie_secure else "nein"},
        {"label": "Session-Leerlauf", "value": f"{env.session_idle_hours} h"},
        {"label": "Session-Maximaldauer", "value": f"{env.session_max_days} Tage"},
        {"label": "Embedding-Dimensionen", "value": env.embedding_dimensions},
        {"label": "Datenverzeichnis", "value": str(env.data_dir)},
    ]
    return render(
        request,
        "admin/settings/system.html",
        {"cfg": cfg, "services": services, "env_info": env_info},
    )


@router.post("/settings/ollama-test", response_class=HTMLResponse)
async def settings_ollama_test(
    request: Request,
    admin: PlatformAdmin,
    ollama_base_url: Annotated[str, Form()],
    ollama_api_key: Annotated[str, Form()] = "",
) -> HTMLResponse:
    provider = OllamaLLMProvider(ollama_base_url.strip(), ollama_api_key.strip() or None)
    try:
        models = await provider.list_models()
        ok, detail = True, f"Verbunden — {len(models)} Modell(e) installiert"
    except Exception as exc:
        ok, detail = False, f"Keine Verbindung: {str(exc)[:200]}"
    return render(request, "setup/_testergebnis.html", {"ok": ok, "detail": detail})


@router.post("/settings/openai-test", response_class=HTMLResponse)
async def settings_openai_test(
    request: Request,
    admin: PlatformAdmin,
    openai_base_url: Annotated[str, Form()],
    openai_api_key: Annotated[str, Form()] = "",
) -> HTMLResponse:
    base = openai_base_url.strip()
    if not base:
        return render(
            request, "setup/_testergebnis.html",
            {"ok": False, "detail": "Keine Endpunkt-URL angegeben"},
        )
    provider = OpenAICompatProvider(base, openai_api_key.strip() or None)
    try:
        models = await provider.list_models()
        ok, detail = True, f"Verbunden — {len(models)} Modell(e) verfügbar"
    except Exception as exc:
        ok, detail = False, f"Keine Verbindung: {str(exc)[:200]}"
    return render(request, "setup/_testergebnis.html", {"ok": ok, "detail": detail})


@router.post("/settings/branding")
async def settings_branding_save(
    admin: PlatformAdmin,
    db: Db,
    platform_name: Annotated[str, Form()] = "",
    platform_subtitle: Annotated[str, Form()] = "",
) -> RedirectResponse:
    await set_setting(db, "platform_name", platform_name.strip() or None)
    await set_setting(db, "platform_subtitle", platform_subtitle.strip() or None)
    await audit(db, "settings.update", actor_user_id=admin.id, meta={"section": "branding"})
    await db.commit()
    return RedirectResponse("/admin/settings/branding", status_code=303)


@router.post("/settings/ki")
async def settings_ki_save(
    admin: PlatformAdmin,
    db: Db,
    ollama_base_url: Annotated[str, Form()],
    default_llm_model: Annotated[str, Form()],
    ollama_api_key: Annotated[str, Form()] = "",
    llm_provider: Annotated[str, Form()] = "ollama",
    openai_base_url: Annotated[str, Form()] = "",
    openai_api_key: Annotated[str, Form()] = "",
    openai_model: Annotated[str, Form()] = "",
) -> RedirectResponse:
    await set_setting(db, "ollama_base_url", ollama_base_url.strip())
    await set_setting(db, "ollama_api_key", ollama_api_key.strip() or None)
    await set_setting(db, "default_llm_model", default_llm_model.strip())
    await set_setting(db, "llm_provider", "openai" if llm_provider == "openai" else "ollama")
    await set_setting(db, "openai_base_url", openai_base_url.strip() or None)
    await set_setting(db, "openai_api_key", openai_api_key.strip() or None)
    await set_setting(db, "openai_model", openai_model.strip() or None)
    await audit(
        db,
        "settings.update",
        actor_user_id=admin.id,
        meta={"section": "ki", "llm_provider": llm_provider},
    )
    await db.commit()
    return RedirectResponse("/admin/settings/ki", status_code=303)


@router.post("/settings/reranking")
async def settings_reranking_save(
    admin: PlatformAdmin,
    db: Db,
    reranker_url: Annotated[str, Form()],
    reranker_enabled: Annotated[bool, Form()] = False,
) -> RedirectResponse:
    await set_setting(db, "reranker_url", reranker_url.strip())
    await set_setting(db, "reranker_enabled", reranker_enabled)
    await audit(db, "settings.update", actor_user_id=admin.id, meta={"section": "reranking"})
    await db.commit()
    return RedirectResponse("/admin/settings/reranking", status_code=303)


@router.post("/settings/connectoren")
async def settings_connectoren_save(
    request: Request, admin: PlatformAdmin, db: Db
) -> RedirectResponse:
    form = await request.form()
    enabled = [
        c.type_id
        for c in all_connectors()
        if form.get(f"connector_enabled_{c.type_id}") is not None
    ]
    await set_setting(db, ENABLED_SETTING_KEY, enabled)
    await audit(db, "settings.update", actor_user_id=admin.id, meta={"section": "connectoren"})
    await db.commit()
    return RedirectResponse("/admin/settings/connectoren", status_code=303)
