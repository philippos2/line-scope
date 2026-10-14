"""専用Composeと実Chromiumで、認証→比較→Graph→Evidence→接続解除を検証する。"""

import argparse
import json
import os
import secrets
import socket
import subprocess
import tempfile
from pathlib import Path

from verify_minimal_flow import DemoFixture, verify


class FrontendFixture(DemoFixture):
    def docker(self, *arguments):
        super().docker("-f", str(self.repository / "compose.frontend.yaml"), *arguments)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-group")
    args = parser.parse_args()
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
        fixture = FrontendFixture(directory, args.docker_group)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        with fixture.credentials_file.open("a") as output:
            output.write(f"LINESCOPE_FRONTEND_PORT={port}\n")
        image = "linescope-browser-check-" + secrets.token_hex(8)
        container = image + "-run"
        secret = Path(directory) / "browser.env"
        descriptor = os.open(secret, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w") as output:
            output.write(
                f"LINESCOPE_BROWSER_TOKEN={fixture.owner}\nLINESCOPE_BROWSER_URL=http://127.0.0.1:{port}\n"
            )
        try:
            verify(fixture)
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
