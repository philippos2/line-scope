import pytest

from graph.test_alternative_facts import AS_OF, OTHER, M, P, Q
from graph.test_common_dependency_reader import adapters as adapters
from graph.test_common_dependency_reader import graph_driver as graph_driver
from graph.test_common_dependency_reader import reader_world as reader_world
from linescope.graph.analysis_budget import GraphAnalysisBudget
from linescope.graph.spof_facts import collect_spof_facts


def collect(reader, candidates=None, **limits):
    with reader.open(GraphAnalysisBudget(5000)) as read:
        return collect_spof_facts(
            read,
            (P, Q),
            candidates,
            as_of=AS_OF,
            max_depth=limits.get("max_depth", 16),
            max_nodes=limits.get("max_nodes", 9),
            page_size=1,
            should_stop=limits.get("should_stop"),
        )


def test_default_candidates_are_per_target_mandatory_ancestors(reader_world):
    result = collect(reader_world[0])
    assert result.complete
    groups = dict(result.candidates_by_target)
    assert M in groups[P] and M in groups[Q]
    assert P not in groups[P] and Q not in groups[Q]
    assert OTHER not in groups[P]
    assert len(result.prerequisites) == 9
    assert next(item for item in result.substitutes if item.target == M).candidates == (OTHER,)


def test_explicit_empty_does_not_discover_candidates(reader_world):
    result = collect(reader_world[0], ())
    assert result.complete and result.substitutes == ()
    assert dict(result.candidates_by_target) == {P: (), Q: ()}
    assert len(result.prerequisites) == 8


def test_explicit_candidates_keep_per_target_self_exclusion(reader_world):
    result = collect(reader_world[0], (P, M))
    assert dict(result.candidates_by_target)[P] == (M,)
    assert P in dict(result.candidates_by_target)[Q]


@pytest.mark.parametrize(
    "kwargs,reason",
    [
        ({"max_nodes": 8}, "NODE_COUNT"),
        ({"max_depth": 1}, "DEPTH"),
        ({"should_stop": lambda: True}, "TIMEOUT"),
    ],
)
def test_limits_apply_to_entire_analysis(reader_world, kwargs, reason):
    result = collect(reader_world[0], **kwargs)
    assert not result.complete and result.limit_reason == reason
    assert len(result.prerequisites) <= kwargs.get("max_nodes", 9)
    assert all(not item.complete for item in result.substitutes)
