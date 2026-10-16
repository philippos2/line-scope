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
        self.live_llm = False

    def request(self, path, **kwargs):
        if self.live_llm and path == "/agent":
            kwargs.setdefault("timeout_seconds", 90)
        return super().request(path, **kwargs)

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
    parser.add_argument("--llm-model", help="導入済みモデルで設備候補検索も確認する")
    parser.add_argument(
        "--economic-only",
        action="store_true",
        help="正式経済入力の業務経路だけをブラウザ確認する（実LLM必須）",
    )
    parser.add_argument(
        "--capacity-only",
        action="store_true",
        help="正式能力入力の登録・訂正・参照を実ブラウザ確認する（実LLM必須）",
    )
    parser.add_argument(
        "--safety-only",
        action="store_true",
        help="正式安全入力の登録・訂正・参照を実ブラウザ確認する（実LLM必須）",
    )
    parser.add_argument(
        "--maintenance-only",
        action="store_true",
        help="正式対応計画・故障履歴を実ブラウザ確認する（実LLM必須）",
    )
    parser.add_argument(
        "--comparison-only",
        action="store_true",
        help="正式入力の統合比較を実モデル・実ブラウザで確認する",
    )
    parser.add_argument("--embedding-model")
    parser.add_argument("--embedding-digest")
    args = parser.parse_args()
    if (
        args.llm_model
        and re.fullmatch(r"[A-Za-z0-9_.:/-]{1,200}", args.llm_model) is None
    ):
        parser.error("Invalid model name")
    if (
        sum(
            (
                args.economic_only,
                args.capacity_only,
                args.safety_only,
                args.maintenance_only,
                args.comparison_only,
            )
        )
        > 1
    ):
        parser.error("Choose one focused workflow")
    if args.comparison_only and not args.llm_model:
        parser.error("--comparison-only requires an installed --llm-model")
    if args.maintenance_only and not args.llm_model:
        parser.error("--maintenance-only requires an installed --llm-model")
    if args.safety_only and not args.llm_model:
        parser.error("--safety-only requires an installed --llm-model")
    if args.capacity_only and not args.llm_model:
        parser.error("--capacity-only requires an installed --llm-model")
    if args.economic_only and not args.llm_model:
        parser.error("--economic-only requires an installed --llm-model")
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
        fixture.live_llm = bool(args.llm_model)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        with fixture.credentials_file.open("a") as output:
            output.write(f"LINESCOPE_FRONTEND_PORT={port}\n")
            if args.llm_model:
                output.write(f"LINESCOPE_LLM_MODEL={args.llm_model}\n")
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
                f"LINESCOPE_BROWSER_DISCOVERY={str(bool(args.llm_model)).lower()}\n"
            )
        try:
            if (
                args.economic_only
                or args.capacity_only
                or args.safety_only
                or args.maintenance_only
                or args.comparison_only
            ):
                fixture.docker(
                    "up", "--build", "-d", "--wait", "--wait-timeout", "120", "api"
                )
                fixture.docker(
                    "run", "--rm", "graph-admin", "linescope", "seed-demo-graph"
                )
                if args.comparison_only:
                    fixture.docker(
                        "run", "--rm", "graph-admin", "linescope", "rebuild-graph"
                    )
            else:
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
                        "scripts/verify-comparison-browser.mjs"
                        if args.comparison_only
                        else "scripts/verify-maintenance-browser.mjs"
                        if args.maintenance_only
                        else "scripts/verify-safety-browser.mjs"
                        if args.safety_only
                        else "scripts/verify-capacity-browser.mjs"
                        if args.capacity_only
                        else "scripts/verify-economic-browser.mjs"
                        if args.economic_only
                        else "scripts/verify-browser.mjs",
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
                        "scope": "Registered comparison workflow"
                        if args.comparison_only
                        else "Registered maintenance workflow"
                        if args.maintenance_only
                        else "Registered safety workflow"
                        if args.safety_only
                        else "Registered capacity workflow"
                        if args.capacity_only
                        else "Registered economics only"
                        if args.economic_only
                        else "Fixed frontend demo, not full UI acceptance",
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
