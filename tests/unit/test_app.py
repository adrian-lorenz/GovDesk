# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

from fastapi.testclient import TestClient

from govdesk.main import create_app


def test_healthz_antwortet():
    with TestClient(create_app()) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_startseite_rendert_deutsch():
    with TestClient(create_app()) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "GovDesk" in response.text
    assert 'lang="de"' in response.text


def test_statische_assets_vorhanden():
    with TestClient(create_app()) as client:
        for pfad in (
            "/static/js/htmx.min.js",
            "/static/css/kern.min.css",
            "/static/fonts/material-symbols-outlined.woff2",
            "/static/fonts/fira-sans/FiraSans-Regular.woff2",
        ):
            assert client.get(pfad).status_code == 200, pfad
