"""Makefile offline targets honour ENV_FILE and the offline profile."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

MAKEFILE_PATH = Path("/repo/Makefile")


def _recipe(makefile: str, target: str) -> str:
    pattern = re.compile(
        rf"^{re.escape(target)}:.*$\n((?:^\t.*\n?)*)",
        re.MULTILINE,
    )
    match = pattern.search(makefile)
    assert match, f"missing Makefile target {target}"
    return match.group(1)


def test_up_offline_uses_profile_and_vllm_services() -> None:
    assert MAKEFILE_PATH.is_file(), f"missing {MAKEFILE_PATH}"
    text = MAKEFILE_PATH.read_text(encoding="utf-8")
    recipe = _recipe(text, "up-offline")
    assert "--profile offline" in recipe
    assert "vllm-llm" in recipe
    assert "vllm-embed" in recipe


def test_ingest_and_test_live_honour_env_file() -> None:
    assert MAKEFILE_PATH.is_file(), f"missing {MAKEFILE_PATH}"
    text = MAKEFILE_PATH.read_text(encoding="utf-8")
    for target in ("test-live", "ingest", "ingest-reset"):
        recipe = _recipe(text, target)
        assert "$(ENV_FILE)" in recipe or "${ENV_FILE}" in recipe, (
            f"{target} must honour ENV_FILE"
        )
        assert "test -f $(ENV_FILE)" in recipe or "test -f ${ENV_FILE}" in recipe, (
            f"{target} existence check must use ENV_FILE"
        )
        # Hardcoded .env alone must not drive these targets.
        assert "test -f .env ||" not in recipe
        assert "--env-file .env " not in recipe.replace(
            "--env-file $(ENV_FILE)", ""
        ).replace("--env-file ${ENV_FILE}", "")
