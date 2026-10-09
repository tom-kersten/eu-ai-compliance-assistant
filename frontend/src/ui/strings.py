"""Dutch user-facing strings for the Streamlit UI."""

from __future__ import annotations

PAGE_TITLE = "EU AI-nalevingsassistent"
PAGE_HEADING = (
    "Stel een vraag over de AI-verordening, AVG, CRA of Digitale omnibus inzake AI."
)

CHAT_INPUT_PLACEHOLDER = "Stel uw vraag…"
SITUATION_PANEL_TITLE = "Wat ik begrijp over uw situatie"
ROLE_LABEL = "Rol"
DOMAIN_LABEL = "Domein"
NOTES_LABEL = "Notities"
ROLE_OPTIONS: dict[str, str] = {
    "provider": "Aanbieder",
    "deployer": "Gebruiksverantwoordelijke",
    "importer": "Importeur",
    "distributor": "Distributeur",
    "unknown": "Onbekend",
}

PROGRESS_LABEL = "Voortgang"
PROGRESS_SEARCHING = "Zoeken…"
PROGRESS_SELECTING = "Selecteren…"
PROGRESS_ANSWERING = "Antwoorden…"
PROGRESS_FOUND = "Gevonden"
PROGRESS_KEPT = "Behouden"
PROGRESS_ADDED = "Toegevoegd"
PROGRESS_UNAVAILABLE = "Niet beschikbaar"

CITATIONS_HEADING = "Bronnen"
CITATION_FALLBACK_LABEL = "Bron"
DISCLAIMER = (
    "Dit is geen juridisch advies. De assistent legt bepalingen uit en wijst "
    "naar de brontekst; u past ze zelf toe."
)
EU_ASSUMPTION = (
    "Aangenomen wordt dat u binnen de EU opereert. Territoriale reikwijdte "
    "wordt per vraag niet beoordeeld."
)
SNAPSHOT_LABEL = "Corpus-snapshot"
SNAPSHOT_FALLBACK = "onbekend"

ERROR_MESSAGES: dict[str, str] = {
    "database_unreachable": "Database niet bereikbaar.",
    "pending_migrations": "Er zijn openstaande database-migraties.",
    "missing_index": "De zoekindex ontbreekt of is leeg.",
    "embedding_mismatch": "Embedding-model of -dimensie komt niet overeen.",
    "retrieval_failed": "Ophalen van bepalingen is mislukt.",
    "llm_invalid_output": "Ongeldig antwoord van het taalmodel.",
    "selection_invalid": "De selectie van bepalingen is ongeldig.",
    "answer_invalid": "Het antwoord is ongeldig.",
    "provider_error": "Fout bij de AI-provider.",
    "internal_error": "Er is een interne fout opgetreden.",
    "client_http_error": "De backend gaf een onverwachte HTTP-status.",
    "client_connection_error": "Geen verbinding met de backend.",
    "client_incomplete_stream": "Het antwoord werd onvolledig afgebroken.",
}

FALLBACK_ERROR = "Er is een fout opgetreden (onbekende code)."


def message_for_code(code: str) -> str:
    """Map an error code to a Dutch message; unknown codes use the fallback."""
    return ERROR_MESSAGES.get(code, FALLBACK_ERROR)
