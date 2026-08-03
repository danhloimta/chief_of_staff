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

import taskctl  # noqa: E402


class TaskCtlTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repository = self.root / "repository"
        self.repository.mkdir()
        self.git(self.repository, "init", "-q", "-b", "main")
        self.git(self.repository, "config", "user.email", "chief@example.com")
        self.git(self.repository, "config", "user.name", "Chief Test")
        (self.repository / "AGENTS.md").write_text("# Rules\n", encoding="utf-8")
        (self.repository / "src").mkdir()
        (self.repository / "src" / "feature.txt").write_text("before\n", encoding="utf-8")
        (self.repository / "bin").mkdir()
        runner = self.repository / "bin" / "test-safe"
        runner.write_text(
            "#!/bin/sh\n"
            "printf 'root-owned test ran\\n'\n"
            "test ! -f tests/root-fail\n",
            encoding="utf-8",
        )
        runner.chmod(0o755)
        self.git(self.repository, "add", ".")
        self.git(self.repository, "commit", "-qm", "base")
        self.base = self.git(self.repository, "rev-parse", "HEAD").stdout.strip()

        self.writer = self.root / "writer"
        self.git(
            self.repository,
            "worktree",
            "add",
            "-q",
            "-b",
            "agent/feature-fix",
            str(self.writer),
            self.base,
        )
        self.task_path = self.root / "ledger" / "task.json"
        self.task = {
            "artifact_type": "herdr_task",
            "schema_version": 3,
            "project_id": "classhub",
            "task_id": "feature-fix",
            "repository": str(self.repository),
            "target_branch": "main",
            "base_revision": self.base,
            "lane": "normal",
            "model": "gpt-5.6-terra",
            "effort": "medium",
            "workspace": "classhub-feature-fix",
            "owner": "writer",
            "objective": "Fix the feature",
            "context": "Focused regression",
            "requirements": ["Feature behaves correctly"],
            "owns": ["src/**", "tests/**"],
            "does_not_own": [".env", "config/**", "vendor/**"],
            "verification": ["bin/test-safe tests/Feature/FocusedTest.php"],
            "authority": {
                "edit": True,
                "commit": True,
                "network": False,
                "external_actions": [],
            },
            "done_when": ["Focused regression passes"],
            "dependencies": [],
            "instruction_layers": [str(self.repository / "AGENTS.md")],
        }
        taskctl.write_json(self.task_path, self.task)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(repository), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )

    def make_candidate(self, path: str = "src/feature.txt") -> str:
        candidate = self.writer / path
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text("after\n", encoding="utf-8")
        self.git(self.writer, "add", ".")
        self.git(self.writer, "commit", "-qm", "candidate")
        return self.git(self.writer, "rev-parse", "HEAD").stdout.strip()

    def make_evidence(self, revision: str, exit_code: int = 0) -> Path:
        evidence_path = self.root / "ledger" / "evidence.json"
        evidence = {
            "artifact_type": "herdr_evidence",
            "schema_version": 3,
            "project_id": "classhub",
            "task_id": "feature-fix",
            "records": [
                {
                    "command": "bin/test-safe tests/Feature/FocusedTest.php",
                    "exit_code": exit_code,
                    "observed_at": "2026-08-02T03:00:00Z",
                    "revision": revision,
                    "workspace": str(self.writer),
                    "output_digest": "sha256:" + ("a" * 64),
                }
            ],
        }
        taskctl.write_json(evidence_path, evidence)
        return evidence_path

    def make_handoff(
        self,
        revision: str,
        evidence: Path,
        changed: list[str],
        *,
        base: str | None = None,
    ) -> dict:
        return {
            "artifact_type": "herdr_handoff",
            "schema_version": 3,
            "project_id": "classhub",
            "task_id": "feature-fix",
            "result": "ready",
            "base_revision": base or self.base,
            "revision": revision,
            "changed_files": changed,
            "evidence": [str(evidence)],
            "questions": [],
            "dependencies": [],
        }

    def test_semantic_verification_accepts_matching_candidate_claim(self) -> None:
        revision = self.make_candidate()
        handoff = self.make_handoff(
            revision, self.make_evidence(revision), ["src/feature.txt"]
        )

        result = taskctl.semantic_verify_handoff(self.task, handoff)

        self.assertEqual(result["changed_files"], ["src/feature.txt"])
        self.assertEqual(result["revision"], revision)

    def test_classhub_normal_task_contract_rejects_sol(self) -> None:
        task = dict(self.task)
        task["model"] = "gpt-5.6-sol"

        with self.assertRaisesRegex(taskctl.ArtifactError, "managed tasks"):
            taskctl.validate_task(task, self.task_path)

    def test_classhub_high_risk_task_contract_also_rejects_sol(self) -> None:
        task = dict(self.task)
        task["lane"] = "high-risk"
        task["model"] = "gpt-5.6-sol"
        task["effort"] = "max"

        with self.assertRaisesRegex(taskctl.ArtifactError, "managed tasks"):
            taskctl.validate_task(task, self.task_path)

    def test_luna_max_task_contract_is_valid(self) -> None:
        task = dict(self.task)
        task["model"] = "gpt-5.6-luna"
        task["effort"] = "max"

        taskctl.validate_task(task, self.task_path)

    def test_legacy_v2_task_remains_valid_for_active_work(self) -> None:
        task = dict(self.task)
        task["schema_version"] = 2
        task.pop("model")
        task.pop("effort")

        taskctl.validate_task(task, self.task_path)

    def test_worker_cannot_move_locked_base_to_hide_forbidden_change(self) -> None:
        forbidden = self.writer / "config" / "unsafe.php"
        forbidden.parent.mkdir()
        forbidden.write_text("unsafe\n")
        self.git(self.writer, "add", ".")
        self.git(self.writer, "commit", "-qm", "forbidden")
        dishonest_base = self.git(self.writer, "rev-parse", "HEAD").stdout.strip()
        revision = self.make_candidate()
        handoff = self.make_handoff(
            revision,
            self.make_evidence(revision),
            ["src/feature.txt"],
            base=dishonest_base,
        )

        with self.assertRaisesRegex(taskctl.ArtifactError, "Root-locked"):
            taskctl.semantic_verify_handoff(self.task, handoff)

    def test_worker_evidence_must_reference_candidate_revision(self) -> None:
        revision = self.make_candidate()
        handoff = self.make_handoff(
            revision, self.make_evidence(self.base), ["src/feature.txt"]
        )

        with self.assertRaisesRegex(taskctl.ArtifactError, "candidate revision"):
            taskctl.semantic_verify_handoff(self.task, handoff)

    def test_root_runs_verification_in_clean_candidate_worktree(self) -> None:
        revision = self.make_candidate()
        handoff = self.make_handoff(
            revision, self.make_evidence(revision), ["src/feature.txt"]
        )

        verification = taskctl.root_verify(
            self.task,
            handoff,
            worktree=self.writer,
            phase="candidate",
            requirements_checked=self.task["requirements"],
            done_when_checked=self.task["done_when"],
            output_dir=self.root / "root-logs",
            timeout=10,
        )

        self.assertEqual(verification["result"], "pass")
        output = Path(verification["commands"][0]["output_file"]).read_text()
        self.assertIn("root-owned test ran", output)

        taskctl.verify_root_candidate(
            self.task,
            handoff,
            verification,
            worktree=self.writer,
            branch="agent/feature-fix",
        )
        verification["revision"] = self.base
        with self.assertRaisesRegex(taskctl.ArtifactError, "revision"):
            taskctl.verify_root_candidate(
                self.task,
                handoff,
                verification,
                worktree=self.writer,
                branch="agent/feature-fix",
            )

    def test_worker_claimed_pass_cannot_override_root_test_failure(self) -> None:
        revision = self.make_candidate()
        failure_marker = self.writer / "tests" / "root-fail"
        failure_marker.parent.mkdir()
        failure_marker.write_text("force failure\n")
        self.git(self.writer, "add", ".")
        self.git(self.writer, "commit", "-qm", "failing regression")
        revision = self.git(self.writer, "rev-parse", "HEAD").stdout.strip()
        handoff = self.make_handoff(
            revision,
            self.make_evidence(revision, exit_code=0),
            ["src/feature.txt", "tests/root-fail"],
        )

        verification = taskctl.root_verify(
            self.task,
            handoff,
            worktree=self.writer,
            phase="candidate",
            requirements_checked=self.task["requirements"],
            done_when_checked=self.task["done_when"],
            output_dir=self.root / "failing-root-logs",
            timeout=10,
        )

        self.assertEqual(verification["result"], "fail")
        self.assertNotEqual(verification["commands"][0]["exit_code"], 0)

    def test_accept_requires_post_integration_root_verification(self) -> None:
        revision = self.make_candidate()
        handoff = self.make_handoff(
            revision, self.make_evidence(revision), ["src/feature.txt"]
        )
        candidate_verification = taskctl.root_verify(
            self.task,
            handoff,
            worktree=self.writer,
            phase="candidate",
            requirements_checked=self.task["requirements"],
            done_when_checked=self.task["done_when"],
            output_dir=self.root / "candidate-logs",
            timeout=10,
        )

        with self.assertRaisesRegex(taskctl.ArtifactError, "integrated"):
            taskctl.verify_root_acceptance(self.task, handoff, candidate_verification)

        self.git(self.repository, "merge", "--ff-only", revision)
        integrated = taskctl.root_verify(
            self.task,
            handoff,
            worktree=self.repository,
            phase="integrated",
            requirements_checked=self.task["requirements"],
            done_when_checked=self.task["done_when"],
            output_dir=self.root / "integrated-logs",
            timeout=10,
        )
        taskctl.verify_root_acceptance(self.task, handoff, integrated)
        handoff_path = self.root / "ledger" / "handoff.json"
        verification_path = self.root / "ledger" / "integrated.json"
        decision_path = self.root / "ledger" / "decision.json"
        taskctl.write_json(handoff_path, handoff)
        taskctl.write_json(verification_path, integrated)
        with redirect_stdout(StringIO()):
            taskctl.command_decision_create(
                Namespace(
                    task=str(self.task_path),
                    handoff=str(handoff_path),
                    root_verification=str(verification_path),
                    event_id="evt-integrated",
                    decision="ACCEPT",
                    evidence_checked=["Root integrated verification passed"],
                    reason="All locked requirements and done conditions passed.",
                    output=str(decision_path),
                )
            )
        decision = taskctl.read_json(decision_path)
        self.assertEqual(decision["decision"], "ACCEPT")
        self.assertEqual(
            Path(decision["root_verification"]), verification_path.resolve()
        )

    def test_unsafe_verification_command_is_rejected(self) -> None:
        with self.assertRaisesRegex(taskctl.ArtifactError, "safe runner"):
            taskctl.verification_argv("php artisan dusk")
        with self.assertRaises(taskctl.ArtifactError):
            taskctl.verification_argv("bin/test-safe tests/Foo; rm -rf data")
        for command in (
            "vendor/bin/pint",
            "composer test:any-arbitrary-script",
            "npm run build",
        ):
            with self.subTest(command=command):
                with self.assertRaisesRegex(taskctl.ArtifactError, "safe runner"):
                    taskctl.verification_argv(command)

        self.assertEqual(
            taskctl.verification_argv("vendor/bin/pint --test"),
            ["vendor/bin/pint", "--test"],
        )

    def test_rename_checks_both_source_and_destination_scope(self) -> None:
        protected = self.writer / "AGENTS.md"
        destination = self.writer / "src" / "moved.txt"
        self.git(self.writer, "mv", str(protected), str(destination))
        self.git(self.writer, "commit", "-qm", "rename protected file")
        revision = self.git(self.writer, "rev-parse", "HEAD").stdout.strip()
        handoff = self.make_handoff(
            revision,
            self.make_evidence(revision),
            ["AGENTS.md", "src/moved.txt"],
        )
        task = dict(self.task)
        task["does_not_own"] = [*self.task["does_not_own"], "AGENTS.md"]

        with self.assertRaisesRegex(
            taskctl.ArtifactError, "outside owns|does_not_own"
        ):
            taskctl.semantic_verify_handoff(task, handoff)

    def test_read_only_investigation_requires_findings_and_no_commit(self) -> None:
        task = dict(self.task)
        task.update(
            {
                "schema_version": taskctl.SCHEMA_VERSION,
                "task_kind": "investigation",
                "authority": {
                    "edit": False,
                    "commit": False,
                    "network": False,
                    "external_actions": [],
                },
            }
        )
        evidence = self.make_evidence(self.base)
        evidence_value = taskctl.read_json(evidence)
        evidence_value["schema_version"] = taskctl.SCHEMA_VERSION
        taskctl.write_json(evidence, evidence_value)
        handoff = {
            "artifact_type": "herdr_handoff",
            "schema_version": taskctl.SCHEMA_VERSION,
            "project_id": task["project_id"],
            "task_id": task["task_id"],
            "result": "investigated",
            "base_revision": self.base,
            "revision": self.base,
            "changed_files": [],
            "evidence": [str(evidence)],
            "questions": [],
            "dependencies": [],
            "findings": ["The focused fixture exposes one reproducible defect."],
        }

        verification = taskctl.root_verify(
            task,
            handoff,
            worktree=self.writer,
            phase="investigation",
            requirements_checked=task["requirements"],
            done_when_checked=task["done_when"],
            output_dir=self.root / "investigation-logs",
            timeout=10,
        )

        self.assertEqual(verification["result"], "pass")
        taskctl.verify_root_investigation(
            task,
            handoff,
            verification,
            worktree=self.writer,
            branch="agent/feature-fix",
        )
        taskctl.verify_root_acceptance(task, handoff, verification)

    def test_investigated_handoff_is_exposed_by_cli_parser(self) -> None:
        args = taskctl.build_parser().parse_args(
            [
                "handoff-create",
                "--task",
                str(self.task_path),
                "--result",
                "investigated",
                "--base-revision",
                self.base,
                "--revision",
                self.base,
                "--finding",
                "One concrete finding",
                "--output",
                str(self.root / "ledger" / "investigation-handoff.json"),
            ]
        )

        self.assertEqual(args.result, "investigated")

    def test_focused_dusk_safe_command_is_allowed(self) -> None:
        command = (
            "bin/dusk-safe tests/Browser/Invoice/InvoiceShowFlowTest.php "
            "--filter=test_owner_can_view_invoice_detail"
        )

        self.assertEqual(
            taskctl.verification_argv(command),
            [
                "bin/dusk-safe",
                "tests/Browser/Invoice/InvoiceShowFlowTest.php",
                "--filter=test_owner_can_view_invoice_detail",
            ],
        )

    def test_direct_artisan_dusk_command_with_test_is_rejected(self) -> None:
        with self.assertRaisesRegex(taskctl.ArtifactError, "safe runner"):
            taskctl.verification_argv("php artisan dusk tests/Browser/FooTest.php")

    def test_ungated_accept_command_is_rejected(self) -> None:
        revision = self.make_candidate()
        evidence = self.make_evidence(revision)
        handoff = self.make_handoff(revision, evidence, ["src/feature.txt"])
        handoff_path = self.root / "ledger" / "handoff.json"
        taskctl.write_json(handoff_path, handoff)
        args = Namespace(
            task=str(self.task_path),
            handoff=str(handoff_path),
            root_verification=None,
            event_id="evt-1",
            decision="ACCEPT",
            evidence_checked=["claim"],
            reason="claimed ready",
            output=str(self.root / "ledger" / "decision.json"),
        )

        with self.assertRaisesRegex(taskctl.ArtifactError, "root-verification"):
            taskctl.command_decision_create(args)


if __name__ == "__main__":
    unittest.main()
