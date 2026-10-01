from pathlib import Path

from app.ingestion.manifest import load_indexed_provisions, load_manifest


def test_eval_refs_exist_in_corpus():
    manifest = load_manifest(Path("corpus/manifest.yaml"))
    provisions = load_indexed_provisions(manifest, Path("corpus"))
    anchors = {prov.anchor for _, prov in provisions}

    import json

    questions = json.loads(Path("eval/eval_questions.json").read_text(encoding="utf-8"))
    # collect all referenced anchors
    refs = set()
    for q in questions:
        refs.update(q.get("must", []))
        refs.update(q.get("optional", []))
        refs.update(q.get("via_reference", []))

    # All refs should be present in anchors (direct compare; no normalizer)
    missing = sorted(refs - anchors)
    assert not missing, f"Missing referenced anchors: {missing}"
