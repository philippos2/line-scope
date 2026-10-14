"""専用Composeで複数設備の要求置換・承認・一括実行・再送をcurl検証する。"""

import argparse

from verify_minimal_flow import disposable_fixture, require, stage, verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-group")
    args = parser.parse_args()
    with disposable_fixture(args.docker_group) as fixture:
        verify(fixture)
        old = fixture.request(
            "/agent", data={"message": "設備[M-204,M-208]の状態を不明に変更して"}
        )["data"]
        saved = fixture.request(
            "/agent",
            data={
                "message": "設備[M-204,M-208]の状態を停止に変更して",
                "replace_update_request_id": old["update_request_id"],
            },
        )["data"]
        require(
            len(saved["canonical_snapshot"]["targets"]) == 2, "Expected two targets"
        )
        invalidated = fixture.request("/update-requests/" + old["update_request_id"])[
            "data"
        ]
        require(
            invalidated["status"] == "INVALIDATED", "Old request must be invalidated"
        )
        fixture.request(
            "/update-requests/" + old["update_request_id"] + "/execute", expected=409
        )
        endpoint = "/update-requests/" + saved["update_request_id"] + "/execute"
        fixture.request(endpoint, expected=409)
        fixture.request(
            "/approvals/" + saved["approval_id"] + "/approve",
            token=fixture.approver,
            data={"snapshot_hash": saved["snapshot_hash"]},
        )
        executed = fixture.request(endpoint)["data"]
        require(executed["status"] == "COMPLETED", "Batch was not completed")
        require(
            len(executed["current_snapshot"]["targets"]) == 2
            and all(
                target["snapshot"]["state_code"] == "STOPPED"
                for target in executed["current_snapshot"]["targets"]
            ),
            "Both current states must match",
        )
        replay = fixture.request(endpoint)["data"]
        require(
            replay["execution_result"] == executed["execution_result"],
            "Retry changed execution",
        )
        stage(
            "multi-equipment",
            targets=2,
            replacement="INVALIDATED",
            execution="COMPLETED",
            retry="PASS",
        )
    stage(
        "result",
        result="PASS",
        transport="curl",
        llm="NOT_USED",
        scope="Real controlled multi-equipment action",
    )


if __name__ == "__main__":
    main()
