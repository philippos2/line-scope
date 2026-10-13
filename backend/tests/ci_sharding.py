"""Opt-in CI partitioning; each runner owns independent PostgreSQL/Neo4j.

Historical timings affect scheduling only. Every collected item belongs to
exactly one shard; new modules receive a fallback weight, never an exclusion.
"""

import json
import re
from hashlib import sha256
from math import isfinite
from pathlib import Path

import pytest


def parse_shard(value):
    if type(value) is not str or re.fullmatch(r"[1-9][0-9]*/[1-9][0-9]*", value) is None:
        raise ValueError("Shard must be INDEX/TOTAL using positive integers")
    index, total = map(int, value.split("/"))
    if index > total:
        raise ValueError("Shard index must not exceed total")
    return index - 1, total


def partition_nodeids(nodeids, weights, total):
    if type(total) is not int or total <= 0:
        raise ValueError("A positive shard count is required")
    if len(nodeids) != len(set(nodeids)):
        raise ValueError("Duplicate collected node IDs")
    if type(weights) is not dict or any(
        type(k) is not str or type(v) not in (int, float) or not isfinite(v) or v < 0
        for k, v in weights.items()
    ):
        raise ValueError("Module weights must be finite nonnegative numbers")
    modules = {nodeid.split("::", 1)[0] for nodeid in nodeids}
    if not modules or total > len(modules):
        raise ValueError("Each shard must contain at least one module")
    load, assignment = [0.0] * total, {}
    for module in sorted(modules, key=lambda name: (-weights.get(name, 1.0), name)):
        shard = min(range(total), key=lambda index: (load[index], index))
        assignment[module] = shard
        load[shard] += max(weights.get(module, 1.0), 0.001)
    groups = [[] for _ in range(total)]
    for nodeid in nodeids:
        groups[assignment[nodeid.split("::", 1)[0]]].append(nodeid)
    return groups


def pytest_addoption(parser):
    parser.addoption("--ci-shard", default=None, help="CI shard INDEX/TOTAL; omit for all tests")


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    value = config.getoption("--ci-shard")
    if value is None:
        return
    try:
        index, total = parse_shard(value)
        weights = json.loads(Path(__file__).with_name("ci_module_timings.json").read_text())[
            "weights"
        ]
        nodeids = [item.nodeid for item in items]
        groups = partition_nodeids(nodeids, weights, total)
    except (ValueError, KeyError, OSError) as error:
        raise pytest.UsageError(f"Invalid CI partition: {error}") from error
    selected = set(groups[index])
    kept, dropped = [], []
    for item in items:
        (kept if item.nodeid in selected else dropped).append(item)
    config.hook.pytest_deselected(items=dropped)
    items[:] = kept
    digest = sha256("\n".join(sorted(nodeids)).encode()).hexdigest()
    reporter = config.pluginmanager.getplugin("terminalreporter")
    if reporter:
        reporter.write_line(
            f"CI shard {value}: collected={len(nodeids)} selected={len(kept)} "
            f"collection_sha256={digest}"
        )
