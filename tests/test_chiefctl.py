from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "herdr-orchestrator"))

import chiefctl  # noqa: E402


class ChiefCtlTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repository = self.root / "classhub"
        self.repository.mkdir()
        subprocess.run(
            ["git", "init", "-q", "-b", "main", str(self.repository)], check=True
        )
        subprocess.run(
            ["git", "-C", str(self.repository), "config", "user.email", "chief@example.com"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.repository), "config", "user.name", "Chief Test"],
            check=True,
        )
        (self.repository / "AGENTS.md").write_text("# ClassHub rules\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(self.repository), "add", "AGENTS.md"], check=True
        )
        subprocess.run(
            ["git", "-C", str(self.repository), "commit", "-qm", "base"], check=True
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_prepare_classhub_creates_contract_and_prompt(self) -> None:
        output = self.root / "runtime"
        args = Namespace(
            repository=str(self.repository),
            output_dir=str(output),
            task_id="invoice-fix",
            lane="high-risk",
            objective="Fix invoice totals",
            context="Totals are wrong after package changes.",
            requirement=["Preserve existing paid totals"],
            owns=["app/Modules/Invoice/**", "tests/Feature/Invoice/**"],
            does_not_own=["database/migrations/**"],
            verification=["bin/test-safe tests/Feature/Invoice"],
            done_when=["Invoice regression passes"],
            dependency=[],
            instruction_layer=[],
            owner="classhub-writer",
            workspace=None,
        )

        with redirect_stdout(StringIO()):
            chiefctl.command_prepare_classhub(args)

        task_path = output / "invoice-fix.task.json"
        prompt_path = output / "invoice-fix.prompt.md"
        self.assertTrue(task_path.is_file())
        self.assertTrue(prompt_path.is_file())
        task = __import__("json").loads(task_path.read_text())
        self.assertEqual(task["project_id"], "classhub")
        self.assertEqual(task["target_branch"], "main")
        self.assertEqual(task["lane"], "high-risk")
        self.assertEqual(len(task["base_revision"]), 40)
        self.assertIn(".env", task["does_not_own"])
        self.assertIn("AGENTS.md", task["does_not_own"])
        self.assertIn("ClassHub lane: high-risk", task["context"])
        self.assertIn("# ClassHub rules", prompt_path.read_text())

    def test_prepare_refuses_to_lock_a_dirty_target_checkout(self) -> None:
        (self.repository / "uncommitted.txt").write_text("user work\n")
        args = Namespace(
            repository=str(self.repository),
            output_dir=str(self.root / "runtime"),
            task_id="unsafe-start",
            lane="tiny",
            objective="Small fix",
            context="A small issue.",
            requirement=["Behavior is corrected"],
            owns=["app/**"],
            does_not_own=[],
            verification=["bin/test-safe tests/Feature/FocusedTest.php"],
            done_when=["Focused check passes"],
            dependency=[],
            instruction_layer=[],
            owner="classhub-writer",
            workspace=None,
        )

        with self.assertRaisesRegex(chiefctl.ChiefError, "must be clean"):
            chiefctl.command_prepare_classhub(args)


if __name__ == "__main__":
    unittest.main()
