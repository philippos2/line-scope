from copy import deepcopy
from itertools import product
from uuid import UUID, uuid4

import psycopg
import pytest

from linescope.canonical import canonical_hash, canonical_json
from linescope.execution import ExecutionContext
from linescope.relations import dependency_relation_create_target, dependency_relation_target
from linescope.snapshot import (
    CanonicalSnapshot,
    build_dependency_relation_snapshot,
    build_equipment_state_snapshot,
    equipment_state_target,
)


def values(**changes):
    return {
        "source_entity_type": "Equipment",
        "source_entity_id": str(UUID(int=10)),
        "target_entity_type": "InfrastructureResource",
        "target_entity_id": str(UUID(int=20)),
        "relation_type": "DEPENDS_ON",
        "effective_from": "2026-10-09T09:00:00+09:00",
        "effective_to": None,
        "required": True,
        "active": True,
        **changes,
    }


def current(identifier=1, **changes):
    return {
        **values(),
        "dependency_relation_id": str(UUID(int=identifier)),
        "version": 4,
        "created_at": "audit excluded",
        "updated_at": "audit excluded",
        **changes,
    }


def snapshot(*targets):
    return build_dependency_relation_snapshot(
        ExecutionContext("maintenance1", "maintenance", uuid4()), list(targets)
    )


def reload(payload):
    return CanonicalSnapshot(canonical_json(payload), canonical_hash(payload))


# Independent domain-model table, not derived from the production validator.
PAIRS = {
    "DEPENDS_ON": set(
        product(
            ["Equipment", "Process", "ProductionOperation"],
            ["Equipment", "InfrastructureResource", "Process"],
        )
    ),
    "PRECEDES": {("Process", "Process"), ("ProductionOperation", "ProductionOperation")},
    "SUPPLIES": set(
        product(
            ["InfrastructureResource", "Equipment"],
            ["Equipment", "Process", "ProductionOperation"],
        )
    ),
    "CONTROLS": {("Equipment", "Equipment")},
    "PRODUCES": {("Process", "Product"), ("ProductionOperation", "Product")},
    "CAN_SUBSTITUTE": {(kind, kind) for kind in ["Equipment", "Process", "InfrastructureResource"]},
}
KINDS = ["Equipment", "Process", "ProductionOperation", "Product", "InfrastructureResource"]


def test_complete_endpoint_matrix_and_required_semantics():
    for relation, source, target, required in product(
        [*PAIRS, "USES", "OTHER"], KINDS, KINDS, [False, True]
    ):
        allowed = (source, target) in PAIRS.get(relation, set()) and (
            not required or relation in {"DEPENDS_ON", "SUPPLIES"}
        )
        input_values = values(
            relation_type=relation,
            source_entity_type=source,
            target_entity_type=target,
            required=required,
        )
        if allowed:
            item = dependency_relation_create_target(input_values)
            assert reload(snapshot(item).data) == snapshot(item)
            assert item["after"]["required"] is required
        else:
            with pytest.raises(ValueError):
                dependency_relation_create_target(input_values)


def test_create_identity_nulls_normalization_and_retry_retention():
    input_values = values()
    original = deepcopy(input_values)
    proposal = dependency_relation_create_target(input_values)
    assert input_values == original
    assert UUID(proposal["target_id"]).version == 4
    assert proposal["target_id"] == proposal["after"]["dependency_relation_id"]
    assert proposal["before"] is proposal["expected_version"] is None
    assert proposal["after"]["version"] == 1
    assert proposal["after"]["effective_to"] is None
    assert proposal["after"]["effective_from"] == "2026-10-09T00:00:00.000000Z"
    assert snapshot(proposal) == reload(snapshot(proposal).data)
    assert proposal["target_id"] != dependency_relation_create_target(input_values)["target_id"]


@pytest.mark.parametrize(
    "field,change",
    [
        ("source_entity_id", str(UUID(int=11))),
        ("target_entity_id", str(UUID(int=21))),
        ("source_entity_type", "Process"),
        ("target_entity_type", "Process"),
        ("effective_from", "2026-10-08T00:00:00Z"),
        ("effective_to", "2026-10-10T00:00:00Z"),
        ("required", False),
        ("active", False),
    ],
)
def test_updates_use_explicit_business_values_and_current_version(field, change):
    original = current()
    proposal = dependency_relation_target(original, {field: change})
    assert original == current()
    assert proposal["before"]["version"] == proposal["expected_version"] == 4
    assert proposal["after"]["version"] == 5
    assert "updated_at" not in proposal["before"]
    assert "created_at" not in proposal["after"]
    for key, value in proposal["business_key"].items():
        assert value == proposal["after"][key]
    assert reload(snapshot(proposal).data) == snapshot(proposal)


def test_type_change_revalidates_whole_record_and_does_not_infer_required():
    with pytest.raises(ValueError):
        dependency_relation_target(current(), {"relation_type": "CAN_SUBSTITUTE"})
    proposal = dependency_relation_target(
        current(),
        {
            "relation_type": "CAN_SUBSTITUTE",
            "target_entity_type": "Equipment",
            "required": False,
        },
    )
    assert proposal["before"]["relation_type"] == "DEPENDS_ON"
    assert proposal["after"]["relation_type"] == "CAN_SUBSTITUTE"
    assert proposal["business_key"]["relation_type"] == "CAN_SUBSTITUTE"
    assert reload(snapshot(proposal).data) == snapshot(proposal)


def test_disable_only_deactivates_and_can_be_reloaded():
    proposal = dependency_relation_target(current(), operation_type="DISABLE")
    assert proposal["after"] == {**proposal["before"], "active": False, "version": 5}
    assert reload(snapshot(proposal).data) == snapshot(proposal)
    with pytest.raises(ValueError):
        dependency_relation_target(current(active=False), operation_type="DISABLE")
    with pytest.raises(ValueError):
        dependency_relation_target(current(), {}, operation_type="DISABLE")


@pytest.mark.parametrize(
    "patch",
    [
        None,
        {},
        [],
        {"version": 100},
        {"dependency_relation_id": str(UUID(int=3))},
        {"created_at": "2026-10-09T00:00:00Z"},
        {"unknown": True},
        {"required": True},
        {"effective_from": "2026-10-09T00:00:00Z"},
    ],
)
def test_invalid_or_normalized_noop_patch_rejected(patch):
    with pytest.raises(ValueError):
        dependency_relation_target(current(), patch)


@pytest.mark.parametrize(
    "field,change",
    [
        ("required", 1),
        ("active", 0),
        ("required", None),
        ("source_entity_type", None),
        ("target_entity_type", []),
        ("relation_type", {}),
        ("source_entity_id", "invalid"),
        ("target_entity_id", None),
        ("effective_from", "2026-10-09T00:00:00"),
        ("effective_to", "2026-10-09T00:00:00Z"),
        ("effective_to", "2026-10-08T00:00:00Z"),
        ("effective_to", "2026-10-10T00:00:00.0000001Z"),
    ],
)
def test_invalid_business_record_rejected(field, change):
    with pytest.raises(ValueError):
        dependency_relation_create_target(values(**{field: change}))


@pytest.mark.parametrize("version", [True, 0, -1, 1.0, None, 2**63 - 1])
def test_invalid_or_overflow_update_version_rejected(version):
    with pytest.raises(ValueError):
        dependency_relation_target(current(version=version), {"required": False})


@pytest.mark.parametrize(
    "change",
    [
        "id",
        "before_id",
        "key",
        "before_missing",
        "after_missing",
        "expected",
        "version",
        "operation",
        "noop",
        "audit",
        "invalid_pair",
        "required",
        "disable_values",
        "disable_inactive",
        "create_before",
        "create_expected",
        "create_version",
    ],
)
def test_persisted_target_corruption_rejected_even_with_recomputed_hash(change):
    proposal = dependency_relation_target(current(), {"required": False})
    if change.startswith("create_"):
        proposal = dependency_relation_create_target(values())
    if change.startswith("disable_"):
        proposal = dependency_relation_target(current(), operation_type="DISABLE")
    payload = snapshot(proposal).data
    item = payload["targets"][0]
    if change == "id":
        item["after"]["dependency_relation_id"] = str(UUID(int=9))
    elif change == "before_id":
        item["before"]["dependency_relation_id"] = str(UUID(int=9))
    elif change == "key":
        item["business_key"]["source_entity_id"] = str(UUID(int=9))
    elif change == "before_missing":
        del item["before"]["effective_to"]
    elif change == "after_missing":
        del item["after"]["active"]
    elif change == "expected":
        item["expected_version"] = True
    elif change == "version":
        item["after"]["version"] = 4
    elif change == "operation":
        item["operation_type"] = "DELETE"
    elif change == "noop":
        item["after"]["required"] = True
    elif change == "audit":
        item["after"]["updated_at"] = "2026-10-09T00:00:00Z"
    elif change == "invalid_pair":
        item["after"]["target_entity_type"] = "Product"
    elif change == "required":
        item["after"]["required"] = 1
    elif change == "disable_values":
        item["after"]["required"] = False
    elif change == "disable_inactive":
        item["before"]["active"] = False
    elif change == "create_before":
        item["before"] = current()
    elif change == "create_expected":
        item["expected_version"] = 1
    elif change == "create_version":
        item["after"]["version"] = 2
    with pytest.raises(ValueError):
        reload(payload)


def test_missing_explicit_fields_and_caller_ids_rejected():
    for field in values():
        incomplete = values()
        del incomplete[field]
        with pytest.raises(ValueError):
            dependency_relation_create_target(incomplete)
    for extra in ({"version": 1}, {"dependency_relation_id": str(uuid4())}):
        with pytest.raises(ValueError):
            dependency_relation_create_target(values(**extra))


def test_multiple_targets_sort_keys_swap_and_collision_rejection():
    first = dependency_relation_target(current(1), {"source_entity_id": str(UUID(int=11))})
    second = dependency_relation_target(
        current(2, source_entity_id=str(UUID(int=11))),
        {
            "source_entity_id": str(UUID(int=10)),
        },
    )
    # Final keys are distinct; swapping old keys must not be rejected as a CREATE conflict.
    assert snapshot(first, second) == snapshot(second, first)
    assert snapshot(first, second).data["targets"][0]["target_id"] == first["target_id"]
    with pytest.raises(ValueError):
        snapshot(first, first)
    duplicate_key = dependency_relation_target(current(3), {"source_entity_id": str(UUID(int=11))})
    with pytest.raises(ValueError):
        snapshot(first, duplicate_key)


def test_category_and_trusted_context_boundaries():
    relation = dependency_relation_create_target(values())
    equipment = equipment_state_target(
        {
            "equipment_id": str(UUID(int=5)),
            "state_code": "RUNNING",
            "version": 1,
        },
        "STOPPED",
    )
    with pytest.raises(ValueError):
        snapshot(relation, equipment)
    with pytest.raises(ValueError):
        build_equipment_state_snapshot(ExecutionContext("floor1", "floor", uuid4()), [relation])
    with pytest.raises(ValueError):
        build_dependency_relation_snapshot({}, [relation])


def test_semantic_normalization_hash_and_snapshot_immutability():
    proposal = dependency_relation_target(current(), {"required": False})
    first = snapshot(proposal)
    equivalent = deepcopy(proposal)
    equivalent["before"]["effective_from"] = "2026-10-09T09:00:00+09:00"
    assert first == snapshot(equivalent)
    changed = dependency_relation_target(current(), {"effective_to": "2026-10-10T00:00:00Z"})
    assert first.snapshot_hash != snapshot(changed).snapshot_hash
    proposal["after"]["active"] = False
    view = first.data
    view["targets"][0]["after"]["active"] = False
    assert first.data["targets"][0]["after"]["active"] is True
    with pytest.raises(ValueError):
        CanonicalSnapshot(first.canonical_text, "0" * 64)


@pytest.mark.integration
def test_domain_endpoint_and_required_matrix_agrees_with_postgresql(db):
    db.migrate()
    with db.transaction() as connection:
        for relation, source, target, required in product(
            [*PAIRS, "USES"], KINDS, KINDS, [False, True]
        ):
            allowed = (source, target) in PAIRS.get(relation, set()) and (
                not required or relation in {"DEPENDS_ON", "SUPPLIES"}
            )
            accepted = True
            try:
                # Nested psycopg transaction uses a savepoint so a rejected row cannot
                # abort subsequent matrix cases. Polymorphic endpoints have no SQL FK.
                with connection.transaction():
                    connection.execute(
                        "INSERT INTO dependency_relation(dependency_relation_id,source_entity_type,"
                        "source_entity_id,target_entity_type,target_entity_id,relation_type,"
                        "effective_from,effective_to,required,active) "
                        "VALUES(%s,%s,%s,%s,%s,%s,%s,NULL,%s,true)",
                        (
                            uuid4(),
                            source,
                            uuid4(),
                            target,
                            uuid4(),
                            relation,
                            "2026-10-09T00:00:00Z",
                            required,
                        ),
                    )
            except psycopg.errors.CheckViolation:
                accepted = False
            assert accepted == allowed, (relation, source, target, required)
