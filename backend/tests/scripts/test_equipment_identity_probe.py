"""The real-model gate must not pass a wrong or unresolved target."""

import runpy
from pathlib import Path

import pytest

PROBE = Path(__file__).resolve().parents[3] / "scripts" / "verify_equipment_identity.py"


def payload(ids, record_read=False, answer="設備を選択してください。"):
    rows = [
        {"tool": "search_equipment", "data": {"items": [{"equipment_id": value} for value in ids]}}
    ]
    if record_read:
        rows.append({"tool": "search_maintenance_records", "data": {"items": []}})
    return {"status": "ok", "errors": [], "answer": answer, "data": {"tool_results": rows}}


def test_probe_requires_actual_identity_and_maintenance_read():
    validate = runpy.run_path(str(PROBE))["validate_answer"]
    validate("unique", payload(["target"], True), {"target"})
    with pytest.raises(ValueError, match="IDENTITY_MISMATCH"):
        validate("unique", payload(["other"], True), {"target"})
    with pytest.raises(ValueError, match="MAINTENANCE_NOT_READ"):
        validate("unique", payload(["target"]), {"target"})


def test_probe_does_not_certify_first_candidate_selection_or_empty_search_as_record_absence():
    validate = runpy.run_path(str(PROBE))["validate_answer"]
    validate("ambiguous", payload(["first", "second"]), {"first", "second"})
    with pytest.raises(ValueError, match="UNRESOLVED_TARGET"):
        validate("ambiguous", payload(["first", "second"], True), {"first", "second"})
    with pytest.raises(ValueError, match="UNRESOLVED_TARGET"):
        validate("missing", payload([], True), set())
