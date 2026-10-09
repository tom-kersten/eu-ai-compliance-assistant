"""Error-code to Dutch message mapping completeness."""

from __future__ import annotations

from ui import strings

DOCUMENTED_CODES = [
    "database_unreachable",
    "pending_migrations",
    "missing_index",
    "embedding_mismatch",
    "retrieval_failed",
    "llm_invalid_output",
    "selection_invalid",
    "answer_invalid",
    "provider_error",
    "internal_error",
]

CLIENT_CODES = [
    "client_http_error",
    "client_connection_error",
    "client_incomplete_stream",
]


def test_all_documented_and_client_codes_mapped() -> None:
    for code in DOCUMENTED_CODES + CLIENT_CODES:
        assert code in strings.ERROR_MESSAGES
        assert strings.ERROR_MESSAGES[code].strip()


def test_fallback_used_for_unknown() -> None:
    assert strings.message_for_code("no_such_code") == strings.FALLBACK_ERROR
    assert strings.FALLBACK_ERROR.strip()


def test_known_code_returns_dutch_message() -> None:
    msg = strings.message_for_code("retrieval_failed")
    assert msg == strings.ERROR_MESSAGES["retrieval_failed"]
    assert msg != strings.FALLBACK_ERROR
