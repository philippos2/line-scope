"""Bounded Ollama/Qdrant HTTP adapters; storage details stay below the use case.

Configured endpoints/collection/key are server-owned. No arbitrary provider URL,
filter, SQL, or vector-store write is accepted from Agent arguments. Model digest
and chunking algorithm define a named vector; incompatible collections fail shut.
"""

import http.client
import json
import math
import re
from hashlib import sha256
from time import monotonic
from urllib.parse import urlsplit

from ..domain.knowledge_chunks import CHUNKING_VERSION


class KnowledgeDependencyError(Exception):
    def __init__(self, status=None):
        super().__init__("Knowledge dependency is unavailable")
        self.status = status


class JsonEndpoint:
    def __init__(self, url, *, key="", timeout=30, max_bytes=8_000_000):
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Invalid knowledge endpoint")
        self.url, self.key, self.timeout, self.max_bytes = parsed, key, timeout, max_bytes
        _ = parsed.port

    def request(self, method, path, payload=None):
        deadline = monotonic() + self.timeout
        cls = (
            http.client.HTTPSConnection
            if self.url.scheme == "https"
            else http.client.HTTPConnection
        )
        connection = cls(self.url.hostname, self.url.port, timeout=self.timeout)
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["api-key"] = self.key
        body = json.dumps(payload, allow_nan=False).encode() if payload is not None else None
        if body is not None and len(body) > self.max_bytes:
            raise KnowledgeDependencyError()
        try:
            connection.request(method, path, body, headers)
            response = connection.getresponse()
            if response.status not in {200, 201}:
                raise KnowledgeDependencyError(response.status)
            content = bytearray()
            while True:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise KnowledgeDependencyError()
                if connection.sock is not None:
                    connection.sock.settimeout(remaining)
                part = response.read1(min(65536, self.max_bytes + 1 - len(content)))
                content.extend(part)
                if len(content) > self.max_bytes:
                    raise KnowledgeDependencyError()
                if not part:
                    break
            value = json.loads(content)
            if type(value) is not dict:
                raise KnowledgeDependencyError()
            return value
        except (OSError, http.client.HTTPException, ValueError):
            raise KnowledgeDependencyError() from None
        finally:
            connection.close()


class OllamaEmbedding:
    def __init__(self, endpoint, *, model, digest, dimensions):
        if not model or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError("Explicit embedding model/digest are required")
        if type(dimensions) is not int or not 0 < dimensions <= 8192:
            raise ValueError("Invalid embedding dimension")
        self.endpoint, self.model, self.digest, self.dimensions = (
            endpoint,
            model,
            digest,
            dimensions,
        )
        self.version = f"ollama:{model}@{digest}:raw:v1"

    def _verify_model(self):
        tags = self.endpoint.request("GET", "/api/tags")
        models = tags.get("models")
        if type(models) is not list or not any(
            type(item) is dict
            and item.get("name") == self.model
            and item.get("digest") == self.digest
            for item in models
        ):
            raise KnowledgeDependencyError()

    def encode(self, texts):
        self._verify_model()
        vectors = []
        for start in range(0, len(texts), 8):
            batch = texts[start : start + 8]
            result = self.endpoint.request(
                "POST",
                "/api/embed",
                {
                    "model": self.model,
                    "input": batch,
                    "truncate": False,
                },
            )
            rows = result.get("embeddings")
            if type(rows) is not list or len(rows) != len(batch):
                raise KnowledgeDependencyError()
            for row in rows:
                if (
                    type(row) is not list
                    or len(row) != self.dimensions
                    or any(
                        type(value) not in {int, float} or not math.isfinite(value) for value in row
                    )
                    or not any(value != 0 for value in row)
                ):
                    raise KnowledgeDependencyError()
            vectors.extend(rows)
        # A tag replaced during generation must not be committed as the old digest.
        self._verify_model()
        return vectors


class QdrantKnowledgeIndex:
    source = "QDRANT"
    demo_only = False

    def __init__(self, endpoint, embedding, *, collection):
        if re.fullmatch(r"[A-Za-z0-9_-]{1,100}", collection) is None:
            raise ValueError("Invalid configured collection")
        self.endpoint, self.embedding = endpoint, embedding
        self.path = "/collections/" + collection
        self.vector_name = (
            "embedding_" + sha256((embedding.version + ":" + CHUNKING_VERSION).encode()).hexdigest()
        )

    def _check(self):
        try:
            result = self.endpoint.request("GET", self.path)["result"]
            vectors = result["config"]["params"]["vectors"]
        except (KeyError, TypeError):
            raise KnowledgeDependencyError() from None
        expected = {self.vector_name}
        if (
            type(vectors) is not dict
            or set(vectors) != expected
            or type(vectors[self.vector_name]) is not dict
            or vectors[self.vector_name].get("size") != self.embedding.dimensions
            or vectors[self.vector_name].get("distance") != "Cosine"
        ):
            raise KnowledgeDependencyError()

    def upsert(self, document_id, hits):
        vectors = self.embedding.encode([hit["text"] for hit in hits])
        try:
            self._check()
        except KnowledgeDependencyError as error:
            if error.status != 404:
                raise
            try:
                self.endpoint.request(
                    "PUT",
                    self.path,
                    {
                        "vectors": {
                            self.vector_name: {
                                "size": self.embedding.dimensions,
                                "distance": "Cosine",
                            },
                        }
                    },
                )
            except KnowledgeDependencyError as creation:
                if creation.status not in {400, 409}:
                    raise
            self._check()
        for start in range(0, len(hits), 32):
            points = [
                {
                    "id": hit["chunk_id"],
                    "vector": {self.vector_name: vector},
                    "payload": {
                        **{key: value for key, value in hit.items() if key != "text"},
                        "access_class": "FACTORY_INTERNAL",
                        "embedding_version": self.embedding.version,
                    },
                }
                for hit, vector in zip(
                    hits[start : start + 32], vectors[start : start + 32], strict=True
                )
            ]
            result = self.endpoint.request(
                "PUT", self.path + "/points?wait=true", {"points": points}
            )
            operation = result.get("result")
            if type(operation) is not dict or operation.get("status") != "completed":
                raise KnowledgeDependencyError()

    def search(self, query, equipment_id, limit):
        self._check()
        vector = self.embedding.encode([query])[0]
        filters = [
            {"key": "access_class", "match": {"value": "FACTORY_INTERNAL"}},
            {"key": "embedding_version", "match": {"value": self.embedding.version}},
            {"key": "chunking_version", "match": {"value": CHUNKING_VERSION}},
        ]
        if equipment_id is not None:
            filters.append({"key": "equipment_id", "match": {"value": str(equipment_id)}})
        result = self.endpoint.request(
            "POST",
            self.path + "/points/query",
            {
                "query": vector,
                "using": self.vector_name,
                "filter": {"must": filters},
                "limit": limit,
                "with_payload": True,
                "with_vector": False,
            },
        )
        try:
            points = result["result"]["points"]
        except (KeyError, TypeError):
            raise KnowledgeDependencyError() from None
        if type(points) is not list or len(points) > limit:
            raise KnowledgeDependencyError()
        if any(
            type(point) is not dict or type(point.get("payload")) is not dict for point in points
        ):
            raise KnowledgeDependencyError()
        return [point["payload"] for point in points]
