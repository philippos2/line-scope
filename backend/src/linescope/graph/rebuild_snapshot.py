"""Internal Rebuild source snapshot; no generation creation or publication.

Caller owns leadership and an exclusive mutation transaction. No connection,
commit, lock acquisition, Outbox drain or synchronization-state change occurs.
"""

from dataclasses import dataclass
from datetime import datetime

from ..domain.canonical import canonical_hash
from ..persistence.core_graph_snapshot import graph_snapshot_rows
from .graph_locks import require_exclusive_graph_mutation_lock
from .projection_payload import build_projection_payload


@dataclass(frozen=True)
class RebuildSnapshot:
    observed_at: datetime
    nodes: tuple[dict, ...]
    aggregates: tuple[dict, ...]

    @property
    def snapshot_hash(self):
        # Observation time is metadata, not source state. Delivery IDs and
        # generation are absent; aggregate state uses the normal worker schema.
        return canonical_hash(
            {
                "schema_version": 1,
                "nodes": list(self.nodes),
                "aggregates": list(self.aggregates),
            }
        )


def read_rebuild_snapshot(connection):
    require_exclusive_graph_mutation_lock(connection)
    rows = graph_snapshot_rows(connection)
    nodes = tuple(row["data"] for row in rows if row["category"] == "NODE")
    aggregates = tuple(
        build_projection_payload(row["kind"], row["data"])
        for row in rows
        if row["category"] == "AGGREGATE"
    )
    return RebuildSnapshot(rows[0]["observed_at"], nodes, aggregates)
