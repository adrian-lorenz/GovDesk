# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Lokale Datei-Ablage für Originaldokumente (unter GOVDESK_DATA_DIR)."""

import uuid
from pathlib import Path, PurePosixPath

from govdesk.core.config import get_settings


def _document_dir(project_id: uuid.UUID) -> Path:
    return get_settings().data_dir / "projects" / str(project_id) / "documents"


def store_file(project_id: uuid.UUID, document_id: uuid.UUID, filename: str, data: bytes) -> str:
    """Speichert unter neutraler UUID (Originalname nur in der DB) und
    liefert den Pfad relativ zu data_dir."""
    suffix = PurePosixPath(filename.lower()).suffix[:10]
    directory = _document_dir(project_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{document_id}{suffix}"
    path.write_bytes(data)
    return str(path.relative_to(get_settings().data_dir))


def read_file(relative_path: str) -> bytes:
    return (get_settings().data_dir / relative_path).read_bytes()


def delete_file(relative_path: str) -> None:
    path = get_settings().data_dir / relative_path
    path.unlink(missing_ok=True)
