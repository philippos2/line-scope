"""専用Composeの代表4経路を順番に検証し、デモ受入結果をJSONで保存する。"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

STAGES = {
    "minimal": "verify_minimal_flow.py",
    "multi_target": "verify_multi_equipment_flow.py",
    "vector": "verify_vector_knowledge_flow.py",
    "summary": "verify_decision_summary.py",
}


def result_status(results):
    statuses = [results.get(stage, {"status": "NOT_RUN"})["status"] for stage in STAGES]
    return (
        "FAIL" if "FAIL" in statuses else "PARTIAL" if "NOT_RUN" in statuses else "PASS"
    )


def verify_child(stage, returncode, output):
    reports = []
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and value.get("result") == "PASS":
            reports.append(value)
    if returncode != 0 or not reports:
        return {
            "status": "FAIL",
            "exit_code": returncode,
            "reason": "CHILD_NOT_VERIFIED",
        }
    report = reports[-1]
    valid = (
        stage == "minimal"
        and report.get("stage") == "result"
        and report.get("real_http") is True
        or stage == "multi_target"
        and report.get("scope") == "Real controlled multi-equipment action"
        or stage == "vector"
        and {"Embedding", "Qdrant", "PostgreSQL"} <= set(report.get("real", []))
        or stage == "summary"
        and report.get("stage") == "summary"
        and report.get("llm_status") == "VALIDATED_ORDER"
    )
    if not valid:
        return {
            "status": "FAIL",
            "exit_code": returncode,
            "reason": "REPORT_CONTRACT_MISMATCH",
        }
    return {"status": "PASS", "report": report}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-group")
    parser.add_argument("--embedding-model", default="embeddinggemma:latest")
    parser.add_argument("--embedding-digest")
    parser.add_argument("--llm-model")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists() or not args.report.parent.is_dir():
        parser.error("reportは既存ディレクトリ内の新規ファイルを指定してください")
    if (
        args.embedding_digest
        and re.fullmatch(r"[0-9a-f]{64}", args.embedding_digest) is None
    ):
        parser.error("embedding digestは64桁のSHA-256を指定してください")
    directory = Path(__file__).resolve().parent
    common = ["--docker-group", args.docker_group] if args.docker_group else []
    results = {}
    for stage, filename in STAGES.items():
        extra = []
        if stage == "vector":
            if not args.embedding_digest:
                results[stage] = {
                    "status": "NOT_RUN",
                    "reason": "EMBEDDING_DIGEST_NOT_SPECIFIED",
                }
                continue
            extra = ["--model", args.embedding_model, "--digest", args.embedding_digest]
        elif stage == "summary":
            if not args.llm_model:
                results[stage] = {
                    "status": "NOT_RUN",
                    "reason": "LLM_MODEL_NOT_SPECIFIED",
                }
                continue
            extra = ["--model", args.llm_model]
        print(f"検証中: {stage}", flush=True)
        child = subprocess.run(
            [sys.executable, str(directory / filename), *common, *extra],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        results[stage] = verify_child(stage, child.returncode, child.stdout)
        print(f"結果: {stage} {results[stage]['status']}", flush=True)
    overall = result_status(results)
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=directory.parent,
        text=True,
        capture_output=True,
        check=False,
    )
    report = {
        "report_version": 1,
        "scope": "DEMO_BACKEND_PATHS_NOT_FULL_BUSINESS_ACCEPTANCE",
        "result": overall,
        "revision": revision.stdout.strip() if revision.returncode == 0 else None,
        "working_tree_dirty": bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=directory.parent,
                text=True,
                capture_output=True,
                check=False,
            ).stdout.strip()
        ),
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "stages": results,
        "limitations": [
            "BUSINESS_INPUTS_INCLUDE_MOCK_FIXTURES",
            "GENERAL_LLM_GROUNDING_NOT_CERTIFIED",
            "WEB_UI_NOT_IMPLEMENTED",
        ],
    }
    descriptor = os.open(args.report, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(
        json.dumps(
            {"result": overall, "report": str(args.report), "scope": report["scope"]}
        )
    )
    if overall == "FAIL":
        raise SystemExit(1)
    if overall == "PARTIAL":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
