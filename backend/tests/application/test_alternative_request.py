from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from linescope.application.graph_request import GraphLimits, validate_alternative_request
from linescope.application.reads import ToolError
from linescope.execution import ExecutionContext

NOW = datetime(2026, 10, 13, tzinfo=timezone.utc)
LIMITS = GraphLimits(16, 100, 50, 5000)
A = {"entity_type": "Equipment", "entity_id": "abcdef01-0000-4000-8000-000000000001"}
P = {"entity_type": "Product", "entity_id": "abcdef02-0000-4000-8000-000000000001"}


def parse(arguments=None, *, role="manager", context=True):
    return validate_alternative_request(
        ExecutionContext("actor", role, uuid4()) if context else None,
        {"important_targets": [P], "excluded_nodes": [A]} if arguments is None else arguments,
        system_limits=LIMITS,
        server_time=NOW,
    )


@pytest.mark.parametrize("role", ["maintenance", "production", "manager"])
def test_authorized_roles_and_all_input_ids(role):
    result = parse(role=role)
    assert result.important_targets == (("Product", P["entity_id"]),)
    assert result.excluded_nodes == (("Equipment", A["entity_id"]),)
    assert result.as_of == NOW and result.effective_limits == LIMITS


def test_identity_is_from_context_not_untrusted_fields():
    with pytest.raises(ToolError) as caught:
        parse({"role": "manager"}, role="floor")
    assert caught.value.code == "AUTHORIZATION_DENIED"
    with pytest.raises(ToolError) as caught:
        parse(context=False)
    assert caught.value.code == "AUTHENTICATION_REQUIRED"


def test_limits_cap_all_roots_and_timeout_stays_server_owned():
    result = parse(
        {
            "important_targets": [P],
            "excluded_nodes": [A],
            "requested_max_depth": 2,
            "requested_max_nodes": 1000,
            "requested_max_paths": 3,
        }
    )
    assert result.effective_limits == GraphLimits(2, 100, 3, 5000)
    with pytest.raises(ToolError) as caught:
        parse({"important_targets": [P], "excluded_nodes": [A], "requested_max_nodes": 1})
    assert caught.value.code == "INVALID_ARGUMENT"


def test_same_typed_node_across_sets_is_counted_once_and_preserved():
    result = parse({"important_targets": [A], "excluded_nodes": [A], "requested_max_nodes": 1})
    assert result.important_targets == result.excluded_nodes


def test_order_and_uuid_case_are_normalized():
    result = parse(
        {
            "important_targets": [P, A],
            "excluded_nodes": [{**A, "entity_id": A["entity_id"].upper()}],
        }
    )
    assert result.important_targets == (("Equipment", A["entity_id"]), ("Product", P["entity_id"]))
    assert result.excluded_nodes == (("Equipment", A["entity_id"]),)


@pytest.mark.parametrize("name", ["important_targets", "excluded_nodes"])
@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        "x",
        {},
        [A, {**A, "entity_id": A["entity_id"].upper()}],
        [{**A, "entity_id": "'; DROP TABLE equipment; --"}],
        [{**A, "entity_type": "Unknown"}],
        [{**A, "role": "manager"}],
    ],
)
def test_invalid_sets_and_each_node_are_rejected(name, value):
    args = {"important_targets": [P], "excluded_nodes": [A], name: value}
    with pytest.raises(ToolError) as caught:
        parse(args)
    assert caught.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize(
    "name,value",
    [
        ("relation_types", ["SUPPLIES"]),
        ("relation_types", None),
        ("timeout_ms", 1),
        ("requested_timeout_ms", 1),
        ("user_id", "owner"),
        pytest.param("context_id", str(uuid4()), id="context-id-spoof"),
        ("target", A),
    ],
)
def test_unrecognized_fields_and_relation_filter_are_rejected(name, value):
    with pytest.raises(ToolError) as caught:
        parse({"important_targets": [P], "excluded_nodes": [A], name: value})
    assert caught.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize(
    "name", ["requested_max_depth", "requested_max_nodes", "requested_max_paths"]
)
@pytest.mark.parametrize("value", [False, 0, -1, "1"])
def test_limit_types_and_values_are_explicit(name, value):
    with pytest.raises(ToolError) as caught:
        parse({"important_targets": [P], "excluded_nodes": [A], name: value})
    assert caught.value.code == "INVALID_ARGUMENT"


def test_future_analysis_rejected_and_historical_time_normalized():
    with pytest.raises(ToolError) as caught:
        parse(
            {
                "important_targets": [P],
                "excluded_nodes": [A],
                "explicit_as_of": (NOW + timedelta(seconds=1)).isoformat(),
            }
        )
    assert caught.value.code == "INVALID_ARGUMENT"
    result = parse(
        {
            "important_targets": [P],
            "excluded_nodes": [A],
            "explicit_as_of": "2026-10-12T09:00:00+09:00",
        }
    )
    assert result.as_of == datetime(2026, 10, 12, tzinfo=timezone.utc)
