"""Fixed Core SELECT for authoritative KnowledgeDocument revalidation."""

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Text,
    column,
    func,
    select,
    table,
    true,
    tuple_,
)
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
    column("updated_at", DateTime(timezone=True)),
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


def _execute(connection, statement):
    compiled = statement.compile(dialect=dialect(), compile_kwargs={"render_postcompile": True})
    return connection.execute(str(compiled), compiled.params)


def activate_document(connection, document):
    """Serialize activation after index upsert; never replace a newer version."""
    from hashlib import sha256

    from sqlalchemy import insert, update

    code = document["document_code"]
    lock = int.from_bytes(sha256(("knowledge:" + code).encode()).digest()[:8], signed=True)
    _execute(connection, select(func.pg_advisory_xact_lock(lock)))
    newest = _execute(
        connection,
        select(func.max(_documents.c.document_version).label("latest_version")).where(
            _documents.c.document_code == code
        ),
    ).fetchone()
    if (
        newest["latest_version"] is not None
        and newest["latest_version"] >= document["document_version"]
    ):
        raise ValueError("Document version must increase")
    _execute(
        connection,
        update(_documents)
        .where(_documents.c.document_code == code)
        .values(active=False, updated_at=func.clock_timestamp()),
    )
    _execute(connection, insert(_documents).values(**document, active=True))
