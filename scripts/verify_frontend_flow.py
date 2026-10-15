"""専用Composeと実Chromiumで、認証→比較→Graph→Evidence→接続解除を検証する。"""

import argparse
import json
import os
import re
import secrets
import socket
import subprocess
import tempfile
from pathlib import Path

from verify_knowledge_flow import ingest
from verify_minimal_flow import DemoFixture, verify


class FrontendFixture(DemoFixture):
    def __init__(self, directory, docker_group=None, *, vector=False):
        super().__init__(directory, docker_group, requester_role="manager")
        self.vector = vector

    def docker(self, *arguments):
        overlay = (
            ("-f", str(self.repository / "compose.rag.yaml")) if self.vector else ()
        )
        super().docker(
            "-f", str(self.repository / "compose.frontend.yaml"), *overlay, *arguments
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-group")
    parser.add_argument("--embedding-model")
    parser.add_argument("--embedding-digest")
    args = parser.parse_args()
    vector = args.embedding_model is not None
    if bool(args.embedding_model) != bool(args.embedding_digest):
        parser.error("Specify both embedding model and digest")
    if vector and (
        re.fullmatch(r"[A-Za-z0-9_.:/-]{1,200}", args.embedding_model) is None
        or re.fullmatch(r"[0-9a-f]{64}", args.embedding_digest) is None
    ):
        parser.error("Explicit model and SHA-256 digest are required")
    docker = ["docker"]
    if args.docker_group:
        import shlex

        def command(parts):
            return ["sg", args.docker_group, "-c", shlex.join(parts)]
    else:

        def command(parts):
            return parts

    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="linescope-frontend-") as directory:
        fixture = FrontendFixture(directory, args.docker_group, vector=vector)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        with fixture.credentials_file.open("a") as output:
            output.write(f"LINESCOPE_FRONTEND_PORT={port}\n")
            if vector:
                output.write(f"LINESCOPE_QDRANT_WRITE_KEY={secrets.token_hex(32)}\n")
                output.write(f"LINESCOPE_QDRANT_READ_KEY={secrets.token_hex(32)}\n")
                output.write(f"LINESCOPE_EMBEDDING_MODEL={args.embedding_model}\n")
                output.write(f"LINESCOPE_EMBEDDING_DIGEST={args.embedding_digest}\n")
                output.write("LINESCOPE_EMBEDDING_DIMENSIONS=768\n")
            else:
                output.write("LINESCOPE_KNOWLEDGE_MOCK_ROOT=/workspace/knowledge\n")
        image = "linescope-browser-check-" + secrets.token_hex(8)
        container = image + "-run"
        secret = Path(directory) / "browser.env"
        descriptor = os.open(secret, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w") as output:
            output.write(
                f"LINESCOPE_BROWSER_TOKEN={fixture.owner}\n"
                f"LINESCOPE_BROWSER_APPROVER_TOKEN={fixture.approver}\n"
                f"LINESCOPE_BROWSER_URL=http://127.0.0.1:{port}\n"
                f"LINESCOPE_BROWSER_VECTOR={str(vector).lower()}\n"
            )
        try:
            verify(fixture)
            ingest(
                fixture,
                1,
                'M-204 保全手順。停止後に点検する。<img src="/never-fetch" onerror="window.documentCommandExecuted=true">',
            )
            fixture.docker("--profile", "frontend", "up", "--build", "-d", "frontend")
            subprocess.run(
                command(
                    docker
                    + [
                        "build",
                        "--target",
                        "browser-check",
                        "-t",
                        image,
                        str(root / "frontend"),
                    ]
                ),
                check=True,
            )
            subprocess.run(
                command(
                    docker
                    + [
                        "run",
                        "--name",
                        container,
                        "--network",
                        "host",
                        "--env-file",
                        str(secret),
                        image,
                        "node",
                        "scripts/verify-browser.mjs",
                    ]
                ),
                check=True,
            )
            for name in ("1440", "390"):
                subprocess.run(
                    command(
                        docker
                        + [
                            "cp",
                            container + ":/tmp/frontend-" + name + ".png",
                            "/tmp/linescope-frontend-" + name + ".png",
                        ]
                    ),
                    check=True,
                )
            print(
                json.dumps(
                    {
                        "result": "PASS",
                        "scope": "Fixed frontend demo, not full UI acceptance",
                    }
                )
            )
        finally:
            subprocess.run(
                command(docker + ["rm", "-f", container]),
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            fixture.docker(
                "--profile", "frontend", "down", "--volumes", "--remove-orphans"
            )
            subprocess.run(
                command(docker + ["image", "rm", image]),
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )


if __name__ == "__main__":
    main()
