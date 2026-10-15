"""省略対象と必須checkの失敗条件を代表値・境界で検証する。"""

import os
import subprocess
import unittest
from unittest.mock import patch

from ci_scope import backend_required, detect_backend, verification_succeeds


class ScopeTest(unittest.TestCase):
    def test_frontend(self):
        self.assertFalse(backend_required(["frontend/src/app/App.tsx"]))

    def test_frontend_compose(self):
        self.assertFalse(backend_required(["compose.frontend.yaml"]))

    def test_empty(self):
        self.assertTrue(backend_required([]))

    def test_backend(self):
        self.assertTrue(backend_required(["backend/src/linescope/main.py"]))

    def test_workflow(self):
        self.assertTrue(backend_required([".github/workflows/ci.yml"]))

    def test_shared_compose(self):
        self.assertTrue(backend_required(["compose.yaml"]))

    def test_unknown(self):
        self.assertTrue(backend_required(["new-shared-config.yaml"]))

    def test_move_from_backend(self):
        self.assertTrue(backend_required(["backend/old.py", "frontend/new.ts"]))

    def test_documentation(self):
        self.assertFalse(backend_required(["docs/requirements/requirements.md"]))

    def test_document_asset(self):
        self.assertFalse(backend_required(["docs/roadmap-gantt.svg"]))

    def test_root_guidance(self):
        for name in ["README.md", "CONTRIBUTING.md", "AGENTS.md", "SKILL.md"]:
            with self.subTest(path=name):
                self.assertFalse(backend_required([name]))

    def test_nested_guidance(self):
        for name in [
            "backend/AGENTS.md",
            ".agents/skills/backend-verification/SKILL.md",
        ]:
            with self.subTest(path=name):
                self.assertFalse(backend_required([name]))

    def test_skill_reference(self):
        self.assertFalse(
            backend_required([".agents/skills/example/references/review.md"])
        )

    def test_documentation_and_frontend(self):
        self.assertFalse(
            backend_required(["docs/guide.md", "frontend/src/app/App.tsx"])
        )

    def test_documentation_and_backend(self):
        self.assertTrue(
            backend_required(["docs/guide.md", "backend/src/linescope/main.py"])
        )

    def test_documentation_and_shared_configuration(self):
        self.assertTrue(backend_required(["AGENTS.md", "compose.yaml"]))

    def test_executable_skill_resource(self):
        self.assertTrue(backend_required([".agents/skills/example/scripts/check.py"]))

    def test_executable_under_docs(self):
        self.assertTrue(backend_required(["docs/example.py"]))

    def test_manual_event_runs_backend(self):
        with patch.dict(
            os.environ, {"CI_SCOPE_EVENT": "workflow_dispatch"}, clear=True
        ):
            self.assertTrue(detect_backend())

    def test_failed_diff_runs_backend(self):
        with (
            patch.dict(
                os.environ,
                {
                    "CI_SCOPE_EVENT": "push",
                    "CI_SCOPE_BASE": "base",
                    "CI_SCOPE_HEAD": "head",
                },
                clear=True,
            ),
            patch(
                "ci_scope.subprocess.check_output",
                side_effect=subprocess.CalledProcessError(1, "git"),
            ),
        ):
            self.assertTrue(detect_backend())


class VerificationTest(unittest.TestCase):
    def test_full_success(self):
        self.assertTrue(
            verification_succeeds("success", "true", "success", "success", "success")
        )

    def test_expected_skip(self):
        self.assertTrue(
            verification_succeeds("success", "false", "skipped", "skipped", "success")
        )

    def test_unexpected_skip(self):
        self.assertFalse(
            verification_succeeds("success", "true", "skipped", "success", "success")
        )

    def test_scope_failure(self):
        self.assertFalse(
            verification_succeeds("failure", "false", "skipped", "skipped", "success")
        )

    def test_backend_failure(self):
        self.assertFalse(
            verification_succeeds("success", "true", "failure", "success", "success")
        )

    def test_frontend_cancelled(self):
        self.assertFalse(
            verification_succeeds("success", "false", "skipped", "skipped", "cancelled")
        )
