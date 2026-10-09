"""Explicit bootstrap fixtures for read demos, not business update operations."""

from uuid import UUID

from psycopg.errors import UniqueViolation

DEMO_EQUIPMENT = (
    (UUID("20400000-0000-4000-8000-000000000001"), "M-204", "Demo machine M-204", "STOPPED"),
    (UUID("20800000-0000-4000-8000-000000000001"), "M-208", "Demo machine M-208", "RUNNING"),
)


class SeedConflict(ValueError):
    """Existing data cannot safely be associated with this fixture."""


def seed_demo(database):
    """Insert missing demo equipment atomically; never reset existing values.

    Migrations must already be applied. No relationships, assignments or Graph
    readiness are created. Fixed UUIDs and codes identify the fixtures; matching
    existing identities retain all metadata, state, versions and timestamps.
    """
    inserted = []
    retained = []
    try:
        with database.transaction() as connection:
            for equipment_id, code, name, state in DEMO_EQUIPMENT:
                created = connection.execute(
                    """INSERT INTO equipment
                       (equipment_id,equipment_code,equipment_name,equipment_type,active)
                       VALUES(%s,%s,%s,'machine',true)
                       ON CONFLICT(equipment_id) DO NOTHING RETURNING equipment_id""",
                    (equipment_id, code, name),
                ).fetchone()
                if created:
                    connection.execute(
                        "INSERT INTO equipment_current_state(equipment_id,state_code) VALUES(%s,%s)",
                        (equipment_id, state),
                    )
                    inserted.append(code)
                    continue
                existing = connection.execute(
                    "SELECT equipment_code FROM equipment WHERE equipment_id=%s FOR UPDATE",
                    (equipment_id,),
                ).fetchone()
                if not existing or existing["equipment_code"] != code:
                    raise SeedConflict(f"Demo equipment identity conflict: {code}")
                current_state = connection.execute(
                    "SELECT equipment_id FROM equipment_current_state WHERE equipment_id=%s FOR UPDATE",
                    (equipment_id,),
                ).fetchone()
                if not current_state:
                    raise SeedConflict(f"Existing demo equipment has no current state: {code}")
                retained.append(code)
    except UniqueViolation as error:
        raise SeedConflict("Demo equipment business code is already in use") from error
    return {"inserted": inserted, "retained": retained}
