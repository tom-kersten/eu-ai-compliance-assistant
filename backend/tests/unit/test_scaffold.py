"""Scaffold checks for the unit suite."""

import pytest


@pytest.mark.unit
def test_scaffold_imports_app_package() -> None:
    import app

    assert app.__name__ == "app"
