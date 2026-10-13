"""RAG reference validation and real PostgreSQL metadata authority."""

from dataclasses import replace
from uuid import uuid4

import psycopg
import pytest
from persistence.test_db_roles import roles as roles
from persistence.test_knowledge_schema import DOCUMENT, execute, values
from sqlalchemy import insert, update

from linescope.application.knowledge_metadata import KnowledgeMetadataGuard
from linescope.application.reads import ToolError
from linescope.execution import ExecutionContext
from linescope.persistence.database import Database
from linescope.persistence.db_roles import READ_ROLE, WRITE_ROLE


def context(role="manager"):
    return ExecutionContext("actor", role, uuid4())


def reference(document, **extra):
    return {
        key: document[key] for key in ("document_id", "document_version", "content_hash")
    } | extra


@pytest.fixture
def source(db):
    db.migrate()
    document = values(source_uri="manuals/m204-v1.md")
    with db.transaction() as connection:
        execute(connection, insert(DOCUMENT).values(**document))
    return db, document


@pytest.mark.parametrize("role,count", [("manager", 2), ("floor", 20)])
def test_authenticated_roles_get_authoritative_metadata_and_empty_observation(source, role, count):
    db, document = source
    guard = KnowledgeMetadataGuard(db)
    result = guard.recheck(context(role), [reference(document)] * count)
    assert len(result.documents) == 1
    assert result.documents[0]["title"] == document["title"]
    assert result.documents[0]["source_uri"] == document["source_uri"]
    assert result.documents[0]["access_class"] == "FACTORY_INTERNAL"
    assert result.observed_at.tzinfo is not None
    empty = guard.recheck(context(role), [])
    assert empty.documents == () and empty.observed_at.tzinfo is not None


@pytest.mark.parametrize("mismatch", ["version", "hash", "inactive", "missing"])
def test_stale_or_missing_index_reference_cannot_authorize_document(source, mismatch):
    db, document = source
    candidate = reference(document)
    if mismatch == "version":
        candidate["document_version"] = 2
    elif mismatch == "hash":
        candidate["content_hash"] = "0" * 64
    elif mismatch == "missing":
        candidate["document_id"] = uuid4()
    else:
        with db.transaction() as connection:
            execute(connection, update(DOCUMENT).values(active=False))
    result = KnowledgeMetadataGuard(db).recheck(context(), [candidate])
    assert result.documents == () and result.observed_at.tzinfo is not None


class NoDatabase:
    def for_reads(self):
        return self

    def connect(self):
        pytest.fail("Invalid input must not connect to PostgreSQL")


@pytest.mark.parametrize(
    "damage", ["id", "boolean_version", "zero_version", "hash", "authority", "size"]
)
def test_invalid_references_are_rejected_before_storage(damage):
    candidate = reference(values())
    if damage == "id":
        candidate["document_id"] = "' OR 1=1 --"
    elif damage == "boolean_version":
        candidate["document_version"] = True
    elif damage == "zero_version":
        candidate["document_version"] = 0
    elif damage == "hash":
        candidate["content_hash"] = "private-secret"
    elif damage == "authority":
        candidate["role"] = "manager"
    candidates = [candidate] * (21 if damage == "size" else 1)
    with pytest.raises(ToolError) as caught:
        KnowledgeMetadataGuard(NoDatabase()).recheck(context(), candidates)
    assert caught.value.code == "INVALID_ARGUMENT"
    assert "private-secret" not in str(caught.value)


def test_untrusted_context_cannot_connect_to_storage():
    with pytest.raises(ToolError) as caught:
        KnowledgeMetadataGuard(NoDatabase()).recheck({"role": "manager"}, [])
    assert caught.value.code == "AUTHENTICATION_REQUIRED"


def test_recheck_observes_revocation_after_earlier_match(source):
    db, document = source
    guard = KnowledgeMetadataGuard(db)
    assert guard.recheck(context(), [reference(document)]).documents
    with db.transaction() as connection:
        execute(connection, update(DOCUMENT).values(active=False))
    assert guard.recheck(context(), [reference(document)]).documents == ()


def test_storage_failure_is_sanitized_without_role_fallback():
    class BrokenDatabase(NoDatabase):
        def connect(self):
            raise psycopg.OperationalError("private-secret SQL database-host")

    with pytest.raises(ToolError) as caught:
        KnowledgeMetadataGuard(BrokenDatabase()).recheck(context(), [reference(values())])
    assert caught.value.code == "DEPENDENCY_UNAVAILABLE"
    assert "private-secret" not in str(caught.value)


def test_real_query_role_reads_metadata_but_cannot_mutate_it(roles):
    admin, stores, _ = roles
    document = values(source_uri="manuals/m204-v1.md")
    with admin.transaction() as connection:
        execute(connection, insert(DOCUMENT).values(**document))
    routed = Database(replace(stores[WRITE_ROLE].settings, read_dsn=stores[READ_ROLE].settings.dsn))
    assert KnowledgeMetadataGuard(routed).recheck(context(), [reference(document)]).documents
    with pytest.raises(psycopg.errors.InsufficientPrivilege), stores[READ_ROLE].transaction() as c:
        execute(c, update(DOCUMENT).values(active=False))
    with pytest.raises(psycopg.errors.InsufficientPrivilege), stores[WRITE_ROLE].transaction() as c:
        execute(c, insert(DOCUMENT).values(**values(document_code="NO-AUTHORITY")))
