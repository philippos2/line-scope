"""CI対象の判定と必須checkの集約。判定不能時はBackendも検証する。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path, PurePosixPath


def documentation_path(path: str) -> bool:
    if path in {"README.md", "CONTRIBUTING.md", "AGENTS.md", "SKILL.md"}:
        return True
    if path.endswith(("/AGENTS.md", "/SKILL.md")):
        return True
    return path.startswith(("docs/", ".agents/skills/")) and PurePosixPath(
        path
    ).suffix.lower() in {
        ".md",
        ".html",
        ".svg",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".pdf",
    }


def backend_required(paths: list[str]) -> bool:
    return not paths or any(
        not (
            path.startswith("frontend/")
            or path == "compose.frontend.yaml"
            or documentation_path(path)
        )
        for path in paths
    )


def verification_succeeds(
    scope: str, backend: str, tests: str, runtime: str, frontend: str
) -> bool:
    if scope != "success" or frontend != "success":
        return False
    if backend == "true":
        return tests == "success" and runtime == "success"
    if backend == "false":
        return tests == "skipped" and runtime == "skipped"
    return False


def detect_backend() -> bool:
    event = os.environ.get("CI_SCOPE_EVENT")
    base = os.environ.get("CI_SCOPE_BASE", "")
    head = os.environ.get("CI_SCOPE_HEAD", "")
    if event not in {"pull_request", "push"} or not base or not head:
        return True
    try:
        if event == "pull_request":
            base = subprocess.check_output(
                ["git", "merge-base", base, head], text=True, stderr=subprocess.DEVNULL
            ).strip()
        output = subprocess.check_output(
            ["git", "diff", "--no-renames", "--name-only", "-z", base, head, "--"],
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        print("差分を判定できないためBackend検証を実行します。", file=sys.stderr)
        return True
    return backend_required(
        output.decode("utf-8", errors="surrogateescape").split("\0")[:-1]
    )


def main() -> int:
    if sys.argv[1:] == ["verify"]:
        return (
            0
            if verification_succeeds(
                os.environ.get("CI_SCOPE_RESULT", ""),
                os.environ.get("CI_BACKEND_REQUIRED", ""),
                os.environ.get("CI_TEST_RESULT", ""),
                os.environ.get("CI_RUNTIME_RESULT", ""),
                os.environ.get("CI_FRONTEND_RESULT", ""),
            )
            else 1
        )
    if sys.argv[1:]:
        return 2
    required = str(detect_backend()).lower()
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write(f"backend={required}\n")
    print(f"Backend検証: {required} / Frontend検証: true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
