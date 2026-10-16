"""実Ollamaによる正式比較Tool参照と、サーバによる日本語要約を専用Composeで検証する。"""

import argparse
import json
import re
import tempfile

from verify_minimal_flow import DemoFixture, require, stage, verify


class SummaryFixture(DemoFixture):
    def request(self, path, **arguments):
        arguments.setdefault("timeout_seconds", 150)
        return super().request(path, **arguments)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-group")
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    if re.fullmatch(r"[A-Za-z0-9_.:/-]{1,200}", args.model) is None:
        parser.error("モデル名の形式が不正です")
    with tempfile.TemporaryDirectory(prefix="linescope-summary-") as directory:
        fixture = SummaryFixture(directory, args.docker_group)
        with fixture.credentials_file.open("a") as output:
            output.write(f"LINESCOPE_LLM_MODEL={args.model}\n")
        try:
            verify(fixture)
            discovered = fixture.request(
                "/agent", data={"message": "M-204の修理と交換を比較して"}
            )
            selection = {
                "equipment_id": discovered["data"]["equipment_id"],
                "period_start": "2026-10-01T00:00:00Z",
                "period_end": "2026-10-02T00:00:00Z",
                "economic_input_id": None,
                "capacity_input_ids": [],
                "safety_input_ids": [],
                "maintenance_input_ids": [],
            }
            result = fixture.request(
                "/agent",
                data={
                    "message": "次の引数でcompare_registered_inputsを呼んで条件を評価してください。"
                    + json.dumps(selection)
                },
            )
            tools = result["data"].get("tool_results", [])
            selected = [
                row for row in tools if row["tool"] == "compare_registered_inputs"
            ]
            require(
                bool(selected),
                "Real model did not reference registered comparison Tool",
            )
            require(
                selected[0]["data"]["source"] == "REGISTERED_INPUT",
                "Registered source missing",
            )
            require(
                "候補から除外" in result["answer"]
                and "MOCK_FIXTURE" not in json.dumps(result),
                "Server constraints missing or fixture fallback present",
            )
            stage(
                "summary",
                result="PASS",
                model=args.model,
                source="REGISTERED_INPUT",
                scope="Registered readonly Tool; not full LLM quality acceptance",
            )
        finally:
            fixture.docker("down", "--volumes", "--remove-orphans")


if __name__ == "__main__":
    main()
