# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Legacy-.doc via LibreOffice-headless (Feature-Flag GOVDESK_ENABLE_DOC_CONVERT).

LibreOffice ist der einzige zuverlässige Weg für das Binärformat; das Flag ist
standardmäßig aus, weil soffice das Docker-Image um ~400 MB vergrößert.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

from govdesk.core.config import get_settings
from govdesk.documents.parsers.base import ParsedDocument, UnsupportedFormatError
from govdesk.documents.parsers.docx import DocxParser


class DocLegacyParser:
    def parse(self, data: bytes) -> ParsedDocument:
        if not get_settings().enable_doc_convert:
            raise UnsupportedFormatError(
                "Das alte .doc-Format wird in dieser Installation nicht unterstützt. "
                "Bitte speichern Sie die Datei als DOCX oder PDF und laden Sie sie erneut hoch. "
                "(Administratoren: GOVDESK_ENABLE_DOC_CONVERT=true aktiviert die Konvertierung.)"
            )
        soffice = shutil.which("soffice") or shutil.which("libreoffice")
        if soffice is None:
            raise UnsupportedFormatError(
                "LibreOffice (soffice) ist nicht installiert — .doc-Konvertierung nicht möglich."
            )
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "eingabe.doc"
            source.write_bytes(data)
            subprocess.run(  # noqa: S603 — feste Argumente, keine Nutzereingabe im Kommando
                [soffice, "--headless", "--convert-to", "docx", "--outdir", tmp, str(source)],
                check=True,
                capture_output=True,
                timeout=120,
            )
            converted = Path(tmp) / "eingabe.docx"
            if not converted.exists():
                raise UnsupportedFormatError("Konvertierung fehlgeschlagen — Datei beschädigt?")
            return DocxParser().parse(converted.read_bytes())
