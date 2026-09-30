"""Unit tests for the new-migration helper."""

from pathlib import Path

import pytest

from app.store.migrate import create_migration


@pytest.mark.unit
def test_new_migration_assigns_next_zero_padded_number(tmp_path: Path) -> None:
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    empty = create_migration(empty_dir, "add_feedback")
    assert empty.name == "0001_add_feedback.sql"
    assert empty.read_text() == ""

    with_one = tmp_path / "with_one"
    with_one.mkdir()
    (with_one / "0001_init.sql").write_text("-- init\n")
    second = create_migration(with_one, "add_feedback")
    assert second.name == "0002_add_feedback.sql"

    with_gap = tmp_path / "with_gap"
    with_gap.mkdir()
    (with_gap / "0001_init.sql").write_text("-- init\n")
    (with_gap / "0003_gap.sql").write_text("-- gap\n")
    after_gap = create_migration(with_gap, "add_notes")
    assert after_gap.name == "0004_add_notes.sql"
