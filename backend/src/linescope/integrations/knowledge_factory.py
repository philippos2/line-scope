"""Compose mutually exclusive real-vector and explicitly opted-in mock adapters."""

from pathlib import Path

from .knowledge_files import ManagedKnowledgeFiles
from .knowledge_vector import JsonEndpoint, OllamaEmbedding, QdrantKnowledgeIndex
from .mock_knowledge_index import MockKnowledgeIndex


def knowledge_adapters(settings):
    if settings.knowledge_root:
        root = Path(settings.knowledge_root)
        index = QdrantKnowledgeIndex(
            JsonEndpoint(settings.qdrant_url, key=settings.qdrant_api_key),
            OllamaEmbedding(
                JsonEndpoint(settings.llm_base_url),
                model=settings.embedding_model,
                digest=settings.embedding_digest,
                dimensions=settings.embedding_dimensions,
            ),
            collection=settings.qdrant_collection,
        )
    elif settings.knowledge_mock_root:
        root = Path(settings.knowledge_mock_root)
        index = MockKnowledgeIndex(root / "mock-index")
    else:
        return None
    return ManagedKnowledgeFiles(root / "sources", max_bytes=1_000_000), index
