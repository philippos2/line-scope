"""Server-owned identity; never part of an LLM tool argument schema."""

from dataclasses import dataclass
from uuid import UUID

from .settings import ROLES


@dataclass(frozen=True)
class ExecutionContext:
    authenticated_user_id: str
    role: str
    request_id: UUID

    def __post_init__(self):
        if (
            not isinstance(self.authenticated_user_id, str)
            or not self.authenticated_user_id.strip()
            or self.role not in ROLES
            or not isinstance(self.request_id, UUID)
        ):
            raise ValueError("Invalid trusted execution context")
