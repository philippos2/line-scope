from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from linescope.application.graph_request import GraphLimits, validate_graph_request
from linescope.application.reads import ToolError
from linescope.execution import ExecutionContext

NOW = datetime(2026, 10, 12, tzinfo=timezone.utc)
LIMITS = GraphLimits(5, 100, 20, 1000)
TARGET = {"entity_type": "Equipment", "entity_id": str(uuid4())}


def context(role="maintenance"):
    return ExecutionContext("actor", role, uuid4())


def parse(arguments=None, *, role="maintenance", tool="trace_downstream_impact"):
    return validate_graph_request(
        context(role),
        tool,
        {"target": TARGET} if arguments is None else arguments,
        system_limits=LIMITS,
        server_time=NOW,
    )


@pytest.mark.parametrize("role", ["maintenance", "production", "manager"])
@pytest.mark.parametrize(
    "tool,direction",
    [("trace_downstream_impact", "IMPACT"), ("trace_upstream_dependencies", "UPSTREAM")],
)
def test_authorized_roles_and_fixed_directions(role, tool, direction):
    result = parse(role=role, tool=tool)
    assert result.direction == direction and result.target == ("Equipment", TARGET["entity_id"])
    assert result.as_of == NOW and result.effective_limits == LIMITS
    assert result.requested_limits == () and "CAN_SUBSTITUTE" not in result.relation_types


def test_floor_cannot_claim_authority_in_arguments():
    with pytest.raises(ToolError) as caught:
        parse({"target": TARGET, "role": "manager"}, role="floor")
    assert caught.value.code == "AUTHORIZATION_DENIED"


def test_missing_trusted_context():
    with pytest.raises(ToolError) as caught:
        validate_graph_request(
            None,
            "trace_downstream_impact",
            {"target": TARGET},
            system_limits=LIMITS,
            server_time=NOW,
        )
    assert caught.value.code == "AUTHENTICATION_REQUIRED"


def test_limits_are_capped_and_timeout_is_server_owned():
    result = parse(
        {
            "target": TARGET,
            "requested_max_depth": 2,
            "requested_max_nodes": 1000,
            "requested_max_paths": 1,
        }
    )
    assert result.effective_limits == GraphLimits(2, 100, 1, 1000)
    assert dict(result.requested_limits) == {"max_depth": 2, "max_nodes": 1000, "max_paths": 1}


@pytest.mark.parametrize(
    "field", ["requested_max_depth", "requested_max_nodes", "requested_max_paths"]
)
@pytest.mark.parametrize("value", [0, -1, True, "1", 1.5, None])
def test_invalid_requested_limits(field, value):
    with pytest.raises(ToolError) as caught:
        parse({"target": TARGET, field: value})
    assert caught.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize(
    "field", ["role", "user_id", "request_id", "timeout_ms", "requested_timeout_ms", "cypher"]
)
def test_unknown_authority_and_query_fields_are_rejected(field):
    with pytest.raises(ToolError) as caught:
        parse({"target": TARGET, field: "untrusted"})
    assert caught.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize(
    "timestamp",
    [NOW.isoformat(), (NOW - timedelta(days=1)).isoformat(), "2026-10-12T09:00:00+09:00"],
)
def test_same_time_or_historical_time_is_allowed(timestamp):
    assert parse({"target": TARGET, "explicit_as_of": timestamp}).as_of <= NOW


@pytest.mark.parametrize(
    "timestamp", [(NOW + timedelta(microseconds=1)).isoformat(), "2026-10-12T00:00:00", None, NOW]
)
def test_future_naive_or_null_time_is_rejected(timestamp):
    with pytest.raises(ToolError):
        parse({"target": TARGET, "explicit_as_of": timestamp})


def test_filter_is_normalized_without_mutating_original_input():
    args = {"target": TARGET, "relation_types": ["USES", "SUPPLIES", "USES"]}
    original = deepcopy(args)
    assert parse(args).relation_types == ("SUPPLIES", "USES")
    assert args == original


@pytest.mark.parametrize("relations", [[], ["CAN_SUBSTITUTE"], ["Unknown"], [True], "USES", None])
def test_invalid_relation_filter(relations):
    with pytest.raises(ToolError):
        parse({"target": TARGET, "relation_types": relations})


@pytest.mark.parametrize(
    "target",
    [
        None,
        {},
        {**TARGET, "role": "manager"},
        {"entity_type": "Equipment` DELETE n", "entity_id": TARGET["entity_id"]},
        {"entity_type": "Equipment", "entity_id": "' OR 1=1 --"},
        {"entity_type": "Equipment", "entity_id": uuid4()},
    ],
)
def test_invalid_typed_target(target):
    with pytest.raises(ToolError):
        parse({"target": target})


@pytest.mark.parametrize("tool", ["find_alternative_paths", "execute", None, []])
def test_unimplemented_or_non_graph_tools_fail_closed(tool):
    with pytest.raises(ToolError):
        parse(tool=tool)


@pytest.mark.parametrize("value", [0, -1, True, "1", None])
def test_server_limits_must_be_explicit_positive_integers(value):
    with pytest.raises(ValueError):
        GraphLimits(5, 100, 20, value)
