"""専用Composeで文書取込み→curl検索→引用→版更新を実行する。

Embed/Qdrantは明示的モック。PostgreSQL正本・認証・本文hash検証は実処理。
python3 scripts/verify_knowledge_flow.py [--docker-group docker]
"""

import argparse
import json
import subprocess
import time

from verify_minimal_flow import disposable_fixture, require, stage


def ingest(fixture, version, text):
    # Developer-owned fixture content only; no user/LLM argument enters Python code.
    program = (
        "from pathlib import Path; import subprocess; "
        f"Path('/tmp/manual.txt').write_text({text!r}, encoding='utf-8'); "
        "subprocess.run(['linescope','ingest-knowledge','--code','MANUAL-204',"
        f"'--version','{version}','--title','保全資料','--file','/tmp/manual.txt'],check=True)"
    )
    fixture.docker(
        "run", "--rm", "--no-deps", "knowledge-admin", "python", "-c", program
    )


def verify(fixture):
    with fixture.credentials_file.open("a") as output:
        output.write("LINESCOPE_KNOWLEDGE_MOCK_ROOT=/workspace/knowledge\n")
    fixture.docker("up", "--build", "-d", "api")
    for attempt in range(30):
        try:
            fixture.request("/health/ready")
            break
        except (subprocess.CalledProcessError, RuntimeError):
            if attempt == 29:
                raise
            time.sleep(1)
    ingest(fixture, 1, "M-204 保全手順。停止後に点検する。")
    request = {"message": "文書検索：M-204"}
    result = fixture.request("/agent", data=request)
    items = result["data"]["items"]
    require(
        result["status"] == "partial" and result["data"]["demo_only"], "Mock marker"
    )
    require(
        len(items) == 1 and items[0]["citation"]["document_version"] == 1, "Version 1"
    )
    require(
        result["evidence"]["citations"] == [items[0]["citation"]], "Server citation"
    )
    fixture.request("/agent", data=request, token="invalid-fixture-token", expected=401)
    stage("knowledge", document_version=1, citations=1, authenticated=True)
    ingest(fixture, 2, "M-204 更新済み保全手順。安全条件を別途確認する。")
    revised = fixture.request("/agent", data=request)
    require(len(revised["data"]["items"]) == 1, "Active version only")
    item = revised["data"]["items"][0]
    require(item["citation"]["document_version"] == 2, "Version 2")
    require(
        item["text"] == "M-204 更新済み保全手順。安全条件を別途確認する。",
        "Source text",
    )
    missing = fixture.request("/agent", data={"message": "文書検索：存在しない文書"})
    require(missing["data"]["items"] == [], "No invented citations")
    return {
        "result": "PASS",
        "real_http": True,
        "transport": "curl",
        "real": ["PostgreSQL", "managed source files", "authorization", "citations"],
        "mock": ["embedding", "Qdrant search"],
        "llm": "NOT_USED",
        "scope": "Connected retrieval demo; not RAG quality acceptance",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-group")
    args = parser.parse_args()
    with disposable_fixture(args.docker_group) as fixture:
        result = verify(fixture)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
