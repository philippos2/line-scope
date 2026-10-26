"""C07–C11: real one-statement reads and fail-closed authoritative observations."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from linescope.application.graph_availability import observe_availability
from linescope.application.reads import ToolError
from linescope.demo_file_seed import seed_demo_file
from linescope.demo_graph_seed import demo_id
from linescope.graph.analysis_budget import GraphAnalysisBudget
from linescope.graph.analysis_states import GraphStateReader
from linescope.persistence.core_reads import get_record_row

RESOURCE = ("InfrastructureResource", str(demo_id("R-02")))
FIXTURE = "docs/demo/data/scenario1.json"


def prepared(db):
    db.migrate()
    seed_demo_file(db, FIXTURE)
    return GraphStateReader(db)


def test_supply_read_preserves_registration_and_statement_time(db):
    reader = prepared(db)
    registered = datetime(2020, 1, 1, tzinfo=timezone.utc)
    with db.transaction() as connection:
        connection.execute("UPDATE infrastructure_supply_state SET registered_at=%s", (registered,))
    result = observe_availability([RESOURCE], reader, GraphAnalysisBudget(5000))
    assert result.values == {RESOURCE: "AVAILABLE"}
    fact = result.facts["resources"][0]
    assert fact["infrastructure_resource_id"] == RESOURCE[1]
    assert fact["version"] == 1 and fact["source"]
    assert datetime.fromisoformat(fact["registered_at"]) == registered
    assert result.facts["observed_at"] > registered
    with db.transaction() as connection:
        row = get_record_row(connection, "get_infrastructure_resource", demo_id("R-02"))
    nested = row["registered_supply_state"]
    assert nested["supply_state"] == "AVAILABLE"
    assert datetime.fromisoformat(nested["observed_at"]) == row["_observed_at"]
    assert nested["record"]["version"] == 1


def test_missing_supply_is_unknown_without_invented_record(db):
    reader = prepared(db)
    with db.transaction() as connection:
        connection.execute("DELETE FROM infrastructure_supply_state")
    result = observe_availability([RESOURCE], reader, GraphAnalysisBudget(5000))
    assert result.values == {} and result.missing_states == (RESOURCE,)
    assert result.facts["resources"] is None
    with db.transaction() as connection:
        nested = get_record_row(connection, "get_infrastructure_resource", demo_id("R-02"))[
            "registered_supply_state"
        ]
    assert nested["supply_state"] == "UNKNOWN" and nested["record"] is None


def test_read_failure_is_not_an_unknown_supply_record():
    class FailedReader:
        def read_availability(self, *args, **kwargs):
            raise ToolError("DEPENDENCY_UNAVAILABLE", "PostgreSQL unavailable")

    with pytest.raises(ToolError) as error:
        observe_availability([RESOURCE], FailedReader(), GraphAnalysisBudget(5000))
    assert error.value.code == "DEPENDENCY_UNAVAILABLE"


@pytest.mark.parametrize("damage", ["id", "enum"])
def test_invalid_authoritative_supply_is_rejected(db, damage):
    delegate = prepared(db)

    class DamagedReader:
        def read_availability(self, *args, **kwargs):
            result = delegate.read_availability(*args, **kwargs)
            record = result["resources"][0]
            record["infrastructure_resource_id" if damage == "id" else "supply_state"] = (
                str(uuid4()) if damage == "id" else "RUNNING"
            )
            return result

    with pytest.raises(ToolError) as error:
        observe_availability([RESOURCE], DamagedReader(), GraphAnalysisBudget(5000))
    assert error.value.code == "INTERNAL_ERROR"
