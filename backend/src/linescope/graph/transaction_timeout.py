"""Translate an internal deadline budget into a positive Neo4j millisecond timeout.

No transaction ownership, retry or driver dependency. Normal leadership has no
remaining budget and retains the configured adapter timeout.
"""

from math import isfinite


class GraphTransactionBudgetExpired(TimeoutError):
    """No positive millisecond remains; never send Neo4j's unlimited zero timeout."""


def neo4j_transaction_timeout(leadership, configured_seconds):
    if (
        type(configured_seconds) not in (int, float)
        or not isfinite(configured_seconds)
        or configured_seconds <= 0
    ):
        raise ValueError("Neo4j transaction timeout must be positive and finite")
    remaining = getattr(leadership, "remaining", None)
    seconds = configured_seconds
    if remaining is not None:
        budget = remaining()
        if type(budget) not in (int, float) or not isfinite(budget) or budget <= 0:
            raise GraphTransactionBudgetExpired("Invalid or expired Graph transaction budget")
        seconds = min(seconds, budget)
    # Bolt represents this timeout in milliseconds. Round down so it cannot
    # extend the remaining budget; zero would disable the server timeout.
    milliseconds = int(seconds * 1000)
    if milliseconds < 1:
        raise GraphTransactionBudgetExpired("No positive Graph transaction budget remains")
    return milliseconds / 1000
