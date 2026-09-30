"""Guard: application SQL lives only under store/."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src" / "app"
# Uppercase only: prose like "Update tracker" must not count as SQL.
_SQL_KEYWORD = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE|TRUNCATE|CREATE\s+TABLE|ALTER\s+TABLE)\b",
)


@pytest.mark.unit
def test_sql_lives_only_in_store() -> None:
    offenders: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        if "store" in path.relative_to(_SRC).parts:
            continue
        text = path.read_text(encoding="utf-8")
        if _SQL_KEYWORD.search(text):
            offenders.append(str(path.relative_to(_SRC)))
    assert offenders == [], f"SQL found outside store/: {offenders}"
