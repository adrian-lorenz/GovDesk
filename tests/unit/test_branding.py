# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

import base64
import io

import pytest
from PIL import Image

from govdesk.core.branding import (
    MAX_LOGO_BYTES,
    contrast_color,
    normalize_color,
    normalize_theme_policy,
    normalize_ui_scale,
    process_logo,
)


def _image_bytes(size: tuple[int, int], image_format: str = "PNG", mode: str = "RGBA") -> bytes:
    image = Image.new(mode, size, (49, 84, 184, 128))
    output = io.BytesIO()
    image.save(output, format=image_format)
    return output.getvalue()


def test_logo_is_resized_and_normalized_to_png() -> None:
    processed = process_logo(_image_bytes((1600, 400)))
    normalized = base64.b64decode(processed.data_base64)

    with Image.open(io.BytesIO(normalized)) as result:
        assert result.format == "PNG"
        assert result.size == (640, 160)
        assert result.mode == "RGBA"
    assert processed.width == 640
    assert processed.height == 160
    assert len(processed.content_hash) == 16


@pytest.mark.parametrize(
    "payload",
    [b"", b"kein bild", b"x" * (MAX_LOGO_BYTES + 1)],
)
def test_invalid_logo_is_rejected(payload: bytes) -> None:
    with pytest.raises(ValueError):
        process_logo(payload)


def test_branding_values_are_normalized() -> None:
    assert normalize_color("#ABC123", "#000000") == "#abc123"
    assert normalize_color("red", "#3154b8") == "#3154b8"
    assert normalize_theme_policy("dark") == "dark"
    assert normalize_theme_policy("system") == "both"
    assert normalize_ui_scale(70) == 80
    assert normalize_ui_scale(120) == 115
    assert normalize_ui_scale("90") == 90


def test_contrast_color_chooses_readable_foreground() -> None:
    assert contrast_color("#ffffff") == "#131525"
    assert contrast_color("#000000") == "#ffffff"
