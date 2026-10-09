from datetime import UTC, datetime

import pytest

from eval.models import EvalReport, EvalReportItem

pytestmark = pytest.mark.unit


def test_report_roundtrip_json(tmp_path):
    items = [
        EvalReportItem(
            id="Q03",
            expected_behavior="answer",
            actual_action="answer",
            behavior_match=True,
            vector_hit=True,
            selection_hit=True,
            llm_call_count=1,
            prompt_tokens=10,
            completion_tokens=20,
            reasoning_tokens=0,
            latency_seconds=0.0,
        )
    ]
    report = EvalReport(
        generated_at=datetime.now(UTC),
        items=items,
        summary={"total": 1},
    )
    p = tmp_path / "r.json"
    p.write_text(report.model_dump_json())
    parsed = EvalReport.model_validate_json(p.read_text())
    assert parsed.summary["total"] == 1
