import pytest
from graph.test_common_dependency_reader import adapters as adapters
from graph.test_common_dependency_reader import graph_driver as graph_driver
from incident_graph_fixture import EQUIPMENT, FIXTURES, seed_incident_demo
from test_demo_graph_seed import counts
from test_demo_graph_seed import source as source

from linescope.demo_seed import SeedConflict


def test_regression_fixture_initializes_shared_and_individual_impact_data(source):
    assert "equipment" in seed_incident_demo(source)
    with source.transaction() as connection:
        states = connection.execute(
            "SELECT state_code FROM equipment_current_state ORDER BY equipment_id"
        ).fetchall()
        assert [row["state_code"] for row in states] == ["STOPPED", "STOPPED"]
        assert connection.execute("SELECT count(*) AS n FROM update_request").fetchone()["n"] == 0
    assert counts(source)["production_operation_equipment_assignment"] == 2
    assert counts(source)["product"] == 3
    assert len(seed_incident_demo(source)["registered_inputs"]["retained"]) == 11
    assert counts(source)["dependency_relation"] == 15
    again = seed_incident_demo(source)
    assert again["inserted"] == [] and len(again["retained"]) == len(FIXTURES)


def test_repeated_incident_seed_preserves_operator_changes(source):
    seed_incident_demo(source)
    with source.transaction() as connection:
        connection.execute(
            "UPDATE equipment_current_state SET state_code='RUNNING',version=version+1 WHERE equipment_id=%s",
            (EQUIPMENT[1][0],),
        )
        connection.execute(
            "UPDATE equipment SET equipment_name=%s WHERE equipment_id=%s",
            ("変更した名称", EQUIPMENT[1][0]),
        )
    seed_incident_demo(source)
    with source.transaction() as connection:
        assert connection.execute(
            "SELECT state_code,version FROM equipment_current_state WHERE equipment_id=%s",
            (EQUIPMENT[1][0],),
        ).fetchone() == {"state_code": "RUNNING", "version": 2}
        assert (
            connection.execute(
                "SELECT equipment_name FROM equipment WHERE equipment_id=%s", (EQUIPMENT[1][0],)
            ).fetchone()["equipment_name"]
            == "変更した名称"
        )


def test_incident_seed_rolls_back_on_edited_relation(source):
    seed_incident_demo(source)
    with source.transaction() as connection:
        connection.execute(
            "UPDATE dependency_relation SET active=false WHERE relation_type='CAN_SUBSTITUTE'"
        )
    before = counts(source)
    with pytest.raises(SeedConflict):
        seed_incident_demo(source)
    assert counts(source) == before


def test_incident_seed_does_not_extend_published_legacy_graph(source):
    from uuid import uuid4

    from linescope.demo_graph_seed import seed_graph_demo

    seed_graph_demo(source)
    with source.transaction() as connection:
        connection.execute("UPDATE graph_projection_control SET active_generation=%s", (uuid4(),))
    before = counts(source)
    with pytest.raises(SeedConflict):
        seed_incident_demo(source)
    assert counts(source) == before


def test_incident_real_graph_keeps_shared_and_individual_product_paths(source, adapters):
    from uuid import uuid4

    from linescope.bootstrap import build_api_services
    from linescope.demo_graph_seed import demo_id
    from linescope.execution import ExecutionContext
    from linescope.graph.administration import GraphAdministration

    seed_incident_demo(source)
    generation = GraphAdministration(source, adapters[1].driver).rebuild().generation
    services = build_api_services(source.settings, source, graph_driver=adapters[1].driver)
    context = ExecutionContext("incident-demo-reader", "manager", uuid4())
    products = []
    try:
        for identifier, _, _, _ in EQUIPMENT:
            result = services.decisions.graph.call(
                context,
                "trace_downstream_impact",
                {"target": {"entity_type": "Equipment", "entity_id": str(identifier)}},
            )
            assert result.data["complete"]
            assert str(result.evidence["graph_generation"]) == str(generation)
            products.append(
                {
                    row["entity_id"]
                    for row in result.data["reached_nodes"]
                    if row["entity_type"] == "Product"
                }
            )
            assert result.data["representative_paths"]
        assert products == [
            {str(demo_id("P-100")), str(demo_id("P-200"))},
            {str(demo_id("P-100")), str(demo_id("P-300"))},
        ]
    finally:
        services.close()
