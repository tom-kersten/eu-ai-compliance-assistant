"""Dutch user-facing strings for the Streamlit UI."""

PAGE_TITLE = "EU AI-nalevingsassistent"
PAGE_HEADING = "Welkom. Stel een vraag over de AI-verordening, AVG, CRA of Omnibus."

# Error messages (Dutch). Unknown codes should use FALLBACK_ERROR.
ERROR_MESSAGES = {
    "database_unreachable": "Database niet bereikbaar",
    "pending_migrations": "Migraties in behandeling",
    "missing_index": "Index ontbreekt",
    "embedding_mismatch": "Embedding-configuratie komt niet overeen",
    "retrieval_failed": "Ophalen van documenten mislukt",
    "llm_invalid_output": "Ongeldig antwoord van LLM",
    "selection_invalid": "Selectie ongeldig",
    "answer_invalid": "Antwoord ongeldig",
    "provider_error": "Fout bij provider",
    "internal_error": "Interne fout",
}

FALLBACK_ERROR = "Er is een fout opgetreden (onbekende code)"
