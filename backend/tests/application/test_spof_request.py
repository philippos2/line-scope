from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from linescope.application.graph_request import GraphLimits, validate_spof_request
from linescope.application.reads import ToolError
from linescope.application.tools import ToolDispatcher
from linescope.execution import ExecutionContext

NOW = datetime(2026, 10, 13, tzinfo=timezone.utc)
LIMITS = GraphLimits(16, 100, 50, 5000)
A = {"entity_type": "Equipment", "entity_id": "abcdef01-0000-4000-8000-000000000001"}
P = {"entity_type": "Product", "entity_id": "abcdef02-0000-4000-8000-000000000001"}


def parse(args=None, *, role="manager", authenticated=True):
    return validate_spof_request(
        ExecutionContext("actor", role, uuid4()) if authenticated else None,
        {"important_targets": [P]} if args is None else args,
        system_limits=LIMITS,
        server_time=NOW,
    )


@pytest.mark.parametrize("role", ["maintenance", "production", "manager"])
def test_allowed_roles_use_server_time_and_default_candidate_discovery(role):
    request = parse(role=role)
    assert request.important_targets == (("Product", P["entity_id"]),)
    assert request.candidate_nodes is None
    assert request.as_of == NOW and request.effective_limits == LIMITS


def test_omitted_empty_and_explicit_candidate_sets_are_distinct():
    assert parse({"important_targets": [P], "candidate_nodes": []}).candidate_nodes == ()
    request = parse({"important_targets": [P], "candidate_nodes": [A]})
    assert request.candidate_nodes == (("Equipment", A["entity_id"]),)


def test_authority_precedes_untrusted_argument_validation():
    with pytest.raises(ToolError) as caught:
        parse({"role": "manager"}, role="floor")
    assert caught.value.code == "AUTHORIZATION_DENIED"
    with pytest.raises(ToolError) as caught:
        parse(authenticated=False)
    assert caught.value.code == "AUTHENTICATION_REQUIRED"


def test_uuid_normalization_order_and_shared_input_budget():
    request = parse(
        {
            "important_targets": [P, A],
            "candidate_nodes": [{**A, "entity_id": A["entity_id"].upper()}],
            "requested_max_nodes": 2,
        }
    )
    assert request.important_targets == (("Equipment", A["entity_id"]), ("Product", P["entity_id"]))
    assert request.candidate_nodes == (("Equipment", A["entity_id"]),)
    with pytest.raises(ToolError) as caught:
        parse({"important_targets": [P], "candidate_nodes": [A], "requested_max_nodes": 1})
    assert caught.value.code == "INVALID_ARGUMENT"


def test_requested_limits_only_reduce_server_limits():
    request = parse(
        {
            "important_targets": [P],
            "requested_max_depth": 2,
            "requested_max_nodes": 1000,
            "requested_max_paths": 3,
        }
    )
    assert request.effective_limits == GraphLimits(2, 100, 3, 5000)
    assert dict(request.requested_limits) == {"max_depth": 2, "max_nodes": 1000, "max_paths": 3}


@pytest.mark.parametrize("field", ["important_targets", "candidate_nodes"])
@pytest.mark.parametrize(
    "value",
    [
        None,
        "x",
        {},
        [A, {**A, "entity_id": A["entity_id"].upper()}],
        [{**A, "entity_type": "Supplier"}],
        [{**A, "entity_id": "' OR 1=1 --"}],
        [{**A, "role": "manager"}],
    ],
)
def test_invalid_node_sets_rejected(field, value):
    with pytest.raises(ToolError) as caught:
        parse({"important_targets": [P], field: value})
    assert caught.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"important_targets": []},
        {"important_targets": [P] * 101},
        {"important_targets": [P], "candidate_nodes": [A] * 101},
    ],
)
def test_missing_empty_or_oversized_required_set_rejected(args):
    with pytest.raises(ToolError) as caught:
        parse(args)
    assert caught.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize(
    "field,value",
    [
        ("relation_types", None),
        ("relation_types", ["SUPPLIES"]),
        ("excluded_nodes", [A]),
        ("timeout_ms", 1),
        ("requested_timeout_ms", 1),
        ("role", "manager"),
        ("user_id", "owner"),
        ("context_id", str(uuid4())),
    ],
)
def test_unknown_fields_and_relation_filter_rejected(field, value):
    with pytest.raises(ToolError) as caught:
        parse({"important_targets": [P], field: value})
    assert caught.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize(
    "field", ["requested_max_depth", "requested_max_nodes", "requested_max_paths"]
)
@pytest.mark.parametrize("value", [False, 0, -1, "1"])
def test_limit_types_and_values_rejected(field, value):
    with pytest.raises(ToolError) as caught:
        parse({"important_targets": [P], "candidate_nodes": [], field: value})
    assert caught.value.code == "INVALID_ARGUMENT"


def test_historical_time_normalized_and_future_rejected_even_with_empty_candidates():
    request = parse({"important_targets": [P], "explicit_as_of": "2026-10-12T09:00:00+09:00"})
    assert request.as_of == datetime(2026, 10, 12, tzinfo=timezone.utc)
    with pytest.raises(ToolError) as caught:
        parse(
            {
                "important_targets": [P],
                "candidate_nodes": [],
                "explicit_as_of": (NOW + timedelta(seconds=1)).isoformat(),
            }
        )
    assert caught.value.code == "INVALID_ARGUMENT"


def test_spof_tool_schema_has_optional_candidates_and_no_relation_filter():
    class NoDatabase:
        def for_reads(self):
            return self

        def transaction(self):
            pytest.fail("Schema inspection must not access storage")

    dispatcher = ToolDispatcher(NoDatabase(), graph=object())
    schema = dispatcher.schemas()["find_single_point_failure_candidates"]
    assert schema["required"] == ["important_targets"]
    assert "candidate_nodes" in schema["properties"]
    assert "relation_types" not in schema["properties"]
