"""Scaffold checks for the live suite (excluded from make test)."""

import pytest


@pytest.mark.live
def test_live_suite_is_collected() -> None:
    assert True
