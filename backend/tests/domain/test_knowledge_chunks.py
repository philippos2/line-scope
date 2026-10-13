from uuid import UUID

import pytest

from linescope.domain.knowledge_chunks import source_chunks

DOCUMENT_ID = UUID("e439f81f-89cd-44bf-ac15-f149e199af72")


def test_unicode_character_boundary_and_deterministic_versioned_identity():
    text = "あ" * 999 + "\r\n続き"
    chunks = source_chunks(DOCUMENT_ID, 1, text.encode())
    assert [len(chunk.text) for chunk in chunks] == [1000, 3]
    assert "".join(chunk.text for chunk in chunks) == text
    assert [chunk.section for chunk in chunks] == ["characters:0-1000", "characters:1000-1003"]
    assert chunks == source_chunks(DOCUMENT_ID, 1, text.encode())
    assert chunks[0].chunk_id != source_chunks(DOCUMENT_ID, 2, text.encode())[0].chunk_id
    assert chunks[0].text not in repr(chunks[0])


def test_empty_and_invalid_utf8_have_no_fabricated_text():
    assert source_chunks(DOCUMENT_ID, 1, b"") == ()
    with pytest.raises(UnicodeDecodeError):
        source_chunks(DOCUMENT_ID, 1, b"\xff")
