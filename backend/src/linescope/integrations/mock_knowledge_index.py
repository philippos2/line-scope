"""Explicit demo replacement for Embed/Qdrant, not a vector search implementation.

Immutable per-document manifests persist across CLI/API processes. Returned text
is used only for candidate ranking; VerifiedKnowledgeContent restores authority.
The directory is server-owned, never selected by an Agent argument.
"""

import json
import os
from pathlib import Path
from uuid import UUID


class MockKnowledgeIndex:
    source = "MOCK_LEXICAL_INDEX"

    def __init__(self, root):
        self.root = Path(root)

    def upsert(self, document_id, hits):
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / (str(UUID(str(document_id))) + ".json")
        with path.open("x", encoding="utf-8") as output:
            json.dump(hits, output, ensure_ascii=False)
            output.flush()
            os.fsync(output.fileno())

    def search(self, query, equipment_id, limit):
        # A small demo index only. Bound candidate files and bytes; never silently
        # report a truncated scan as a complete vector search.
        if not self.root.is_dir():
            raise ValueError("Demo index is not initialized")
        paths = sorted(self.root.glob("*.json"))
        if len(paths) > 100:
            raise ValueError("Demo index limit exceeded")
        ranked = []
        for path in paths:
            if path.is_symlink() or path.stat().st_size > 2_000_000:
                raise ValueError("Invalid demo index")
            hits = json.loads(path.read_text(encoding="utf-8"))
            for hit in hits:
                if equipment_id is not None and hit.get("equipment_id") != str(equipment_id):
                    continue
                score = sum(word.casefold() in hit["text"].casefold() for word in query.split())
                if score:
                    ranked.append((score, hit["chunk_id"], hit))
        return [hit for _, _, hit in sorted(ranked, key=lambda x: (-x[0], x[1]))[:limit]]
