"""Explicit bootstrap fixtures for read demos, not business update operations."""

from uuid import UUID

from psycopg.errors import UniqueViolation

from .graph.graph_locks import acquire_graph_mutation_lock
from .persistence.core_demo_seed import (
    insert_row,
    lock_seed_control,
    read_row,
    require_demo_rebuild,
)

DEMO_EQUIPMENT = (
    (UUID("20400000-0000-4000-8000-000000000001"), "M-204", "Demo machine M-204", "STOPPED"),
    (UUID("20800000-0000-4000-8000-000000000001"), "M-208", "Demo machine M-208", "RUNNING"),
)


class SeedConflict(ValueError):
    """Existing data cannot safely be associated with this fixture."""


def _seed_equipment(connection):
    inserted, retained = [], []
    for equipment_id, code, name, state in DEMO_EQUIPMENT:
        created = insert_row(
            connection,
            "equipment",
            {
                "equipment_id": equipment_id,
                "equipment_code": code,
                "equipment_name": name,
                "equipment_type": "machine",
                "active": True,
            },
        )
        if created:
            insert_row(
                connection,
                "equipment_current_state",
                {"equipment_id": equipment_id, "state_code": state},
            )
            inserted.append(code)
            continue
        existing = read_row(connection, "equipment", equipment_id)
        if not existing or existing["equipment_code"] != code:
            raise SeedConflict(f"Demo equipment identity conflict: {code}")
        if not read_row(connection, "equipment_current_state", equipment_id):
            raise SeedConflict(f"Existing demo equipment has no current state: {code}")
        retained.append(code)
    return {"inserted": inserted, "retained": retained}


def _lock_seed(connection):
    acquire_graph_mutation_lock(connection, shared=False)
    control = lock_seed_control(connection)
    if control is None or control["rebuild_flag"]:
        raise SeedConflict("Demo seed requires initialized control and no active Rebuild")
    return control


def seed_demo(database):
    """Atomic explicit bootstrap; existing values are never reset.

    New rows invalidate Graph in the same transaction. No fake business
    Approval, history or Outbox is manufactured for administrative fixtures.
    """
    try:
        with database.transaction() as connection:
            control = _lock_seed(connection)
            result = _seed_equipment(connection)
            if result["inserted"]:
                if control["active_generation"] is not None:
                    raise SeedConflict(
                        "New demo rows require seeding before the first Graph Rebuild"
                    )
                require_demo_rebuild(connection)
            return result
    except UniqueViolation as error:
        raise SeedConflict("Demo equipment business code is already in use") from error
