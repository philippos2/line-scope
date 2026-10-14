"""Admin rebuild from PG and immutable sources, then fenced alias publication.

Staging never becomes authoritative. No auto retry on unknown publication and no
collection deletion: old and unsuccessful generations remain inspectable.
"""

import re
from uuid import uuid4

import psycopg

from ..domain.knowledge_chunks import CHUNKING_VERSION, source_chunks
from ..integrations.knowledge_hints import restore_hint
from ..integrations.knowledge_vector import QdrantKnowledgeIndex
from ..persistence.core_knowledge import (
    active_document_rows,
    knowledge_publication_lock,
    rebuild_leader_lock,
)


class KnowledgeRebuildError(Exception):
    pass


class KnowledgeRebuild:
    def __init__(self, database, files, index):
        self.database, self.files, self.index = database, files, index

    def _snapshot(self, connection):
        return [
            {key: value for key, value in row.items() if key != "updated_at"}
            for row in active_document_rows(connection)
        ]

    def rebuild(self, *, alias):
        if re.fullmatch(r"[A-Za-z0-9_-]{1,60}", alias) is None or not isinstance(
            self.index, QdrantKnowledgeIndex
        ):
            raise ValueError("Rebuild requires a configured vector index and valid alias")
        with self.database.connect() as leader:
            leader.isolation_level = psycopg.IsolationLevel.READ_COMMITTED
            rebuild_leader_lock(leader, alias)
            initial = self._snapshot(leader)
            if len(initial) > 1000:
                raise KnowledgeRebuildError("Source document limit exceeded")
            generation = alias + "_gen_" + uuid4().hex
            candidate = QdrantKnowledgeIndex(
                self.index.endpoint, self.index.embedding, collection=generation
            )
            self.index.embedding._verify_model()
            candidate.create()
            expected, unknown_hints = [], []
            for document in initial:
                body = self.files.read(document["source_uri"], document["content_hash"])
                equipment, legacy = restore_hint(self.files, document)
                if legacy:
                    unknown_hints.append(str(document["document_id"]))
                hits = [
                    {
                        "document_id": str(document["document_id"]),
                        "document_version": document["document_version"],
                        "content_hash": document["content_hash"],
                        "chunk_id": str(chunk.chunk_id),
                        "chunking_version": CHUNKING_VERSION,
                        "section": chunk.section,
                        "text": chunk.text,
                        "equipment_id": equipment,
                    }
                    for chunk in source_chunks(
                        document["document_id"], document["document_version"], body
                    )
                ]
                if len(expected) + len(hits) > 10000:
                    raise KnowledgeRebuildError("Source chunk limit exceeded")
                candidate.upsert(document["document_id"], hits)
                expected.extend(hits)
            candidate.verify(expected)
            # Initial build runs without publication exclusion. Final revalidation
            # and atomic Qdrant alias swap block new ingestion upsert/activation.
            with self.database.connect() as publication:
                publication.isolation_level = psycopg.IsolationLevel.READ_COMMITTED
                knowledge_publication_lock(publication)
                if self._snapshot(publication) != initial:
                    raise KnowledgeRebuildError("Active documents changed; rebuild again")
                previous = candidate.publish(alias)
                if self._snapshot(publication) != initial:
                    raise KnowledgeRebuildError("Publication outcome requires inspection")
            return {
                "alias": alias,
                "generation": generation,
                "previous_generation": previous,
                "document_count": len(initial),
                "chunk_count": len(expected),
                "legacy_equipment_hints_unknown": unknown_hints,
                "status": "PUBLISHED",
            }
