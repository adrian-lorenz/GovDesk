# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

# ---- Build-Stage: Abhängigkeiten mit uv installieren ----
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

WORKDIR /app

# Erst nur Lock + Metadaten: Docker-Layer-Cache für Dependencies
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---- Runtime-Stage ----
FROM python:3.14-slim-bookworm

RUN useradd --create-home --uid 1000 govdesk

WORKDIR /app
COPY --from=builder --chown=govdesk:govdesk /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    GOVDESK_DATA_DIR=/data

RUN mkdir /data && chown govdesk:govdesk /data
VOLUME /data

USER govdesk
EXPOSE 8000

CMD ["govdesk", "serve"]
