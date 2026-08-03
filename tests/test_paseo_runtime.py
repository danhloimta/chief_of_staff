from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "herdr-orchestrator"))

import paseo_runtime  # noqa: E402


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.responses: list[subprocess.CompletedProcess[str]] = []

    def queue(
        self,
        value: object | str,
        *,
        returncode: int = 0,
        stderr: str = "",
    ) -> None:
        stdout = value if isinstance(value, str) else json.dumps(value)
        self.responses.append(
            subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)
        )

    def __call__(self, command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        self.calls.append(command)
        if not self.responses:
            raise AssertionError(f"unexpected command: {command}")
        response = self.responses.pop(0)
        return subprocess.CompletedProcess(
            command,
            response.returncode,
            stdout=response.stdout,
            stderr=response.stderr,
        )


class FakeClient:
    def __init__(
        self,
        *,
        workspaces: list[dict] | None = None,
        agents: list[dict] | None = None,
        inspections: dict[str, dict] | None = None,
    ) -> None:
        self.workspaces = workspaces or []
        self.agents = agents or []
        self.inspections = inspections or {}

    def list_workspaces(self) -> list[dict]:
        return self.workspaces

    def list_agents(self, *, labels: dict[str, str] | None = None) -> list[dict]:
        del labels
        return self.agents

    def inspect_agent(self, agent_id: str) -> dict:
        return self.inspections[agent_id]


class PaseoRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repository = self.root / "repository"
        self.repository.mkdir()
        self.git(self.repository, "init", "-q", "-b", "main")
        self.git(self.repository, "config", "user.email", "chief@example.com")
        self.git(self.repository, "config", "user.name", "Chief Test")
        (self.repository / "file.txt").write_text("base\n", encoding="utf-8")
        self.git(self.repository, "add", "file.txt")
        self.git(self.repository, "commit", "-qm", "base")
        self.base = self.git(self.repository, "rev-parse", "HEAD").stdout.strip()
        self.task_path = self.root / "task" / "task.json"
        self.task_path.parent.mkdir()
        self.task = {
            "project_id": "fixture",
            "task_id": "bug-fix",
            "repository": str(self.repository),
            "target_branch": "main",
            "base_revision": self.base,
            "owner": "writer",
            "model": "gpt-5.6-luna",
            "effort": "max",
        }

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

    def make_ledger(self) -> tuple[Path, dict]:
        path = self.root / "task" / "bug-fix.paseo-ledger.json"
        ledger = paseo_runtime.create_ledger(
            self.task,
            self.task_path,
            path,
            worktree_path=self.root / "worktree",
            worktree_branch="chief/fixture/bug-fix",
        )
        return path, ledger

    def test_client_uses_argv_and_explicit_local_workspace(self) -> None:
        runner = FakeRunner()
        runner.queue(
            {
                "workspaceId": "workspace_12345678",
                "isolation": "local",
                "cwd": str(self.root),
            }
        )
        client = paseo_runtime.PaseoClient("/opt/paseo", runner=runner)

        result = client.create_local_workspace(self.root, title="fixture-task")

        self.assertEqual(result["workspaceId"], "workspace_12345678")
        self.assertEqual(
            runner.calls[0],
            [
                "/opt/paseo",
                "workspace",
                "create",
                "--isolation",
                "local",
                "--path",
                str(self.root.resolve()),
                "--title",
                "fixture-task",
                "--json",
            ],
        )

    def test_client_rejects_malformed_json_even_on_zero_exit(self) -> None:
        runner = FakeRunner()
        runner.queue("not-json")
        client = paseo_runtime.PaseoClient("paseo", runner=runner)

        with self.assertRaisesRegex(paseo_runtime.PaseoRuntimeError, "malformed JSON"):
            client.status()

    def test_archive_requires_exact_structured_identity_and_status(self) -> None:
        runner = FakeRunner()
        runner.queue(
            {
                "workspaceId": "workspace_12345678",
                "status": "archived",
                "archivedAt": "2026-08-02T03:00:00Z",
            }
        )
        client = paseo_runtime.PaseoClient("paseo", runner=runner)

        client.archive_workspace("workspace_12345678")

        self.assertEqual(
            runner.calls[0],
            [
                "paseo",
                "workspace",
                "archive",
                "workspace_12345678",
                "--json",
            ],
        )
        runner.queue(
            {
                "agentId": "different_agent_123",
                "status": "archived",
            }
        )
        with self.assertRaisesRegex(
            paseo_runtime.PaseoRuntimeError, "different agent"
        ):
            client.archive_agent("agent_123456789")

    def test_client_never_uses_a_shell_string_for_launch(self) -> None:
        runner = FakeRunner()
        runner.queue(
            {
                "agentId": "agent_123456789",
                "status": "running",
                "provider": "codex",
                "cwd": str(self.root),
            }
        )
        client = paseo_runtime.PaseoClient("paseo", runner=runner)

        client.launch(
            workspace_id="workspace_12345678",
            model="gpt-5.6-luna",
            thinking="reasoning-max",
            title="task:writer",
            labels={"chief.task_id": "bug-fix"},
            prompt="Fix the bug; do not push.",
        )

        command = runner.calls[0]
        self.assertIsInstance(command, list)
        self.assertEqual(command[-1], "Fix the bug; do not push.")
        self.assertIn("--background", command)
        self.assertNotIn("--output-schema", command)

    def test_resolve_thinking_id_requires_one_deterministic_mapping(self) -> None:
        models = [
            {
                "id": "gpt-5.6-luna",
                "model": "GPT-5.6 Luna",
                "thinkingOptionIds": ["reasoning-medium", "reasoning-max"],
            }
        ]

        self.assertEqual(
            paseo_runtime.resolve_thinking_id(models, "gpt-5.6-luna", "max"),
            "reasoning-max",
        )
        with self.assertRaisesRegex(paseo_runtime.PaseoRuntimeError, "Cannot map"):
            paseo_runtime.resolve_thinking_id(models, "gpt-5.6-luna", "high")

    def test_attempts_are_durable_idempotent_and_cannot_skip_acceptance(self) -> None:
        ledger_path, ledger = self.make_ledger()
        paseo_runtime.transition(ledger, "WORKTREE_READY")
        first = paseo_runtime.new_attempt(ledger, "initial", kind="launch")
        paseo_runtime.save_ledger(ledger_path, ledger)
        paseo_runtime.record_dispatch(ledger, first["attempt_id"], "agent_123456789")
        changed = paseo_runtime.record_terminal_signal(
            ledger,
            first["attempt_id"],
            status="idle",
            message="Agent is idle.",
        )

        self.assertTrue(changed)
        self.assertEqual(ledger["state"], "WAIT")
        self.assertFalse(
            paseo_runtime.record_terminal_signal(
                ledger,
                first["attempt_id"],
                status="idle",
                message="Agent is idle.",
            )
        )
        with self.assertRaisesRegex(paseo_runtime.PaseoRuntimeError, "Invalid coordinator"):
            paseo_runtime.transition(ledger, "ACCEPTED")

        paseo_runtime.transition(ledger, "REVISE")
        second = paseo_runtime.new_attempt(ledger, "correction", kind="correction")
        paseo_runtime.record_dispatch(ledger, second["attempt_id"], "agent_123456789")
        self.assertFalse(
            paseo_runtime.record_terminal_signal(
                ledger,
                first["attempt_id"],
                status="idle",
                message="Agent is idle.",
            )
        )
        self.assertEqual(ledger["state"], "RUNNING")
        self.assertEqual(second["dispatch_sequence"], 2)

    def test_full_task_contract_is_bound_by_digest(self) -> None:
        _, ledger = self.make_ledger()
        changed = dict(self.task)
        changed["requirements"] = ["weakened after launch"]

        with self.assertRaisesRegex(
            paseo_runtime.PaseoRuntimeError, "exact task contract"
        ):
            paseo_runtime.assert_ledger_task_binding(
                ledger, changed, self.task_path
            )

    def test_bound_artifact_rejects_content_changes(self) -> None:
        _, ledger = self.make_ledger()
        artifact = self.root / "handoff.json"
        paseo_runtime.atomic_write_json(artifact, {"revision": self.base})
        paseo_runtime.bind_artifact(ledger, "handoff", artifact)

        paseo_runtime.atomic_write_json(artifact, {"revision": "f" * 40})

        with self.assertRaisesRegex(
            paseo_runtime.PaseoRuntimeError, "changed after its gate"
        ):
            paseo_runtime.read_bound_artifact(ledger, "handoff")

    def test_ambiguous_correction_can_be_resolved_without_ledger_editing(self) -> None:
        _, ledger = self.make_ledger()
        paseo_runtime.transition(ledger, "WORKTREE_READY")
        launch = paseo_runtime.new_attempt(ledger, "initial", kind="launch")
        paseo_runtime.record_dispatch(ledger, launch["attempt_id"], "agent_123456789")
        paseo_runtime.record_terminal_signal(
            ledger, launch["attempt_id"], status="idle", message="needs correction"
        )
        paseo_runtime.transition(ledger, "REVISE")
        correction = paseo_runtime.new_attempt(
            ledger, "correction", kind="correction"
        )
        paseo_runtime.transition(ledger, "WAIT", wait_reason="delivery ambiguous")

        paseo_runtime.resolve_ambiguous_correction(ledger, delivered=True)

        self.assertEqual(ledger["state"], "RUNNING")
        self.assertEqual(correction["status"], "running")

        paseo_runtime.record_terminal_signal(
            ledger, correction["attempt_id"], status="idle", message="retry"
        )
        paseo_runtime.transition(ledger, "REVISE")
        second = paseo_runtime.new_attempt(ledger, "second", kind="correction")
        paseo_runtime.transition(ledger, "WAIT", wait_reason="delivery ambiguous")

        paseo_runtime.resolve_ambiguous_correction(ledger, delivered=False)

        self.assertEqual(second["status"], "terminal")
        next_attempt = paseo_runtime.new_attempt(
            ledger, "safe retry", kind="correction"
        )
        self.assertEqual(next_attempt["dispatch_sequence"], 4)

    def test_worktree_is_created_from_exact_locked_base(self) -> None:
        worktree = self.root / "writer"
        branch = "chief/fixture/bug-fix"

        paseo_runtime.create_task_worktree(
            self.task,
            worktree=worktree,
            branch=branch,
        )

        self.assertEqual(
            self.git(worktree, "rev-parse", "HEAD").stdout.strip(), self.base
        )
        self.assertEqual(
            self.git(worktree, "branch", "--show-current").stdout.strip(), branch
        )

    def test_worktree_creation_fails_when_target_branch_moved(self) -> None:
        (self.repository / "other.txt").write_text("moved\n", encoding="utf-8")
        self.git(self.repository, "add", "other.txt")
        self.git(self.repository, "commit", "-qm", "move target")

        with self.assertRaisesRegex(paseo_runtime.PaseoRuntimeError, "Target branch moved"):
            paseo_runtime.create_task_worktree(
                self.task,
                worktree=self.root / "writer",
                branch="chief/fixture/bug-fix",
            )

    def test_workspace_agent_git_chain_is_verified(self) -> None:
        worktree = self.root / "writer"
        paseo_runtime.create_task_worktree(
            self.task,
            worktree=worktree,
            branch="chief/fixture/bug-fix",
        )
        inspection = {
            "Id": "agent_123456789",
            "Provider": "codex",
            "Model": "gpt-5.6-luna",
            "Thinking": "reasoning-max",
            "Cwd": str(worktree),
            "ParentAgentId": "rootagent_123456",
            "Capabilities": {"Persistence": True},
        }
        client = FakeClient(
            workspaces=[
                {
                    "workspaceId": "workspace_12345678",
                    "isolation": "local",
                    "cwd": str(worktree),
                }
            ]
        )

        paseo_runtime.verify_agent_inspection(
            inspection,
            agent_id="agent_123456789",
            model="gpt-5.6-luna",
            thinking="reasoning-max",
            worktree=worktree,
            root_agent_id="rootagent_123456",
        )
        paseo_runtime.verify_workspace_chain(
            client,
            workspace_id="workspace_12345678",
            worktree=worktree,
            agent_inspection=inspection,
        )

        client.workspaces[0]["isolation"] = "worktree"
        observed = paseo_runtime.verify_workspace_chain(
            client,
            workspace_id="workspace_12345678",
            worktree=worktree,
            agent_inspection=inspection,
        )
        self.assertEqual(observed["isolation"], "worktree")

        inspection["Cwd"] = str(self.root / "wrong")
        with self.assertRaisesRegex(paseo_runtime.PaseoRuntimeError, "differs"):
            paseo_runtime.verify_workspace_chain(
                client,
                workspace_id="workspace_12345678",
                worktree=worktree,
                agent_inspection=inspection,
            )

    def test_nested_worker_child_is_rejected(self) -> None:
        child = "childagent_123456"
        worker = "workeragent_12345"
        client = FakeClient(
            agents=[{"id": worker}, {"id": child}],
            inspections={
                child: {"Id": child, "ParentAgentId": worker},
            },
        )

        with self.assertRaisesRegex(paseo_runtime.PaseoRuntimeError, "forbidden nested"):
            paseo_runtime.assert_no_worker_children(client, worker)

    def test_lost_launch_response_requires_exactly_one_label_and_cwd_match(self) -> None:
        _, ledger = self.make_ledger()
        paseo_runtime.transition(ledger, "WORKTREE_READY")
        attempt = paseo_runtime.new_attempt(ledger, "initial", kind="launch")
        worktree = Path(ledger["resources"]["worktree"]["path"])
        client = FakeClient(
            agents=[
                {
                    "id": "agent_123456789",
                    "cwd": str(worktree),
                }
            ]
        )

        recovered = paseo_runtime.reconcile_lost_launch(
            client,
            ledger,
            attempt_id=attempt["attempt_id"],
            worktree=worktree,
        )

        self.assertEqual(recovered, "agent_123456789")

        ambiguous = FakeClient(agents=[])
        with self.assertRaisesRegex(paseo_runtime.PaseoRuntimeError, "found 0"):
            paseo_runtime.reconcile_lost_launch(
                ambiguous,
                ledger,
                attempt_id=attempt["attempt_id"],
                worktree=worktree,
            )
        self.assertEqual(ledger["state"], "WAIT")


if __name__ == "__main__":
    unittest.main()
