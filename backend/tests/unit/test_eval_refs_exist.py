import json
from pathlib import Path

import pytest

from app.ingestion.manifest import load_indexed_provisions, load_manifest

pytestmark = pytest.mark.unit


def test_eval_refs_exist_in_corpus():
    manifest = load_manifest(Path("corpus/manifest.yaml"))
    provisions = load_indexed_provisions(manifest, Path("corpus"))
    # Eval refs are document-qualified ("AI-verordening:art_3"); anchors are not.
    refs_in_corpus = {f"{doc.key}:{prov.anchor}" for doc, prov in provisions}

    questions = json.loads(Path("eval/eval_questions.json").read_text(encoding="utf-8"))
    referenced = set()
    for q in questions:
        referenced.update(q.get("must", []))
        referenced.update(q.get("optional", []))
        referenced.update(q.get("via_reference", []))

    assert referenced, "eval file references no provisions"
    missing = sorted(referenced - refs_in_corpus)
    assert not missing, f"Missing referenced anchors: {missing}"
