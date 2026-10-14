import json
import os
from contextlib import contextmanager
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from linescope.application.knowledge_flow import KnowledgeIngestion
from linescope.integrations.knowledge_factory import knowledge_adapters
from linescope.integrations.knowledge_vector import (
    JsonEndpoint,
    KnowledgeDependencyError,
    OllamaEmbedding,
    QdrantKnowledgeIndex,
)
from linescope.interfaces.api import create_app

DIGEST = "a" * 64


class EmbeddingEndpoint:
    def __init__(self):
        self.calls = []
        self.rows = [[1, 0, 0]]
        self.digest = DIGEST

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if path == "/api/tags":
            return {"models": [{"name": "trial:latest", "digest": self.digest}]}
        return {"embeddings": self.rows}


def embedding(endpoint):
    return OllamaEmbedding(endpoint, model="trial:latest", digest=DIGEST, dimensions=3)


def test_embedding_contract_checks_digest_and_disables_truncation():
    endpoint = EmbeddingEndpoint()
    assert embedding(endpoint).encode(["設備保全手順"]) == [[1, 0, 0]]
    assert endpoint.calls[1][2] == {
        "model": "trial:latest",
        "input": ["設備保全手順"],
        "truncate": False,
    }
    assert endpoint.calls[0][1] == endpoint.calls[-1][1] == "/api/tags"


@pytest.mark.parametrize("rows", [[[1, 0]], [[float("nan"), 0, 1]], []])
def test_invalid_embedding_shape_fails_closed(rows):
    endpoint = EmbeddingEndpoint()
    endpoint.rows = rows
    with pytest.raises(KnowledgeDependencyError):
        embedding(endpoint).encode(["保全"])


def test_model_replaced_during_generation_is_rejected():
    endpoint = EmbeddingEndpoint()
    original = endpoint.request

    def changing(method, path, payload=None):
        result = original(method, path, payload)
        if path == "/api/embed":
            endpoint.digest = "b" * 64
        return result

    endpoint.request = changing
    with pytest.raises(KnowledgeDependencyError):
        embedding(endpoint).encode(["保全"])


@contextmanager
def server(handler):
    instance = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{instance.server_port}"
    finally:
        instance.shutdown()
        thread.join(timeout=5)
        instance.server_close()


class QuietHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_json(self, value, status=200):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_http_failure_and_response_size_do_not_expose_provider_data():
    class Handler(QuietHandler):
        def do_GET(self):
            self.send_json(
                {"private": "credential must not leak"}, 503 if self.path == "/fail" else 200
            )

    with server(Handler) as url:
        for path in ("/fail", "/large"):
            with pytest.raises(KnowledgeDependencyError) as caught:
                JsonEndpoint(url, max_bytes=5).request("GET", path)
            assert str(caught.value) == "Knowledge dependency is unavailable"


def test_incompatible_collection_cannot_mix_model_versions():
    class Endpoint:
        def request(self, *args):
            return {
                "result": {
                    "config": {
                        "params": {"vectors": {"old_model": {"size": 3, "distance": "Cosine"}}}
                    }
                }
            }

    index = QdrantKnowledgeIndex(Endpoint(), embedding(EmbeddingEndpoint()), collection="trial")
    with pytest.raises(KnowledgeDependencyError):
        index.search("保全", None, 5)


@pytest.fixture
def live(world_db, tmp_path):
    # Real Qdrant with deterministic embedding HTTP fixture; no model download in CI.
    url = os.getenv("LINESCOPE_TEST_QDRANT_URL")
    if not url:
        pytest.skip("Set LINESCOPE_TEST_QDRANT_URL")

    class Handler(QuietHandler):
        def do_GET(self):
            self.send_json({"models": [{"name": "trial:latest", "digest": DIGEST}]})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_json({"embeddings": [[1, 0, 0] for _ in body["input"]]})

    with server(Handler) as ollama:
        settings = replace(
            world_db.settings,
            knowledge_root=str(tmp_path),
            qdrant_url=url,
            qdrant_api_key="disposable-vector-write-key",
            llm_base_url=ollama,
            embedding_model="trial:latest",
            embedding_digest=DIGEST,
            embedding_dimensions=3,
            qdrant_collection="test_" + uuid4().hex,
            users={"reader": {"user_id": "reader", "role": "floor"}},
        )
        files, index = knowledge_adapters(settings)
        ingest = KnowledgeIngestion(world_db, files, index)
        ingest.ingest(code="MANUAL", version=1, title="保全手順", body="M-204の保全手順".encode())
        try:
            yield settings, world_db, index
        finally:
            index.endpoint.request("DELETE", index.path)


@pytest.fixture
def world_db(db):
    db.migrate()
    return db


def test_real_qdrant_ingestion_to_api_citation(live):
    settings, db, index = live
    points = index.endpoint.request(
        "POST", index.path + "/points/scroll", {"limit": 5, "with_payload": True}
    )
    payload = points["result"]["points"][0]["payload"]
    assert "text" not in payload
    assert payload["embedding_version"] == index.embedding.version
    read_settings = replace(settings, qdrant_api_key="disposable-vector-read-key")
    with TestClient(create_app(read_settings, db)) as client:
        result = client.post(
            "/agent",
            headers={"Authorization": "Bearer reader"},
            json={"message": "文書検索：M-204"},
        )
    assert result.status_code == 200
    data = result.json()["data"]
    assert data["search_source"] == "QDRANT" and data["demo_only"] is False
    assert data["items"][0]["text"] == "M-204の保全手順"
    assert result.json()["evidence"]["citations"] == [data["items"][0]["citation"]]


def test_real_qdrant_read_key_cannot_mutate(live):
    settings, _, index = live
    readonly = JsonEndpoint(settings.qdrant_url, key="disposable-vector-read-key")
    with pytest.raises(KnowledgeDependencyError) as caught:
        readonly.request("DELETE", index.path)
    assert caught.value.status == 403
    assert index.endpoint.request("GET", index.path)["result"]


def test_real_configuration_rejects_mock_fallback_and_hides_key():
    from linescope.settings import Settings

    with pytest.raises(ValueError, match="Complete real"):
        Settings(knowledge_root="/managed")
    with pytest.raises(ValueError, match="mutually exclusive"):
        Settings(knowledge_root="/managed", knowledge_mock_root="/mock")
    settings = Settings(
        knowledge_root="/managed",
        qdrant_url="http://qdrant:6333",
        qdrant_api_key="private-key",
        embedding_model="trial:latest",
        embedding_digest=DIGEST,
    )
    assert "private-key" not in repr(settings)
