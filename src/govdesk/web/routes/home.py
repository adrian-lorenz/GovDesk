# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

router = APIRouter()


@router.get("/")
async def index(request: Request) -> RedirectResponse:
    if getattr(request.state, "user", None) is not None:
        return RedirectResponse("/projects", status_code=303)
    return RedirectResponse("/login", status_code=303)
