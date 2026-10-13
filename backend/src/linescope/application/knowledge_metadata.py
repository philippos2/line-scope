"""Internal RAG metadata boundary, not a Tool or content/citation verifier."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import psycopg
from pydantic import Field, StrictInt, StrictStr, ValidationError

from ..execution import ExecutionContext
from ..persistence.core_knowledge import matching_document_rows
from .reads import Arguments, ToolError

MAX_REFERENCES = 20  # v1 retrieval's maximum result count; not the test-review threshold.


class _Reference(Arguments):
    document_id: UUID
    document_version: StrictInt = Field(gt=0, le=2**63 - 1)
    content_hash: StrictStr = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class KnowledgeMetadataObservation:
    documents: tuple[dict, ...]
    observed_at: datetime


class KnowledgeMetadataGuard:
    def __init__(self, database):
        self.database = database.for_reads()

    def recheck(self, context, references):
        if not isinstance(context, ExecutionContext):
            raise ToolError("AUTHENTICATION_REQUIRED", "Trusted execution context is required")
        if type(references) is not list or len(references) > MAX_REFERENCES:
            raise ToolError("INVALID_ARGUMENT", "Invalid knowledge references")
        try:
            validated = [_Reference.model_validate(item) for item in references]
        except ValidationError as error:
            raise ToolError("INVALID_ARGUMENT", "Invalid knowledge references") from error
        keys = sorted(
            {(item.document_id, item.document_version, item.content_hash) for item in validated}
        )
        try:
            with self.database.connect() as connection:
                connection.isolation_level = psycopg.IsolationLevel.READ_COMMITTED
                connection.read_only = True
                with connection.transaction():
                    rows = matching_document_rows(connection, keys)
            return KnowledgeMetadataObservation(
                tuple(
                    {key: value for key, value in row.items() if key != "_observed_at"}
                    for row in rows
                    if row["document_id"] is not None
                ),
                rows[0]["_observed_at"],
            )
        except (psycopg.errors.LockNotAvailable, psycopg.errors.QueryCanceled) as error:
            raise ToolError("RESOURCE_BUSY", "Knowledge metadata read timed out") from error
        except psycopg.Error as error:
            # No alternate role/connection retry and no raw exception in the contract.
            raise ToolError(
                "DEPENDENCY_UNAVAILABLE", "Knowledge metadata is unavailable"
            ) from error
