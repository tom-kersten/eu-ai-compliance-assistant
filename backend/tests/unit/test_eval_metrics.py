from eval.metrics import selection_hit, vector_hit

from app.schemas.api import RetrievedEvent, RetrievedItem, SelectionEvent


def test_vector_and_selection_hit_false_for_empty():
    retrieved = RetrievedEvent(provisions=[])
    assert not vector_hit(retrieved, ["AI-verordening:art_3"])
    selection = SelectionEvent(kept=[], discarded=[], added=[], unavailable=[])
    assert not selection_hit(selection, ["AI-verordening:art_3"])


def test_vector_and_selection_hit_true_when_present():
    items = [RetrievedItem(ref="AI-verordening:art_3", title=None, similarity=0.9)]
    retrieved = RetrievedEvent(provisions=items)
    assert vector_hit(retrieved, ["AI-verordening:art_3"])
    selection = SelectionEvent(
        kept=["AI-verordening:art_3"],
        discarded=[],
        added=[],
        unavailable=[],
    )
    assert selection_hit(selection, ["AI-verordening:art_3"])
