"""Pure DependencyRelation proposals; no authorization or Graph/DB mutation.

Prepare/Execute must check endpoint existence/active, final-set uniqueness,
interval overlap and mixed cycles against the complete PostgreSQL state.
"""

from uuid import uuid4

from .canonical import normalize_timestamp, normalize_uuid

FIELDS = {
    "dependency_relation_id",
    "source_entity_type",
    "source_entity_id",
    "target_entity_type",
    "target_entity_id",
    "relation_type",
    "effective_from",
    "effective_to",
    "required",
    "active",
    "version",
}
KEY_FIELDS = {
    "source_entity_type",
    "source_entity_id",
    "target_entity_type",
    "target_entity_id",
    "relation_type",
    "effective_from",
}
INPUT_FIELDS = FIELDS - {"dependency_relation_id", "version"}
TARGET_FIELDS = {
    "target_type",
    "target_id",
    "business_key",
    "operation_type",
    "before",
    "after",
    "expected_version",
}
MAX_VERSION = 2**63 - 1
ENDPOINTS = {
    "DEPENDS_ON": (
        {"Equipment", "Process", "ProductionOperation"},
        {"Equipment", "InfrastructureResource", "Process"},
    ),
    "PRECEDES": ({"Process", "ProductionOperation"}, None),
    "SUPPLIES": (
        {"InfrastructureResource", "Equipment"},
        {"Equipment", "Process", "ProductionOperation"},
    ),
    "CONTROLS": ({"Equipment"}, {"Equipment"}),
    "PRODUCES": ({"Process", "ProductionOperation"}, {"Product"}),
    "CAN_SUBSTITUTE": ({"Equipment", "Process", "InfrastructureResource"}, None),
}


def _exact(value, fields):
    if type(value) is not dict or set(value) != fields:
        raise ValueError("Invalid DependencyRelation fields")


def _record(value):
    _exact(value, FIELDS)
    relation, source, target = (
        value["relation_type"],
        value["source_entity_type"],
        value["target_entity_type"],
    )
    if any(type(item) is not str for item in (relation, source, target)):
        raise ValueError("Relation and endpoint types must be text")
    if relation not in ENDPOINTS:
        raise ValueError("Unsupported DependencyRelation type")
    sources, targets = ENDPOINTS[relation]
    if source not in sources or (target != source if targets is None else target not in targets):
        raise ValueError("Invalid DependencyRelation endpoint combination")
    if type(value["required"]) is not bool or type(value["active"]) is not bool:
        raise ValueError("Relation required and active must be boolean")
    if value["required"] and relation not in {"DEPENDS_ON", "SUPPLIES"}:
        raise ValueError("Relation type does not use required")
    version = value["version"]
    if type(version) is not int or not 1 <= version <= MAX_VERSION:
        raise ValueError("Relation version must be a positive BIGINT")
    start = normalize_timestamp(value["effective_from"])
    end = normalize_timestamp(value["effective_to"]) if value["effective_to"] is not None else None
    if end is not None and start >= end:
        raise ValueError("Relation interval must be nonempty")
    return {
        "dependency_relation_id": normalize_uuid(value["dependency_relation_id"]),
        "source_entity_type": source,
        "source_entity_id": normalize_uuid(value["source_entity_id"]),
        "target_entity_type": target,
        "target_entity_id": normalize_uuid(value["target_entity_id"]),
        "relation_type": relation,
        "effective_from": start,
        "effective_to": end,
        "required": value["required"],
        "active": value["active"],
        "version": version,
    }


def _key(record):
    return {field: record[field] for field in KEY_FIELDS}


def validate_relation_target(value):
    """Validate persisted targets too; business_key identifies the final row."""
    _exact(value, TARGET_FIELDS)
    if value["target_type"] != "DependencyRelation":
        raise ValueError("Invalid DependencyRelation target type")
    identifier = normalize_uuid(value["target_id"])
    after = _record(value["after"])
    _exact(value["business_key"], KEY_FIELDS)
    # Apply the same schema normalization to the key without inferring fields.
    key = _key(_record({**after, **value["business_key"]}))
    if identifier != after["dependency_relation_id"] or key != _key(after):
        raise ValueError("Relation target identity or business key disagrees")
    operation = value["operation_type"]
    before, expected = value["before"], value["expected_version"]
    if operation == "CREATE":
        if before is not None or expected is not None or after["version"] != 1:
            raise ValueError("Invalid DependencyRelation CREATE")
    elif operation in ("UPDATE", "DISABLE"):
        before = _record(before)
        if identifier != before["dependency_relation_id"]:
            raise ValueError("Relation ID is immutable")
        if (
            type(expected) is not int
            or expected != before["version"]
            or after["version"] != expected + 1
        ):
            raise ValueError("Relation versions disagree")
        if operation == "DISABLE":
            if (
                not before["active"]
                or after["active"]
                or any(before[field] != after[field] for field in INPUT_FIELDS - {"active"})
            ):
                raise ValueError("DISABLE must only deactivate an active relation")
        elif all(before[field] == after[field] for field in INPUT_FIELDS):
            raise ValueError("Relation UPDATE must change a business value")
    else:
        raise ValueError("Unsupported DependencyRelation operation")
    return {
        "target_type": "DependencyRelation",
        "target_id": identifier,
        "business_key": key,
        "operation_type": operation,
        "before": before,
        "after": after,
        "expected_version": expected,
    }


def dependency_relation_create_target(values):
    """Allocate an ID once; Prepare retries must retain the resulting target."""
    _exact(values, INPUT_FIELDS)
    after = _record({**values, "dependency_relation_id": str(uuid4()), "version": 1})
    return validate_relation_target(
        {
            "target_type": "DependencyRelation",
            "target_id": after["dependency_relation_id"],
            "business_key": _key(after),
            "operation_type": "CREATE",
            "before": None,
            "after": after,
            "expected_version": None,
        }
    )


def dependency_relation_target(current, patch=None, *, operation_type="UPDATE"):
    """Derive versions from trusted current state, excluding audit timestamps."""
    if type(current) is not dict:
        raise ValueError("Current DependencyRelation must be a record")
    before = _record({k: v for k, v in current.items() if k not in {"created_at", "updated_at"}})
    if operation_type == "DISABLE":
        if patch is not None:
            raise ValueError("DISABLE takes no patch")
        changes = {"active": False}
    elif operation_type == "UPDATE":
        if type(patch) is not dict or not patch or not set(patch) <= INPUT_FIELDS:
            raise ValueError("Invalid DependencyRelation patch")
        changes = patch
    else:
        raise ValueError("Use the CREATE builder for new relations")
    after = _record({**before, **changes, "version": before["version"] + 1})
    return validate_relation_target(
        {
            "target_type": "DependencyRelation",
            "target_id": before["dependency_relation_id"],
            "business_key": _key(after),
            "operation_type": operation_type,
            "before": before,
            "after": after,
            "expected_version": before["version"],
        }
    )
