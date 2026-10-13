import hashlib
import os

import pytest

from linescope.integrations.knowledge_files import KnowledgeFileError, ManagedKnowledgeFiles


def digest(body):
    return hashlib.sha256(body).hexdigest()


@pytest.mark.parametrize("filename", ["manual.txt", "手順/manual.txt"])
def test_verified_raw_bytes_at_size_boundary(tmp_path, filename):
    body = "保全\r\n手順".encode()
    path = tmp_path / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    files = ManagedKnowledgeFiles(tmp_path, max_bytes=len(body))
    assert files.read(filename, digest(body)) == body


@pytest.mark.parametrize("source_uri", ["../secret.txt", "/secret.txt", "https://host/secret"])
def test_unmanaged_identifiers_are_rejected(tmp_path, source_uri):
    with pytest.raises(KnowledgeFileError) as caught:
        ManagedKnowledgeFiles(tmp_path, max_bytes=1024).read(source_uri, digest(b"secret"))
    assert source_uri not in str(caught.value)


@pytest.mark.parametrize("directory_link", [False, True])
def test_symlink_file_or_directory_cannot_escape_root(tmp_path, directory_link):
    root = tmp_path / "managed"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "source.txt").write_bytes(b"secret")
    if directory_link:
        (root / "link").symlink_to(outside, target_is_directory=True)
        filename = "link/source.txt"
    else:
        (root / "link.txt").symlink_to(outside / "source.txt")
        filename = "link.txt"
    with pytest.raises(KnowledgeFileError):
        ManagedKnowledgeFiles(root, max_bytes=1024).read(filename, digest(b"secret"))


def test_fifo_is_rejected_without_waiting_for_writer(tmp_path):
    os.mkfifo(tmp_path / "pipe")
    with pytest.raises(KnowledgeFileError):
        ManagedKnowledgeFiles(tmp_path, max_bytes=1024).read("pipe", digest(b""))


def test_oversized_source_is_rejected(tmp_path):
    (tmp_path / "manual.txt").write_bytes(b"12345")
    with pytest.raises(KnowledgeFileError):
        ManagedKnowledgeFiles(tmp_path, max_bytes=4).read("manual.txt", digest(b"12345"))


def test_modified_bytes_cannot_pass_original_hash(tmp_path):
    (tmp_path / "manual.txt").write_bytes(b"modified private content")
    with pytest.raises(KnowledgeFileError) as caught:
        ManagedKnowledgeFiles(tmp_path, max_bytes=1024).read("manual.txt", digest(b"original"))
    assert str(caught.value) == "Verified knowledge source is unavailable"


def test_missing_file_does_not_expose_filesystem_path(tmp_path):
    with pytest.raises(KnowledgeFileError) as caught:
        ManagedKnowledgeFiles(tmp_path, max_bytes=1024).read("private.txt", digest(b""))
    assert str(tmp_path) not in str(caught.value) and caught.value.__cause__ is None
