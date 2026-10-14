"""実Ollamaの表示順選択と、サーバによる日本語要約を専用Composeで検証する。"""

import argparse
import re
import tempfile

from verify_minimal_flow import DemoFixture, require, stage, verify


class SummaryFixture(DemoFixture):
    def request(self, path, **arguments):
        return super().request(path, timeout_seconds=30, **arguments)


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
            result = fixture.request(
                "/agent", data={"message": "M-204の修理と交換を比較して"}
            )
            summary = result["data"]["decision_package"]["summary"]
            require(
                summary["llm_status"] == "VALIDATED_ORDER",
                "Real model did not select a valid order",
            )
            require(
                summary["llm_scope"] == "PRESENTATION_ORDER_ONLY",
                "Model exceeded presentation scope",
            )
            require(
                "1,900,000円" in result["answer"]
                and "継続案を除外" in result["answer"],
                "Server facts or constraints missing",
            )
            stage(
                "summary",
                result="PASS",
                model=args.model,
                llm_status=summary["llm_status"],
                source=summary["source"],
                scope="Presentation order only; not full LLM quality acceptance",
            )
        finally:
            fixture.docker("down", "--volumes", "--remove-orphans")


if __name__ == "__main__":
    main()
