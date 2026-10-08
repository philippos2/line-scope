"""Authenticated, process-local continuation tokens for keyset pagination."""

import base64
import hashlib
import hmac
import json
import secrets
from uuid import UUID


class CursorCodec:
    def __init__(self):
        self._secret = secrets.token_bytes(32)

    @staticmethod
    def binding(context, tool, filters):
        payload = {
            "user": context.authenticated_user_id,
            "role": context.role,
            "tool": tool,
            "filter": filters,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def encode(self, binding, after):
        payload = json.dumps([1, binding, str(after)], separators=(",", ":")).encode()
        body = base64.urlsafe_b64encode(payload).decode().rstrip("=")
        signature = hmac.new(self._secret, body.encode(), hashlib.sha256).hexdigest()
        return body + "." + signature

    def decode(self, token, binding):
        if not isinstance(token, str) or not 1 <= len(token) <= 2048:
            raise ValueError("Invalid cursor")
        try:
            body, signature = token.split(".")
            expected = hmac.new(self._secret, body.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError("Invalid cursor")
            payload = json.loads(
                base64.b64decode(
                    body + "=" * (-len(body) % 4),
                    altchars=b"-_",
                    validate=True,
                )
            )
            if not isinstance(payload, list) or len(payload) != 3:
                raise ValueError("Invalid cursor")
            if type(payload[0]) is not int or payload[0] != 1 or payload[1] != binding:
                raise ValueError("Invalid cursor")
            return UUID(payload[2])
        except (ValueError, TypeError, UnicodeError, AttributeError) as error:
            raise ValueError("Invalid cursor") from error
