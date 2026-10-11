import pytest

from linescope.graph.analysis_budget import GraphAnalysisBudget, GraphAnalysisTimeout
from linescope.graph.transaction_timeout import neo4j_transaction_timeout


def test_deadline_does_not_extend_when_checked():
    now = [10.0]
    budget = GraphAnalysisBudget(1000, clock=lambda: now[0])
    assert budget.remaining() == 1
    now[0] = 10.75
    budget.require()
    assert budget.remaining() == 0.25
    assert neo4j_transaction_timeout(budget, 5) == 0.25
    now[0] = 11
    with pytest.raises(GraphAnalysisTimeout):
        budget.require()


@pytest.mark.parametrize("now", [10.999, 11, 12])
def test_expiry_boundary(now):
    clock = [10.0]
    budget = GraphAnalysisBudget(1000, clock=lambda: clock[0])
    clock[0] = now
    if now < 11:
        assert budget.remaining() > 0
    else:
        with pytest.raises(GraphAnalysisTimeout):
            budget.remaining()


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "1000", None])
def test_invalid_server_timeout(value):
    with pytest.raises(ValueError):
        GraphAnalysisBudget(value)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, None])
def test_invalid_clock_fails_closed(value):
    with pytest.raises(ValueError):
        GraphAnalysisBudget(1000, clock=lambda: value)
    clock = [10.0]
    budget = GraphAnalysisBudget(1000, clock=lambda: clock[0])
    clock[0] = value
    with pytest.raises(GraphAnalysisTimeout):
        budget.require()
