"""Bounded JSON bootstrap adapter; fixture values remain outside Python."""

from datetime import datetime
from pathlib import Path

from psycopg.errors import UniqueViolation

from .demo_graph_seed import demo_id, seed_graph_rows
from .demo_input_record import make_record
from .demo_seed import SeedConflict, _lock_seed
from .domain.canonical import normalize_timestamp, strict_json
from .domain.input_values import exact, text
from .persistence.core_demo_seed import require_demo_rebuild

MAX_BYTES = 1_000_000
# Fixed schema, never a caller-selected SQL table/identifier.
GROUPS = {
    "processes": ("process", "process_id", "process_code", {"process_name", "active"}),
    "products": ("product", "product_id", "product_code", {"product_name", "active"}),
    "infrastructure": (
        "infrastructure_resource",
        "infrastructure_resource_id",
        "resource_code",
        {"resource_name", "resource_type", "active"},
    ),
    "operations": (
        "production_operation",
        "production_operation_id",
        "operation_code",
        {"process_code", "planned_status", "planned_start", "planned_end", "active"},
    ),
    "assignments": (
        "production_operation_equipment_assignment",
        "assignment_id",
        "code",
        {"operation_code", "equipment_code", "effective_from", "effective_to", "active"},
    ),
    "relations": (
        "dependency_relation",
        "dependency_relation_id",
        "code",
        {
            "source_entity_type",
            "source_code",
            "target_entity_type",
            "target_code",
            "relation_type",
            "effective_from",
            "effective_to",
            "required",
            "active",
        },
    ),
}
TYPES = {
    "Equipment": "equipment",
    "Process": "processes",
    "Product": "products",
    "ProductionOperation": "operations",
    "InfrastructureResource": "infrastructure",
}


def load_demo_file(filename):
    with Path(filename).open("rb") as stream:
        body = stream.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("Demo JSON exceeds size limit")
    value = strict_json(body)
    if type(value.get("schema_version")) is not int or value["schema_version"] not in {1, 2}:
        raise ValueError("Unsupported demo schema version")
    extra = {"infrastructure_states"} if value["schema_version"] == 2 else set()
    exact(
        value,
        {"schema_version", "equipment", *GROUPS, "economic_inputs", "capacity_inputs", *extra},
    )
    codes = {}
    for group in ("equipment", *GROUPS, "economic_inputs", "capacity_inputs"):
        rows = value[group]
        if type(rows) is not list or len(rows) > 200:
            raise ValueError("Bounded demo arrays required")
        codes[group] = set()
        key = (
            "equipment_code"
            if group == "equipment"
            else (GROUPS[group][2] if group in GROUPS else "input_code")
        )
        for row in rows:
            if type(row) is not dict or key not in row:
                raise ValueError("Missing demo code")
            code = text(row[key], 100)
            if code in codes[group]:
                raise ValueError("Duplicate demo code")
            codes[group].add(code)
    # demo_id uses the code as its label, so cross-group aliases must not collide.
    all_codes = [code for group in codes.values() for code in group]
    if len(set(all_codes)) != len(all_codes):
        raise ValueError("Demo codes must be globally distinct")

    def reference(group, code):
        if type(code) is not str or code not in codes[group]:
            raise ValueError("Unknown demo reference")
        return demo_id(code)

    equipment = []
    for row in value["equipment"]:
        exact(row, {"equipment_code", "equipment_name", "state_code"})
        if row["state_code"] not in {"STOPPED", "RUNNING", "UNDER_MAINTENANCE", "UNKNOWN"}:
            raise ValueError("Unknown registered equipment state")
        equipment.append(
            (
                demo_id(row["equipment_code"]),
                row["equipment_code"],
                text(row["equipment_name"]),
                row["state_code"],
            )
        )
    fixtures = []
    for group, (table, id_key, code_key, fields) in GROUPS.items():
        for original in value[group]:
            exact(original, {code_key, *fields})
            label = original[code_key]
            row = {id_key: demo_id(label), **original}
            if code_key == "code":
                row.pop("code")
            for field in fields & {"active", "required"}:
                if type(row[field]) is not bool:
                    raise ValueError("Boolean declaration required")
            for field in fields & {
                "planned_start",
                "planned_end",
                "effective_from",
                "effective_to",
            }:
                if row[field] is not None:
                    row[field] = datetime.fromisoformat(normalize_timestamp(row[field]))
                elif field != "effective_to":
                    raise ValueError("Required demo timestamp")
            for name in fields - {
                "active",
                "required",
                "planned_start",
                "planned_end",
                "effective_from",
                "effective_to",
            }:
                text(row[name])
            if group == "operations":
                row["process_id"] = reference("processes", row.pop("process_code"))
            elif group == "assignments":
                row["production_operation_id"] = reference("operations", row.pop("operation_code"))
                row["equipment_id"] = reference("equipment", row.pop("equipment_code"))
            elif group == "relations":
                for end in ("source", "target"):
                    kind = row[end + "_entity_type"]
                    if kind not in TYPES:
                        raise ValueError("Unknown demo entity type")
                    row[end + "_entity_id"] = reference(TYPES[kind], row.pop(end + "_code"))
            identity = (
                (code_key, "active")
                if group in {"processes", "products", "infrastructure"}
                else None
            )
            fixtures.append((table, label, row, identity))
    supply_rows = value.get("infrastructure_states", [])
    if type(supply_rows) is not list or len(supply_rows) > 200:
        raise ValueError("Bounded infrastructure states required")
    seen_resources = set()
    for item in supply_rows:
        exact(item, {"resource_code", "supply_state", "source"})
        identifier = reference("infrastructure", item["resource_code"])
        if identifier in seen_resources or item["supply_state"] not in {
            "AVAILABLE",
            "UNAVAILABLE",
            "UNKNOWN",
        }:
            raise ValueError("Duplicate resource or invalid supply state")
        seen_resources.add(identifier)
        row = {
            "infrastructure_resource_id": identifier,
            "supply_state": item["supply_state"],
            "source": text(item["source"]),
        }
        fixtures.append(
            ("infrastructure_supply_state", "supply:" + item["resource_code"], row, tuple(row))
        )
    records = []
    for group, kind in (("economic_inputs", "economic"), ("capacity_inputs", "capacity")):
        for row in value[group]:
            extra = {"product_code"} if kind == "capacity" else set()
            exact(row, {"input_code", "equipment_code", "payload", *extra})
            payload = dict(row["payload"])
            if "incident_losses" in payload:
                losses = payload["incident_losses"]
                if type(losses) is not list:
                    raise ValueError("Loss scopes must be an array")
                payload["incident_losses"] = []
                for loss in losses:
                    exact(
                        loss,
                        {
                            "scope_key",
                            "product_code",
                            "loss_per_hour",
                            "independent",
                            "source",
                            "certainty",
                        },
                    )
                    item = dict(loss)
                    item["product_id"] = str(reference("products", item.pop("product_code")))
                    payload["incident_losses"].append(item)
            records.append(
                make_record(
                    kind,
                    row["input_code"],
                    str(reference("equipment", row["equipment_code"])),
                    payload,
                    **(
                        {"product_id": str(reference("products", row["product_code"]))}
                        if extra
                        else {}
                    ),
                )
            )
    return equipment, fixtures, records


def seed_demo_file(database, filename):
    equipment, fixtures, records = load_demo_file(filename)
    try:
        with database.transaction() as connection:
            control = _lock_seed(connection)
            result = seed_graph_rows(connection, fixtures, equipment)
            inserted, retained = [], []
            for queries, target in records:
                existing = queries.read(connection, target["target_id"], lock=True)
                if existing is None:
                    queries.write(connection, target)
                    inserted.append(target["after"]["input_code"])
                elif any(
                    str(existing[key]) != str(target["after"][key])
                    for key in (
                        "input_code",
                        "equipment_id",
                        *(("product_id",) if queries.INPUT.name == "capacity_input" else ()),
                    )
                ):
                    raise SeedConflict("Demo input identity conflict")
                else:
                    retained.append(existing["input_code"])
            if result["inserted"] or result["equipment"]["inserted"] or inserted:
                if control["active_generation"] is not None:
                    raise SeedConflict("Demo JSON additions require a first Graph Rebuild")
                require_demo_rebuild(connection)
            return {**result, "registered_inputs": {"inserted": inserted, "retained": retained}}
    except UniqueViolation as error:
        raise SeedConflict("Demo JSON business identity conflict") from error
