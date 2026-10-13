"""Bounded source-byte reads from a server-owned POSIX directory.

source_uri is a relative managed-file identifier, not a network URL. Open each
component relative to a directory descriptor without following symlinks; a
resolve/check/open sequence would leave a path replacement race. The caller
obtains the identifier and SHA-256 from authorized PostgreSQL metadata.
"""

import hashlib
import os
import re
import stat
from contextlib import ExitStack
from pathlib import Path


class KnowledgeFileError(Exception):
    def __init__(self):
        super().__init__("Verified knowledge source is unavailable")


class ManagedKnowledgeFiles:
    def __init__(self, root: Path, *, max_bytes: int):
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("A positive source byte limit is required")
        self.root = Path(root)
        self.max_bytes = max_bytes

    def read(self, source_uri, content_hash):
        if (
            type(source_uri) is not str
            or not source_uri
            or any(character in source_uri for character in ("\\", ":", "\x00", "?", "#", "%"))
            or any(part in {"", ".", ".."} for part in source_uri.split("/"))
            or type(content_hash) is not str
            or re.fullmatch(r"[0-9a-f]{64}", content_hash) is None
        ):
            raise KnowledgeFileError()
        parts = source_uri.split("/")
        try:
            with ExitStack() as stack:
                directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                stack.callback(os.close, directory)
                for part in parts[:-1]:
                    directory = os.open(
                        part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
                    )
                    stack.callback(os.close, directory)
                descriptor = os.open(
                    parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
                )
                stack.callback(os.close, descriptor)
                info = os.fstat(descriptor)
                if not stat.S_ISREG(info.st_mode) or info.st_size > self.max_bytes:
                    raise KnowledgeFileError()
                # The extra byte detects growth after fstat, without an unbounded read.
                with os.fdopen(os.dup(descriptor), "rb") as source:
                    body = source.read(self.max_bytes + 1)
                if len(body) > self.max_bytes or hashlib.sha256(body).hexdigest() != content_hash:
                    raise KnowledgeFileError()
                return body
        except OSError:
            # Never include the path, source bytes or raw filesystem exception.
            raise KnowledgeFileError() from None
