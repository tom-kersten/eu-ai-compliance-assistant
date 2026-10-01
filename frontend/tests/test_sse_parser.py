from ui.client import FinalEvent, RetrievedEvent, SSEParser, StatusEvent


def load_fixture(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def test_full_stream_parses(tmp_path):
    data = load_fixture("tests/fixtures/sse/full.events")
    p = SSEParser()
    events = p.feed(data)
    # feed returns events parsed up to first double-newline; there may be leftover,
    # so flush any remaining content
    events += p.feed(b"")
    types = [e.__class__ for e in events]
    assert StatusEvent in types
    assert RetrievedEvent in types
    assert FinalEvent in types


def test_partial_chunk_reconstruction():
    data = load_fixture("tests/fixtures/sse/partial_chunk.events")
    # split into two chunks to simulate partial arriving content
    half = len(data) // 2
    p = SSEParser()
    e1 = p.feed(data[:half])
    e2 = p.feed(data[half:])
    events = e1 + e2 + p.feed(b"")
    assert any(isinstance(e, FinalEvent) for e in events)
