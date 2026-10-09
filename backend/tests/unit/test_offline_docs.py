"""OFFLINE.md headings and README offline quickstart."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

OFFLINE_PATH = Path("/repo/docs/OFFLINE.md")
README_PATH = Path("/repo/README.md")

REQUIRED_HEADINGS = (
    "Usage",
    "Hardware",
    "Quantization",
    "Maximum context length",
    "Served model name",
    "Image",
    "Flags",
)


def test_offline_md_has_required_headings_and_unverified_or_live_result() -> None:
    assert OFFLINE_PATH.is_file(), f"missing {OFFLINE_PATH}"
    text = OFFLINE_PATH.read_text(encoding="utf-8")
    for heading in REQUIRED_HEADINGS:
        assert heading in text, f"OFFLINE.md missing heading: {heading}"

    has_live_result = ("row count" in text.lower() or "rows" in text.lower()) and (
        "wall time" in text.lower() or "wall-time" in text.lower()
    )
    if not has_live_result:
        assert "Unverified" in text


def test_readme_offline_quickstart_links_and_commands() -> None:
    assert README_PATH.is_file(), f"missing {README_PATH}"
    text = README_PATH.read_text(encoding="utf-8")
    assert "Quickstart (offline)" in text
    assert "docs/OFFLINE.md" in text
    assert "make up-offline" in text
    assert "make ingest ENV_FILE=.env.offline" in text
    assert "make test-live ENV_FILE=.env.offline" in text
