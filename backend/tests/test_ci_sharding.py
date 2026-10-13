"""Partition invariants and actual pytest execution without disposable stores."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from ci_sharding import parse_shard, partition_nodeids


@pytest.mark.parametrize("value", ["", "0/2", "1/0", "3/2", "1", "1/2/3", "-1/2", "1.0/2"])
def test_invalid_shard_is_rejected(value):
    with pytest.raises(ValueError):
        parse_shard(value)


def test_partition_preserves_all_cases_module_scope_and_execution_order():
    nodes = ["a.py::test_x[1]", "b.py::test_y", "a.py::test_x[2]", "new.py::test_z"]
    groups = partition_nodeids(nodes, {"a.py": 9, "b.py": 5, "removed.py": 100}, 2)
    assert set(groups[0]).isdisjoint(groups[1])
    assert sorted(groups[0] + groups[1]) == sorted(nodes)
    assert next(group for group in groups if nodes[0] in group) == [nodes[0], nodes[2]]
    assert partition_nodeids(list(reversed(nodes)), {"b.py": 5, "a.py": 9}, 2) == [
        list(reversed(group)) for group in groups
    ]


def test_measured_cost_balances_heavy_modules_instead_of_case_counts():
    nodes = ["a.py::test_1", "b.py::test_1", "c.py::test_1", "d.py::test_1"]
    weights = {"a.py": 9, "b.py": 8, "c.py": 7, "d.py": 6}
    groups = partition_nodeids(nodes, weights, 2)
    assert [sum(weights[node.split("::")[0]] for node in group) for group in groups] == [15, 15]


@pytest.mark.parametrize("total", [0, -1, True, 1.5, 3])
def test_invalid_or_empty_partition_is_rejected(total):
    with pytest.raises(ValueError):
        partition_nodeids(["a.py::test_x", "b.py::test_y"], {}, total)


@pytest.mark.parametrize("weight", [-1, True, "1", float("inf"), float("nan")])
def test_invalid_weight_fails_closed(weight):
    with pytest.raises(ValueError):
        partition_nodeids(["a.py::test_x"], {"a.py": weight}, 1)


def test_duplicate_collected_case_is_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        partition_nodeids(["a.py::test_x", "a.py::test_x"], {}, 1)


def run_pytest(directory, *args):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).parent)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "ci_sharding",
            "-p",
            "no:cacheprovider",
            "-q",
            *args,
        ],
        cwd=directory,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_actual_pytest_shards_cover_all_parameterized_cases_and_propagate_failure(tmp_path):
    (tmp_path / "test_a.py").write_text(
        "import pytest\n@pytest.mark.parametrize('value', [1, 2, 3])\n"
        "def test_value(value):\n    assert value > 0\n"
    )
    (tmp_path / "test_b.py").write_text(
        "def test_first():\n    assert True\ndef test_second():\n    assert True\n"
    )
    complete = run_pytest(tmp_path)
    first = run_pytest(tmp_path, "--ci-shard", "1/2")
    second = run_pytest(tmp_path, "--ci-shard", "2/2")
    assert complete.returncode == first.returncode == second.returncode == 0
    assert "5 passed" in complete.stdout
    assert "collected=5 selected=3" in first.stdout and "3 passed, 2 deselected" in first.stdout
    assert "collected=5 selected=2" in second.stdout and "2 passed, 3 deselected" in second.stdout
    assert (
        first.stdout.split("collection_sha256=")[1].split()[0]
        == (second.stdout.split("collection_sha256=")[1].split()[0])
    )
    (tmp_path / "test_b.py").write_text("def test_failure():\n    assert False\n")
    failed = run_pytest(tmp_path, "--ci-shard", "2/2")
    assert failed.returncode == 1 and "1 failed" in failed.stdout


def test_invalid_cli_shard_cannot_run_cases(tmp_path):
    (tmp_path / "test_a.py").write_text("def test_failure():\n    assert False\n")
    result = run_pytest(tmp_path, "--ci-shard", "0/2")
    assert result.returncode == 4
    assert "Invalid CI partition" in result.stderr and "1 failed" not in result.stdout
