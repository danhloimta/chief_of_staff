from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "herdr-orchestrator"))

import chiefctl  # noqa: E402
import paseo_runtime  # noqa: E402
import taskctl  # noqa: E402


class FakePaseoClient:
    def __init__(self) -> None:
        self.workspace_id = "workspace_12345678"
        self.agent_id = "agent_123456789"
        self.worktree: Path | None = None
        self.sent_agent_ids: list[str] = []
        self.root_agent_id = "rootagent_123456"
        self.wait_result = {
            "agentId": self.agent_id,
            "status": "idle",
            "message": "Agent is idle.",
        }

    def version(self) -> str:
        return paseo_runtime.TESTED_PASEO_VERSION

    def status(self) -> dict:
        return {
            "localDaemon": "running",
            "connectedDaemon": "reachable",
            "cliVersion": paseo_runtime.TESTED_PASEO_VERSION,
            "daemonVersion": paseo_runtime.TESTED_PASEO_VERSION,
        }

    def provider_models(self, provider: str = "codex") -> list[dict]:
        self.provider = provider
        return [
            {
                "id": "gpt-5.6-luna",
                "model": "GPT-5.6 Luna",
                "thinkingOptionIds": ["reasoning-medium", "reasoning-max"],
            },
            {
                "id": "gpt-5.6-terra",
                "model": "GPT-5.6 Terra",
                "thinkingOptionIds": ["reasoning-medium", "reasoning-max"],
            },
        ]

    def create_local_workspace(self, path: Path, *, title: str) -> dict:
        self.worktree = path.resolve()
        self.workspace_title = title
        return {
            "workspaceId": self.workspace_id,
            "isolation": "local",
            "cwd": str(self.worktree),
        }

    def launch(self, **kwargs: object) -> dict:
        self.launch_kwargs = kwargs
        return {
            "agentId": self.agent_id,
            "status": "running",
            "provider": "codex",
            "cwd": str(self.worktree),
        }

    def inspect_agent(self, agent_id: str) -> dict:
        self.inspected_agent_id = agent_id
        if agent_id == self.root_agent_id:
            return {
                "Id": agent_id,
                "Provider": "codex",
                "Model": "gpt-5.6-sol",
                "Thinking": "reasoning-high",
                "Status": "running",
                "Cwd": str(ROOT.resolve()),
                "ParentAgentId": None,
                "Capabilities": {"Persistence": True},
            }
        return {
            "Id": agent_id,
            "Provider": "codex",
            "Model": "gpt-5.6-luna",
            "Thinking": "reasoning-max",
            "Status": "running",
            "Cwd": str(self.worktree),
            "ParentAgentId": os.environ.get("PASEO_AGENT_ID", "").strip() or None,
            "Capabilities": {"Persistence": True},
        }

    def list_workspaces(self) -> list[dict]:
        if self.worktree is None or not hasattr(self, "workspace_title"):
            return []
        return [
            {
                "workspaceId": self.workspace_id,
                "name": self.workspace_title,
                "isolation": "local",
                "cwd": str(self.worktree),
            }
        ]

    def list_agents(self, *, labels: dict[str, str] | None = None) -> list[dict]:
        del labels
        return [{"id": self.agent_id, "cwd": str(self.worktree)}]

    def wait(self, agent_id: str, timeout: int) -> dict:
        self.waited = (agent_id, timeout)
        return self.wait_result

    def send_correction(self, agent_id: str, prompt_file: Path) -> dict:
        self.sent_agent_ids.append(agent_id)
        self.correction_prompt = prompt_file.read_text(encoding="utf-8")
        return {"agentId": agent_id, "status": "sent"}

    def stop(self, agent_id: str) -> dict:
        return {"agentId": agent_id, "status": "stopped"}

    def archive_agent(self, agent_id: str) -> dict:
        self.archived_agent_id = agent_id
        return {"agentId": agent_id, "status": "archived"}

    def archive_workspace(self, workspace_id: str) -> dict:
        self.archived_workspace_id = workspace_id
        return {"workspaceId": workspace_id, "status": "archived"}


class ChiefCtlTest(unittest.TestCase):
    def setUp(self) -> None:
        self.environment_patch = patch.dict(
            os.environ, {"PASEO_AGENT_ID": ""}
        )
        self.environment_patch.start()
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
        (self.repository / "bin").mkdir()
        for name in ("harness", "test-safe"):
            executable = self.repository / "bin" / name
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)
        subprocess.run(
            ["git", "-C", str(self.repository), "add", "."], check=True
        )
        subprocess.run(
            ["git", "-C", str(self.repository), "commit", "-qm", "base"], check=True
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()
        self.environment_patch.stop()

    def test_default_repository_is_portable_and_overridable(self) -> None:
        self.assertEqual(chiefctl.default_repository({}), chiefctl.ROOT.parent / "classhub")
        self.assertEqual(
            chiefctl.default_repository({"CLASSHUB_REPOSITORY": "~/custom-classhub"}),
            Path.home() / "custom-classhub",
        )

    def test_prepare_classhub_creates_contract_and_prompt(self) -> None:
        output = self.root / "runtime"
        args = Namespace(
            repository=str(self.repository),
            output_dir=str(output),
            task_id="invoice-fix",
            lane="normal",
            task_kind="implementation",
            model=None,
            effort=None,
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

        stdout = StringIO()
        with redirect_stdout(stdout):
            chiefctl.command_prepare_classhub(args)

        task_path = output / "invoice-fix.task.json"
        prompt_path = output / "invoice-fix.prompt.md"
        self.assertTrue(task_path.is_file())
        self.assertTrue(prompt_path.is_file())
        task = __import__("json").loads(task_path.read_text())
        self.assertEqual(task["project_id"], "classhub")
        self.assertEqual(task["target_branch"], "main")
        self.assertEqual(task["lane"], "normal")
        self.assertEqual(task["task_kind"], "implementation")
        self.assertEqual(task["model"], "gpt-5.6-luna")
        self.assertEqual(task["effort"], "max")
        self.assertEqual(len(task["base_revision"]), 40)
        self.assertIn(".env", task["does_not_own"])
        self.assertIn("AGENTS.md", task["does_not_own"])
        self.assertIn("ClassHub lane: normal", task["context"])
        prompt = prompt_path.read_text()
        self.assertIn("# ClassHub rules", prompt)
        self.assertIn("model: gpt-5.6-luna", prompt)
        self.assertIn("effort: max", prompt)
        self.assertIn("nested delegation: forbidden", prompt)
        result = json.loads(stdout.getvalue())
        self.assertTrue(
            any(
                "gpt-5.6-luna/max" in step
                and "Paseo thinking ID" in step
                for step in result["next"]
            )
        )

    def prepare_runtime_task(self) -> tuple[Path, Path]:
        output = self.root / "runtime"
        args = Namespace(
            repository=str(self.repository),
            output_dir=str(output),
            task_id="runtime-fix",
            lane="normal",
            task_kind="implementation",
            model=None,
            effort=None,
            objective="Fix runtime behavior",
            context="A bounded fixture issue.",
            requirement=["Runtime behavior is corrected"],
            owns=["src/**", "tests/**"],
            does_not_own=[],
            verification=["bin/test-safe tests/Feature/RuntimeTest.php"],
            done_when=["Focused runtime check passes"],
            dependency=[],
            instruction_layer=[],
            owner="classhub-writer",
            workspace=None,
        )
        with redirect_stdout(StringIO()):
            chiefctl.command_prepare_classhub(args)
        return output / "runtime-fix.task.json", output / "runtime-fix.prompt.md"

    def prepare_investigation_task(self) -> tuple[Path, Path]:
        output = self.root / "investigation-runtime"
        args = Namespace(
            repository=str(self.repository),
            output_dir=str(output),
            task_id="find-runtime-bug",
            lane="normal",
            task_kind="investigation",
            model=None,
            effort=None,
            objective="Find the bounded runtime bug",
            context="Read-only investigation fixture.",
            requirement=["Identify one reproducible defect"],
            owns=["src/**", "tests/**"],
            does_not_own=[],
            verification=["bin/test-safe tests/Feature/RuntimeTest.php"],
            done_when=["Root reproduces the reported defect"],
            dependency=[],
            instruction_layer=[],
            owner="classhub-investigator",
            workspace=None,
        )
        with redirect_stdout(StringIO()):
            chiefctl.command_prepare_classhub(args)
        return output / "find-runtime-bug.task.json", output / "find-runtime-bug.prompt.md"

    def test_mocked_paseo_launch_wait_and_correction_reuse_one_agent(self) -> None:
        task_path, prompt_path = self.prepare_runtime_task()
        fake = FakePaseoClient()
        launch_args = Namespace(
            task=str(task_path),
            prompt=str(prompt_path),
            ledger=None,
            worktree=None,
            branch=None,
        )

        with patch.object(chiefctl, "require_live_client", return_value=fake):
            with redirect_stdout(StringIO()):
                chiefctl.command_paseo_launch(launch_args)

            ledger_path = task_path.parent / "runtime-fix.paseo-ledger.json"
            ledger = paseo_runtime.read_json(ledger_path)
            self.assertEqual(ledger["state"], "RUNNING")
            self.assertEqual(ledger["resources"]["agent"]["id"], fake.agent_id)
            self.assertEqual(ledger["resources"]["workspace"]["isolation"], "local")
            self.assertEqual(ledger["attempts"][0]["dispatch_sequence"], 1)
            launched_prompt = str(fake.launch_kwargs["prompt"])
            self.assertIn(
                f"Authoritative execution checkout: {Path(ledger['resources']['worktree']['path']).resolve()}",
                launched_prompt,
            )
            self.assertIn(
                f"Target trust-anchor repository: {self.repository.resolve()}",
                launched_prompt,
            )
            self.assertIn("authorized to run `git add` and `git commit`", launched_prompt)
            self.assertIn("Do not create agents or subagents", launched_prompt)
            worktree = Path(ledger["resources"]["worktree"]["path"])
            head = subprocess.run(
                ["git", "-C", str(worktree), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            self.assertEqual(head, ledger["target"]["base_revision"])

            with redirect_stdout(StringIO()):
                chiefctl.command_paseo_wait(
                    Namespace(
                        task=str(task_path),
                        ledger=None,
                        handoff=None,
                        timeout=321,
                    )
                )
            ledger = paseo_runtime.read_json(ledger_path)
            self.assertEqual(ledger["state"], "WAIT")
            self.assertEqual(fake.waited, (fake.agent_id, 321))
            target_head = subprocess.run(
                ["git", "-C", str(self.repository), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            self.assertEqual(target_head, ledger["target"]["base_revision"])

            correction = task_path.parent / "correction.md"
            correction.write_text("Fix the exact Root-reported failure.\n", encoding="utf-8")
            with redirect_stdout(StringIO()):
                chiefctl.command_paseo_correct(
                    Namespace(
                        task=str(task_path),
                        ledger=None,
                        prompt_file=str(correction),
                    )
                )
            ledger = paseo_runtime.read_json(ledger_path)
            self.assertEqual(ledger["state"], "RUNNING")
            self.assertEqual(len(ledger["attempts"]), 2)
            self.assertEqual(ledger["attempts"][1]["dispatch_sequence"], 2)
            self.assertEqual(fake.sent_agent_ids, [fake.agent_id])
            self.assertIn("Authoritative execution checkout:", fake.correction_prompt)
            self.assertIn("Fix the exact Root-reported failure.", fake.correction_prompt)

    def test_read_only_investigation_accepts_without_integrating_a_commit(self) -> None:
        task_path, prompt_path = self.prepare_investigation_task()
        task = taskctl.read_json(task_path)
        self.assertFalse(task["authority"]["edit"])
        self.assertFalse(task["authority"]["commit"])
        fake = FakePaseoClient()
        with patch.object(chiefctl, "require_live_client", return_value=fake):
            with redirect_stdout(StringIO()):
                chiefctl.command_paseo_launch(
                    Namespace(
                        task=str(task_path),
                        prompt=str(prompt_path),
                        ledger=None,
                        worktree=None,
                        branch=None,
                    )
                )
            ledger_path = task_path.parent / "find-runtime-bug.paseo-ledger.json"
            ledger = paseo_runtime.read_json(ledger_path)
            worktree = Path(ledger["resources"]["worktree"]["path"])
            evidence_path = task_path.parent / "find-runtime-bug.evidence.json"
            taskctl.write_json(
                evidence_path,
                {
                    "artifact_type": "herdr_evidence",
                    "schema_version": taskctl.SCHEMA_VERSION,
                    "project_id": task["project_id"],
                    "task_id": task["task_id"],
                    "records": [
                        {
                            "command": task["verification"][0],
                            "exit_code": 0,
                            "observed_at": "2026-08-03T03:00:00Z",
                            "revision": task["base_revision"],
                            "workspace": str(worktree),
                            "output_digest": "sha256:" + ("a" * 64),
                        }
                    ],
                },
            )
            handoff_path = task_path.parent / "find-runtime-bug.handoff.json"
            taskctl.write_json(
                handoff_path,
                {
                    "artifact_type": "herdr_handoff",
                    "schema_version": taskctl.SCHEMA_VERSION,
                    "project_id": task["project_id"],
                    "task_id": task["task_id"],
                    "result": "investigated",
                    "base_revision": task["base_revision"],
                    "revision": task["base_revision"],
                    "changed_files": [],
                    "evidence": [str(evidence_path)],
                    "questions": [],
                    "dependencies": [],
                    "findings": ["The focused runtime flow exposes a reproducible defect."],
                },
            )
            with redirect_stdout(StringIO()):
                chiefctl.command_paseo_wait(
                    Namespace(
                        task=str(task_path),
                        ledger=None,
                        handoff=str(handoff_path),
                        timeout=60,
                    )
                )
            ledger = paseo_runtime.read_json(ledger_path)
            self.assertEqual(ledger["state"], "HANDOFF_RECEIVED")

            verification_path = task_path.parent / "investigation.root-verification.json"
            verification = taskctl.root_verify(
                task,
                taskctl.read_json(handoff_path),
                worktree=worktree,
                phase="investigation",
                requirements_checked=task["requirements"],
                done_when_checked=task["done_when"],
                output_dir=task_path.parent / "investigation-logs",
                timeout=10,
            )
            taskctl.write_json(verification_path, verification)
            with redirect_stdout(StringIO()):
                chiefctl.command_paseo_record_gate(
                    Namespace(
                        task=str(task_path),
                        ledger=None,
                        gate="investigation-verified",
                        artifact=str(verification_path),
                    )
                )
            ledger = paseo_runtime.read_json(ledger_path)
            self.assertEqual(ledger["state"], "INVESTIGATION_VERIFIED")

            decision_path = task_path.parent / "find-runtime-bug.decision.json"
            with redirect_stdout(StringIO()):
                taskctl.command_decision_create(
                    Namespace(
                        task=str(task_path),
                        handoff=str(handoff_path),
                        root_verification=str(verification_path),
                        event_id=paseo_runtime.event_id(ledger),
                        decision="ACCEPT",
                        evidence_checked=["Root reproduced the finding"],
                        reason="The read-only finding was independently reproduced.",
                        output=str(decision_path),
                    )
                )
                chiefctl.command_paseo_record_gate(
                    Namespace(
                        task=str(task_path),
                        ledger=None,
                        gate="accepted",
                        artifact=str(decision_path),
                    )
                )

        final = paseo_runtime.read_json(ledger_path)
        self.assertEqual(final["state"], "ACCEPTED")
        target_head = subprocess.run(
            ["git", "-C", str(self.repository), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        self.assertEqual(target_head, task["base_revision"])

    def test_wait_persists_terminal_event_and_fails_on_nested_worker(self) -> None:
        task_path, prompt_path = self.prepare_runtime_task()
        fake = FakePaseoClient()
        with patch.object(chiefctl, "require_live_client", return_value=fake):
            with redirect_stdout(StringIO()):
                chiefctl.command_paseo_launch(
                    Namespace(
                        task=str(task_path),
                        prompt=str(prompt_path),
                        ledger=None,
                        worktree=None,
                        branch=None,
                    )
                )
            child_id = "childagent_123456"
            original_inspect = fake.inspect_agent

            def inspect(agent_id: str) -> dict:
                if agent_id == child_id:
                    return {"Id": child_id, "ParentAgentId": fake.agent_id}
                return original_inspect(agent_id)

            with patch.object(
                fake,
                "list_agents",
                side_effect=[
                    [{"id": fake.agent_id}],
                    [{"id": fake.agent_id}, {"id": child_id}],
                ],
            ):
                with patch.object(fake, "inspect_agent", side_effect=inspect):
                    with self.assertRaisesRegex(
                        paseo_runtime.PaseoRuntimeError, "forbidden nested"
                    ):
                        chiefctl.command_paseo_wait(
                            Namespace(
                                task=str(task_path),
                                ledger=None,
                                handoff=None,
                                timeout=90,
                            )
                        )

        ledger = paseo_runtime.read_json(
            task_path.parent / "runtime-fix.paseo-ledger.json"
        )
        self.assertEqual(ledger["state"], "FAILED")
        self.assertEqual(ledger["attempts"][0]["status"], "terminal")
        self.assertIn("topology violation", ledger["wait_reason"])

    def test_launch_recovers_workspace_after_create_response_is_lost(self) -> None:
        task_path, prompt_path = self.prepare_runtime_task()

        class LostResponseClient(FakePaseoClient):
            def __init__(self) -> None:
                super().__init__()
                self.lost_once = False

            def create_local_workspace(self, path: Path, *, title: str) -> dict:
                value = super().create_local_workspace(path, title=title)
                if not self.lost_once:
                    self.lost_once = True
                    raise paseo_runtime.PaseoRuntimeError(
                        "simulated lost workspace response"
                    )
                return value

        fake = LostResponseClient()
        args = Namespace(
            task=str(task_path),
            prompt=str(prompt_path),
            ledger=None,
            worktree=None,
            branch=None,
        )
        with patch.object(chiefctl, "require_live_client", return_value=fake):
            with self.assertRaisesRegex(
                paseo_runtime.PaseoRuntimeError, "lost workspace response"
            ):
                chiefctl.command_paseo_launch(args)
            with redirect_stdout(StringIO()):
                chiefctl.command_paseo_launch(args)

        ledger = paseo_runtime.read_json(
            task_path.parent / "runtime-fix.paseo-ledger.json"
        )
        self.assertEqual(ledger["resources"]["workspace"]["id"], fake.workspace_id)
        self.assertEqual(ledger["state"], "RUNNING")
        self.assertEqual(len(ledger["attempts"]), 1)

    def test_mocked_paseo_flow_accepts_only_after_both_root_verifications(self) -> None:
        task_path, prompt_path = self.prepare_runtime_task()
        task = taskctl.read_json(task_path)
        fake = FakePaseoClient()
        with patch.object(chiefctl, "require_live_client", return_value=fake):
            with redirect_stdout(StringIO()):
                chiefctl.command_paseo_launch(
                    Namespace(
                        task=str(task_path),
                        prompt=str(prompt_path),
                        ledger=None,
                        worktree=None,
                        branch=None,
                    )
                )

            ledger_path = task_path.parent / "runtime-fix.paseo-ledger.json"
            ledger = paseo_runtime.read_json(ledger_path)
            worktree = Path(ledger["resources"]["worktree"]["path"])
            changed = worktree / "src" / "runtime.txt"
            changed.parent.mkdir()
            changed.write_text("fixed\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(worktree), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(worktree), "commit", "-qm", "fix runtime"],
                check=True,
            )
            revision = subprocess.run(
                ["git", "-C", str(worktree), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            evidence_path = task_path.parent / "runtime-fix.evidence.json"
            taskctl.write_json(
                evidence_path,
                {
                    "artifact_type": "herdr_evidence",
                    "schema_version": taskctl.SCHEMA_VERSION,
                    "project_id": task["project_id"],
                    "task_id": task["task_id"],
                    "records": [
                        {
                            "command": task["verification"][0],
                            "exit_code": 0,
                            "observed_at": "2026-08-02T03:00:00Z",
                            "revision": revision,
                            "workspace": str(worktree),
                            "output_digest": "sha256:" + ("a" * 64),
                        }
                    ],
                },
            )
            handoff_path = task_path.parent / "runtime-fix.handoff.json"
            taskctl.write_json(
                handoff_path,
                {
                    "artifact_type": "herdr_handoff",
                    "schema_version": taskctl.SCHEMA_VERSION,
                    "project_id": task["project_id"],
                    "task_id": task["task_id"],
                    "result": "ready",
                    "base_revision": task["base_revision"],
                    "revision": revision,
                    "changed_files": ["src/runtime.txt"],
                    "evidence": [str(evidence_path)],
                    "questions": [],
                    "dependencies": [],
                    "findings": [],
                },
            )

            evidence = taskctl.read_json(evidence_path)
            evidence["records"][0]["workspace"] = str(self.repository)
            taskctl.write_json(evidence_path, evidence)
            ledger = paseo_runtime.read_json(ledger_path)
            with self.assertRaisesRegex(
                chiefctl.ChiefError, "exact writer worktree"
            ):
                chiefctl.verify_handoff_checkout(
                    task, taskctl.read_json(handoff_path), ledger
                )
            evidence["records"][0]["workspace"] = str(worktree)
            taskctl.write_json(evidence_path, evidence)

            with redirect_stdout(StringIO()):
                chiefctl.command_paseo_wait(
                    Namespace(
                        task=str(task_path),
                        ledger=None,
                        handoff=str(handoff_path),
                        timeout=900,
                    )
                )
            ledger = paseo_runtime.read_json(ledger_path)
            self.assertEqual(ledger["state"], "HANDOFF_RECEIVED")

            candidate_path = task_path.parent / "candidate.root-verification.json"
            candidate = taskctl.root_verify(
                task,
                taskctl.read_json(handoff_path),
                worktree=worktree,
                phase="candidate",
                requirements_checked=task["requirements"],
                done_when_checked=task["done_when"],
                output_dir=task_path.parent / "candidate-logs",
                timeout=10,
            )
            taskctl.write_json(candidate_path, candidate)
            with redirect_stdout(StringIO()):
                chiefctl.command_paseo_record_gate(
                    Namespace(
                        task=str(task_path),
                        ledger=None,
                        gate="candidate",
                        artifact=str(candidate_path),
                    )
                )
            ledger = paseo_runtime.read_json(ledger_path)
            self.assertEqual(ledger["state"], "CANDIDATE_VERIFIED")

            original_handoff = handoff_path.read_bytes()
            handoff_path.write_bytes(original_handoff + b"\n")
            with self.assertRaisesRegex(
                paseo_runtime.PaseoRuntimeError, "changed after its gate"
            ):
                chiefctl.command_paseo_record_gate(
                    Namespace(
                        task=str(task_path),
                        ledger=None,
                        gate="integrated",
                        artifact=None,
                    )
                )
            handoff_path.write_bytes(original_handoff)

            subprocess.run(
                ["git", "-C", str(self.repository), "merge", "--ff-only", revision],
                check=True,
                capture_output=True,
                text=True,
            )
            with redirect_stdout(StringIO()):
                chiefctl.command_paseo_record_gate(
                    Namespace(
                        task=str(task_path),
                        ledger=None,
                        gate="integrated",
                        artifact=None,
                    )
                )

            integrated_path = task_path.parent / "integrated.root-verification.json"
            integrated = taskctl.root_verify(
                task,
                taskctl.read_json(handoff_path),
                worktree=self.repository,
                phase="integrated",
                requirements_checked=task["requirements"],
                done_when_checked=task["done_when"],
                output_dir=task_path.parent / "integrated-logs",
                timeout=10,
            )
            taskctl.write_json(integrated_path, integrated)
            with redirect_stdout(StringIO()):
                chiefctl.command_paseo_record_gate(
                    Namespace(
                        task=str(task_path),
                        ledger=None,
                        gate="integrated-verified",
                        artifact=str(integrated_path),
                    )
                )

            decision_path = task_path.parent / "runtime-fix.decision.json"
            ledger = paseo_runtime.read_json(ledger_path)
            with redirect_stdout(StringIO()):
                taskctl.command_decision_create(
                    Namespace(
                        task=str(task_path),
                        handoff=str(handoff_path),
                        root_verification=str(integrated_path),
                        event_id=paseo_runtime.event_id(ledger),
                        decision="ACCEPT",
                        evidence_checked=["Root integrated verification passed"],
                        reason="Both Root-owned verification phases passed.",
                        output=str(decision_path),
                    )
                )

            late_change = self.repository / "late-untracked.txt"
            late_change.write_text("late user change\n", encoding="utf-8")
            with self.assertRaisesRegex(taskctl.ArtifactError, "clean"):
                chiefctl.command_paseo_record_gate(
                    Namespace(
                        task=str(task_path),
                        ledger=None,
                        gate="accepted",
                        artifact=str(decision_path),
                    )
                )
            late_change.unlink()
            with redirect_stdout(StringIO()):
                chiefctl.command_paseo_record_gate(
                    Namespace(
                        task=str(task_path),
                        ledger=None,
                        gate="accepted",
                        artifact=str(decision_path),
                    )
                )

            final_ledger = paseo_runtime.read_json(ledger_path)
            self.assertEqual(final_ledger["state"], "ACCEPTED")
            self.assertEqual(
                Path(final_ledger["artifacts"]["integrated_verification"]).resolve(),
                integrated_path.resolve(),
            )

    def test_doctor_live_checks_paseo_context_routes_and_persistence(self) -> None:
        fake = FakePaseoClient()
        fake.worktree = ROOT.resolve()
        policy = self.root / "PASEO_ORCHESTRATOR.md"
        policy.write_text("# policy\n", encoding="utf-8")
        root_id = "rootagent_123456"

        with patch.object(chiefctl.shutil, "which", return_value="/opt/paseo"):
            with patch.object(chiefctl, "PASEO_POLICY", policy):
                checks, ready = chiefctl.doctor(
                    self.repository,
                    True,
                    client=fake,
                    environment={"PASEO_AGENT_ID": root_id},
                )

        self.assertTrue(ready, checks)
        self.assertTrue(any(item["name"] == "paseo_codex_routes" for item in checks))

    def test_doctor_live_accepts_external_root_in_chief_repository(self) -> None:
        fake = FakePaseoClient()
        policy = self.root / "PASEO_ORCHESTRATOR.md"
        policy.write_text("# policy\n", encoding="utf-8")

        with patch.object(chiefctl.shutil, "which", return_value="/opt/paseo"):
            with patch.object(chiefctl, "PASEO_POLICY", policy):
                checks, ready = chiefctl.doctor(
                    self.repository,
                    True,
                    client=fake,
                    environment={},
                    current_cwd=ROOT,
                )

        self.assertTrue(ready, checks)
        root_context = next(
            item for item in checks if item["name"] == "paseo_root_context"
        )
        self.assertIn('"mode": "external"', root_context["detail"])

    def test_doctor_live_rejects_external_root_from_another_directory(self) -> None:
        fake = FakePaseoClient()
        policy = self.root / "PASEO_ORCHESTRATOR.md"
        policy.write_text("# policy\n", encoding="utf-8")

        with patch.object(chiefctl.shutil, "which", return_value="/opt/paseo"):
            with patch.object(chiefctl, "PASEO_POLICY", policy):
                checks, ready = chiefctl.doctor(
                    self.repository,
                    True,
                    client=fake,
                    environment={},
                    current_cwd=self.root,
                )

        self.assertFalse(ready)
        self.assertTrue(
            any(item["name"] == "paseo_root_mode" and not item["ok"] for item in checks)
        )

    def test_doctor_live_rejects_version_mismatch_and_missing_persistence(self) -> None:
        fake = FakePaseoClient()
        fake.worktree = ROOT.resolve()
        fake.workspace_title = "root"
        policy = self.root / "PASEO_ORCHESTRATOR.md"
        policy.write_text("# policy\n", encoding="utf-8")

        with patch.object(chiefctl.shutil, "which", return_value="/opt/paseo"):
            with patch.object(chiefctl, "PASEO_POLICY", policy):
                with patch.object(
                    fake,
                    "status",
                    return_value={
                        "localDaemon": "running",
                        "connectedDaemon": "reachable",
                        "cliVersion": paseo_runtime.TESTED_PASEO_VERSION,
                        "daemonVersion": "0.2.4",
                    },
                ):
                    checks, ready = chiefctl.doctor(
                        self.repository,
                        True,
                        client=fake,
                        environment={"PASEO_AGENT_ID": fake.root_agent_id},
                    )
                self.assertFalse(ready)
                self.assertTrue(
                    any(
                        item["name"] == "paseo_live_capabilities"
                        and "version mismatch" in item["detail"]
                        for item in checks
                    )
                )

                root = fake.inspect_agent(fake.root_agent_id)
                root["Cwd"] = str(ROOT.resolve())
                root["Capabilities"]["Persistence"] = False
                with patch.object(fake, "inspect_agent", return_value=root):
                    checks, ready = chiefctl.doctor(
                        self.repository,
                        True,
                        client=fake,
                        environment={"PASEO_AGENT_ID": fake.root_agent_id},
                    )
                self.assertFalse(ready)
                self.assertTrue(
                    any(
                        item["name"] == "paseo_root_context" and not item["ok"]
                        for item in checks
                    )
                )

    def test_launch_recovers_exact_worktree_after_ledger_save_interruption(self) -> None:
        task_path, prompt_path = self.prepare_runtime_task()
        fake = FakePaseoClient()
        original_save = paseo_runtime.save_ledger
        interrupted = False

        def interrupt_once(path: Path, ledger: dict) -> None:
            nonlocal interrupted
            if ledger["state"] == "WORKTREE_READY" and not interrupted:
                interrupted = True
                raise OSError("simulated atomic ledger interruption")
            original_save(path, ledger)

        args = Namespace(
            task=str(task_path),
            prompt=str(prompt_path),
            ledger=None,
            worktree=None,
            branch=None,
        )
        with patch.object(chiefctl, "require_live_client", return_value=fake):
            with patch.object(paseo_runtime, "save_ledger", side_effect=interrupt_once):
                with self.assertRaisesRegex(OSError, "simulated"):
                    chiefctl.command_paseo_launch(args)

            with redirect_stdout(StringIO()):
                chiefctl.command_paseo_launch(args)

        ledger = paseo_runtime.read_json(
            task_path.parent / "runtime-fix.paseo-ledger.json"
        )
        self.assertEqual(ledger["state"], "RUNNING")
        self.assertEqual(len(ledger["attempts"]), 1)

    def test_archive_refuses_unaccepted_candidate_without_touching_paseo(self) -> None:
        task_path, prompt_path = self.prepare_runtime_task()
        fake = FakePaseoClient()
        with patch.object(chiefctl, "require_live_client", return_value=fake):
            with redirect_stdout(StringIO()):
                chiefctl.command_paseo_launch(
                    Namespace(
                        task=str(task_path),
                        prompt=str(prompt_path),
                        ledger=None,
                        worktree=None,
                        branch=None,
                    )
                )
            with self.assertRaisesRegex(chiefctl.ChiefError, "ACCEPTED"):
                chiefctl.command_paseo_archive(
                    Namespace(task=str(task_path), ledger=None)
                )

        self.assertFalse(hasattr(fake, "archived_workspace_id"))

    def test_archive_discard_empty_requires_wait_and_clean_base(self) -> None:
        task_path, prompt_path = self.prepare_runtime_task()
        fake = FakePaseoClient()
        with patch.object(chiefctl, "require_live_client", return_value=fake):
            with redirect_stdout(StringIO()):
                chiefctl.command_paseo_launch(
                    Namespace(
                        task=str(task_path),
                        prompt=str(prompt_path),
                        ledger=None,
                        worktree=None,
                        branch=None,
                    )
                )
            with self.assertRaisesRegex(chiefctl.ChiefError, "WAIT/FAILED"):
                chiefctl.command_paseo_archive(
                    Namespace(task=str(task_path), ledger=None, discard_empty=True)
                )
            with redirect_stdout(StringIO()):
                chiefctl.command_paseo_wait(
                    Namespace(
                        task=str(task_path),
                        ledger=None,
                        handoff=None,
                        timeout=30,
                    )
                )
                chiefctl.command_paseo_archive(
                    Namespace(task=str(task_path), ledger=None, discard_empty=True)
                )

        self.assertEqual(fake.archived_workspace_id, fake.workspace_id)
        ledger = paseo_runtime.read_json(
            task_path.parent / "runtime-fix.paseo-ledger.json"
        )
        self.assertTrue(ledger["cleanup"]["workspace_archived"])
        self.assertIn("No candidate existed", ledger["cleanup"]["retained_reason"])

    def test_ledger_target_tampering_is_rejected_before_reconciliation(self) -> None:
        task_path, prompt_path = self.prepare_runtime_task()
        fake = FakePaseoClient()
        with patch.object(chiefctl, "require_live_client", return_value=fake):
            with redirect_stdout(StringIO()):
                chiefctl.command_paseo_launch(
                    Namespace(
                        task=str(task_path),
                        prompt=str(prompt_path),
                        ledger=None,
                        worktree=None,
                        branch=None,
                    )
                )
        ledger_path = task_path.parent / "runtime-fix.paseo-ledger.json"
        ledger = paseo_runtime.read_json(ledger_path)
        ledger["target"]["base_revision"] = "f" * 40
        paseo_runtime.save_ledger(ledger_path, ledger)

        with self.assertRaisesRegex(
            paseo_runtime.PaseoRuntimeError, "exact task contract"
        ):
            chiefctl.task_context(str(task_path), None)

    def test_prepare_refuses_to_lock_a_dirty_target_checkout(self) -> None:
        (self.repository / "uncommitted.txt").write_text("user work\n")
        args = Namespace(
            repository=str(self.repository),
            output_dir=str(self.root / "runtime"),
            task_id="unsafe-start",
            lane="tiny",
            task_kind="implementation",
            model=None,
            effort=None,
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

    def test_prepare_rejects_high_risk_and_existing_task_identity(self) -> None:
        task_path, _ = self.prepare_runtime_task()
        args = Namespace(
            repository=str(self.repository),
            output_dir=str(task_path.parent),
            task_id="runtime-fix",
            lane="normal",
            task_kind="implementation",
            model=None,
            effort=None,
            objective="Do not overwrite",
            context="Existing task identity",
            requirement=["Keep original contract"],
            owns=["src/**"],
            does_not_own=[],
            verification=["bin/test-safe tests/Feature/RuntimeTest.php"],
            done_when=["Original task remains"],
            dependency=[],
            instruction_layer=[],
            owner="classhub-writer",
            workspace=None,
        )
        with self.assertRaisesRegex(chiefctl.ChiefError, "overwrite"):
            chiefctl.command_prepare_classhub(args)

        args.task_id = "high-risk-not-supported"
        args.lane = "high-risk"
        with self.assertRaisesRegex(chiefctl.ChiefError, "only tiny and normal"):
            chiefctl.command_prepare_classhub(args)

    def test_tiny_task_defaults_to_luna_medium(self) -> None:
        model, effort = chiefctl.route_classhub_model("tiny", None, None)

        self.assertEqual(model, "gpt-5.6-luna")
        self.assertEqual(effort, "medium")

    def test_classhub_writer_route_rejects_sol(self) -> None:
        with self.assertRaisesRegex(chiefctl.ChiefError, "Sol is not allowed"):
            chiefctl.route_classhub_model("normal", "gpt-5.6-sol", "medium")

    def test_normal_and_high_risk_tasks_default_to_luna_max(self) -> None:
        self.assertEqual(
            chiefctl.route_classhub_model("normal", None, None),
            ("gpt-5.6-luna", "max"),
        )
        self.assertEqual(
            chiefctl.route_classhub_model("high-risk", None, None),
            ("gpt-5.6-luna", "max"),
        )

    def test_explicit_luna_xhigh_is_supported(self) -> None:
        self.assertEqual(
            chiefctl.route_classhub_model("normal", "gpt-5.6-luna", "xhigh"),
            ("gpt-5.6-luna", "xhigh"),
        )


if __name__ == "__main__":
    unittest.main()
