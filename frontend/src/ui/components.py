"""Small Streamlit render helpers. No business logic."""

from __future__ import annotations

from typing import Any

import streamlit as st

from ui import strings
from ui.client import RetrievedEvent, SelectionEvent, StatusEvent


def render_history(history: list[dict[str, Any]]) -> None:
    for msg in history:
        role = msg.get("role", "assistant")
        with st.chat_message(role):
            st.markdown(msg.get("content") or "")


def render_progress(events: list[Any]) -> None:
    if not events:
        return
    with st.status(strings.PROGRESS_LABEL, expanded=True) as status:
        for event in events:
            if isinstance(event, StatusEvent):
                step = event.step or ""
                if step == "searching":
                    status.update(label=strings.PROGRESS_SEARCHING)
                    st.write(strings.PROGRESS_SEARCHING)
                elif step == "selecting":
                    status.update(label=strings.PROGRESS_SELECTING)
                    st.write(strings.PROGRESS_SELECTING)
                elif step == "answering":
                    status.update(label=strings.PROGRESS_ANSWERING)
                    st.write(strings.PROGRESS_ANSWERING)
            elif isinstance(event, RetrievedEvent):
                refs = [p.get("ref", "") for p in event.provisions]
                st.write(f"{strings.PROGRESS_FOUND}: {', '.join(refs) or '—'}")
            elif isinstance(event, SelectionEvent):
                st.write(f"{strings.PROGRESS_KEPT}: {', '.join(event.kept) or '—'}")
                st.write(f"{strings.PROGRESS_ADDED}: {', '.join(event.added) or '—'}")
                st.write(
                    f"{strings.PROGRESS_UNAVAILABLE}: "
                    f"{', '.join(event.unavailable) or '—'}"
                )
        status.update(label=strings.PROGRESS_LABEL, state="complete")


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
