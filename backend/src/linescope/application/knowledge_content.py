"""Restore index hits from verified sources, then recheck authority.

This service is not yet a published Tool. The search adapter supplies candidate
IDs, never authoritative text, title, source_uri or access decisions. The
metadata guard owns PostgreSQL authorization; the file adapter owns filesystem
I/O. Retrieval/generation must invoke this boundary immediately before using
evidence; it does not promise authorization remains unchanged after return.
"""

from uuid import UUID

from pydantic import BaseModel, Field, StrictInt, StrictStr, ValidationError

from ..domain.knowledge_chunks import CHUNKING_VERSION, source_chunks
from ..execution import ExecutionContext
from ..integrations.knowledge_files import KnowledgeFileError
from .knowledge_metadata import MAX_REFERENCES
from .reads import ToolError


class _Hit(BaseModel):
    # Ignore index text/metadata beyond identifiers; never copy it into evidence.
    document_id: UUID
    document_version: StrictInt = Field(gt=0, le=2**63 - 1)
    content_hash: StrictStr = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    chunk_id: UUID
    chunking_version: StrictStr

    def reference(self):
        return self.model_dump(include={"document_id", "document_version", "content_hash"})


class VerifiedKnowledgeContent:
    def __init__(self, metadata_guard, files):
        self.metadata_guard, self.files = metadata_guard, files

    def restore(self, context, hits):
        if not isinstance(context, ExecutionContext):
            raise ToolError("AUTHENTICATION_REQUIRED", "Trusted execution context is required")
        if type(hits) is not list or len(hits) > MAX_REFERENCES:
            raise ToolError("INVALID_ARGUMENT", "Invalid knowledge hits")
        try:
            candidates = [_Hit.model_validate(hit) for hit in hits]
        except ValidationError:
            raise ToolError("INVALID_ARGUMENT", "Invalid knowledge hits") from None
        references = [candidate.reference() for candidate in candidates]
        observation = self.metadata_guard.recheck(context, references)
        documents = {document["document_id"]: document for document in observation.documents}
        restored, cache, seen = [], {}, set()
        for candidate in candidates:
            document = documents.get(candidate.document_id)
            if (
                document is None
                or document["document_version"] != candidate.document_version
                or document["content_hash"] != candidate.content_hash
                or candidate.chunking_version != CHUNKING_VERSION
            ):
                continue
            if candidate.document_id not in cache:
                try:
                    body = self.files.read(document["source_uri"], document["content_hash"])
                    cache[candidate.document_id] = {
                        chunk.chunk_id: chunk
                        for chunk in source_chunks(
                            candidate.document_id, candidate.document_version, body
                        )
                    }
                except (KnowledgeFileError, UnicodeError):
                    # Fail closed; never fall back to text stored in Qdrant.
                    raise ToolError(
                        "DEPENDENCY_UNAVAILABLE", "Verified knowledge source is unavailable"
                    ) from None
            chunk = cache[candidate.document_id].get(candidate.chunk_id)
            if chunk is None or chunk.chunk_id in seen:
                continue
            seen.add(chunk.chunk_id)
            restored.append(
                {
                    "text": chunk.text,
                    "citation": {
                        "document_id": str(candidate.document_id),
                        "document_version": candidate.document_version,
                        "content_hash": document["content_hash"],
                        "title": document["title"],
                        "source_uri": document["source_uri"],
                        "chunk_id": str(chunk.chunk_id),
                        "section": chunk.section,
                        "chunking_version": CHUNKING_VERSION,
                    },
                }
            )
        final = self.metadata_guard.recheck(context, references)
        active = {
            (str(document["document_id"]), document["document_version"], document["content_hash"])
            for document in final.documents
        }
        return {
            "items": [
                item
                for item in restored
                if (
                    item["citation"]["document_id"],
                    item["citation"]["document_version"],
                    item["citation"]["content_hash"],
                )
                in active
            ],
            "observed_at": final.observed_at.isoformat(),
        }
