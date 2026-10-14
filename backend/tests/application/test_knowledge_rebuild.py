from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from integrations import test_knowledge_vector as vector_test
from persistence.test_knowledge_schema import DOCUMENT, execute
from sqlalchemy import update

from linescope.application.knowledge_flow import KnowledgeIngestion
from linescope.application.knowledge_rebuild import KnowledgeRebuild, KnowledgeRebuildError
from linescope.integrations.knowledge_factory import knowledge_adapters
from linescope.integrations.knowledge_files import KnowledgeFileError
from linescope.integrations.knowledge_vector import KnowledgeDependencyError, QdrantKnowledgeIndex
from linescope.interfaces.api import create_app

vector_world = vector_test.live
world_db = vector_test.world_db


@pytest.fixture
def rebuilding(vector_world):
    settings, db, index = vector_world
    files, _ = knowledge_adapters(settings)
    alias = "live_" + uuid4().hex
    service = KnowledgeRebuild(db, files, index)
    try:
        yield settings, db, index, files, alias, service
    finally:
        if alias in index.aliases():
            index.endpoint.request(
                "POST",
                "/collections/aliases",
                {"actions": [{"delete_alias": {"alias_name": alias}}]},
            )
        collections = index.endpoint.request("GET", "/collections")["result"]["collections"]
        for item in collections:
            if item["name"].startswith(alias + "_gen_"):
                index.endpoint.request("DELETE", "/collections/" + item["name"])


def query(settings, db, alias):
    configured = replace(
        settings, qdrant_collection=alias, qdrant_api_key="disposable-vector-read-key"
    )
    with TestClient(create_app(configured, db)) as client:
        response = client.post(
            "/agent",
            headers={"Authorization": "Bearer reader"},
            json={"message": "文書検索：保全手順"},
        )
    assert response.status_code == 200
    return response.json()["data"]


def test_rebuild_publishes_and_preserves_equipment_filter(rebuilding):
    settings, db, index, files, alias, service = rebuilding
    equipment = uuid4()
    document = KnowledgeIngestion(db, files, index).ingest(
        code="EQ", version=1, title="設備資料", body="保全手順".encode(), equipment_id=equipment
    )
    report = service.rebuild(alias=alias)
    assert report["status"] == "PUBLISHED" and report["document_count"] == 2
    assert report["chunk_count"] == 2 and report["legacy_equipment_hints_unknown"] == []
    assert len(query(settings, db, alias)["items"]) == 2
    copied = QdrantKnowledgeIndex(index.endpoint, index.embedding, collection=alias)
    hits = copied.search("保全", equipment, 5)
    assert len(hits) == 1 and hits[0]["document_id"] == document["document_id"]


def test_source_failure_keeps_previous_generation(rebuilding):
    _, _, index, files, alias, service = rebuilding
    previous = service.rebuild(alias=alias)["generation"]
    next(files.root.glob("*.txt")).write_bytes(b"forged")
    with pytest.raises(KnowledgeFileError):
        service.rebuild(alias=alias)
    assert index.aliases()[alias] == previous


def test_version_change_during_build_requires_new_validation(rebuilding, monkeypatch):
    settings, db, index, files, alias, service = rebuilding
    previous = service.rebuild(alias=alias)["generation"]
    original = QdrantKnowledgeIndex.verify

    def changing(candidate, expected):
        original(candidate, expected)
        KnowledgeIngestion(db, files, index).ingest(
            code="MANUAL", version=2, title="新版", body="新版保全手順".encode()
        )

    with monkeypatch.context() as patch:
        patch.setattr(QdrantKnowledgeIndex, "verify", changing)
        with pytest.raises(KnowledgeRebuildError, match="Active documents changed"):
            service.rebuild(alias=alias)
    assert index.aliases()[alias] == previous
    latest = service.rebuild(alias=alias)
    assert latest["generation"] != previous
    assert query(settings, db, alias)["items"][0]["citation"]["document_version"] == 2


def test_unknown_alias_response_does_not_delete_or_auto_retry(rebuilding, monkeypatch):
    _, _, index, _, alias, service = rebuilding
    previous = service.rebuild(alias=alias)["generation"]
    original = index.endpoint.request
    publications = []

    def lose_response(method, path, payload=None):
        result = original(method, path, payload)
        if method == "POST" and path == "/collections/aliases":
            publications.append(payload)
            raise KnowledgeDependencyError()
        return result

    with monkeypatch.context() as patch:
        patch.setattr(index.endpoint, "request", lose_response)
        with pytest.raises(KnowledgeDependencyError):
            service.rebuild(alias=alias)
    assert len(publications) == 1
    current = index.aliases()[alias]
    assert current != previous
    assert original("GET", "/collections/" + current)["result"]
    assert original("GET", "/collections/" + previous)["result"]


def test_ingestion_waits_until_alias_publication_finishes(rebuilding, monkeypatch):
    settings, db, index, files, alias, service = rebuilding
    service.rebuild(alias=alias)
    live_index = QdrantKnowledgeIndex(index.endpoint, index.embedding, collection=alias)
    entered, release, upserted = Event(), Event(), Event()
    publish, upsert = QdrantKnowledgeIndex.publish, live_index.upsert

    def gated(candidate, name):
        entered.set()
        assert release.wait(5)
        return publish(candidate, name)

    def observed(*args):
        upserted.set()
        return upsert(*args)

    monkeypatch.setattr(QdrantKnowledgeIndex, "publish", gated)
    monkeypatch.setattr(live_index, "upsert", observed)
    with ThreadPoolExecutor(max_workers=2) as executor:
        rebuild = executor.submit(service.rebuild, alias=alias)
        assert entered.wait(5)
        incoming = executor.submit(
            KnowledgeIngestion(db, files, live_index).ingest,
            code="MANUAL",
            version=2,
            title="新版",
            body="新版保全手順".encode(),
        )
        try:
            assert not upserted.wait(0.2)
        finally:
            release.set()
        assert rebuild.result(timeout=10)["status"] == "PUBLISHED"
        incoming.result(timeout=10)
    assert query(settings, db, alias)["items"][0]["citation"]["document_version"] == 2


def test_empty_active_snapshot_can_publish_empty_generation(rebuilding):
    settings, db, _, _, alias, service = rebuilding
    with db.transaction() as connection:
        execute(connection, update(DOCUMENT).values(active=False))
    report = service.rebuild(alias=alias)
    assert report["document_count"] == report["chunk_count"] == 0
    assert query(settings, db, alias)["items"] == []


def test_changed_provenance_is_not_used_as_an_equipment_hint(rebuilding):
    _, _, index, files, alias, service = rebuilding
    previous = service.rebuild(alias=alias)["generation"]
    next(files.root.glob("*.meta.json")).write_bytes(b"{}")
    with pytest.raises(KnowledgeFileError):
        service.rebuild(alias=alias)
    assert index.aliases()[alias] == previous


def test_candidate_payload_mismatch_prevents_publication(rebuilding, monkeypatch):
    _, _, index, _, alias, service = rebuilding
    previous = service.rebuild(alias=alias)["generation"]
    original = index.endpoint.request

    def forged(method, path, payload=None):
        result = original(method, path, payload)
        if method == "POST" and path.endswith("/points"):
            result["result"][0]["payload"]["content_hash"] = "b" * 64
        return result

    with monkeypatch.context() as patch:
        patch.setattr(index.endpoint, "request", forged)
        with pytest.raises(KnowledgeDependencyError):
            service.rebuild(alias=alias)
    assert index.aliases()[alias] == previous


def test_legacy_source_is_rebuilt_without_inventing_equipment_association(rebuilding):
    settings, db, _, files, alias, service = rebuilding
    next(files.root.glob("*.txt")).rename(files.root / "legacy.txt")
    with db.transaction() as connection:
        execute(connection, update(DOCUMENT).values(source_uri="legacy.txt"))
    report = service.rebuild(alias=alias)
    assert len(report["legacy_equipment_hints_unknown"]) == 1
    assert query(settings, db, alias)["items"][0]["citation"]["source_uri"] == "legacy.txt"
