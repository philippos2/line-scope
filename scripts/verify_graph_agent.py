"""Opt-in HTTP read probe for seed-demo-graph; not a business acceptance test."""

import argparse
import json
import os
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from linescope.demo_graph_seed import demo_id
from linescope.demo_seed import DEMO_EQUIPMENT


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_result(payload):
    if (
        payload.get("status") != "ok"
        or payload.get("errors")
        or payload.get("warnings")
    ):
        raise ValueError("AGENT_ERRORS")
    results = payload.get("data", {}).get("tool_results", [])
    graph = [row for row in results if row.get("tool") == "trace_downstream_impact"]
    if len(graph) != 1:
        raise ValueError("GRAPH_TOOL_RESULT_MISSING")
    row = graph[0]
    data = row["data"]
    root = {"entity_type": "Equipment", "entity_id": str(DEMO_EQUIPMENT[0][0])}
    expected = {
        (kind, str(demo_id(code)))
        for kind, codes in (
            ("Process", ("P-10", "P-20")),
            ("ProductionOperation", ("OP-30", "OP-40")),
            ("Product", ("P-100", "P-200")),
        )
        for code in codes
    }
    reached = {
        (item["entity_type"], item["entity_id"]) for item in data["reached_nodes"]
    }
    if (
        data["target"] != root
        or data["complete"] is not True
        or data["graph_sync_state"] != "CURRENT"
        or data["analysis_mode"] != "CURRENT"
        or data.get("analysis_scope") != "DEPENDENCY_REACHABILITY"
        or data.get("not_evaluated")
        != ["OPERATIONAL_IMPACT", "CAPACITY", "SAFETY", "ECONOMICS"]
        or reached != expected
    ):
        raise ValueError("GRAPH_FIXTURE_MISMATCH")
    paths = data["representative_paths"]
    ends = {
        (path["nodes"][-1]["entity_type"], path["nodes"][-1]["entity_id"])
        for path in paths
    }
    if ends != expected or any(
        path["nodes"][0] != root
        or len(path["edges"]) != len(path["nodes"]) - 1
        or (path["nodes"][-1]["entity_type"] == "Product" and len(path["edges"]) != 3)
        for path in paths
    ):
        raise ValueError("GRAPH_PATH_MISMATCH")
    evidence = [
        item
        for item in payload.get("evidence", {}).get("tool_results", [])
        if item.get("tool_call_id") == row["tool_call_id"]
        and item.get("tool") == row["tool"]
    ]
    if (
        len(evidence) != 1
        or not evidence[0].get("graph_generation")
        or evidence[0].get("analysis_scope") != data["analysis_scope"]
        or evidence[0].get("not_evaluated") != data["not_evaluated"]
        or evidence[0].get("representative_paths") != data["representative_paths"]
        or len(data["representative_paths"]) != 6
        or evidence[0].get("state_versions") != {"Equipment:" + root["entity_id"]: 1}
    ):
        raise ValueError("GRAPH_EVIDENCE_MISMATCH")
    return {"reached_objects": 6, "affected_products": 2, "representative_paths": 6}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    url = urlsplit(args.base_url)
    token = os.environ.get("LINESCOPE_PROBE_TOKEN", "")
    if url.scheme not in {"http", "https"} or url.username or url.password or not token:
        parser.error("HTTP(S) URLとLINESCOPE_PROBE_TOKENが必要です")
    request = Request(
        args.base_url.rstrip("/") + "/agent",
        data=json.dumps(
            {"message": "M-204が停止した場合の下流の影響対象と経路を調べて"}
        ).encode(),
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
        },
    )
    started = monotonic()
    try:
        with build_opener(NoRedirect).open(request, timeout=90) as response:
            payload = json.load(response)
        metrics = validate_result(payload)
    except (
        HTTPError,
        URLError,
        TimeoutError,
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        AttributeError,
    ):
        print(json.dumps({"passed": False, "code": "GRAPH_AGENT_PROBE_FAILED"}))
        return 1
    print(
        json.dumps(
            {
                "passed": True,
                **metrics,
                "duration_seconds": round(monotonic() - started, 2),
                "scope": "demo_graph_read_probe_only",
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
