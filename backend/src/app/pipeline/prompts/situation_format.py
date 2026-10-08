from __future__ import annotations

from app.schemas.llm import Situation

_ROLE_GLOSS = {
    "provider": "aanbieder",
    "deployer": "gebruiksverantwoordelijke",
    "importer": "importeur",
    "distributor": "distributeur",
    "unknown": "unknown (not stated)",
}


def format_situation(situation: Situation) -> str:
    """Render situation fields with Dutch role glosses for the prompts."""
    role_label = _ROLE_GLOSS.get(situation.role, situation.role)
    domain = situation.domain if situation.domain else "unknown"
    notes = situation.notes if situation.notes else "none"
    return f"role: {situation.role} ({role_label})\ndomain: {domain}\nnotes: {notes}"
