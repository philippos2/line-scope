import pytest

from linescope.agent.temporal_request import TEMPORAL_TOOLS, bind_time, time_evidence
from linescope.application.reads import ReadResult, ToolError

AS_OF = "2026-10-08T00:00:00.000000Z"


@pytest.mark.parametrize("tool", sorted(TEMPORAL_TOOLS))
def test_request_time_is_bound_for_every_temporal_tool(tool):
    arguments = {"explicit_as_of": "2026-10-08T09:00:00+09:00"}
    bound = bind_time(tool, arguments, AS_OF)
    assert bound["explicit_as_of"] == AS_OF
    assert arguments["explicit_as_of"] == "2026-10-08T09:00:00+09:00"
    assert bind_time(tool, {}, AS_OF) == {"explicit_as_of": AS_OF}
    evidence = time_evidence(tool, ReadResult({}, {"source": "POSTGRESQL"}), AS_OF)
    assert evidence.evidence["request_temporal_scope"] == "CURRENT_REGISTRATION_AT_AS_OF"


@pytest.mark.parametrize("supplied", ["2026-10-09T00:00:00Z", "now"])
def test_model_cannot_change_or_invent_the_request_time(supplied):
    with pytest.raises(ToolError) as error:
        bind_time("trace_downstream_impact", {"explicit_as_of": supplied}, AS_OF)
    assert error.value.code == "INVALID_ARGUMENT"


def test_current_reads_keep_current_scope_and_original_evidence():
    args = {"equipment_id": "id"}
    assert bind_time("get_equipment_state", args, AS_OF) is args
    result = ReadResult({"state_code": "RUNNING"}, {"version": 7})
    annotated = time_evidence("get_equipment_state", result, AS_OF)
    assert annotated.evidence["request_temporal_scope"] == "CURRENT_STATE_AT_OBSERVATION"
    assert annotated.evidence["version"] == 7
    assert result.evidence == {"version": 7}
    assert time_evidence("get_equipment_state", result, None) is result
