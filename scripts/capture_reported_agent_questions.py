"""Capture reported questions verbatim through the real API, without scoring prose.

No environment creation, business writes, warmup inference, retry or UI prefix.
Run in Docker. Credentials stay in the environment, raw responses stay private.
"""

import argparse
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


class DirectAPI(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        return None


def utc():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    path.chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path(__file__).parent / "fixtures/reported-agent-questions.json",
    )
    parser.add_argument("--list", action="store_true", help="No network or inference")
    parser.add_argument("--api")
    parser.add_argument("--revision")
    parser.add_argument("--model")
    parser.add_argument("--approved-start")
    parser.add_argument("--approved-until")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    raw_registry = args.registry.read_bytes()
    cases = json.loads(raw_registry)["cases"]
    if not cases or any(
        not isinstance(c["message"], str) or not c["message"] or c["repetitions"] != 3
        for c in cases
    ):
        parser.error("A nonempty verbatim registry with three repetitions is required")
    if any(
        not isinstance(c["id"], str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", c["id"])
        for c in cases
    ):
        parser.error("Case IDs must be safe artifact names")
    if len({c["id"] for c in cases}) != len(cases):
        parser.error("Case IDs must be unique")
    if args.list:
        print(
            json.dumps(
                {"cases": len(cases), "requests": 3 * len(cases), "concurrency": 1},
                ensure_ascii=False,
            )
        )
        return 0
    if not all(
        (
            args.api,
            args.revision,
            args.model,
            args.approved_start,
            args.approved_until,
            args.output,
        )
    ):
        parser.error(
            "Explicit API, revision, model, approved window and new private output directory are required"
        )
    base = urllib.parse.urlsplit(args.api)
    if (
        base.scheme not in {"http", "https"}
        or not base.hostname
        or base.username
        or base.password
        or base.query
        or base.fragment
        or base.path not in {"", "/"}
    ):
        parser.error(
            "Use the direct API origin without credentials, query, fragment or proxy path"
        )
    start_time = datetime.fromisoformat(args.approved_start)
    end_time = datetime.fromisoformat(args.approved_until)
    if start_time.tzinfo is None or end_time.tzinfo is None:
        parser.error("Approved timestamps must include their timezone")
    start = start_time.timestamp()
    end = end_time.timestamp()
    if not start <= time.time() < end:
        parser.error("The explicitly approved window is not current")
    token = os.environ.get("LINESCOPE_AGENT_TOKEN")
    if not token:
        parser.error("Private LINESCOPE_AGENT_TOKEN is required")
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    report = {
        "api": args.api,
        "product_revision": args.revision,
        "model": args.model,
        "model_digest": "NOT_CAPTURED",
        "started": utc(),
        "planned": len(cases) * 3,
        "registry_sha256": hashlib.sha256(raw_registry).hexdigest(),
        "input_policy": "Exact registry message, no prefix, normalization, context_id or as_of",
        "responses": [],
        "stop_reason": None,
        "verdict": "未確認",
    }
    timeout_streak = 0
    opener = urllib.request.build_opener(DirectAPI())
    try:
        for case in cases:
            for repeat in range(1, 4):
                if time.time() + 135 >= end:
                    report["stop_reason"] = "APPROVED_WINDOW_RESERVE"
                    return 2
                name = f"{case['id']}-{repeat}"
                payload = json.dumps(
                    {"message": case["message"]}, ensure_ascii=False
                ).encode("utf-8")
                (args.output / f"{name}.request.json").write_bytes(payload)
                (args.output / f"{name}.request.json").chmod(0o600)
                row = {
                    "id": case["id"],
                    "repeat": repeat,
                    "started": utc(),
                    "verdict": "未確認",
                }
                report["responses"].append(row)
                request = urllib.request.Request(
                    args.api.rstrip("/") + "/agent",
                    data=payload,
                    method="POST",
                    headers={
                        "Authorization": "Bearer " + token,
                        "Content-Type": "application/json",
                    },
                )
                began = time.monotonic()
                response = None
                try:
                    try:
                        response = opener.open(
                            request, timeout=min(125, end - time.time())
                        )
                    except urllib.error.HTTPError as error:
                        response = error
                    with response:
                        body = response.read()
                        row["http_status"] = response.status
                    path = args.output / f"{name}.response.body"
                    path.write_bytes(body)
                    path.chmod(0o600)
                    row["response_file"] = path.name
                    row["response_sha256"] = hashlib.sha256(body).hexdigest()
                    try:
                        parsed = json.loads(body)
                    except (ValueError, UnicodeDecodeError):
                        parsed = {}
                    if not isinstance(parsed, dict):
                        parsed = {}
                    row["request_id"] = parsed.get("request_id")
                    limited = any(
                        isinstance(error, dict)
                        and error.get("code") == "AGENT_LIMIT_REACHED"
                        for error in parsed.get("errors", [])
                    )
                    timeout_streak = timeout_streak + 1 if limited else 0
                    if timeout_streak >= 2:
                        report["stop_reason"] = "TWO_CONSECUTIVE_AGENT_LIMITS"
                    data = parsed.get("data")
                    if isinstance(data, dict) and data.get("update_request_id"):
                        report["stop_reason"] = "UNEXPECTED_UPDATE_REQUEST"
                    if 300 <= row["http_status"] < 400:
                        report["stop_reason"] = "UNEXPECTED_REDIRECT"
                    if row["http_status"] in {401, 403}:
                        report["stop_reason"] = "AUTHENTICATION_OR_AUTHORIZATION_FAILED"
                except (OSError, urllib.error.URLError) as error:
                    row["transport_error_type"] = type(error).__name__
                    # No synthetic response body or automatic transport retry.
                    timeout_streak += 1
                    if timeout_streak >= 2:
                        report["stop_reason"] = "TWO_CONSECUTIVE_TRANSPORT_FAILURES"
                finally:
                    row["elapsed_ms"] = round((time.monotonic() - began) * 1000)
                    write_json(args.output / "manifest.json", report)
                    print(
                        json.dumps(
                            {
                                k: row[k]
                                for k in (
                                    "id",
                                    "repeat",
                                    "elapsed_ms",
                                    "http_status",
                                    "transport_error_type",
                                )
                                if k in row
                            }
                        ),
                        flush=True,
                    )
                if report["stop_reason"]:
                    return 2
        return 0 if all("response_file" in row for row in report["responses"]) else 2
    finally:
        report["finished"] = utc()
        report["completed"] = len(report["responses"])
        report["collection_complete"] = (
            report["completed"] == report["planned"]
            and not report["stop_reason"]
            and all("response_file" in row for row in report["responses"])
        )
        # A complete capture is not a semantic PASS. Review all raw answers separately.
        write_json(args.output / "manifest.json", report)


if __name__ == "__main__":
    raise SystemExit(main())
