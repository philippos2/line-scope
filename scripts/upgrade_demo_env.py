"""Append new role secrets without replacing existing credentials or demo data."""

import os
import secrets
import stat
from pathlib import Path


def upgrade(destination):
    with destination.open("r+", encoding="utf-8") as output:
        if stat.S_IMODE(os.fstat(output.fileno()).st_mode) != 0o600:
            raise ValueError("Private .env must have mode 0600")
        content = output.read()
        keys = {
            line.split("=", 1)[0].strip()
            for line in content.splitlines()
            if "=" in line and not line.lstrip().startswith("#")
        }
        missing = [
            key
            for key in ("LINESCOPE_QUERY_PASSWORD", "LINESCOPE_RUNTIME_PASSWORD")
            if key not in keys
        ]
        if missing:
            output.write(
                ("\n" if content and not content.endswith("\n") else "")
                + "".join(f"{key}={secrets.token_hex(32)}\n" for key in missing)
            )
            output.flush()
            os.fsync(output.fileno())
    return bool(missing)


def main():
    try:
        changed = upgrade(Path(__file__).resolve().parents[1] / ".env")
    except (OSError, ValueError):
        raise SystemExit(
            "Private .env upgrade failed; check existence and mode 0600."
        ) from None
    print(
        "Private .env updated."
        if changed
        else "Private .env already contains role settings."
    )


if __name__ == "__main__":
    main()
