"""Probe authenticated PostgreSQL readiness without printing credentials."""

import json
import sys
from urllib.request import Request, urlopen

from linescope.settings import Settings


def main():
    try:
        settings = Settings.env()
        token = next(iter(settings.users))
        request = Request(
            "http://127.0.0.1:8000/health/ready",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urlopen(request, timeout=3) as response:
            payload = json.load(response)
        return 0 if payload["data"]["postgresql"] == "available" else 1
    except (ValueError, StopIteration, OSError, KeyError, TypeError):
        return 1


if __name__ == "__main__":
    sys.exit(main())
