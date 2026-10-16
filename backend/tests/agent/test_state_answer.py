from types import SimpleNamespace

import pytest

from linescope.agent.state_answer import state_answer
from linescope.application.reads import ReadResult


@pytest.mark.parametrize("mixed", [False, True])
def test_state_summary_uses_verified_state_without_replacing_mixed_analysis(mixed):
    observations = [
        SimpleNamespace(
            tool="get_equipment_state",
            result=ReadResult({"state_code": "STOPPED", "version": 10}, {"source": "POSTGRESQL"}),
        )
    ]
    if mixed:
        observations.append(
            SimpleNamespace(tool="trace_downstream_impact", result=ReadResult({}, {}))
        )
    answer = state_answer(observations)
    if mixed:
        assert answer is None
    else:
        assert "STOPPED" in answer and "version 10" in answer
        assert "判断できません" in answer
