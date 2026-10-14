"""Connected admin ingestion / authenticated retrieval with explicit mock search.

No LLM-generated interpretation or business mutation. Plain-text source and PG
metadata are real; Embed/Qdrant and prose generation remain replaceable internals.
"""

import os
from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID, uuid4

import psycopg
from pydantic import Field, StrictInt, StrictStr, ValidationError

from ..domain.knowledge_chunks import CHUNKING_VERSION, source_chunks
from ..execution import ExecutionContext
from ..persistence.core_knowledge import activate_document
from .reads import Arguments, ReadResult, ToolError


class RetrievalArguments(Arguments):
    query: StrictStr = Field(min_length=1, max_length=2000)
    equipment_id: UUID | None = None
    limit: StrictInt = Field(default=5, ge=1, le=20)


class KnowledgeIngestion:
    """Administrative CLI only; runtime/Agent never receives this capability."""

    def __init__(self, database, files, index):
        self.database, self.files, self.index = database, files, index

    def ingest(self, *, code, version, title, body, equipment_id=None):
        if (
            type(code) is not str
            or not code.strip()
            or len(code) > 200
            or type(title) is not str
            or not title.strip()
            or len(title) > 500
            or type(version) is not int
            or not 0 < version <= 2**63 - 1
            or type(body) is not bytes
            or not body
            or len(body) > self.files.max_bytes
        ):
            raise ValueError("Invalid knowledge document")
        document_id = uuid4()
        chunks = source_chunks(document_id, version, body)
        equipment = str(UUID(str(equipment_id))) if equipment_id is not None else None
        content_hash = sha256(body).hexdigest()
        source_uri = document_id.hex + ".txt"
        # Exclusive creation: existing managed content is never overwritten.
        self.files.root.mkdir(parents=True, exist_ok=True)
        with (self.files.root / source_uri).open("xb") as output:
            output.write(body)
            output.flush()
            os.fsync(output.fileno())
        self.files.read(source_uri, content_hash)
        self.index.upsert(
            document_id,
            [
                {
                    "document_id": str(document_id),
                    "document_version": version,
                    "content_hash": content_hash,
                    "chunk_id": str(chunk.chunk_id),
                    "chunking_version": CHUNKING_VERSION,
                    "text": chunk.text,
                    "equipment_id": equipment,
                }
                for chunk in chunks
            ],
        )
        # Failed activation can leave unreachable derived/filesystem artifacts;
        # the previous active metadata remains authoritative and available.
        with self.database.connect() as connection:
            connection.isolation_level = psycopg.IsolationLevel.READ_COMMITTED
            with connection.transaction():
                activate_document(
                    connection,
                    {
                        "document_id": document_id,
                        "document_code": code,
                        "document_version": version,
                        "title": title,
                        "source_uri": source_uri,
                        "access_class": "FACTORY_INTERNAL",
                        "content_hash": content_hash,
                    },
                )
        return {
            "document_id": str(document_id),
            "document_version": version,
            "source": self.index.source,
            "chunk_count": len(chunks),
        }


@dataclass(frozen=True)
class KnowledgeAgentResult:
    data: dict
    evidence: dict
    answer: str


class KnowledgeRetrieval:
    def __init__(self, content, index):
        self.content, self.index = content, index

    def retrieve(self, context, arguments):
        if not isinstance(context, ExecutionContext):
            raise ToolError("AUTHENTICATION_REQUIRED", "Trusted execution context is required")
        try:
            args = RetrievalArguments.model_validate(arguments)
        except ValidationError:
            raise ToolError("INVALID_ARGUMENT", "Invalid knowledge search arguments") from None
        if not args.query.strip():
            raise ToolError("INVALID_ARGUMENT", "A nonempty query is required")
        try:
            hits = self.index.search(args.query, args.equipment_id, 20)
        except Exception:
            raise ToolError("DEPENDENCY_UNAVAILABLE", "Knowledge index is unavailable") from None
        restored = self.content.restore(context, hits)
        items = restored["items"][: args.limit]
        return ReadResult(
            {
                "items": items,
                "search_source": self.index.source,
                "demo_only": True,
                "complete": False,
                "observed_at": restored["observed_at"],
            },
            {"citations": [item["citation"] for item in items]},
        )

    @staticmethod
    def matches(message):
        return message.startswith("文書検索:") or message.startswith("文書検索：")

    def run(self, context, incoming):
        if incoming.explicit_as_of or incoming.replace_update_request_id:
            raise ToolError("INVALID_ARGUMENT", "Knowledge search covers active documents only")
        result = self.retrieve(context, {"query": incoming.message[5:]})
        return KnowledgeAgentResult(
            result.data,
            result.evidence,
            f"正本で確認した文書抜粋を{len(result.data['items'])}件提示します。"
            "検索はモックです。抜粋は参考資料であり、安全性や費用の確定判断ではありません。"
            if result.data["items"]
            else "確認できる文書根拠がありません。モック検索のため、文書が存在しないとは断定できません。",
        )
