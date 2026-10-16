"""専用Composeで実Embedding/Qdrantによる取込み→curl引用応答を検証する。

事前にホストOllamaへ試験モデルをpullし、installed digestを引数で指定する。
認証情報・専用volumeを終了時に削除する。モデル品質受入とは区別する。
"""

import argparse
import json
import re
import secrets
import tempfile
import time

from verify_knowledge_flow import ingest
from verify_minimal_flow import DemoFixture, require, stage


class VectorFixture(DemoFixture):
    def docker(self, *arguments):
        super().docker("-f", str(self.repository / "compose.rag.yaml"), *arguments)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-group")
    parser.add_argument("--model", default="embeddinggemma:latest")
    parser.add_argument("--digest", required=True)
    parser.add_argument("--dimensions", type=int, default=768)
    args = parser.parse_args()
    if (
        re.fullmatch(r"[A-Za-z0-9_.:/-]{1,200}", args.model) is None
        or re.fullmatch(r"[0-9a-f]{64}", args.digest) is None
    ):
        parser.error("Explicit model and SHA-256 digest are required")
    with tempfile.TemporaryDirectory(prefix="linescope-vector-") as directory:
        fixture = VectorFixture(directory, args.docker_group)
        with fixture.credentials_file.open("a") as output:
            output.write(f"LINESCOPE_QDRANT_WRITE_KEY={secrets.token_hex(32)}\n")
            output.write(f"LINESCOPE_QDRANT_READ_KEY={secrets.token_hex(32)}\n")
            output.write(f"LINESCOPE_EMBEDDING_MODEL={args.model}\n")
            output.write(f"LINESCOPE_EMBEDDING_DIGEST={args.digest}\n")
            output.write(f"LINESCOPE_EMBEDDING_DIMENSIONS={args.dimensions}\n")
        try:
            fixture.docker("up", "--build", "-d", "api")
            for attempt in range(30):
                try:
                    fixture.request("/health/ready")
                    break
                except Exception:
                    if attempt == 29:
                        raise
                    time.sleep(1)
            ingest(fixture, 1, "M-204 保全手順。停止後に点検する。")
            response = fixture.request(
                "/agent", data={"message": "文書検索：M-204の保全手順"}
            )
            data = response["data"]
            require(
                data["search_source"] == "QDRANT" and not data["demo_only"],
                "Real vector path",
            )
            require(len(data["items"]) == 1, "Verified citation")
            require(
                response["evidence"]["citations"] == [data["items"][0]["citation"]],
                "Server citation",
            )
            stage(
                "real-vector",
                model=args.model,
                citation_version=1,
                real_embedding=True,
                real_qdrant=True,
            )
            ingest(fixture, 2, "M-204 更新済み保全手順。安全条件を別途確認する。")
            revised = fixture.request(
                "/agent", data={"message": "文書検索：M-204の保全手順"}
            )
            require(
                len(revised["data"]["items"]) == 1
                and revised["data"]["items"][0]["citation"]["document_version"] == 2,
                "Old version excluded",
            )
            fixture.docker(
                "run",
                "--rm",
                "--no-deps",
                "knowledge-admin",
                "linescope",
                "rebuild-knowledge",
                "--alias",
                "knowledge_live",
            )
            with fixture.credentials_file.open("a") as output:
                output.write("LINESCOPE_QDRANT_COLLECTION=knowledge_live\n")
            fixture.docker("up", "-d", "--no-deps", "--force-recreate", "api")
            for attempt in range(30):
                try:
                    rebuilt = fixture.request(
                        "/agent", data={"message": "文書検索：M-204の保全手順"}
                    )
                    break
                except Exception:
                    if attempt == 29:
                        raise
                    time.sleep(1)
            require(
                len(rebuilt["data"]["items"]) == 1
                and rebuilt["data"]["items"][0]["citation"]["document_version"] == 2,
                "Rebuilt active source",
            )
            ingest(fixture, 3, "M-204 第3版保全手順。再構築後の取込み確認。")
            fixture.docker(
                "run",
                "--rm",
                "--no-deps",
                "knowledge-admin",
                "linescope",
                "rebuild-knowledge",
                "--alias",
                "knowledge_live",
            )
            published = fixture.request(
                "/agent", data={"message": "文書検索：M-204の保全手順"}
            )
            require(
                len(published["data"]["items"]) == 1
                and published["data"]["items"][0]["citation"]["document_version"] == 3,
                "Second alias switch retains new ingestion",
            )
            stage("rebuild", active_version=3, publications=2, alias="knowledge_live")
            fixture.docker("run", "--rm", "graph-admin", "linescope", "seed-demo-graph")
            fixture.docker("run", "--rm", "graph-admin", "linescope", "rebuild-graph")
            for message in (
                (
                    "設備M-204の保全予定DECISION-PLANを開始2026-11-01T00:00:00Z、"
                    "終了2026-11-01T01:00:00Z、状態計画済みで登録して"
                ),
                (
                    "設備M-204の保全実績DECISION-RECORDを実施2026-10-14T00:00:00Z、"
                    "結果「軸を点検しました」、保全予定DECISION-PLANに紐づけて登録して"
                ),
            ):
                prepared = fixture.request("/agent", data={"message": message})["data"]
                fixture.request(
                    "/approvals/" + prepared["approval_id"] + "/approve",
                    token=fixture.approver,
                    data={"snapshot_hash": prepared["snapshot_hash"]},
                )
                fixture.request(
                    "/update-requests/" + prepared["update_request_id"] + "/execute"
                )
            compared = fixture.request(
                "/agent", data={"message": "M-204の修理と交換を比較して"}
            )
            comparison = compared["data"]["decision_package"]["comparison"]
            maintenance = compared["data"]["decision_package"]["maintenance"]
            require(
                maintenance["plans"]["items"][0]["plan_code"] == "DECISION-PLAN"
                and maintenance["records"]["items"][0]["record_code"]
                == "DECISION-RECORD"
                and maintenance["retrieval_complete"]
                and not maintenance["assessment_complete"]
                and maintenance["records"]["evidence"]["source"] == "POSTGRESQL",
                "Approved maintenance facts reach the decision package",
            )
            require(
                all(row["total_cost"] is None for row in comparison["options"]),
                "Unselected costs must remain unknown",
            )
            require(
                compared["data"]["selection_required"]
                and comparison["decision_completeness"] == "PARTIAL",
                "Explicit input selection required",
            )
            require(
                comparison["document_status"] == "VERIFIED_SOURCE",
                "Real document references in package",
            )
            require(
                compared["evidence"]["documents"]["citations"][0]["document_version"]
                == 3,
                "Current citation in package",
            )
            require(
                compared["status"] == "partial"
                and comparison["source"] == "REGISTERED_INPUT",
                "Registered inputs have no fixture fallback",
            )
            stage(
                "decision-package",
                repair_total=None,
                selected_inputs=False,
                verified_document_version=3,
            )
            fixture.docker("stop", "qdrant")
            unavailable = fixture.request(
                "/agent", data={"message": "文書検索：M-204"}, expected=503
            )
            require(not unavailable["evidence"], "No invented citation during outage")
        finally:
            fixture.docker("down", "--volumes", "--remove-orphans")
    print(
        json.dumps(
            {
                "result": "PASS",
                "real": ["Embedding", "Qdrant", "PostgreSQL", "source", "curl"],
                "mock": ["decision comparison inputs"],
                "llm": "NOT_USED",
                "model": args.model,
                "model_digest": args.digest,
                "scope": "Real retrieval and fixture-based calculations; not full business acceptance",
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
