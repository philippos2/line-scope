"""Bound native-type rejection updates on an already authorized, locked transaction.

Query-only column declarations mirror migration 003, never generate DDL, and
do not model the complete tables. The human service owns authorization, locks,
audit and commit/rollback. This is not a generic Core write executor.
"""

from sqlalchemy import DateTime, Text, column, func, table, update
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.dialects.postgresql.psycopg import dialect

_approval = table(
    "approval",
    column("approval_id", UUID()),
    column("approver_id", Text()),
    column("status", Text()),
    column("updated_at", DateTime(timezone=True)),
)
_request = table(
    "update_request",
    column("update_request_id", UUID()),
    column("status", Text()),
    column("updated_at", DateTime(timezone=True)),
)


def reject_proposal_state(connection, approval_id, request_id, actor_id):
    """Preserve the two UPDATEs and their order; never commit or acquire a connection."""
    approval = (
        update(_approval)
        .where(_approval.c.approval_id == approval_id)
        .values(status="REJECTED", approver_id=actor_id, updated_at=func.clock_timestamp())
    )
    request = (
        update(_request)
        .where(_request.c.update_request_id == request_id)
        .values(status="REJECTED", updated_at=func.clock_timestamp())
    )
    for statement in (approval, request):
        compiled = statement.compile(dialect=dialect())
        # Values are UUID/text only, natively adapted by psycopg. No JSON/custom
        # type processing or SQLAlchemy Engine/autobegin is introduced here.
        connection.execute(str(compiled), compiled.params)
