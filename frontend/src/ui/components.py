"""Small Streamlit render helpers. No business logic."""

from __future__ import annotations

from typing import Any

import streamlit as st

from ui import strings
from ui.client import RetrievedEvent, SelectionEvent, StatusEvent

_STEP_LABELS = {
    "searching": strings.PROGRESS_SEARCHING,
    "selecting": strings.PROGRESS_SELECTING,
    "answering": strings.PROGRESS_ANSWERING,
}


def render_message(msg: dict[str, Any]) -> None:
    with st.chat_message(msg.get("role", "assistant")):
        st.markdown(msg.get("content") or "")


def render_history(
    history: list[dict[str, Any]], progress_events: list[Any] | None = None
) -> None:
    """Render the conversation, with the latest question's progress right after it."""
    last_user = max(
        (i for i, msg in enumerate(history) if msg.get("role") == "user"),
        default=None,
    )
    for i, msg in enumerate(history):
        render_message(msg)
        if i == last_user and progress_events:
            render_progress(progress_events)


def write_progress_event(status: Any, event: Any) -> None:
    """Append one stream event to an open `st.status` block."""
    if isinstance(event, StatusEvent):
        label = _STEP_LABELS.get(event.step or "")
        if label:
            status.update(label=label)
            status.write(label)
    elif isinstance(event, RetrievedEvent):
        refs = [p.get("ref", "") for p in event.provisions]
        status.write(f"{strings.PROGRESS_FOUND}: {', '.join(refs) or '—'}")
    elif isinstance(event, SelectionEvent):
        status.write(f"{strings.PROGRESS_KEPT}: {', '.join(event.kept) or '—'}")
        status.write(f"{strings.PROGRESS_ADDED}: {', '.join(event.added) or '—'}")
        status.write(
            f"{strings.PROGRESS_UNAVAILABLE}: {', '.join(event.unavailable) or '—'}"
        )


def render_progress(events: list[Any]) -> None:
    """The finished progress of an answered question, collapsed."""
    status = st.status(strings.PROGRESS_LABEL, expanded=False)
    for event in events:
        write_progress_event(status, event)
    status.update(label=strings.PROGRESS_LABEL, state="complete", expanded=False)


def render_situation_panel(_situation: dict[str, Any]) -> dict[str, Any]:
    """Render editable situation fields bound to session widget keys.

    Widget keys must already hold any pending backend situation before this
    is called — Streamlit rejects writes to widget keys after instantiation.
    Returns the current values for request serialization.
    """
    st.subheader(strings.SITUATION_PANEL_TITLE)
    role_keys = list(strings.ROLE_OPTIONS.keys())
    role_labels = [strings.ROLE_OPTIONS[k] for k in role_keys]

    selected_label = st.selectbox(
        strings.ROLE_LABEL,
        options=role_labels,
        key="situation_role_label",
    )
    role = role_keys[role_labels.index(selected_label)]

    domain = st.text_input(strings.DOMAIN_LABEL, key="situation_domain")
    notes = st.text_area(strings.NOTES_LABEL, key="situation_notes")
    return {"role": role, "domain": domain, "notes": notes}


def render_citation_expanders(citations: list[dict[str, Any]]) -> None:
    if not citations:
        return
    st.markdown(f"**{strings.CITATIONS_HEADING}**")
    fallback = strings.CITATION_FALLBACK_LABEL
    for cite in citations:
        header = cite.get("header") or cite.get("ref") or fallback
        with st.expander(header):
            st.markdown(cite.get("body") or "")


def render_footer(snapshot_date: str | None = None) -> None:
    st.divider()
    st.markdown(strings.DISCLAIMER)
    st.markdown(strings.EU_ASSUMPTION)
    date_text = snapshot_date or strings.SNAPSHOT_FALLBACK
    st.markdown(f"**{strings.SNAPSHOT_LABEL}:** {date_text}")
