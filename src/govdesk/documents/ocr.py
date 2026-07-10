# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""OCR beim Einbetten: Bilddateien und gescannte PDF-Seiten per Vision-Modell.

Läuft ausschließlich im Ingest-Worker (Queue) — nie im Request. Das Modell
(Standard: glm-ocr:latest) wird über die Ollama-API mit Bildanhang befragt;
alles bleibt on-premises.
"""

import asyncio
import base64
import logging

import httpx

from govdesk.core.app_settings import RuntimeConfig
from govdesk.documents.parsers.base import Block

logger = logging.getLogger(__name__)

# Dateiendungen, die als Bild per OCR eingelesen werden.
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}

# Obergrenzen, damit ein 300-Seiten-Scan den Worker nicht stundenlang bindet.
MAX_OCR_PAGES = 40
_RENDER_SCALE = 2.0  # ~144 dpi — guter Kompromiss aus Lesbarkeit und Größe
_MIN_PAGE_CHARS = 25  # weniger extrahierter Text ⇒ Seite gilt als Scan

_OCR_PROMPT = (
    "Extrahiere den vollständigen Text aus diesem Bild. Gib NUR den erkannten "
    "Text zurück — keine Beschreibung, keine Einleitung, keine Codeblöcke. "
    "Erhalte Absätze und Überschriften durch Leerzeilen; gib Tabellen als "
    "einfache Textzeilen wieder."
)


# OCR einer Seite kann bei großen Vision-Modellen dauern.
_OCR_TIMEOUT_SECONDS = 300.0


async def ocr_image(cfg: RuntimeConfig, image: bytes) -> str:
    """Text eines Bilds über das Vision-Modell der Ollama-Instanz."""
    headers = {}
    if cfg.ollama_api_key:
        headers["Authorization"] = f"Bearer {cfg.ollama_api_key}"
    payload = {
        "model": cfg.ocr_model,
        "stream": False,
        "options": {"temperature": 0},
        "messages": [
            {
                "role": "user",
                "content": _OCR_PROMPT,
                "images": [base64.b64encode(image).decode()],
            }
        ],
    }
    async with httpx.AsyncClient(timeout=_OCR_TIMEOUT_SECONDS) as client:
        response = await client.post(
            f"{cfg.ollama_base_url.rstrip('/')}/api/chat", json=payload, headers=headers
        )
        response.raise_for_status()
        return (response.json().get("message") or {}).get("content", "").strip()


def _text_blocks(text: str, page_no: int | None) -> list[Block]:
    blocks = []
    for absatz in text.split("\n\n"):
        cleaned = " ".join(absatz.split())
        if cleaned:
            blocks.append(Block(text=cleaned, page_no=page_no))
    return blocks


async def ocr_image_to_blocks(cfg: RuntimeConfig, image: bytes) -> list[Block]:
    text = await ocr_image(cfg, image)
    if not text:
        raise ValueError(
            f"OCR ({cfg.ocr_model}) hat keinen Text erkannt — ist das Bild lesbar?"
        )
    return _text_blocks(text, page_no=None)


def _render_pdf_page(pdf_bytes: bytes, page_no: int) -> bytes:
    """Rendert eine PDF-Seite (1-basiert) als PNG — synchron, für to_thread.

    Nutzt denselben Stdlib-PNG-Encoder wie die Quellen-Vorschau (kein Pillow).
    """
    import pypdfium2 as pdfium

    from govdesk.documents.highlight import _encode_png

    pdf = pdfium.PdfDocument(pdf_bytes)
    try:
        page = pdf[page_no - 1]
        bitmap = page.render(scale=_RENDER_SCALE, rev_byteorder=True)
        return _encode_png(
            bitmap.width, bitmap.height, bitmap.n_channels, bytes(bitmap.buffer), bitmap.stride
        )
    finally:
        pdf.close()


async def ocr_missing_pdf_pages(
    cfg: RuntimeConfig, pdf_bytes: bytes, blocks: list[Block]
) -> list[Block]:
    """Ergänzt Blöcke um OCR-Text für PDF-Seiten ohne (nennenswerte) Textebene.

    Seiten mit vorhandenem Text bleiben unangetastet; die OCR-Blöcke werden
    seitenrichtig einsortiert, damit das Chunking die Reihenfolge behält.
    """
    import pypdfium2 as pdfium

    def _seitenzahl() -> int:
        pdf = pdfium.PdfDocument(pdf_bytes)
        try:
            return len(pdf)
        finally:
            pdf.close()

    seiten = await asyncio.to_thread(_seitenzahl)
    zeichen_je_seite: dict[int, int] = {}
    for b in blocks:
        if b.page_no:
            zeichen_je_seite[b.page_no] = zeichen_je_seite.get(b.page_no, 0) + len(b.text)

    scan_seiten = [
        n for n in range(1, seiten + 1) if zeichen_je_seite.get(n, 0) < _MIN_PAGE_CHARS
    ]
    if not scan_seiten:
        return blocks
    uebersprungen = len(scan_seiten) - MAX_OCR_PAGES
    if uebersprungen > 0:
        logger.warning(
            "OCR: %d Scan-Seiten über dem Limit von %d — werden übersprungen",
            uebersprungen,
            MAX_OCR_PAGES,
        )
        scan_seiten = scan_seiten[:MAX_OCR_PAGES]

    ocr_bloecke: dict[int, list[Block]] = {}
    for n in scan_seiten:
        png = await asyncio.to_thread(_render_pdf_page, pdf_bytes, n)
        text = await ocr_image(cfg, png)
        if text:
            ocr_bloecke[n] = _text_blocks(text, page_no=n)

    if not ocr_bloecke:
        return blocks

    # Seitenrichtig zusammenführen: bestehende + OCR-Blöcke nach Seite sortiert
    # (stabil — Reihenfolge innerhalb einer Seite bleibt erhalten).
    alle = blocks + [b for bloecke in ocr_bloecke.values() for b in bloecke]
    alle.sort(key=lambda b: b.page_no or 0)
    logger.info("OCR: %d Scan-Seiten gelesen (%s)", len(ocr_bloecke), cfg.ocr_model)
    return alle
