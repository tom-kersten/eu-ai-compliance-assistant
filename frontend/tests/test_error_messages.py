from ui import strings


def test_error_codes_covered():
    codes = [
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
    for c in codes:
        assert c in strings.ERROR_MESSAGES


def test_fallback_used_for_unknown():
    assert strings.ERROR_MESSAGES.get("no_such_code") is None
    assert strings.FALLBACK_ERROR
