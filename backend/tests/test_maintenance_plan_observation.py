from contextlib import contextmanager
from copy import deepcopy
from uuid import UUID

import psycopg
import pytest
from test_maintenance_plan_execute import approved as approved_plans
from test_maintenance_plan_execute import settings
from test_maintenance_prepare import identity

from linescope.execute import MaintenancePlanUpdateExecute
from linescope.proposals import ProposalError, ProposalStore


@pytest.fixture
def completed(db):
    db, _, saved = approved_plans.__wrapped__(db)
    service = MaintenancePlanUpdateExecute(db, settings())
    result = service.execute(identity(), str(saved.update_request_id))
    return db, service, result, saved


def test_current_plans_match_confirmed_after_without_mutating_result(completed):
    _, service, result, _ = completed
    original = deepcopy(result)
    observed = service.observe_current(result)
    assert observed["observed_at"].utcoffset().total_seconds() == 0
    assert len(observed["current_snapshot"]["targets"]) == 2
    for current, target in zip(
        observed["current_snapshot"]["targets"], result["targets"], strict=True
    ):
        assert current["target_id"] == target["target_id"]
        assert current["snapshot"] == target["after"]
    assert [p["version_delta"] for p in observed["current_versions"]] == [0, 0]
    assert result == original


def test_uncommitted_change_is_not_current_and_later_commit_has_version_difference(completed):
    db, service, result, _ = completed
    with db.transaction() as c:
        c.execute(
            "UPDATE maintenance_plan SET plan_status='PLANNED',version=7 WHERE maintenance_plan_id=%s",
            (UUID(int=20),),
        )
        before = service.observe_current(result)
        assert before["current_versions"][0]["version_delta"] == 0
    after = service.observe_current(result)
    assert [p["version_delta"] for p in after["current_versions"]] == [1, 0]
    assert after["current_snapshot"]["targets"][0]["snapshot"]["plan_status"] == "PLANNED"
    assert result["targets"][0]["after"]["plan_status"] == "CANCELLED"


def test_missing_plan_is_not_reported_as_complete_observation(completed):
    db, service, result, saved = completed
    with db.transaction() as c:
        c.execute("DELETE FROM maintenance_plan WHERE maintenance_plan_id=%s", (UUID(int=21),))
    with pytest.raises(ProposalError) as caught:
        service.observe_current(result)
    assert caught.value.code == "TARGET_NOT_FOUND"
    assert ProposalStore(db).get(identity(), str(saved.update_request_id))["status"] == "COMPLETED"


def test_reference_failure_does_not_change_confirmed_result(completed):
    db, _, result, saved = completed
    original = deepcopy(result)

    class Unavailable:
        @contextmanager
        def transaction(self):
            raise psycopg.OperationalError("private-secret")
            yield

    with pytest.raises(ProposalError) as caught:
        MaintenancePlanUpdateExecute(Unavailable(), settings()).observe_current(result)
    assert caught.value.code == "DEPENDENCY_UNAVAILABLE"
    assert result == original
    assert ProposalStore(db).get(identity(), str(saved.update_request_id))["status"] == "COMPLETED"
