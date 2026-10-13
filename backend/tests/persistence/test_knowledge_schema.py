"""KnowledgeDocument metadata invariants on real disposable PostgreSQL."""

from hashlib import sha256
from uuid import uuid4

import psycopg
import pytest
from sqlalchemy import column, insert, select, table, update
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.dialects.postgresql.psycopg import dialect

DOCUMENT = table(
    "knowledge_document",
    column("document_id", PGUUID()),
    column("document_code"),
    column("document_version"),
    column("title"),
    column("source_uri"),
    column("access_class"),
    column("active"),
    column("content_hash"),
    column("created_at"),
    column("updated_at"),
)


@pytest.fixture
def store(db):
    db.migrate()
    return db


def values(**overrides):
    return {
        "document_id": uuid4(),
        "document_code": "MANUAL-M204",
        "document_version": 1,
        "title": "設備保全手順",
        "source_uri": None,
        "access_class": "FACTORY_INTERNAL",
        "active": True,
        "content_hash": sha256("正本本文".encode()).hexdigest(),
        **overrides,
    }


def execute(connection, statement):
    compiled = statement.compile(dialect=dialect())
    return connection.execute(str(compiled), compiled.params)


def test_document_metadata_round_trip_and_timestamp_defaults(store):
    document = values(document_code="'; DROP TABLE knowledge_document; --")
    with store.transaction() as connection:
        row = execute(
            connection, insert(DOCUMENT).values(**document).returning(DOCUMENT)
        ).fetchone()
        assert {key: row[key] for key in document} == document
        assert row["created_at"].tzinfo is not None and row["updated_at"].tzinfo is not None
        assert execute(connection, select(DOCUMENT)).fetchall() == [row]


@pytest.mark.parametrize("version", [0, -1])
def test_nonpositive_document_version_is_rejected(store, version):
    with pytest.raises(psycopg.errors.CheckViolation), store.transaction() as connection:
        execute(connection, insert(DOCUMENT).values(**values(document_version=version)))


@pytest.mark.parametrize(
    "field", ["document_code", "title", "access_class", "content_hash", "active"]
)
def test_required_metadata_is_not_nullable(store, field):
    with pytest.raises(psycopg.errors.NotNullViolation), store.transaction() as connection:
        execute(connection, insert(DOCUMENT).values(**values(**{field: None})))


def test_unknown_access_class_is_rejected(store):
    with pytest.raises(psycopg.errors.CheckViolation), store.transaction() as connection:
        execute(connection, insert(DOCUMENT).values(**values(access_class="PUBLIC")))


@pytest.mark.parametrize("content_hash", ["f" * 63, "g" * 64])
def test_hash_length_and_alphabet_are_enforced(store, content_hash):
    with pytest.raises(psycopg.errors.CheckViolation), store.transaction() as connection:
        execute(connection, insert(DOCUMENT).values(**values(content_hash=content_hash)))


def test_document_code_and_version_are_unique_even_when_inactive(store):
    with store.transaction() as connection:
        execute(connection, insert(DOCUMENT).values(**values(active=False)))
    with pytest.raises(psycopg.errors.UniqueViolation), store.transaction() as connection:
        execute(connection, insert(DOCUMENT).values(**values(active=False)))


def test_active_version_is_unique_and_failed_switch_rolls_back(store):
    first, second = values(), values(document_version=2, active=False)
    with store.transaction() as connection:
        execute(connection, insert(DOCUMENT).values(**first))
        execute(connection, insert(DOCUMENT).values(**second))
    with pytest.raises(psycopg.errors.UniqueViolation), store.transaction() as connection:
        execute(
            connection,
            update(DOCUMENT)
            .where(DOCUMENT.c.document_id == second["document_id"])
            .values(active=True),
        )
    with store.transaction() as connection:
        assert (
            execute(
                connection, select(DOCUMENT.c.document_id).where(DOCUMENT.c.active.is_(True))
            ).fetchone()["document_id"]
            == first["document_id"]
        )
        execute(
            connection,
            update(DOCUMENT)
            .where(DOCUMENT.c.document_id == first["document_id"])
            .values(active=False),
        )
        execute(
            connection,
            update(DOCUMENT)
            .where(DOCUMENT.c.document_id == second["document_id"])
            .values(active=True),
        )
    with store.transaction() as connection:
        assert (
            execute(
                connection, select(DOCUMENT.c.document_id).where(DOCUMENT.c.active.is_(True))
            ).fetchone()["document_id"]
            == second["document_id"]
        )
