"""Fixed Core SELECT for authoritative KnowledgeDocument revalidation."""

from sqlalchemy import BigInteger, Boolean, Text, column, func, select, table, true, tuple_
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.dialects.postgresql.psycopg import dialect

_documents = table(
    "knowledge_document",
    column("document_id", PGUUID()),
    column("document_code", Text()),
    column("document_version", BigInteger()),
    column("title", Text()),
    column("source_uri", Text()),
    column("access_class", Text()),
    column("active", Boolean()),
    column("content_hash", Text()),
)


def matching_document_rows(connection, references):
    matches = (
        select(_documents)
        .where(
            _documents.c.active.is_(True),
            _documents.c.access_class == "FACTORY_INTERNAL",
            tuple_(
                _documents.c.document_id,
                _documents.c.document_version,
                _documents.c.content_hash,
            ).in_(references),
        )
        .subquery("matches")
    )
    observation = select(true().label("present")).subquery("observation")
    statement = (
        select(matches, func.statement_timestamp().label("_observed_at"))
        .select_from(observation.outerjoin(matches, true()))
        .order_by(matches.c.document_id)
    )
    # Expand tuple placeholders for the psycopg bridge, never literal values.
    compiled = statement.compile(dialect=dialect(), compile_kwargs={"render_postcompile": True})
    return connection.execute(str(compiled), compiled.params).fetchall()
