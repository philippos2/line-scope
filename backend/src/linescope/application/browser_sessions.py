"""Bounded process-local browser sessions; identity remains in server settings."""

from secrets import token_urlsafe
from threading import RLock
from time import monotonic

COOKIE = "linescope_session"


class BrowserSessions:
    def __init__(self, *, clock=monotonic, lifetime=8 * 60 * 60, capacity=256):
        self.clock, self.lifetime, self.capacity = clock, lifetime, capacity
        self._entries = {}
        self._lock = RLock()

    def _purge(self):
        now = self.clock()
        self._entries = {key: row for key, row in self._entries.items() if now < row[1]}

    def create(self, token, previous=None):
        with self._lock:
            self._purge()
            self._entries.pop(previous, None)
            if len(self._entries) >= self.capacity:
                return None
            session = token_urlsafe(32)
            self._entries[session] = (token, self.clock() + self.lifetime)
            return session

    def resolve(self, session):
        with self._lock:
            self._purge()
            row = self._entries.get(session)
            return row[0] if row else None

    def revoke(self, session):
        with self._lock:
            self._entries.pop(session, None)
