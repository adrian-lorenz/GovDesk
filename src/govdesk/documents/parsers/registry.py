# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Zuordnung Dateiendung → Parser. Weitere Formate kommen in Slice 3."""

from pathlib import PurePosixPath

from govdesk.documents.parsers.base import DocumentParser, UnsupportedFormatError
from govdesk.documents.parsers.doc_legacy import DocLegacyParser
from govdesk.documents.parsers.docx import DocxParser
from govdesk.documents.parsers.html import HtmlParser
from govdesk.documents.parsers.odt import OdtParser
from govdesk.documents.parsers.pdf import PdfParser
from govdesk.documents.parsers.text import MarkdownParser, TextParser

_PARSERS: dict[str, DocumentParser] = {
    ".pdf": PdfParser(),
    ".txt": TextParser(),
    ".md": MarkdownParser(),
    ".markdown": MarkdownParser(),
    ".docx": DocxParser(),
    ".doc": DocLegacyParser(),
    ".odt": OdtParser(),
    ".html": HtmlParser(),
    ".htm": HtmlParser(),
}

SUPPORTED_EXTENSIONS = sorted(_PARSERS)


def parser_for(filename: str) -> DocumentParser:
    suffix = PurePosixPath(filename.lower()).suffix
    parser = _PARSERS.get(suffix)
    if parser is None:
        supported = ", ".join(SUPPORTED_EXTENSIONS)
        raise UnsupportedFormatError(
            f"Dateiformat „{suffix or filename}“ wird noch nicht unterstützt. "
            f"Unterstützte Formate: {supported}"
        )
    return parser
