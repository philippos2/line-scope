"""Developer-selected scenario inputs, never authoritative business facts."""

from .demo_comparison import fixture

SCENARIO_PATCHES = {
    "SAFETY_STOP": ("DEGRADED", {"hard_safety_stop": True}),
    "SUFFICIENT_CAPACITY": ("STOPPED", {"required_capacity": 60, "available_capacity": 80}),
    "MISSING_LOSS": ("STOPPED", {"product_loss_per_hour": {"P-100": 120000, "P-200": None}}),
    "MISSING_REPAIR_COST": ("STOPPED", {"repair_cost": None}),
    "NONADDITIVE_LOSS": ("STOPPED", {"independent_addition": False}),
}
DEMO_SCENARIOS = frozenset({"STOPPED", "DEGRADED", *SCENARIO_PATCHES})


def scenario_inputs(name):
    if name not in DEMO_SCENARIOS:
        raise ValueError("Unknown configured demo scenario")
    base, patch = SCENARIO_PATCHES.get(name, (name, {}))
    inputs = fixture(base)
    # Copy nested values so one request cannot alter subsequent fixture inputs.
    from copy import deepcopy

    inputs.update(deepcopy(patch))
    inputs["fixture_version"] += ":" + name
    return inputs
