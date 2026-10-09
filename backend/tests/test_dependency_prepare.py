from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from threading import Barrier
from uuid import UUID, uuid4

import psycopg
import pytest
from test_production_prepare import AGENT_HASH, END, NEW_END, START, counts, identity

from linescope.dependency_prepare import DependencyPrepare
from linescope.proposals import ProposalError


def uid(number):
    return str(UUID(int=number))


def create(**changes):
    return {
        "operation_type": "CREATE",
        "source_entity_type": "Process",
        "source_entity_id": uid(11),
        "target_entity_type": "InfrastructureResource",
        "target_entity_id": uid(40),
        "relation_type": "DEPENDS_ON",
        "effective_from": START,
        "effective_to": None,
        "required": True,
        "active": True,
        **changes,
    }


def update(number=200, **patch):
    return {
        "operation_type": "UPDATE",
        "dependency_relation_id": uid(number),
        "patch": patch or {"effective_to": NEW_END},
    }


def disable(number=201):
    return {"operation_type": "DISABLE", "dependency_relation_id": uid(number)}


@pytest.fixture
def service(db):
    db.migrate()
    with db.transaction() as connection:
        for number in (100, 101, 102):
            connection.execute(
                "INSERT INTO equipment(equipment_id,equipment_code,equipment_name,equipment_type,active) VALUES(%s,%s,'Machine','machine',%s)",
                (UUID(int=number), f"EQ{number}", number != 102),
            )
        for number in (10, 11):
            connection.execute(
                "INSERT INTO process(process_id,process_code,process_name,active) VALUES(%s,%s,'Process',true)",
                (UUID(int=number), f"P{number}"),
            )
        connection.execute(
            "INSERT INTO infrastructure_resource(infrastructure_resource_id,resource_code,resource_name,resource_type,active) VALUES(%s,'R','Resource','power',true)",
            (UUID(int=40),),
        )
        connection.execute(
            "INSERT INTO product(product_id,product_code,product_name,active) VALUES(%s,'PROD','Product',true)",
            (UUID(int=30),),
        )
        connection.execute(
            "INSERT INTO production_operation(production_operation_id,operation_code,process_id,planned_status,planned_start,planned_end,active,version) VALUES(%s,'OP',%s,'PLANNED',%s,%s,true,3)",
            (UUID(int=20), UUID(int=10), START, END),
        )
        connection.execute(
            "INSERT INTO production_operation_equipment_assignment(assignment_id,production_operation_id,equipment_id,effective_from,effective_to,active,version) VALUES(%s,%s,%s,%s,NULL,true,1)",
            (UUID(int=300), UUID(int=20), UUID(int=100), START),
        )
        for number, source, target, end in ((200, 100, 10, END), (201, 101, 11, None)):
            connection.execute(
                "INSERT INTO dependency_relation(dependency_relation_id,source_entity_type,source_entity_id,target_entity_type,target_entity_id,relation_type,effective_from,effective_to,required,active,version) VALUES(%s,'Equipment',%s,'Process',%s,'DEPENDS_ON',%s,%s,true,true,5)",
                (UUID(int=number), UUID(int=source), UUID(int=target), START, end),
            )
    return db, DependencyPrepare(db)


def prepare(svc, targets=None, **kwargs):
    return svc.prepare(
        kwargs.pop("context", identity("maintenance")),
        targets or [create()],
        kwargs.pop("key", uuid4()),
        agent_input_hash=kwargs.pop("agent_input_hash", AGENT_HASH),
        **kwargs,
    )


def test_composite_all_business_snapshots_and_source_unchanged(service):
    db, svc = service
    saved = prepare(svc, [create(), update(), disable()])
    assert saved.operation_type == "COMPOSITE" and saved.status == "WAITING_APPROVAL"
    targets = saved.snapshot.data["targets"]
    assert {t["operation_type"] for t in targets} == {"CREATE", "UPDATE", "DISABLE"}
    for target in targets:
        assert target["target_type"] == "DependencyRelation"
        if target["operation_type"] == "CREATE":
            assert (
                target["before"] is None
                and target["expected_version"] is None
                and target["after"]["version"] == 1
            )
        else:
            assert target["expected_version"] == 5 and target["after"]["version"] == 6
            assert len(target["before"]) == 11
    with db.transaction() as connection:
        assert (
            connection.execute("SELECT count(*) AS n FROM dependency_relation").fetchone()["n"] == 2
        )
        assert all(
            row["version"] == 5 and row["active"]
            for row in connection.execute("SELECT * FROM dependency_relation")
        )
    assert counts(db) == {"requests": 1, "targets": 3, "approvals": 1}


@pytest.mark.parametrize("role", ["maintenance", "production", "manager"])
def test_request_roles(service, role):
    assert prepare(service[1], context=identity(role)).status == "WAITING_APPROVAL"


def test_reject_floor_before_db():
    class NoDatabase:
        def transaction(self):
            pytest.fail("Unauthorized DB call")

    with pytest.raises(ProposalError) as caught:
        prepare(DependencyPrepare(NoDatabase()), context=identity("floor"))
    assert caught.value.code == "AUTHORIZATION_DENIED"


@pytest.mark.parametrize(
    "value",
    [
        {},
        create(version=1),
        create(dependency_relation_id=uid(500)),
        create(required=1),
        create(relation_type="USES"),
        create(effective_from=None),
        create(effective_to="2026-10-09T00:00:00"),
        update(expected_version=5),
        {"operation_type": "UPDATE", "dependency_relation_id": uid(200), "patch": {}},
        {**disable(), "patch": {"active": False}},
        {**update(), "patch": {"dependency_relation_id": uid(200)}},
    ],
)
def test_invalid_schema(service, value):
    with pytest.raises(ProposalError) as caught:
        prepare(service[1], [value])
    assert caught.value.code == "INVALID_ARGUMENT" and counts(service[0])["requests"] == 0


@pytest.mark.parametrize(
    "values",
    [
        [update(), disable(200)],
        [create(), create()],
        [update(999)],
        [create(source_entity_id=uid(999))],
        [create(source_entity_type="Equipment", source_entity_id=uid(102))],
        [create(effective_to=START)],
        [create(relation_type="PRECEDES")],
        [
            create(
                source_entity_type="Equipment",
                source_entity_id=uid(100),
                target_entity_type="Equipment",
                target_entity_id=uid(101),
                relation_type="CONTROLS",
                required=True,
            )
        ],
        [update(required=True)],
    ],
)
def test_bad_target_rejects_entire_request(service, values):
    with pytest.raises(ProposalError):
        prepare(service[1], [disable(), *values])
    assert counts(service[0]) == {"requests": 0, "targets": 0, "approvals": 0}


def test_disable_inactive_rejected(service):
    db, svc = service
    with db.transaction() as connection:
        connection.execute(
            "UPDATE dependency_relation SET active=false WHERE dependency_relation_id=%s",
            (UUID(int=201),),
        )
    with pytest.raises(ProposalError) as caught:
        prepare(svc, [disable()])
    assert caught.value.code == "BUSINESS_RULE_VIOLATION"


def test_business_key_swap_uses_final_set(service):
    saved = prepare(
        service[1],
        [
            update(200, source_entity_id=uid(101), target_entity_id=uid(11), effective_to=None),
            update(201, source_entity_id=uid(100), target_entity_id=uid(10), effective_to=END),
        ],
    )
    assert len(saved.snapshot.data["targets"]) == 2
    first = next(t for t in saved.snapshot.data["targets"] if t["target_id"] == uid(200))
    assert first["business_key"]["source_entity_id"] == uid(101)
    assert first["before"]["source_entity_id"] == uid(100)


def test_shortening_allows_create_at_adjacent_boundary(service):
    new = create(
        source_entity_type="Equipment",
        source_entity_id=uid(100),
        target_entity_type="Process",
        target_entity_id=uid(10),
        effective_from=END,
    )
    saved = prepare(service[1], [new])
    assert saved.operation_type == "CREATE"
    with pytest.raises(ProposalError) as caught:
        prepare(service[1], [{**new, "effective_from": START}])
    assert caught.value.code == "BUSINESS_RULE_VIOLATION"


def test_update_shrink_before_create_final_interval_validation(service):
    db, svc = service
    with db.transaction() as connection:
        connection.execute(
            "UPDATE dependency_relation SET effective_to=NULL WHERE dependency_relation_id=%s",
            (UUID(int=200),),
        )
    new = create(
        source_entity_type="Equipment",
        source_entity_id=uid(100),
        target_entity_type="Process",
        target_entity_id=uid(10),
        effective_from=END,
    )
    with pytest.raises(ProposalError):
        prepare(svc, [new])
    assert prepare(svc, [update(effective_to=END), new]).operation_type == "COMPOSITE"


def test_mixed_logical_cycle_and_repair_by_disable(service):
    db, svc = service
    reverse = create(
        source_entity_id=uid(10), target_entity_type="Equipment", target_entity_id=uid(100)
    )
    with pytest.raises(ProposalError) as caught:
        prepare(svc, [reverse])
    assert caught.value.code == "BUSINESS_RULE_VIOLATION"
    assert prepare(svc, [disable(200), reverse]).status == "WAITING_APPROVAL"


def test_supplies_cycle_is_allowed(service):
    left = create(
        source_entity_type="Equipment",
        source_entity_id=uid(100),
        target_entity_type="Equipment",
        target_entity_id=uid(101),
        relation_type="SUPPLIES",
    )
    right = {**left, "source_entity_id": uid(101), "target_entity_id": uid(100)}
    assert prepare(service[1], [left, right]).status == "WAITING_APPROVAL"


def test_replay_terminal_after_source_changes_and_no_id_regeneration(service, monkeypatch):
    import linescope.relations as module

    db, svc = service
    key = uuid4()
    values = [create(), update(), disable()]
    first = prepare(svc, values, key=key)
    with db.transaction() as connection:
        connection.execute("DELETE FROM dependency_relation")
        connection.execute("UPDATE update_request SET status='REJECTED'")
        connection.execute("UPDATE approval SET status='REJECTED',approver_id='manager1'")
    monkeypatch.setattr(module, "uuid4", lambda: pytest.fail("Replay allocated ID"))
    again = deepcopy(list(reversed(values)))
    again[-1]["effective_from"] = "2026-10-09T09:00:00+09:00"
    second = prepare(svc, again, key=key)
    assert second.replayed and second.snapshot == first.snapshot and second.status == "REJECTED"
    with pytest.raises(ProposalError) as caught:
        prepare(svc, [create(required=False)], key=key)
    assert caught.value.code == "DUPLICATE_REQUEST"


def test_parallel_key_is_one_fixed_snapshot(service):
    _, svc = service
    key = uuid4()
    barrier = Barrier(4)

    def run(_):
        barrier.wait(timeout=10)
        return prepare(svc, key=key)

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(run, range(4)))
    assert len({r.update_request_id for r in results}) == 1
    assert len({r.snapshot.canonical_text for r in results}) == 1
    assert sum(not r.replayed for r in results) == 1


def test_rollback_all_targets_and_old_request(service):
    db, svc = service
    old = prepare(svc)
    key = uuid4()
    before = counts(db)
    with db.transaction() as connection:
        connection.execute(
            "CREATE FUNCTION fail_approval() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'fixture'; END $$"
        )
        connection.execute(
            "CREATE TRIGGER fail_insert BEFORE INSERT ON approval FOR EACH ROW EXECUTE FUNCTION fail_approval()"
        )
    with pytest.raises(ProposalError):
        prepare(
            svc,
            [create(), update(), disable()],
            key=key,
            supersedes_update_request_id=old.update_request_id,
        )
    assert counts(db) == before
    with db.transaction() as connection:
        assert (
            connection.execute("SELECT status FROM update_request").fetchone()["status"]
            == "WAITING_APPROVAL"
        )
        connection.execute("DROP TRIGGER fail_insert ON approval")
    new = prepare(
        svc,
        [create(), update(), disable()],
        key=key,
        supersedes_update_request_id=old.update_request_id,
    )
    assert len(new.snapshot.data["targets"]) == 3


def test_single_statement_reads_all_typed_endpoints_and_uses(service, monkeypatch):
    _, svc = service
    original = svc.store._transaction
    statements = []

    class Recorder:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, sql, params=None):
            statements.append(sql)
            return self.connection.execute(sql, params)

    @contextmanager
    def transaction(*, read_only=False):
        with original(read_only=read_only) as connection:
            yield Recorder(connection) if read_only else connection

    monkeypatch.setattr(svc.store, "_transaction", transaction)
    prepare(svc)
    reads = [s for s in statements if "AS relations" in s]
    assert len(reads) == 1 and "AS assignments" in reads[0] and "AS endpoints" in reads[0]
    assert "FOR UPDATE" not in reads[0]


@pytest.mark.parametrize(
    "error,code",
    [
        (psycopg.errors.QueryCanceled("secret"), "RESOURCE_BUSY"),
        (psycopg.OperationalError("secret"), "DEPENDENCY_UNAVAILABLE"),
    ],
)
def test_read_errors_safe(service, monkeypatch, error, code):
    _, svc = service
    original = svc.store._transaction
    calls = 0

    @contextmanager
    def transaction(*, read_only=False):
        nonlocal calls
        calls += 1
        with original(read_only=read_only) as connection:
            if calls == 2:
                raise error
            yield connection

    monkeypatch.setattr(svc.store, "_transaction", transaction)
    with pytest.raises(ProposalError) as caught:
        prepare(svc)
    assert caught.value.code == code and "secret" not in str(caught.value)


def test_missing_explicit_end(service):
    value = create()
    del value["effective_to"]
    with pytest.raises(ProposalError) as caught:
        prepare(service[1], [value])
    assert caught.value.code == "INVALID_ARGUMENT"


@pytest.mark.parametrize("side", ["source", "target"])
def test_inactive_endpoint_refused(service, side):
    db, svc = service
    with db.transaction() as connection:
        if side == "source":
            connection.execute(
                "UPDATE process SET active=false WHERE process_id=%s", (UUID(int=11),)
            )
        else:
            connection.execute("UPDATE infrastructure_resource SET active=false")
    with pytest.raises(ProposalError) as caught:
        prepare(svc)
    assert caught.value.code == "BUSINESS_RULE_VIOLATION" and counts(db)["requests"] == 0


def test_typed_endpoint_does_not_match_another_entity_with_same_uuid(service):
    with pytest.raises(ProposalError) as caught:
        prepare(service[1], [create(source_entity_id=uid(100))])
    assert caught.value.code == "TARGET_NOT_FOUND"


def test_version_overflow_refused(service):
    db, svc = service
    with db.transaction() as connection:
        connection.execute(
            "UPDATE dependency_relation SET version=9223372036854775807 WHERE dependency_relation_id=%s",
            (UUID(int=200),),
        )
    with pytest.raises(ProposalError) as caught:
        prepare(svc, [update()])
    assert caught.value.code == "INTERNAL_ERROR" and counts(db)["requests"] == 0


def test_new_ids_not_generated_when_any_update_invalid(service, monkeypatch):
    import linescope.relations as module

    monkeypatch.setattr(
        module, "uuid4", lambda: pytest.fail("Allocated before business validation")
    )
    with pytest.raises(ProposalError) as caught:
        prepare(service[1], [create(), update(required=True)])
    assert caught.value.code == "BUSINESS_RULE_VIOLATION"


@pytest.mark.parametrize("collision", ["existing", "new"])
def test_generated_id_collisions_refused(service, monkeypatch, collision):
    import linescope.relations as module

    monkeypatch.setattr(module, "uuid4", lambda: UUID(int=200 if collision == "existing" else 900))
    values = (
        [create()]
        if collision == "existing"
        else [create(), create(effective_from=END, active=False)]
    )
    with pytest.raises(ProposalError) as caught:
        prepare(service[1], values)
    assert caught.value.code == "INTERNAL_ERROR" and counts(service[0])["requests"] == 0


@pytest.mark.parametrize("change", ["agent", "replacement", "explicit_field"])
def test_retry_input_mismatch(service, change):
    _, svc = service
    key = uuid4()
    prepare(svc, [update()], key=key)
    kwargs = {}
    values = [update()]
    if change == "agent":
        kwargs["agent_input_hash"] = "f" * 64
    elif change == "replacement":
        kwargs["supersedes_update_request_id"] = uuid4()
    else:
        values = [update(effective_to=NEW_END, active=True)]
    with pytest.raises(ProposalError) as caught:
        prepare(svc, values, key=key, **kwargs)
    assert caught.value.code == "DUPLICATE_REQUEST"


def test_retry_key_owner_scope_and_current_permission(service):
    _, svc = service
    key = uuid4()
    first = prepare(svc, key=key)
    second = prepare(svc, key=key, context=identity("production", user="production2"))
    assert first.update_request_id != second.update_request_id
    with pytest.raises(ProposalError) as caught:
        prepare(svc, key=key, context=identity("floor"))
    assert caught.value.code == "AUTHORIZATION_DENIED"


def test_single_observation_preserves_old_version_after_direct_sql_change(service, monkeypatch):
    db, svc = service
    original = svc.store._transaction
    calls = 0

    @contextmanager
    def transaction(*, read_only=False):
        nonlocal calls
        calls += 1
        with original(read_only=read_only) as connection:
            yield connection
        if calls == 2:
            with db.transaction() as connection:
                connection.execute("UPDATE dependency_relation SET version=9,effective_to=NULL")

    monkeypatch.setattr(svc.store, "_transaction", transaction)
    saved = prepare(svc, [update()])
    assert saved.snapshot.data["targets"][0]["expected_version"] == 5
    assert saved.snapshot.data["targets"][0]["before"]["effective_to"] == END
