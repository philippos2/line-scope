"""Acceptance runner must not certify missing, failed or contradictory probes."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "demo_acceptance", Path(__file__).resolve().parents[3] / "scripts/verify_demo_acceptance.py"
)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


@pytest.mark.parametrize(
    "stage,code,output,status",
    [
        ("minimal", 0, 'noise\n{"stage":"result","result":"PASS","real_http":true}', "PASS"),
        ("minimal", 1, '{"stage":"result","result":"PASS","real_http":true}', "FAIL"),
        ("minimal", 0, "startup completed", "FAIL"),
        ("summary", 0, '{"stage":"summary","result":"PASS","llm_status":"FALLBACK"}', "FAIL"),
        ("summary", 0, '{"stage":"summary","result":"PASS","source":"REGISTERED_INPUT"}', "PASS"),
        (
            "summary",
            0,
            '{"stage":"summary","result":"PASS","llm_status":"VALIDATED_ORDER"}',
            "FAIL",
        ),
    ],
)
def test_report_requires_actual_success_and_matching_scope(stage, code, output, status):
    assert runner.verify_child(stage, code, output)["status"] == status
    assert runner.result_status({stage: {"status": status}}) == (
        "PARTIAL" if status == "PASS" else "FAIL"
    )
