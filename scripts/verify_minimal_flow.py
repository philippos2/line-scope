"""最小シナリオを専用Compose環境でcurl実行し、終了時に環境を削除する。

実行: python3 scripts/verify_minimal_flow.py
Docker groupが必要な環境: --docker-group docker
通常の.envやvolumeは使わない。LLMは未使用、比較・費用等は明示的なモック。
"""

import argparse
import json
import os
import secrets
import shlex
import shutil
import socket
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path


class DemoFixture:
    def __init__(self, directory, docker_group=None):
        self.repository = Path(__file__).resolve().parents[1]
        self.project = "linescope-minimal-" + secrets.token_hex(8)
        self.docker_group = docker_group
        self.owner, self.approver = secrets.token_hex(32), secrets.token_hex(32)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        users = {
            self.owner: {"user_id": "demo_requester", "role": "maintenance"},
            self.approver: {"user_id": "demo_approver", "role": "manager"},
        }
        self.credentials_file = Path(directory) / "private.env"
        descriptor = os.open(
            self.credentials_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        with os.fdopen(descriptor, "w") as output:
            for name in ("POSTGRES", "QUERY", "RUNTIME", "PROJECTION", "NEO4J"):
                output.write(f"LINESCOPE_{name}_PASSWORD={secrets.token_hex(32)}\n")
            output.write(
                "LINESCOPE_USERS='" + json.dumps(users, separators=(",", ":")) + "'\n"
            )
            output.write(
                f"LINESCOPE_API_PORT={self.port}\nLINESCOPE_DEMO_DECISION_MOCK=true\n"
            )
        self.child_env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("LINESCOPE_")
        }

    def docker(self, *arguments):
        command = [
            "docker",
            "compose",
            "-p",
            self.project,
            "--env-file",
            str(self.credentials_file),
            "-f",
            str(self.repository / "compose.yaml"),
            *arguments,
        ]
        if self.docker_group:
            command = ["sg", self.docker_group, "-c", shlex.join(command)]
        subprocess.run(command, cwd=self.repository, env=self.child_env, check=True)

    def request(self, path, *, token=None, data=None, expected=200):
        command = [
            "curl",
            "--silent",
            "--show-error",
            "--max-time",
            "15",
            "--config",
            "-",
            "--write-out",
            "\n%{http_code}",
            f"http://127.0.0.1:{self.port}{path}",
        ]
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as payload:
            if data is not None:
                json.dump(data, payload, ensure_ascii=False)
                payload.flush()
                command += [
                    "--request",
                    "POST",
                    "--header",
                    "Content-Type: application/json",
                    "--data-binary",
                    "@" + payload.name,
                ]
            elif path.endswith("/execute"):
                command += ["--request", "POST"]
            # Token goes through stdin, not the process argument list or output.
            config = f'header = "Authorization: Bearer {token or self.owner}"\n'
            result = subprocess.run(
                command, input=config, text=True, capture_output=True, check=True
            )
        body, status = result.stdout.rsplit("\n", 1)
        require(int(status) == expected, f"HTTP {status}: expected {expected}")
        return json.loads(body)


@contextmanager
def disposable_fixture(docker_group=None):
    with tempfile.TemporaryDirectory(prefix="linescope-minimal-") as directory:
        fixture = DemoFixture(directory, docker_group)
        try:
            yield fixture
        finally:
            fixture.docker("down", "--volumes", "--remove-orphans")


def require(condition, message):
    # Verification must remain enabled when Python runs with -O.
    if not condition:
        raise RuntimeError(message)


def stage(name, **values):
    print(json.dumps({"stage": name, **values}, ensure_ascii=False), flush=True)


def verify(fixture):
    fixture.docker("up", "--build", "-d", "api")
    for _ in range(30):
        try:
            fixture.request("/health/ready")
            break
        except (subprocess.CalledProcessError, RuntimeError):
            time.sleep(1)
    else:
        raise RuntimeError("API did not become ready")
    fixture.docker("run", "--rm", "graph-admin", "linescope", "seed-demo-graph")
    fixture.docker("run", "--rm", "graph-admin", "linescope", "rebuild-graph")
    analysis = fixture.request(
        "/agent",
        data={"message": "M-204の異常について影響・修理・交換・代替を比較して"},
    )
    package = analysis["data"]["decision_package"]
    require(
        analysis["status"] == "partial" and analysis["data"]["demo_only"],
        "Demo boundary missing",
    )
    require(package["equipment"]["state_code"] == "STOPPED", "Unexpected initial state")
    require(package["comparison"]["source"] == "MOCK_FIXTURE", "Mock label missing")
    stage(
        "analysis",
        http=200,
        graph=package["impact"]["graph_sync_state"],
        current_state=package["equipment"]["state_code"],
        comparison_source="MOCK_FIXTURE",
        mock_repair_total=package["comparison"]["options"][0]["total_cost"],
    )
    prepared = fixture.request(
        "/agent", data={"message": package["next_actions"]["prepare_message"]}
    )["data"]
    require(
        prepared["status"] == "WAITING_APPROVAL", "Prepare did not wait for approval"
    )
    target = prepared["canonical_snapshot"]["targets"][0]
    endpoint = "/update-requests/" + prepared["update_request_id"] + "/execute"
    stage(
        "prepare",
        http=200,
        state=prepared["status"],
        before=target["before"]["state_code"],
        after=target["after"]["state_code"],
    )
    denied = fixture.request(endpoint, expected=409)
    stage("execute_before_approval", http=409, code=denied["errors"][0]["code"])
    fixture.request(
        "/approvals/" + prepared["approval_id"] + "/approve",
        token=fixture.approver,
        data={"snapshot_hash": prepared["snapshot_hash"]},
    )
    stage("approval", http=200, separate_fixture_actor=True)
    confirmed = fixture.request(endpoint)["data"]
    require(confirmed["status"] == "COMPLETED", "Execution did not complete")
    require(
        confirmed["current_snapshot"]["targets"][0]["snapshot"]["state_code"]
        == "UNDER_MAINTENANCE",
        "Current state disagrees with execution",
    )
    replay = fixture.request(endpoint)["data"]
    require(
        replay["execution_result"] == confirmed["execution_result"],
        "Replay changed result",
    )
    current = fixture.request(
        "/agent", data={"message": "M-204の修理と交換を比較して"}
    )["data"]["decision_package"]
    require(
        current["equipment"]["state_code"] == "UNDER_MAINTENANCE", "Reanalysis is stale"
    )
    stage(
        "confirmed",
        http=200,
        state=current["equipment"]["state_code"],
        version=current["equipment"]["version"],
        replay_preserves_result=True,
    )
    return {
        "result": "PASS",
        "real_http": True,
        "transport": "curl",
        "real_stores": ["PostgreSQL", "Neo4j"],
        "llm": "NOT_USED",
        "mock": ["economics", "capacity", "risk", "document_retrieval", "comparison"],
        "actors": "disposable authenticated requester and approver fixtures",
        "scope": "M0 fixed scenario, not Golden acceptance",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-group", help="必要な場合にsgで使うDocker group名")
    parser.add_argument(
        "--report", type=Path, help="結果JSONの新規保存先（既存ファイルは上書きしない）"
    )
    args = parser.parse_args()
    for tool in ("docker", "curl", *(("sg",) if args.docker_group else ())):
        if shutil.which(tool) is None:
            parser.error(f"必要なコマンドがありません: {tool}")
    if args.report and args.report.exists():
        parser.error("reportの保存先に既存ファイルがあります")
    with disposable_fixture(args.docker_group) as fixture:
        result = verify(fixture)
    if args.report:
        with args.report.open("x", encoding="utf-8") as output:
            json.dump(result, output, ensure_ascii=False, indent=2)
    stage("result", **result)


if __name__ == "__main__":
    main()
