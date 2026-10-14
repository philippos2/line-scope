"""Immutable ingestion provenance for optional equipment search hints.

The manifest digest is part of PG source_uri, binding auxiliary input to the
managed source. It never grants authority. Legacy sources without a manifest
have unknown equipment association, not a guessed one.
"""

import json
import re
from hashlib import sha256
from uuid import UUID

from .knowledge_files import KnowledgeFileError


def manifest(document_id, version, content_hash, equipment_id):
    body = json.dumps(
        {
            "document_id": str(document_id),
            "document_version": version,
            "content_hash": content_hash,
            "equipment_id": equipment_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    uri = document_id.hex + "_" + sha256(body).hexdigest() + ".txt"
    return uri, body


def restore_hint(files, document):
    uri = document["source_uri"]
    match = re.fullmatch(r"[0-9a-f]{32}_([0-9a-f]{64})\.txt", uri or "")
    if match is None:
        return None, True
    try:
        metadata = json.loads(files.read(uri + ".meta.json", match.group(1)))
        if (
            metadata["document_id"] != str(document["document_id"])
            or metadata["document_version"] != document["document_version"]
            or metadata["content_hash"] != document["content_hash"]
        ):
            raise KnowledgeFileError()
        equipment = metadata["equipment_id"]
        return str(UUID(equipment)) if equipment is not None else None, False
    except (KeyError, TypeError, ValueError):
        raise KnowledgeFileError() from None
