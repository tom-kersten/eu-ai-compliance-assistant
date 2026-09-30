"""Scaffold checks for the frontend suite."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from ui import strings


def test_hello_page_renders() -> None:
    app_path = Path(__file__).resolve().parents[1] / "src" / "ui" / "app.py"
    at = AppTest.from_file(str(app_path))
    at.run()

    assert not at.exception
    assert at.title[0].value == strings.PAGE_TITLE
