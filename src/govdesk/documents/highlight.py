# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""On-demand-Rendering einer PDF-Seite mit markierter Fundstelle.

Nutzt pypdfium2 (PDFium, Apache-2.0/BSD) — es rendert die Seite zu einem PNG und
liefert Textpositionen. Der zitierte Chunk-Text wird whitespace-tolerant auf der
Seite lokalisiert (die Ingestion normalisiert Leerraum, das PDF nicht), sodass wir
keine Bounding-Boxes vorab speichern und keine Migration brauchen.
"""

import base64
import struct
import zlib
from dataclasses import dataclass

import pypdfium2 as pdfium

# Render-Auflösung deckeln: genug für scharfe Lesbarkeit im Modal, aber kein
# unnötig großes Base64-Bild in der Antwort.
_MAX_RENDER_PX = 1600
_MIN_NEEDLE_CHARS = 12  # zu kurze Fragmente matchen sonst beliebig


@dataclass(frozen=True)
class Rect:
    """Position relativ zur Seitengröße (0..1), Ursprung oben links."""

    left: float
    top: float
    width: float
    height: float


@dataclass(frozen=True)
class PageHighlight:
    image_data_uri: str
    aspect_ratio: float  # Breite / Höhe der gerenderten Seite
    rects: list[Rect]


def _encode_png(width: int, height: int, channels: int, buffer: bytes, stride: int) -> bytes:
    """Kodiert ein RGB/RGBA/Graustufen-Bitmap als PNG — nur mit der Stdlib (kein Pillow)."""
    color_type = {1: 0, 3: 2, 4: 6}[channels]
    row_bytes = width * channels
    raw = bytearray()
    for y in range(height):
        start = y * stride
        raw.append(0)  # Filter-Byte „None" pro Zeile
        raw += buffer[start : start + row_bytes]

    def _chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + _chunk(b"IEND", b"")
    )


def _normalize(text: str) -> tuple[str, list[int]]:
    """Kollabiert Leerraum und liefert die Zuordnung normiert→roh (Zeichenindex)."""
    chars: list[str] = []
    mapping: list[int] = []
    prev_space = False
    for i, ch in enumerate(text):
        if ch.isspace():
            if not prev_space and chars:
                chars.append(" ")
                mapping.append(i)
            prev_space = True
        else:
            chars.append(ch)
            mapping.append(i)
            prev_space = False
    return "".join(chars), mapping


def _rects_for_range(
    textpage, raw_start: int, raw_len: int, page_w: float, page_h: float
) -> list[Rect]:
    count = textpage.count_rects(raw_start, raw_len)
    rects: list[Rect] = []
    for idx in range(count):
        left, bottom, right, top = textpage.get_rect(idx)
        if right <= left or top <= bottom:
            continue
        rects.append(
            Rect(
                left=left / page_w,
                top=(page_h - top) / page_h,
                width=(right - left) / page_w,
                height=(top - bottom) / page_h,
            )
        )
    return rects


def render_page_with_highlights(
    pdf_bytes: bytes, page_no: int, needles: list[str]
) -> PageHighlight | None:
    """Rendert Seite `page_no` (1-basiert) und markiert die Fundstellen der `needles`.

    Gibt None zurück, wenn die Seite nicht existiert. Nicht gefundene Textstellen
    werden stillschweigend übersprungen (die Seite wird trotzdem angezeigt).
    """
    pdf = pdfium.PdfDocument(pdf_bytes)
    try:
        index = page_no - 1
        if index < 0 or index >= len(pdf):
            return None
        page = pdf[index]
        page_w, page_h = page.get_size()
        if page_w <= 0 or page_h <= 0:
            return None

        textpage = page.get_textpage()
        try:
            raw_text = textpage.get_text_range()
            norm_text, mapping = _normalize(raw_text)

            rects: list[Rect] = []
            for needle in needles:
                norm_needle, _ = _normalize(needle)
                norm_needle = norm_needle.strip()
                if len(norm_needle) < _MIN_NEEDLE_CHARS:
                    continue
                pos = norm_text.find(norm_needle)
                if pos < 0:
                    continue
                raw_start = mapping[pos]
                raw_end = mapping[pos + len(norm_needle) - 1]
                rects.extend(
                    _rects_for_range(textpage, raw_start, raw_end - raw_start + 1, page_w, page_h)
                )
        finally:
            textpage.close()

        scale = min(_MAX_RENDER_PX / max(page_w, page_h), 3.0)
        scale = max(scale, 1.0)
        bitmap = page.render(scale=scale, rev_byteorder=True)
        png = _encode_png(
            bitmap.width, bitmap.height, bitmap.n_channels, bytes(bitmap.buffer), bitmap.stride
        )
        data_uri = "data:image/png;base64," + base64.b64encode(png).decode("ascii")

        return PageHighlight(
            image_data_uri=data_uri,
            aspect_ratio=page_w / page_h,
            rects=rects,
        )
    finally:
        pdf.close()
