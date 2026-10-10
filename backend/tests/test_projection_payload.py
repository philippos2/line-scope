"""Pure projection contracts; no claim that an edge was applied to Neo4j."""

from copy import deepcopy

import pytest
from test_assignments import row as assignment
from test_relation_snapshot import current as relation

from linescope.canonical import canonical_hash, canonical_json
from linescope.projection_payload import (
    build_projection_payload,
    load_projection_payload,
    projection_payload_hash,
    validate_projection_payload,
)


@pytest.fixture(params=["DependencyRelation", "ProductionOperationEquipmentAssignment"])
def payload(request):
    return build_projection_payload(
        request.param, relation() if request.param == "DependencyRelation" else assignment()
    )


def test_complete_normalized_state_and_hash_round_trip(payload):
    assert payload["aggregate_version"] == payload["state"]["version"]
    assert "created_at" not in payload["state"] and "updated_at" not in payload["state"]
    assert (
        load_projection_payload(canonical_json(payload), projection_payload_hash(payload))
        == payload
    )
    assert projection_payload_hash(payload) == canonical_hash(payload)
    assert payload["state"]["effective_from"].endswith(".000000Z")


def test_disabled_state_is_retained_and_changes_hash(payload):
    original = projection_payload_hash(payload)
    payload["state"]["active"] = False
    assert validate_projection_payload(payload)["state"]["active"] is False
    assert projection_payload_hash(payload) != original


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("schema_version", 2),
        ("aggregate_version", True),
        ("aggregate_version", 99),
        ("aggregate_id", "not-uuid"),
        ("aggregate_type", "Equipment"),
    ],
)
def test_header_must_match_supported_normalized_state(payload, field, value):
    payload[field] = value
    with pytest.raises(ValueError):
        validate_projection_payload(payload)


@pytest.mark.parametrize("field", ["generation", "source_outbox_id", "payload_hash"])
def test_delivery_metadata_is_not_part_of_payload_contract(payload, field):
    payload[field] = "not part of canonical state"
    with pytest.raises(ValueError):
        projection_payload_hash(payload)


@pytest.mark.parametrize(
    "change", ["missing", "extra", "bool_version", "bad_period", "unnormalized_time"]
)
def test_invalid_or_partial_state_is_rejected_on_reload(payload, change):
    if change == "missing":
        del payload["state"]["active"]
    elif change == "extra":
        payload["state"]["guessed_capacity"] = 80
    elif change == "bool_version":
        payload["state"]["version"] = True
    elif change == "bad_period":
        payload["state"]["effective_to"] = payload["state"]["effective_from"]
    else:
        payload["state"]["effective_from"] = "2026-10-09T09:00:00+09:00"
    with pytest.raises(ValueError):
        load_projection_payload(canonical_json(payload), canonical_hash(payload))


def test_audit_metadata_does_not_change_built_projection_hash(payload):
    state = deepcopy(payload["state"])
    state.update(created_at="audit one", updated_at="audit two")
    assert build_projection_payload(payload["aggregate_type"], state) == payload


def test_hash_mismatch_rejected(payload):
    with pytest.raises(ValueError, match="hash mismatch"):
        load_projection_payload(canonical_json(payload), "0" * 64)


def test_duplicate_keys_rejected(payload):
    text = canonical_json(payload)
    with pytest.raises(ValueError):
        load_projection_payload(
            text[:-1] + ',"schema_version":1}', projection_payload_hash(payload)
        )


def test_reordering_object_keys_keeps_hash(payload):
    reordered = dict(reversed(list(payload.items())))
    assert projection_payload_hash(reordered) == projection_payload_hash(payload)
