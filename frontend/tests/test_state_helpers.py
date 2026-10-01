from ui import state


def test_final_stores_action():
    session = {}
    state.ensure_session(session)

    class DummyFinal:
        action = "clarify"
        answer = None
        clarifying_questions = ["Is dit duidelijk?"]
        citations = []
        situation = {"role": "beheerder"}
        usage = {}
        corpus_snapshot = None

    state.apply_event(session, DummyFinal())
    assert session["history"][-1]["role"] == "assistant"
    assert session["history"][-1]["action"] == "clarify"
    assert session["situation"]["role"] == "beheerder"


def test_serialize_history_includes_action_only_on_assistant():
    history = [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Ok", "action": "answer"},
    ]
    serialized = state.serialize_history_for_request(history)
    assert serialized[0].get("action") is None
    assert serialized[1].get("action") == "answer"
