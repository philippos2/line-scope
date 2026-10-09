"""Trusted Agent request parsing and ephemeral clarification context.

This module does not classify intent, authorize Prepare, or call an LLM.
Persistent proposal replay must precede context lookup in the orchestrator.
"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from threading import Lock
from time import monotonic
from uuid import uuid4

from .canonical import canonical_hash, normalize_timestamp, normalize_uuid, strict_json
from .execution import ExecutionContext
from .proposals import ProposalError


def _authenticated(context):
    if not isinstance(context, ExecutionContext):
        raise ProposalError("AUTHENTICATION_REQUIRED", "Trusted execution context is required")


@dataclass(frozen=True)
class AgentInput:
    message: str
    context_id: str | None
    explicit_as_of: str | None
    replace_update_request_id: str | None
    retry_key: str

    @property
    def input_hash(self):
        return canonical_hash(
            {
                "message": self.message,
                "explicit_as_of": self.explicit_as_of,
                "context_id": self.context_id,
                "replace_update_request_id": self.replace_update_request_id,
            }
        )

    @classmethod
    def parse(cls, context, body, *, received_at, idempotency_key=None):
        _authenticated(context)
        try:
            data = strict_json(body)
            if type(data) is not dict or set(data) - {
                "message",
                "context_id",
                "as_of",
                "replace_update_request_id",
            }:
                raise ValueError("Invalid Agent fields")
            message = data.get("message")
            if type(message) is not str or not message.strip():
                raise ValueError("Message is required")
            # Preserve the original message, including whitespace, for retry identity.
            canonical_hash(message)
            context_id = normalize_uuid(data["context_id"]) if "context_id" in data else None
            replacement = (
                normalize_uuid(data["replace_update_request_id"])
                if "replace_update_request_id" in data
                else None
            )
            observed = normalize_timestamp(received_at)
            as_of = normalize_timestamp(data["as_of"]) if "as_of" in data else None
            if as_of is not None and datetime.fromisoformat(as_of) > datetime.fromisoformat(
                observed
            ):
                raise ValueError("Future analysis time is not permitted")
            key = normalize_uuid(idempotency_key) if idempotency_key is not None else str(uuid4())
            return cls(message, context_id, as_of, replacement, key)
        except (ValueError, TypeError) as error:
            raise ProposalError("INVALID_ARGUMENT", "Invalid Agent request") from error


class ConversationStore:
    """One-process, server-owned clarification data; never an authority source."""

    def __init__(self, *, ttl_seconds=1800, clock=monotonic):
        if type(ttl_seconds) not in (int, float) or not isfinite(ttl_seconds) or ttl_seconds <= 0:
            raise ValueError("Context TTL must be positive and finite")
        self.ttl_seconds, self.clock = ttl_seconds, clock
        self._entries = {}
        self._lock = Lock()

    def create(self, context, data):
        _authenticated(context)
        copied = deepcopy(data)
        with self._lock:
            now = self.clock()
            self._entries = {
                key: value
                for key, value in self._entries.items()
                if now < value[2] + self.ttl_seconds
            }
            identity = str(uuid4())
            self._entries[identity] = (context.authenticated_user_id, copied, now)
            return identity

    def _lookup(self, context, identity, now):
        _authenticated(context)
        try:
            identity = normalize_uuid(identity)
        except ValueError as error:
            raise ProposalError("INVALID_ARGUMENT", "Invalid context ID") from error
        entry = self._entries.get(identity)
        if entry is None:
            raise ProposalError("CONTEXT_EXPIRED", "Conversation context is unavailable")
        if entry[0] != context.authenticated_user_id:
            raise ProposalError(
                "AUTHORIZATION_DENIED", "Conversation context belongs to another user"
            )
        if now >= entry[2] + self.ttl_seconds:
            del self._entries[identity]
            raise ProposalError("CONTEXT_EXPIRED", "Conversation context is unavailable")
        return identity, entry

    def get(self, context, identity):
        with self._lock:
            _, entry = self._lookup(context, identity, self.clock())
            # Reading does not extend the TTL; only a server-owned update does.
            return deepcopy(entry[1])

    def update(self, context, identity, data):
        _authenticated(context)
        copied = deepcopy(data)
        with self._lock:
            now = self.clock()
            identity, entry = self._lookup(context, identity, now)
            self._entries[identity] = (entry[0], copied, now)
