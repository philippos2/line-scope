import json
from pathlib import Path
from uuid import uuid4

import pytest
from graph.test_common_dependency_reader import adapters as adapters
from graph.test_common_dependency_reader import graph_driver as graph_driver
from interfaces.test_registered_decisions import auth, client
from test_demo_graph_seed import counts
from test_demo_graph_seed import source as source

from linescope.demo_file_seed import MAX_BYTES, load_demo_file, seed_demo_file
from linescope.demo_graph_seed import demo_id
from linescope.demo_seed import SeedConflict

FIXTURE = Path("docs/demo/data/scenario1.json")


class UnavailableLLM:
    def complete(self, *args, **kwargs):
        raise AssertionError("Explicit reads must not call the unavailable LLM")


@pytest.mark.parametrize(
    "fault",
    ["unknown", "version", "duplicate", "reference", "boolean", "payload", "json-key", "size"],
)
def test_file_validation_rejects_invalid_input_before_writes(tmp_path, fault):
    data = json.loads(FIXTURE.read_text())
    if fault == "unknown":
        data["sql"] = "DROP TABLE equipment"
    elif fault == "version":
        data["schema_version"] = 2
    elif fault == "duplicate":
        data["equipment"].append(data["equipment"][0])
    elif fault == "reference":
        data["assignments"][0]["equipment_code"] = "not-registered"
    elif fault == "boolean":
        data["relations"][0]["required"] = "true"
    elif fault == "payload":
        data["capacity_inputs"][0]["payload"]["role"] = "manager"
    body = json.dumps(data)
    if fault == "json-key":
        body = '{"schema_version":1,"schema_version":1}'
    elif fault == "size":
        body = " " * (MAX_BYTES + 1)
    path = tmp_path / "input.json"
    path.write_text(body)
    with pytest.raises((ValueError, TypeError)):
        load_demo_file(path)


@pytest.mark.parametrize(
    "role,filter_,count,status",
    [
        ("manager", {"name": "第1"}, 1, 200),
        ("production", {"equipment_code": "M-204"}, 1, 200),
        ("maintenance", {"equipment_code": "m-204"}, 0, 200),
        ("unknown", {"name": "第1"}, 0, 401),
    ],
)
def test_direct_search_without_llm_preserves_filter_and_permissions(
    source, role, filter_, count, status
):
    seed_demo_file(source, FIXTURE)
    with client(source, None, llm=UnavailableLLM()) as api:
        response = api.post(
            "/agent",
            headers=auth(role),
            json={
                "message": "関係分析 "
                + json.dumps(
                    {
                        "tool": "search_equipment",
                        "arguments": {"filter": filter_, "page_size": 20, "cursor": None},
                    }
                )
            },
        )
    assert response.status_code == status, response.text
    if status == 200:
        rows = response.json()["data"]["tool_results"][0]["data"]["items"]
        assert len(rows) == count
        if count:
            assert rows[0]["equipment_code"] == "M-204"


def test_cli_bootstrap_and_repeat_preserve_values(source, monkeypatch, capsys):
    from linescope import cli

    monkeypatch.setattr(cli.Settings, "env", lambda: source.settings)
    monkeypatch.setattr(cli, "Database", lambda _: source)
    monkeypatch.setattr("sys.argv", ["linescope", "seed-demo-file", "--file", str(FIXTURE)])
    cli.main()
    assert len(json.loads(capsys.readouterr().out)["registered_inputs"]["inserted"]) == 2
    with source.transaction() as connection:
        connection.execute(
            "UPDATE equipment SET equipment_name='変更後' WHERE equipment_code='M-204'"
        )
        connection.execute(
            "UPDATE equipment_current_state SET state_code='UNDER_MAINTENANCE',version=2"
        )
        connection.execute("UPDATE economic_input SET version=2")
    again = seed_demo_file(source, FIXTURE)
    assert len(again["registered_inputs"]["retained"]) == 2
    with source.transaction() as connection:
        assert (
            connection.execute(
                "SELECT equipment_name FROM equipment WHERE equipment_code='M-204'"
            ).fetchone()["equipment_name"]
            == "変更後"
        )
        assert (
            connection.execute("SELECT min(version) AS v FROM equipment_current_state").fetchone()[
                "v"
            ]
            == 2
        )
        assert connection.execute("SELECT version FROM economic_input").fetchone()["version"] == 2
        assert connection.execute("SELECT count(*) AS n FROM update_request").fetchone()["n"] == 0


def test_failure_after_graph_and_first_input_rolls_back_everything(source, monkeypatch):
    from linescope.persistence import core_capacity

    before = counts(source)
    with source.transaction() as connection:
        prior_fatal = connection.execute(
            "SELECT fatal_error FROM graph_projection_control"
        ).fetchone()["fatal_error"]

    def fail(*args):
        raise ValueError("Injected second input failure")

    monkeypatch.setattr(core_capacity, "write", fail)
    with pytest.raises(ValueError, match="second input"):
        seed_demo_file(source, FIXTURE)
    assert counts(source) == before
    with source.transaction() as connection:
        assert connection.execute("SELECT count(*) AS n FROM economic_input").fetchone()["n"] == 0
        assert (
            connection.execute("SELECT fatal_error FROM graph_projection_control").fetchone()[
                "fatal_error"
            ]
            == prior_fatal
        )


def test_file_seed_rejects_rebuild_in_progress(source):
    with source.transaction() as connection:
        connection.execute("UPDATE graph_projection_control SET rebuild_flag=true")
    before = counts(source)
    with pytest.raises(SeedConflict):
        seed_demo_file(source, FIXTURE)
    assert counts(source) == before


def test_file_seed_rejects_additions_to_published_graph(source):
    with source.transaction() as connection:
        connection.execute("UPDATE graph_projection_control SET active_generation=%s", (uuid4(),))
    before = counts(source)
    with pytest.raises(SeedConflict):
        seed_demo_file(source, FIXTURE)
    assert counts(source) == before


def test_file_seed_rejects_edited_relationship_without_reset(source):
    seed_demo_file(source, FIXTURE)
    with source.transaction() as connection:
        connection.execute(
            "UPDATE dependency_relation SET active=false WHERE relation_type='CAN_SUBSTITUTE'"
        )
    before = counts(source)
    with pytest.raises(SeedConflict):
        seed_demo_file(source, FIXTURE)
    assert counts(source) == before


def test_json_scenario_real_api_graph_and_comparison(source, adapters):
    from linescope.graph.administration import GraphAdministration

    seed_demo_file(source, FIXTURE)
    GraphAdministration(source, adapters[1].driver).rebuild()
    m204, m208 = str(demo_id("M-204")), str(demo_id("M-208"))
    with client(source, adapters[1].driver, llm=UnavailableLLM()) as api:

        def post(path, values):
            r = api.post(path, headers=auth(), json=values)
            assert r.status_code == 200, r.text
            return r.json()["data"]

        loss = post(
            "/incidents/investigate",
            {
                "equipment_ids": [m204],
                "economic_input_ids": [str(demo_id("M-204-S1-ECONOMIC"))],
                "period_start": "2026-10-18T00:00:00Z",
                "period_end": "2026-10-19T00:00:00Z",
            },
        )
        assert loss["loss"]["loss_per_hour"] == "200000"
        products = loss["impacts"][0]["product_ids"]
        assert set(products) == {str(demo_id("P-100")), str(demo_id("P-200"))}
        selected = post(
            "/agent",
            {
                "message": "関係分析 "
                + json.dumps(
                    {
                        "tool": "find_alternative_paths",
                        "arguments": {
                            "important_targets": [
                                {"entity_type": "Product", "entity_id": p} for p in products
                            ],
                            "excluded_nodes": [{"entity_type": "Equipment", "entity_id": m204}],
                        },
                    }
                )
            },
        )
        result = selected["tool_results"][0]["data"]
        candidates = [c for row in result["alternatives"] for c in row["candidates"]]
        assert any(c["candidate"]["entity_id"] == m208 for c in candidates)
        assert result["representative_paths"]
        comparison = post(
            "/decisions/compare",
            {
                "equipment_id": m204,
                "economic_input_id": str(demo_id("M-204-S1-ECONOMIC")),
                "capacity_input_ids": [str(demo_id("M-208-S1-CAPACITY"))],
                "safety_input_ids": [],
                "maintenance_input_ids": [],
                "period_start": "2026-10-18T00:00:00Z",
                "period_end": "2026-10-19T00:00:00Z",
            },
        )
        options = comparison["decision_package"]["comparison"]["options"]
        substitute = next(o for o in options if o["option"] == "SUBSTITUTE")
        assert substitute["required_rate"] == "60" and substitute["available_rate"] == "80"
        assert substitute["feasibility"] != "FEASIBLE"
        assert substitute["condition_assessment"]["quality"] == "UNKNOWN"
        print(
            json.dumps(
                {"loss": loss, "alternatives": selected, "comparison": comparison},
                ensure_ascii=False,
            )
        )
