# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

from typing import Any

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from govdesk.db.base import Base, TimestampMixin


class AppSetting(Base, TimestampMixin):
    """Zur Laufzeit änderbare Plattform-Konfiguration (Wizard, /admin/settings).

    Umgebungsvariablen liefern nur Initialwerte; was hier steht, gewinnt.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
