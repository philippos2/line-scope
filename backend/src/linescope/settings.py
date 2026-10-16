from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .domain.demo_scenarios import DEMO_SCENARIOS

ROLES = {"floor", "maintenance", "production", "manager"}


@dataclass(frozen=True)
class Settings:
    dsn: str = field(default="postgresql://localhost:5432/linescope", repr=False)
    users: dict = field(default_factory=dict, repr=False)
    connect_seconds: int = 5
    statement_ms: int = 5000
    lock_ms: int = 5000
    log_level: str = "INFO"
    llm_base_url: str = field(default="http://127.0.0.1:11434", repr=False)
    llm_model: str = field(default="", repr=False)
    llm_context_tokens: int = 16384
    read_dsn: str | None = field(default=None, repr=False)
    # Compatibility-only settings; no runtime business fixture provider is assembled.
    demo_decision_mock: bool = False
    demo_decision_scenario: str = "AUTO"
    knowledge_mock_root: str = field(default="", repr=False)
    knowledge_root: str = field(default="", repr=False)
    qdrant_url: str = field(default="", repr=False)
    qdrant_api_key: str = field(default="", repr=False)
    qdrant_collection: str = "knowledge_v1"
    embedding_model: str = ""
    embedding_digest: str = ""
    embedding_dimensions: int = 768

    neo4j_uri: str | None = field(default=None, repr=False)
    neo4j_user: str = field(default="", repr=False)
    neo4j_password: str = field(default="", repr=False)
    neo4j_database: str = "neo4j"
    graph_max_depth: int = 16
    graph_max_nodes: int = 1000
    graph_max_paths: int = 1000
    graph_timeout_ms: int = 5000

    def __post_init__(self):
        if type(self.knowledge_root) is not str or (
            self.knowledge_root and not self.knowledge_root.startswith("/")
        ):
            raise ValueError("Knowledge root must be an absolute server-owned path")
        if self.knowledge_root and self.knowledge_mock_root:
            raise ValueError("Real and mock knowledge modes are mutually exclusive")
        if type(self.qdrant_url) is not str or type(self.qdrant_api_key) is not str:
            raise ValueError("Invalid Qdrant configuration")
        if (
            type(self.qdrant_collection) is not str
            or re.fullmatch(r"[A-Za-z0-9_-]{1,100}", self.qdrant_collection) is None
        ):
            raise ValueError("Invalid configured collection")
        if type(self.embedding_dimensions) is not int or not 0 < self.embedding_dimensions <= 8192:
            raise ValueError("Invalid embedding dimension")
        if (
            self.knowledge_root
            or self.qdrant_url
            or self.embedding_model
            or self.embedding_digest
            or self.qdrant_api_key
        ):
            if not (
                self.knowledge_root
                and self.qdrant_url
                and self.qdrant_api_key
                and type(self.embedding_model) is str
                and self.embedding_model.strip() == self.embedding_model
                and self.embedding_model
                and type(self.embedding_digest) is str
                and re.fullmatch(r"[0-9a-f]{64}", self.embedding_digest)
            ):
                raise ValueError("Complete real knowledge configuration is required")
            vector_url = urlsplit(self.qdrant_url)
            if (
                vector_url.scheme not in {"http", "https"}
                or not vector_url.hostname
                or vector_url.username
                or vector_url.password
                or vector_url.query
                or vector_url.fragment
                or vector_url.path not in {"", "/"}
            ):
                raise ValueError("Invalid Qdrant URL")
            _ = vector_url.port

        if type(self.knowledge_mock_root) is not str or (
            self.knowledge_mock_root and not self.knowledge_mock_root.startswith("/")
        ):
            raise ValueError("Knowledge mock root must be an absolute server-owned path")
        if type(self.demo_decision_mock) is not bool:
            raise ValueError("Demo decision mode must be a server boolean")
        if (
            type(self.demo_decision_scenario) is not str
            or self.demo_decision_scenario not in {"AUTO", *DEMO_SCENARIOS}
            or (not self.demo_decision_mock and self.demo_decision_scenario != "AUTO")
        ):
            raise ValueError("Named scenarios require explicit demo mode and a fixed scenario")
        if type(self.llm_base_url) is not str or type(self.llm_model) is not str:
            raise ValueError("Invalid LLM configuration")
        url = urlsplit(self.llm_base_url)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path not in {"", "/"}
        ):
            raise ValueError("Invalid Ollama server URL")
        _ = url.port
        if self.llm_model != self.llm_model.strip():
            raise ValueError("Invalid model name")
        if type(self.log_level) is not str or self.log_level not in {
            "DEBUG",
            "INFO",
            "WARNING",
            "ERROR",
        }:
            raise ValueError("LINESCOPE_LOG_LEVEL must be DEBUG, INFO, WARNING or ERROR")
        if not isinstance(self.dsn, str) or not self.dsn.strip():
            raise ValueError("LINESCOPE_DSN must be nonempty")
        if self.read_dsn is not None and (
            type(self.read_dsn) is not str or not self.read_dsn.strip()
        ):
            raise ValueError("LINESCOPE_READ_DSN must be nonempty when configured")
        if (
            any(
                type(v) is not str
                for v in (self.neo4j_user, self.neo4j_password, self.neo4j_database)
            )
            or not self.neo4j_database.strip()
        ):
            raise ValueError("Invalid Neo4j configuration")
        if self.neo4j_uri is not None:
            if type(self.neo4j_uri) is not str:
                raise ValueError("Invalid Neo4j configuration")
            graph_url = urlsplit(self.neo4j_uri)
            if (
                graph_url.scheme not in {"bolt", "bolt+s", "neo4j", "neo4j+s"}
                or not graph_url.hostname
                or graph_url.username
                or graph_url.password
                or graph_url.query
                or graph_url.fragment
                or graph_url.path not in {"", "/"}
                or any(
                    type(v) is not str or not v.strip()
                    for v in (self.neo4j_user, self.neo4j_password, self.neo4j_database)
                )
            ):
                raise ValueError("Invalid Neo4j configuration")
            _ = graph_url.port
        elif self.neo4j_user or self.neo4j_password:
            raise ValueError("Neo4j credentials require a configured URI")
        for name in (
            "llm_context_tokens",
            "connect_seconds",
            "statement_ms",
            "lock_ms",
            "graph_max_depth",
            "graph_max_nodes",
            "graph_max_paths",
            "graph_timeout_ms",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if not isinstance(self.users, dict):
            raise ValueError("LINESCOPE_USERS must be a JSON object")
        roles_by_user = {}
        for token, user in self.users.items():
            if (
                not isinstance(token, str)
                or not token.strip()
                or not isinstance(user, dict)
                or set(user) != {"user_id", "role"}
                or not isinstance(user["user_id"], str)
                or not user["user_id"].strip()
                or user["role"] not in ROLES
            ):
                raise ValueError("Invalid trusted user configuration")
            old = roles_by_user.setdefault(user["user_id"], user["role"])
            if old != user["role"]:
                raise ValueError("Conflicting roles for same user")

    @classmethod
    def env(cls):
        values = {}
        for name in cls.__dataclass_fields__:
            raw = os.getenv("LINESCOPE_" + name.upper())
            if raw is not None:
                values[name] = (
                    json.loads(raw)
                    if name in {"users", "demo_decision_mock"}
                    else raw
                    if name
                    in {
                        "knowledge_mock_root",
                        "demo_decision_scenario",
                        "knowledge_root",
                        "qdrant_url",
                        "qdrant_api_key",
                        "qdrant_collection",
                        "embedding_model",
                        "embedding_digest",
                        "dsn",
                        "read_dsn",
                        "log_level",
                        "llm_base_url",
                        "llm_model",
                        "neo4j_uri",
                        "neo4j_user",
                        "neo4j_password",
                        "neo4j_database",
                    }
                    else int(raw)
                )
        return cls(**values)
