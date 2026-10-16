"""専用環境で実Read Agentの回答と根拠を保存する。文章品質は別途レビューする。"""

import argparse
import json
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid5

from verify_minimal_flow import DemoFixture, stage

EQUIPMENT_ID = "20400000-0000-4000-8000-000000000001"
NAMESPACE = UUID("3e31b1d7-e229-4b4e-84ea-3c01cbd54cdd")

QUESTIONS = {
    "state_and_cause": "M-204の現在状態と故障原因を調べて。登録情報でわからないことは明示して。",
    "downstream": "M-204が停止した場合の下流の影響対象と経路を調べて。実際の停止や能力、安全性の未評価事項も示して。",
    "missing_equipment": "設備M-999999の現在状態を調べて。見つからなければ明示して。",
    "upstream": "M-204の上流依存を調べて。停止影響や能力、安全性の評価とは区別して。",
    "common": (
        f"製品P-100（Product ID: {uuid5(NAMESPACE, 'P-100')}）と"
        f"製品P-200（Product ID: {uuid5(NAMESPACE, 'P-200')}）の共通する上流依存候補を調べて。"
        "故障原因やSPOFと断定せず、不完全性と未評価事項も示して。"
    ),
}


def validate_observations(scenario, payload):
    """Validate server facts, never infer prose truth from a successful HTTP status."""
    rows = payload.get("data", {}).get("tool_results", [])
    if any(
        row.get("tool", "").startswith("prepare_")
        or row.get("tool") in {"approve", "execute"}
        for row in rows
    ):
        raise ValueError("UNEXPECTED_MUTATION")
    if not isinstance(payload.get("answer"), str) or not payload["answer"].strip():
        raise ValueError("ANSWER_MISSING")
    if scenario == "missing_equipment":
        if rows:
            if any(
                row.get("tool") != "search_equipment"
                or row.get("data", {}).get("items") != []
                or row.get("data", {}).get("next_cursor") is not None
                for row in rows
            ):
                raise ValueError("UNEXPECTED_MISSING_TARGET_FACTS")
        elif payload.get("data", {}).get("needs_input") is not True:
            raise ValueError("MISSING_TARGET_NOT_ACKNOWLEDGED")
        return
    if payload.get("status") != "ok" or payload.get("errors"):
        raise ValueError("AGENT_ERRORS")
    tool = {
        "state_and_cause": "get_equipment_state",
        "downstream": "trace_downstream_impact",
        "upstream": "trace_upstream_dependencies",
        "common": "find_common_dependencies",
    }[scenario]
    selected = [row for row in rows if row.get("tool") == tool]
    if not selected:
        raise ValueError("EXPECTED_TOOL_MISSING")
    evidence = payload.get("evidence", {}).get("tool_results", [])
    for row in selected:
        if not any(
            item.get("tool_call_id") == row.get("tool_call_id")
            and item.get("tool") == tool
            for item in evidence
        ):
            raise ValueError("EVIDENCE_MISSING")
        data = row["data"]
        if scenario == "state_and_cause":
            if (
                data.get("equipment_id") != EQUIPMENT_ID
                or data.get("state_code") != "STOPPED"
            ):
                raise ValueError("STATE_FIXTURE_MISMATCH")
        elif scenario == "downstream":
            expected = {
                (kind, str(uuid5(NAMESPACE, code)))
                for kind, codes in (
                    ("Process", ("P-10", "P-20")),
                    ("ProductionOperation", ("OP-30", "OP-40")),
                    ("Product", ("P-100", "P-200")),
                )
                for code in codes
            }
            reached = {
                (n["entity_type"], n["entity_id"]) for n in data["reached_nodes"]
            }
            if (
                data.get("target")
                != {"entity_type": "Equipment", "entity_id": EQUIPMENT_ID}
                or reached != expected
                or data.get("graph_sync_state") != "CURRENT"
                or data.get("complete") is not True
                or data.get("analysis_scope") != "DEPENDENCY_REACHABILITY"
                or data.get("not_evaluated")
                != ["OPERATIONAL_IMPACT", "CAPACITY", "SAFETY", "ECONOMICS"]
            ):
                raise ValueError("GRAPH_FIXTURE_MISMATCH")
        else:
            expected = {("InfrastructureResource", str(uuid5(NAMESPACE, "R-02")))}
            if scenario == "common":
                expected |= {
                    (kind, str(uuid5(NAMESPACE, code)))
                    for kind, codes in (
                        ("Process", ("P-10", "P-20")),
                        ("ProductionOperation", ("OP-30", "OP-40")),
                    )
                    for code in codes
                }
                expected.add(("Equipment", EQUIPMENT_ID))
                targets = {
                    (node["entity_type"], node["entity_id"])
                    for node in data.get("targets", [])
                }
                if targets != {
                    ("Product", str(uuid5(NAMESPACE, code)))
                    for code in ("P-100", "P-200")
                }:
                    raise ValueError("COMMON_TARGET_MISMATCH")
            elif data.get("target") != {
                "entity_type": "Equipment",
                "entity_id": EQUIPMENT_ID,
            }:
                raise ValueError("UPSTREAM_TARGET_MISMATCH")
            actual = {
                (node["entity_type"], node["entity_id"])
                for node in data.get(
                    "common_candidates" if scenario == "common" else "reached_nodes", []
                )
            }
            if (
                actual != expected
                or data.get("complete") is not True
                or data.get("graph_sync_state") != "CURRENT"
                or data.get("analysis_scope") != "DEPENDENCY_REACHABILITY"
                or data.get("not_evaluated")
                != ["OPERATIONAL_IMPACT", "CAPACITY", "SAFETY", "ECONOMICS"]
            ):
                raise ValueError("DEPENDENCY_FIXTURE_MISMATCH")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-group")
    parser.add_argument("--model", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if re.fullmatch(r"[A-Za-z0-9_.:/-]{1,200}", args.model) is None:
        parser.error("モデル名の形式が不正です")
    if args.report.exists() or not args.report.parent.is_dir():
        parser.error("reportは既存ディレクトリ内の新規ファイルを指定してください")
    report = {
        "report_version": 1,
        "dataset_version": "read-demo-v2",
        "model": args.model,
        "revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "working_tree_dirty": bool(
            subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
        ),
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "scope": "FIXED_READ_BASELINE_NOT_GENERAL_LLM_ACCEPTANCE",
        "prose_review": "REQUIRED",
        "review_criteria": [
            "登録状態と一致し、故障原因を捏造しない",
            "経路外の影響を追加せず、構造到達と実停止を区別する",
            "能力・安全・経済の未評価事項を保持する",
            "存在しない設備の事実や実施していない変更を作らない",
        ],
        "cases": [],
    }
    descriptor = os.open(args.report, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as output:
        try:
            with tempfile.TemporaryDirectory(
                prefix="linescope-read-quality-"
            ) as directory:
                fixture = DemoFixture(directory, args.docker_group)
                with fixture.credentials_file.open("a") as credentials:
                    credentials.write(f"LINESCOPE_LLM_MODEL={args.model}\n")
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
                    fixture.docker(
                        "run", "--rm", "graph-admin", "linescope", "seed-demo-graph"
                    )
                    fixture.docker(
                        "run", "--rm", "graph-admin", "linescope", "rebuild-graph"
                    )
                    observed_calls = 0
                    for scenario, question in QUESTIONS.items():
                        case = {"scenario": scenario, "question": question}
                        try:
                            payload = fixture.request(
                                "/agent",
                                data={"message": question},
                                timeout_seconds=90,
                                expected=None,
                            )
                            case["response"] = {
                                key: payload.get(key)
                                for key in (
                                    "status",
                                    "answer",
                                    "data",
                                    "evidence",
                                    "errors",
                                    "warnings",
                                )
                            }
                            case["http_status"] = payload.pop("_probe_http_status")
                            if case["http_status"] != 200:
                                raise ValueError("HTTP_ERROR")
                            validate_observations(scenario, payload)
                        except (
                            ValueError,
                            KeyError,
                            TypeError,
                            RuntimeError,
                            subprocess.CalledProcessError,
                        ) as error:
                            case["structured_result"] = "FAIL"
                            reason = (
                                str(error)
                                if isinstance(error, ValueError)
                                else "PROBE_REQUEST_FAILED"
                            )
                            case["failure_code"] = (
                                reason
                                if re.fullmatch(r"[A-Z_]{1,80}", reason)
                                else "OBSERVATION_VALIDATION_FAILED"
                            )
                        else:
                            case["structured_result"] = "PASS"
                        logs = fixture.docker(
                            "logs",
                            "--no-color",
                            "--no-log-prefix",
                            "api",
                            capture_output=True,
                        )
                        calls = []
                        for line in logs.stdout.splitlines():
                            try:
                                event = json.loads(line)
                            except ValueError:
                                continue
                            if (
                                isinstance(event, dict)
                                and event.get("event") == "llm.call.completed"
                            ):
                                calls.append(
                                    {
                                        key: event[key]
                                        for key in (
                                            "duration_ms",
                                            "result_code",
                                            "llm_input_bytes",
                                            "llm_output_bytes",
                                            "llm_tool_count",
                                        )
                                        if key in event
                                    }
                                )
                        case["llm_calls"] = calls[observed_calls:]
                        observed_calls = len(calls)
                        report["cases"].append(case)
                        stage(
                            scenario,
                            structured_result=case["structured_result"],
                            prose_review="REQUIRED",
                        )
                finally:
                    fixture.docker("down", "--volumes", "--remove-orphans")
        finally:
            report["result"] = (
                "STRUCTURED_PASS_REVIEW_REQUIRED"
                if len(report["cases"]) == len(QUESTIONS)
                and all(case["structured_result"] == "PASS" for case in report["cases"])
                else "FAIL"
            )
            json.dump(report, output, ensure_ascii=False, indent=2)
            output.write("\n")
    stage("result", result=report["result"], prose_review="REQUIRED")
    return 0 if report["result"] == "STRUCTURED_PASS_REVIEW_REQUIRED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
