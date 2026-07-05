# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""End-to-End-Smoke: dünner pytest-Wrapper um scripts/smoke_test.sh.

Voraussetzung: laufende Instanz (App + Worker + Dienste, Setup abgeschlossen).
Start:  GOVDESK_E2E=1 uv run pytest tests/e2e -q
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent


@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("GOVDESK_E2E"), reason="GOVDESK_E2E nicht gesetzt")
def test_smoke_script():
    result = subprocess.run(
        [str(REPO_ROOT / "scripts" / "smoke_test.sh")],
        capture_output=True,
        text=True,
        timeout=600,
        env={**os.environ},
    )
    assert result.returncode == 0, f"Smoke-Test fehlgeschlagen:\n{result.stdout}\n{result.stderr}"
