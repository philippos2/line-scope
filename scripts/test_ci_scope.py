"""省略対象と必須checkの失敗条件を代表値・境界で検証する。"""

import unittest

from ci_scope import backend_required, verification_succeeds


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
