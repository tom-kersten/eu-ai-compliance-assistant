"""Unit tests for the replaceable token estimator."""

from __future__ import annotations

import pytest

from app.ingestion.tokens import estimate_tokens


@pytest.mark.unit
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", 0),
        ("a", 1),
        ("abc", 1),
        ("abcd", 2),
    ],
)
def test_estimate_tokens_ceil_len_div_3(text: str, expected: int) -> None:
    assert estimate_tokens(text) == expected
