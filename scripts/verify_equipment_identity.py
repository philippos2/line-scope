"""Read-only real-model check for equipment names/codes; no seed or environment creation."""

import argparse
import json
import os
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def tool_rows(payload):
    if payload.get("status") not in {"ok", "partial"} or payload.get("errors"):
        raise ValueError("AGENT_RESPONSE_FAILED")
    rows = payload.get("data", {}).get("tool_results", [])
    if not isinstance(rows, list) or not rows:
        raise ValueError("NO_VERIFIED_READ")
    if any(
        row.get("tool") not in {"search_equipment", "search_maintenance_records"}
        for row in rows
    ):
        raise ValueError("UNEXPECTED_TOOL")
    return rows


def equipment_rows(rows):
    return [
        item
        for row in rows
        if row.get("tool") == "search_equipment"
        for item in row.get("data", {}).get("items", [])
    ]


def validate_answer(kind, payload, expected_ids):
    rows = tool_rows(payload)
    found = {item.get("equipment_id") for item in equipment_rows(rows)}
    records = [row for row in rows if row.get("tool") == "search_maintenance_records"]
    if found != expected_ids:
        raise ValueError("EQUIPMENT_IDENTITY_MISMATCH")
    answer = payload.get("answer", "")
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("ANSWER_MISSING")
    if kind == "unique":
        if not records:
            raise ValueError("MAINTENANCE_NOT_READ")
    elif records:
        raise ValueError("UNRESOLVED_TARGET_WAS_USED")
    if kind == "ambiguous" and not re.search(
        "選択|選ん|指定|絞|どちら|複数|特定.*でき", answer
    ):
        raise ValueError("CLARIFICATION_NOT_REQUESTED")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--equipment-code", required=True)
    parser.add_argument("--equipment-name", required=True)
    parser.add_argument("--ambiguous-name")
    parser.add_argument("--missing-name")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    token = os.environ.get("LINESCOPE_VERIFY_TOKEN", "")
    if not token or "\n" in token or "\r" in token:
        raise ValueError("PRIVATE_TOKEN_REQUIRED")

    def post(message):
        req = Request(
            args.url.rstrip("/") + "/agent",
            data=json.dumps({"message": message}, ensure_ascii=False).encode(),
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(req, timeout=130) as response:
                return json.load(response)
        except HTTPError as error:
            # Preserve the structured API failure in the case report as well.
            with error:
                return json.load(error)

    def search(field, text):
        payload = post(
            "関係分析 "
            + json.dumps(
                {
                    "tool": "search_equipment",
                    "arguments": {
                        "filter": {field: text},
                        "page_size": 20,
                        "cursor": None,
                    },
                },
                ensure_ascii=False,
            )
        )
        rows = tool_rows(payload)
        if any(row.get("data", {}).get("next_cursor") for row in rows):
            raise ValueError("BASELINE_SEARCH_INCOMPLETE")
        return {item["equipment_id"] for item in equipment_rows(rows)}

    target = search("equipment_code", args.equipment_code)
    if len(target) != 1 or search("name", args.equipment_name) != target:
        raise ValueError("BASELINE_TARGET_NOT_UNIQUE")
    cases = [
        ("unique", args.equipment_code, target),
        ("unique", args.equipment_name, target),
    ]
    if args.ambiguous_name:
        candidates = search("name", args.ambiguous_name)
        if len(candidates) < 2:
            raise ValueError("BASELINE_NOT_AMBIGUOUS")
        cases.append(("ambiguous", args.ambiguous_name, candidates))
    if args.missing_name:
        if search("name", args.missing_name) or search(
            "equipment_code", args.missing_name
        ):
            raise ValueError("BASELINE_NOT_MISSING")
        cases.append(("missing", args.missing_name, set()))
    report = []
    for kind, text, expected in cases:
        payload = post(f"{text}が最後にメンテナンスされたのはいつか？")
        item = {
            "case": kind,
            "target_text": text,
            "request_id": payload.get("request_id"),
            "answer": payload.get("answer"),
            "status": payload.get("status"),
            "errors": payload.get("errors", []),
            "tools": payload.get("data", {}).get("tool_results", []),
            "result": "FAIL",
        }
        report.append(item)
        try:
            validate_answer(kind, payload, expected)
            item["result"] = "PASS"
        except ValueError as error:
            item["reason"] = str(error)
            raise
        finally:
            args.output.write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    print(
        json.dumps(
            {"result": "PASS", "cases": len(report), "real_model": True},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except (ValueError, HTTPError, URLError, TimeoutError) as error:
        # Never print credentials, raw response bodies or provider exceptions.
        raise SystemExit(
            str(error) if isinstance(error, ValueError) else type(error).__name__
        ) from None
