# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Validierung und Normalisierung des plattformweiten Brandings."""

import base64
import hashlib
import io
import re
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

DEFAULT_PRIMARY_COLOR = "#3154b8"
DEFAULT_ACCENT_COLOR = "#0f7b6c"
DEFAULT_UI_SCALE = 90
THEME_POLICIES = frozenset({"both", "light", "dark"})

MAX_LOGO_BYTES = 5 * 1024 * 1024
MAX_LOGO_PIXELS = 20_000_000
MAX_LOGO_SIZE = (640, 192)

_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass(frozen=True)
class ProcessedLogo:
    data_base64: str
    content_hash: str
    width: int
    height: int


def normalize_color(value: object, default: str) -> str:
    text = str(value or "").strip()
    return text.lower() if _HEX_COLOR.fullmatch(text) else default


def normalize_theme_policy(value: object) -> str:
    text = str(value or "")
    return text if text in THEME_POLICIES else "both"


def normalize_ui_scale(value: object) -> int:
    try:
        number = int(value)
    except TypeError, ValueError:
        return DEFAULT_UI_SCALE
    return max(80, min(number, 115))


def contrast_color(background: str) -> str:
    """Schwarz/Weiß mit gutem Kontrast zur konfigurierten Aktionsfarbe."""
    color = normalize_color(background, DEFAULT_PRIMARY_COLOR)
    red, green, blue = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    luminance = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255
    return "#131525" if luminance > 0.58 else "#ffffff"


def process_logo(data: bytes) -> ProcessedLogo:
    if not data:
        raise ValueError("Die Logodatei ist leer.")
    if len(data) > MAX_LOGO_BYTES:
        raise ValueError("Das Logo darf höchstens 5 MB groß sein.")

    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in {"PNG", "JPEG", "WEBP"}:
                raise ValueError("Logo nicht lesbar. Erlaubt sind PNG, JPEG und WebP.")
            if source.width * source.height > MAX_LOGO_PIXELS:
                raise ValueError("Das Logo hat zu viele Bildpunkte.")
            source.seek(0)
            source.load()
            image = ImageOps.exif_transpose(source)
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGBA")
            else:
                image = image.copy()
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as exc:
        raise ValueError("Logo nicht lesbar. Erlaubt sind PNG, JPEG und WebP.") from exc

    image.thumbnail(MAX_LOGO_SIZE, Image.Resampling.LANCZOS)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    normalized = output.getvalue()
    return ProcessedLogo(
        data_base64=base64.b64encode(normalized).decode("ascii"),
        content_hash=hashlib.sha256(normalized).hexdigest()[:16],
        width=image.width,
        height=image.height,
    )
