"""Create private local Docker credentials without replacing an existing file."""

import json
import os
import secrets
from pathlib import Path


def main():
    destination = Path(__file__).resolve().parents[1] / ".env"
    users = {
        secrets.token_hex(32): {"user_id": user, "role": role}
        for user, role in [
            ("floor1", "floor"),
            ("maintenance1", "maintenance"),
            ("production1", "production"),
            ("manager1", "manager"),
            ("manager2", "manager"),
        ]
    }
    content = (
        f"LINESCOPE_POSTGRES_PASSWORD={secrets.token_hex(32)}\n"
        f"LINESCOPE_USERS='{json.dumps(users, separators=(',', ':'))}'\n"
        "LINESCOPE_API_PORT=8000\n"
    )
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as output:
        output.write(content)
    print("Created private .env for local Docker use; credentials were not printed.")


if __name__ == "__main__":
    main()
