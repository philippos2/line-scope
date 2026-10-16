"""実Embedding/Qdrantの小規模検索baseline。閾値の承認・LLM品質は別判定。"""

import argparse
import hashlib
import json
import re
import secrets
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from verify_minimal_flow import DemoFixture, require

CORPUS = {
    "BEARING": (
        "軸受過熱",
        "M-204の軸受過熱。軸受温度が上昇した場合は設備を停止し、潤滑油の不足と軸受損傷を点検する。運転再開には別途安全条件の確認が必要。",
    ),
    "VIBRATION": (
        "振動異常",
        "M-204の振動異常。振動が増えた場合は据付ボルトの緩み、軸の芯ずれ、回転部の偏心を停止後に点検する。",
    ),
    "COOLING": (
        "冷却系統",
        "冷却水の流量低下や水温上昇では、冷却水ポンプ、ストレーナの詰まり、配管漏れを点検する。",
    ),
    "ELECTRIC": (
        "電気系統",
        "モーターが起動しない場合は電源遮断と無電圧確認を行い、過負荷リレー、配線の断線、電源電圧を点検する。",
    ),
    "LOCKOUT": (
        "隔離手順",
        "保全作業前は電源を遮断し、ロックアウトとタグアウトを行う。残留圧力と蓄積エネルギーを解放し、ゼロエネルギーを確認する。",
    ),
    "DELIVERY": (
        "交換部品の調達",
        "M-204の交換部品の調達lead timeは14日。調達待ちと交換作業時間と生産停止時間は別であり、納期だけで停止期間を決定しない。",
    ),
}
QUERIES = [
    ("軸受の温度が高くなったときに何を点検するか", "BEARING"),
    ("機械の振動が大きくなった場合の確認項目", "VIBRATION"),
    ("冷却水の流れが弱くなったときの調査", "COOLING"),
    ("モーターが動かないときに点検する電気部品", "ELECTRIC"),
    ("保全作業前にエネルギーを隔離する手順", "LOCKOUT"),
    ("交換部品が届くまでの日数と停止時間の関係", "DELIVERY"),
]


class RetrievalFixture(DemoFixture):
    def docker(self, *arguments, **kwargs):
        return super().docker(
            "-f", str(self.repository / "compose.rag.yaml"), *arguments, **kwargs
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-group")
    parser.add_argument("--model", default="embeddinggemma:latest")
    parser.add_argument("--digest", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if (
        re.fullmatch(r"[A-Za-z0-9_.:/-]{1,200}", args.model) is None
        or re.fullmatch(r"[a-f0-9]{64}", args.digest) is None
    ):
        parser.error("Explicit installed model and digest required")
    if args.report.exists() or not args.report.parent.is_dir():
        parser.error("New report path required")
    report = {
        "dataset_version": "retrieval-demo-v1",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "working_tree_dirty": bool(
            subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
        ),
        "model": args.model,
        "digest": args.digest,
        "dimensions": 768,
        "scope": "SYNTHETIC_SIX_DOCUMENT_BASELINE_NOT_GENERAL_ACCEPTANCE",
        "llm": "NOT_USED",
        "corpus": CORPUS,
        "cases": [],
        "threshold_approval": "PENDING",
    }
    with args.report.open("x") as output:
        try:
            with tempfile.TemporaryDirectory(
                prefix="linescope-retrieval-quality-"
            ) as directory:
                fixture = RetrievalFixture(directory, args.docker_group)
                with fixture.credentials_file.open("a") as env:
                    env.write(f"LINESCOPE_QDRANT_WRITE_KEY={secrets.token_hex(32)}\n")
                    env.write(f"LINESCOPE_QDRANT_READ_KEY={secrets.token_hex(32)}\n")
                    env.write(
                        f"LINESCOPE_EMBEDDING_MODEL={args.model}\nLINESCOPE_EMBEDDING_DIGEST={args.digest}\nLINESCOPE_EMBEDDING_DIMENSIONS=768\n"
                    )
                try:
                    fixture.docker("up", "--build", "-d", "api")
                    for attempt in range(30):
                        try:
                            fixture.request("/health/ready")
                            break
                        except (subprocess.CalledProcessError, RuntimeError):
                            if attempt == 29:
                                raise
                            time.sleep(1)
                    for code, (title, body) in CORPUS.items():
                        program = (
                            "from pathlib import Path; import subprocess; "
                            f"Path('/tmp/baseline.txt').write_text({body!r},encoding='utf-8'); "
                            f"subprocess.run(['linescope','ingest-knowledge','--code',{code!r},'--version','1','--title',{title!r},'--file','/tmp/baseline.txt'],check=True)"
                        )
                        fixture.docker(
                            "run",
                            "--rm",
                            "--no-deps",
                            "knowledge-admin",
                            "python",
                            "-c",
                            program,
                        )
                    for query, expected in QUERIES:
                        started = time.monotonic()
                        response = fixture.request(
                            "/agent",
                            data={"message": "文書検索：" + query},
                            timeout_seconds=90,
                        )
                        items = response["data"]["items"]
                        require(
                            response["data"]["search_source"] == "QDRANT"
                            and not response["data"]["demo_only"],
                            "Real retrieval required",
                        )
                        require(
                            response["evidence"]["citations"]
                            == [row["citation"] for row in items],
                            "Citation mismatch",
                        )
                        titles = [row["citation"]["title"] for row in items]
                        grounded = all(
                            any(
                                row["text"] == body
                                and row["citation"]["title"] == title
                                and row["citation"]["document_version"] == 1
                                and row["citation"]["content_hash"]
                                == hashlib.sha256(body.encode()).hexdigest()
                                for title, body in CORPUS.values()
                            )
                            for row in items
                        )
                        require(grounded, "Unverified source content")
                        rank = (
                            titles.index(CORPUS[expected][0]) + 1
                            if CORPUS[expected][0] in titles
                            else None
                        )
                        report["cases"].append(
                            {
                                "query": query,
                                "expected": expected,
                                "rank": rank,
                                "titles": titles,
                                "citation_grounded": grounded,
                                "duration_ms": int((time.monotonic() - started) * 1000),
                                "response": response,
                            }
                        )
                finally:
                    fixture.docker("down", "--volumes", "--remove-orphans")
            ranks = [row["rank"] for row in report["cases"]]
            report["metrics"] = {
                "hit_at_1": sum(rank == 1 for rank in ranks) / len(QUERIES),
                "recall_at_3": sum(rank is not None and rank <= 3 for rank in ranks)
                / len(QUERIES),
                "mrr": sum(1 / rank if rank else 0 for rank in ranks) / len(QUERIES),
                "citation_grounded": all(
                    row["citation_grounded"] for row in report["cases"]
                ),
            }
            report["result"] = "MEASURED_REVIEW_REQUIRED"
        finally:
            report.setdefault("result", "FAIL")
            json.dump(report, output, ensure_ascii=False, indent=2)
            output.write("\n")
    print(
        json.dumps({"result": report["result"], "metrics": report.get("metrics")}),
        flush=True,
    )
    return 0 if report["result"] == "MEASURED_REVIEW_REQUIRED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
