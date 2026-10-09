"""Streamlit chat UI for the EU AI compliance assistant."""

from __future__ import annotations

from typing import Any

import streamlit as st

from ui import client, components, state, strings
from ui.client import ErrorEvent, FinalEvent


def _apply_pending_situation() -> None:
    """Copy backend situation into widget defaults before widgets are created."""
    if not st.session_state.get("situation_pending"):
        return
    sit = st.session_state.get("situation") or state.default_situation()
    role = sit.get("role") or "unknown"
    st.session_state["situation_role_label"] = strings.ROLE_OPTIONS.get(
        role, strings.ROLE_OPTIONS["unknown"]
    )
    st.session_state["situation_domain"] = sit.get("domain") or ""
    st.session_state["situation_notes"] = sit.get("notes") or ""
    st.session_state["situation_pending"] = False


def _load_corpus_snapshot() -> None:
    if st.session_state.get("_corpus_loaded"):
        return
    st.session_state["_corpus_loaded"] = True
    try:
        info = client.get_client().fetch_corpus()
        st.session_state["corpus_snapshot"] = info.snapshot_date
    except Exception:
        if not st.session_state.get("corpus_snapshot"):
            st.session_state["corpus_snapshot"] = strings.SNAPSHOT_FALLBACK


def _run_ask(prompt: str, situation: dict[str, Any]) -> None:
    state.append_user_message(st.session_state, prompt)
    st.session_state["progress_events"] = []

    messages = state.serialize_history_for_request(st.session_state["history"])
    sit_payload = state.serialize_situation(situation)

    progress_placeholder = st.empty()
    events: list[Any] = []
    backend = client.get_client()
    for event in backend.ask(messages, sit_payload):
        if isinstance(event, (FinalEvent, ErrorEvent)):
            state.apply_event(st.session_state, event)
            break
        events.append(event)
        st.session_state["progress_events"] = list(events)
        with progress_placeholder.container():
            components.render_progress(events)
    else:
        # Stream exhausted without final/error — client.ask should have yielded one.
        pass

    # Rerun so pending situation is applied before widgets on the next pass,
    # and history/citations render from session state.
    st.rerun()


def main() -> None:
    st.set_page_config(page_title=strings.PAGE_TITLE, layout="wide")
    state.ensure_session(st.session_state)
    _apply_pending_situation()
    _load_corpus_snapshot()

    st.title(strings.PAGE_TITLE)
    st.write(strings.PAGE_HEADING)

    with st.sidebar:
        # Seed widget keys on first load so selectbox/text_input have defaults.
        if "situation_role_label" not in st.session_state:
            role = st.session_state["situation"].get("role") or "unknown"
            st.session_state["situation_role_label"] = strings.ROLE_OPTIONS.get(
                role, strings.ROLE_OPTIONS["unknown"]
            )
        if "situation_domain" not in st.session_state:
            st.session_state["situation_domain"] = (
                st.session_state["situation"].get("domain") or ""
            )
        if "situation_notes" not in st.session_state:
            st.session_state["situation_notes"] = (
                st.session_state["situation"].get("notes") or ""
            )
        situation = components.render_situation_panel(st.session_state["situation"])
        # Keep plain session situation in sync with widget values for serialization.
        st.session_state["situation"] = {
            "role": situation["role"],
            "domain": situation["domain"] or None,
            "notes": situation["notes"] or None,
        }

    components.render_history(st.session_state["history"])

    last = st.session_state.get("last_response")
    if isinstance(last, FinalEvent) and last.action == "answer" and last.citations:
        components.render_citation_expanders(last.citations)
    elif isinstance(last, ErrorEvent):
        st.error(strings.message_for_code(last.code))

    if st.session_state.get("progress_events"):
        components.render_progress(st.session_state["progress_events"])

    components.render_footer(st.session_state.get("corpus_snapshot"))

    prompt = st.chat_input(strings.CHAT_INPUT_PLACEHOLDER)
    if prompt:
        _run_ask(prompt.strip(), st.session_state["situation"])


main()
