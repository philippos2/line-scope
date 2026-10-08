from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

ROLES = {"floor", "maintenance", "production", "manager"}


@dataclass(frozen=True)
class Settings:
    dsn: str = field(default="postgresql://localhost:5432/linescope", repr=False)
    users: dict = field(default_factory=dict, repr=False)
    connect_seconds: int = 5
    statement_ms: int = 5000
    lock_ms: int = 5000

    def __post_init__(self):
        if not isinstance(self.dsn, str) or not self.dsn.strip():
            raise ValueError("LINESCOPE_DSN must be nonempty")
        for name in ("connect_seconds", "statement_ms", "lock_ms"):
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
                    json.loads(raw) if name == "users" else raw if name == "dsn" else int(raw)
                )
        return cls(**values)
