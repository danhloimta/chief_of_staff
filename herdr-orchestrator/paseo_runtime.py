#!/usr/bin/env python3
"""Deterministic Paseo control-plane helpers for the Chief of Staff MVP."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


TESTED_PASEO_VERSION = "0.2.5"
LEDGER_SCHEMA_VERSION = 2
LEDGER_ARTIFACT_TYPE = "paseo_coordinator_ledger"
OPAQUE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,}$")
TASK_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
PASEO_STATES = {
    "PREPARED",
    "WORKTREE_READY",
    "RUNNING",
    "HANDOFF_RECEIVED",
    "CANDIDATE_VERIFIED",
    "INTEGRATED",
    "INTEGRATED_VERIFIED",
    "INVESTIGATION_VERIFIED",
    "ACCEPTED",
    "WAIT",
    "REVISE",
    "FAILED",
    "RETAINED",
}
ALLOWED_TRANSITIONS = {
    "PREPARED": {"WORKTREE_READY", "WAIT", "FAILED", "RETAINED"},
    "WORKTREE_READY": {"RUNNING", "WAIT", "FAILED", "RETAINED"},
    "RUNNING": {"HANDOFF_RECEIVED", "WAIT", "REVISE", "FAILED", "RETAINED"},
    "HANDOFF_RECEIVED": {
        "CANDIDATE_VERIFIED",
        "INVESTIGATION_VERIFIED",
        "REVISE",
        "WAIT",
        "FAILED",
        "RETAINED",
    },
    "CANDIDATE_VERIFIED": {"INTEGRATED", "REVISE", "WAIT", "FAILED", "RETAINED"},
    "INTEGRATED": {"INTEGRATED_VERIFIED", "WAIT", "FAILED", "RETAINED"},
    "INTEGRATED_VERIFIED": {"ACCEPTED", "WAIT", "FAILED", "RETAINED"},
    "INVESTIGATION_VERIFIED": {"ACCEPTED", "WAIT", "FAILED", "RETAINED"},
    "WAIT": {"RUNNING", "HANDOFF_RECEIVED", "REVISE", "FAILED", "RETAINED"},
    "REVISE": {"RUNNING", "WAIT", "FAILED", "RETAINED"},
    "FAILED": {"RETAINED"},
    "RETAINED": set(),
    "ACCEPTED": set(),
}


class PaseoRuntimeError(RuntimeError):
    """Raised when deterministic Paseo orchestration cannot proceed safely."""


Runner = Callable[..., subprocess.CompletedProcess[str]]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    rendered = json.dumps(value, indent=2, sort_keys=True) + "\n"
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(rendered)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def atomic_write_text(path: Path, value: str) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(value)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PaseoRuntimeError(f"Paseo ledger not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PaseoRuntimeError(
            f"Invalid JSON in {path}: line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    if not isinstance(value, dict):
        raise PaseoRuntimeError(f"Expected a JSON object: {path}")
    return value


def canonical_digest(value: Any) -> str:
    rendered = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(rendered).hexdigest()


def file_digest(path: Path) -> str:
    try:
        content = path.resolve().read_bytes()
    except OSError as exc:
        raise PaseoRuntimeError(f"Cannot read bound artifact: {path.resolve()}") from exc
    return "sha256:" + hashlib.sha256(content).hexdigest()


def require_full_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not OPAQUE_ID_PATTERN.fullmatch(value):
        raise PaseoRuntimeError(f"{field} must be a full opaque Paseo ID")
    return value


def require_task_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not TASK_ID_PATTERN.fullmatch(value):
        raise PaseoRuntimeError(f"{field} is not a safe task identity")
    return value


def require_absolute_path(value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise PaseoRuntimeError(f"{field} must be a non-empty absolute path")
    path = Path(value)
    if not path.is_absolute():
        raise PaseoRuntimeError(f"{field} must be an absolute path")
    return path.resolve()


def validate_ledger(ledger: dict[str, Any]) -> None:
    required = {
        "artifact_type",
        "schema_version",
        "project_id",
        "task_id",
        "task",
        "task_digest",
        "state",
        "created_at",
        "updated_at",
        "target",
        "resources",
        "attempts",
        "active_attempt_id",
        "artifacts",
        "artifact_digests",
        "cleanup",
        "last_reconciled_at",
        "wait_reason",
    }
    missing = sorted(required - ledger.keys())
    unknown = sorted(ledger.keys() - required)
    if missing or unknown:
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unknown:
            details.append("unknown: " + ", ".join(unknown))
        raise PaseoRuntimeError("Invalid Paseo ledger fields: " + "; ".join(details))
    if ledger["artifact_type"] != LEDGER_ARTIFACT_TYPE:
        raise PaseoRuntimeError("Invalid Paseo ledger artifact_type")
    if ledger["schema_version"] != LEDGER_SCHEMA_VERSION:
        raise PaseoRuntimeError("Unsupported Paseo ledger schema_version")
    require_task_id(ledger["project_id"], "project_id")
    require_task_id(ledger["task_id"], "task_id")
    require_absolute_path(ledger["task"], "task")
    if not isinstance(ledger["task_digest"], str) or not re.fullmatch(
        r"sha256:[0-9a-f]{64}", ledger["task_digest"]
    ):
        raise PaseoRuntimeError("task_digest must be a SHA-256 digest")
    if ledger["state"] not in PASEO_STATES:
        raise PaseoRuntimeError(f"Invalid coordinator state: {ledger['state']}")
    target = ledger["target"]
    if not isinstance(target, dict) or set(target) != {
        "repository",
        "branch",
        "base_revision",
    }:
        raise PaseoRuntimeError("Invalid ledger target")
    require_absolute_path(target["repository"], "target.repository")
    if not isinstance(target["branch"], str) or not target["branch"].strip():
        raise PaseoRuntimeError("target.branch must be non-empty")
    if not isinstance(target["base_revision"], str) or not re.fullmatch(
        r"[0-9a-f]{40}|[0-9a-f]{64}", target["base_revision"]
    ):
        raise PaseoRuntimeError("target.base_revision must be a full Git hash")
    resources = ledger["resources"]
    if not isinstance(resources, dict) or set(resources) != {
        "worktree",
        "workspace",
        "agent",
    }:
        raise PaseoRuntimeError("Invalid ledger resources")
    worktree = resources["worktree"]
    if not isinstance(worktree, dict) or set(worktree) != {"path", "branch", "created"}:
        raise PaseoRuntimeError("Invalid worktree resource")
    if worktree["path"] is not None:
        require_absolute_path(worktree["path"], "resources.worktree.path")
    if not isinstance(worktree["branch"], str) or not worktree["branch"].strip():
        raise PaseoRuntimeError("resources.worktree.branch must be non-empty")
    if not isinstance(worktree["created"], bool):
        raise PaseoRuntimeError("resources.worktree.created must be boolean")
    workspace = resources["workspace"]
    if not isinstance(workspace, dict) or set(workspace) != {
        "id",
        "created",
        "isolation",
        "observed_isolation",
        "name",
    }:
        raise PaseoRuntimeError("Invalid workspace resource")
    if workspace["id"] is not None:
        require_full_id(workspace["id"], "resources.workspace.id")
    if workspace["isolation"] != "local":
        raise PaseoRuntimeError("MVP Paseo workspace isolation must be local")
    if workspace["observed_isolation"] not in {None, "local", "worktree"}:
        raise PaseoRuntimeError("Invalid observed Paseo workspace classification")
    if not isinstance(workspace["name"], str) or not workspace["name"].strip():
        raise PaseoRuntimeError("resources.workspace.name must be non-empty")
    if not isinstance(workspace["created"], bool):
        raise PaseoRuntimeError("resources.workspace.created must be boolean")
    agent = resources["agent"]
    expected_agent_keys = {
        "id",
        "created",
        "role",
        "provider",
        "model",
        "effort",
        "thinking",
        "parent_agent_id",
        "persistence",
    }
    if not isinstance(agent, dict) or set(agent) != expected_agent_keys:
        raise PaseoRuntimeError("Invalid agent resource")
    if agent["id"] is not None:
        require_full_id(agent["id"], "resources.agent.id")
    if agent["parent_agent_id"] is not None:
        require_full_id(agent["parent_agent_id"], "resources.agent.parent_agent_id")
    if not isinstance(agent["created"], bool):
        raise PaseoRuntimeError("resources.agent.created must be boolean")
    attempts = ledger["attempts"]
    if not isinstance(attempts, list):
        raise PaseoRuntimeError("attempts must be a list")
    sequences: list[int] = []
    ids: set[str] = set()
    for attempt in attempts:
        if not isinstance(attempt, dict) or set(attempt) != {
            "attempt_id",
            "dispatch_sequence",
            "kind",
            "status",
            "prompt_digest",
            "created_at",
            "dispatched_at",
            "terminal_at",
            "terminal_status",
            "wait_message",
            "agent_id",
        }:
            raise PaseoRuntimeError("Invalid attempt record")
        attempt_id = require_full_id(attempt["attempt_id"], "attempt_id")
        if attempt_id in ids:
            raise PaseoRuntimeError("Duplicate attempt_id")
        ids.add(attempt_id)
        sequence = attempt["dispatch_sequence"]
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence <= 0:
            raise PaseoRuntimeError("dispatch_sequence must be a positive integer")
        sequences.append(sequence)
        if attempt["kind"] not in {"launch", "correction"}:
            raise PaseoRuntimeError("attempt kind must be launch or correction")
        if attempt["status"] not in {"dispatching", "running", "terminal"}:
            raise PaseoRuntimeError("Invalid attempt status")
        if not isinstance(attempt["prompt_digest"], str) or not re.fullmatch(
            r"sha256:[0-9a-f]{64}", attempt["prompt_digest"]
        ):
            raise PaseoRuntimeError("Invalid attempt prompt_digest")
        if attempt["agent_id"] is not None:
            require_full_id(attempt["agent_id"], "attempt.agent_id")
    if sequences != list(range(1, len(sequences) + 1)):
        raise PaseoRuntimeError("dispatch_sequence values must be monotonic and contiguous")
    active_attempt_id = ledger["active_attempt_id"]
    if active_attempt_id is not None and active_attempt_id not in ids:
        raise PaseoRuntimeError("active_attempt_id does not identify a recorded attempt")
    if not isinstance(ledger["artifacts"], dict) or set(ledger["artifacts"]) != {
        "handoff",
        "candidate_verification",
        "integrated_verification",
        "decision",
    }:
        raise PaseoRuntimeError("Invalid artifact linkage")
    for name, artifact_path in ledger["artifacts"].items():
        if artifact_path is not None:
            require_absolute_path(artifact_path, f"artifacts.{name}")
    artifact_digests = ledger["artifact_digests"]
    if not isinstance(artifact_digests, dict) or set(artifact_digests) != set(
        ledger["artifacts"]
    ):
        raise PaseoRuntimeError("Invalid artifact digest linkage")
    for name, digest in artifact_digests.items():
        if digest is not None and (
            not isinstance(digest, str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
        ):
            raise PaseoRuntimeError(f"artifact_digests.{name} must be a SHA-256 digest")
        if (ledger["artifacts"][name] is None) != (digest is None):
            raise PaseoRuntimeError(f"artifact path/digest mismatch for {name}")
    if not isinstance(ledger["cleanup"], dict) or set(ledger["cleanup"]) != {
        "agent_archived",
        "workspace_archived",
        "worktree_removed",
        "retained_reason",
    }:
        raise PaseoRuntimeError("Invalid cleanup record")
    for name in ("agent_archived", "workspace_archived", "worktree_removed"):
        if not isinstance(ledger["cleanup"][name], bool):
            raise PaseoRuntimeError(f"cleanup.{name} must be boolean")
    retained_reason = ledger["cleanup"]["retained_reason"]
    if retained_reason is not None and (
        not isinstance(retained_reason, str) or not retained_reason.strip()
    ):
        raise PaseoRuntimeError("cleanup.retained_reason must be null or non-empty")


def assert_ledger_task_binding(
    ledger: dict[str, Any], task: dict[str, Any], task_path: Path
) -> None:
    """Bind durable coordinator state to the exact immutable task contract."""
    validate_ledger(ledger)
    expected_target = {
        "repository": str(Path(task["repository"]).resolve()),
        "branch": task["target_branch"],
        "base_revision": task["base_revision"],
    }
    agent = ledger["resources"]["agent"]
    if (
        ledger["project_id"] != task["project_id"]
        or ledger["task_id"] != task["task_id"]
        or Path(ledger["task"]).resolve() != task_path.resolve()
        or ledger["target"] != expected_target
        or agent["role"] != task["owner"]
        or agent["model"] != task.get("model")
        or agent["effort"] != task.get("effort")
        or ledger["task_digest"] != canonical_digest(task)
    ):
        raise PaseoRuntimeError("Paseo ledger is not bound to the exact task contract")


def create_ledger(
    task: dict[str, Any],
    task_path: Path,
    ledger_path: Path,
    *,
    worktree_path: Path,
    worktree_branch: str,
) -> dict[str, Any]:
    if ledger_path.exists():
        ledger = read_json(ledger_path)
        assert_ledger_task_binding(ledger, task, task_path)
        recorded_worktree = ledger["resources"]["worktree"]
        if (
            Path(recorded_worktree["path"]).resolve() != worktree_path.resolve()
            or recorded_worktree["branch"] != worktree_branch
        ):
            raise PaseoRuntimeError(
                "Existing Paseo ledger uses a different worktree identity"
            )
        return ledger
    now = utc_now()
    ledger = {
        "artifact_type": LEDGER_ARTIFACT_TYPE,
        "schema_version": LEDGER_SCHEMA_VERSION,
        "project_id": task["project_id"],
        "task_id": task["task_id"],
        "task": str(task_path.resolve()),
        "task_digest": canonical_digest(task),
        "state": "PREPARED",
        "created_at": now,
        "updated_at": now,
        "target": {
            "repository": str(Path(task["repository"]).resolve()),
            "branch": task["target_branch"],
            "base_revision": task["base_revision"],
        },
        "resources": {
            "worktree": {
                "path": str(worktree_path.resolve()),
                "branch": worktree_branch,
                "created": False,
            },
            "workspace": {
                "id": None,
                "created": False,
                "isolation": "local",
                "observed_isolation": None,
                "name": (
                    f"{task['project_id']}-{task['task_id']}-"
                    f"{uuid.uuid4().hex[:12]}"
                ),
            },
            "agent": {
                "id": None,
                "created": False,
                "role": task["owner"],
                "provider": "codex",
                "model": task.get("model"),
                "effort": task.get("effort"),
                "thinking": None,
                "parent_agent_id": None,
                "persistence": None,
            },
        },
        "attempts": [],
        "active_attempt_id": None,
        "artifacts": {
            "handoff": None,
            "candidate_verification": None,
            "integrated_verification": None,
            "decision": None,
        },
        "artifact_digests": {
            "handoff": None,
            "candidate_verification": None,
            "integrated_verification": None,
            "decision": None,
        },
        "cleanup": {
            "agent_archived": False,
            "workspace_archived": False,
            "worktree_removed": False,
            "retained_reason": None,
        },
        "last_reconciled_at": None,
        "wait_reason": None,
    }
    validate_ledger(ledger)
    atomic_write_json(ledger_path, ledger)
    return ledger


def save_ledger(path: Path, ledger: dict[str, Any]) -> None:
    ledger["updated_at"] = utc_now()
    validate_ledger(ledger)
    atomic_write_json(path, ledger)


def bind_artifact(
    ledger: dict[str, Any], name: str, path: Path
) -> dict[str, Any]:
    if name not in ledger["artifacts"]:
        raise PaseoRuntimeError(f"Unknown ledger artifact slot: {name}")
    resolved = path.resolve()
    value = read_json(resolved)
    ledger["artifacts"][name] = str(resolved)
    ledger["artifact_digests"][name] = file_digest(resolved)
    return value


def read_bound_artifact(ledger: dict[str, Any], name: str) -> dict[str, Any]:
    if name not in ledger["artifacts"]:
        raise PaseoRuntimeError(f"Unknown ledger artifact slot: {name}")
    path_value = ledger["artifacts"][name]
    digest = ledger["artifact_digests"][name]
    if path_value is None or digest is None:
        raise PaseoRuntimeError(f"Ledger has no bound {name} artifact")
    path = Path(path_value).resolve()
    if file_digest(path) != digest:
        raise PaseoRuntimeError(f"Bound {name} artifact changed after its gate")
    return read_json(path)


def transition(
    ledger: dict[str, Any],
    next_state: str,
    *,
    wait_reason: str | None = None,
) -> bool:
    current = ledger["state"]
    if next_state == current:
        return False
    if next_state not in ALLOWED_TRANSITIONS.get(current, set()):
        raise PaseoRuntimeError(f"Invalid coordinator transition: {current} -> {next_state}")
    ledger["state"] = next_state
    ledger["wait_reason"] = wait_reason if next_state in {"WAIT", "FAILED", "RETAINED"} else None
    return True


def new_attempt(ledger: dict[str, Any], prompt: str, *, kind: str) -> dict[str, Any]:
    if kind not in {"launch", "correction"}:
        raise PaseoRuntimeError("Attempt kind must be launch or correction")
    if kind == "launch" and ledger["state"] != "WORKTREE_READY":
        raise PaseoRuntimeError("Initial launch requires WORKTREE_READY state")
    if kind == "correction" and ledger["state"] not in {"REVISE", "WAIT"}:
        raise PaseoRuntimeError("Correction requires REVISE or WAIT state")
    active = active_attempt(ledger)
    if active and active["status"] != "terminal":
        raise PaseoRuntimeError("Cannot dispatch while the previous attempt is active")
    sequence = len(ledger["attempts"]) + 1
    attempt = {
        "attempt_id": f"att_{uuid.uuid4().hex}",
        "dispatch_sequence": sequence,
        "kind": kind,
        "status": "dispatching",
        "prompt_digest": "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "created_at": utc_now(),
        "dispatched_at": None,
        "terminal_at": None,
        "terminal_status": None,
        "wait_message": None,
        "agent_id": ledger["resources"]["agent"]["id"],
    }
    ledger["attempts"].append(attempt)
    ledger["active_attempt_id"] = attempt["attempt_id"]
    return attempt


def active_attempt(ledger: dict[str, Any]) -> dict[str, Any] | None:
    active_id = ledger.get("active_attempt_id")
    if active_id is None:
        return None
    for attempt in ledger["attempts"]:
        if attempt["attempt_id"] == active_id:
            return attempt
    raise PaseoRuntimeError("active_attempt_id is missing from attempts")


def record_dispatch(
    ledger: dict[str, Any],
    attempt_id: str,
    agent_id: str,
) -> None:
    attempt = active_attempt(ledger)
    if not attempt or attempt["attempt_id"] != attempt_id:
        raise PaseoRuntimeError("Dispatch does not match the active attempt")
    if attempt["status"] != "dispatching":
        raise PaseoRuntimeError("Attempt is not awaiting dispatch")
    full_agent_id = require_full_id(agent_id, "agent_id")
    existing = ledger["resources"]["agent"]["id"]
    if existing is not None and existing != full_agent_id:
        raise PaseoRuntimeError("Correction was addressed to a different agent")
    attempt["agent_id"] = full_agent_id
    attempt["status"] = "running"
    attempt["dispatched_at"] = utc_now()
    ledger["resources"]["agent"]["id"] = full_agent_id
    ledger["resources"]["agent"]["created"] = True
    transition(ledger, "RUNNING")


def record_terminal_signal(
    ledger: dict[str, Any],
    attempt_id: str,
    *,
    status: str,
    message: str,
) -> bool:
    attempt = next(
        (item for item in ledger["attempts"] if item["attempt_id"] == attempt_id),
        None,
    )
    if attempt is None:
        raise PaseoRuntimeError("Terminal signal references an unknown attempt")
    if ledger["active_attempt_id"] != attempt_id:
        return False
    if attempt["status"] == "terminal":
        if attempt["terminal_status"] == status and attempt["wait_message"] == message:
            return False
        raise PaseoRuntimeError("Contradictory terminal signal for the active attempt")
    if attempt["status"] != "running":
        raise PaseoRuntimeError("Cannot record a terminal signal before dispatch")
    if status not in {"idle", "completed", "timeout", "permission", "error"}:
        raise PaseoRuntimeError(f"Unsupported Paseo terminal status: {status}")
    attempt["status"] = "terminal"
    attempt["terminal_at"] = utc_now()
    attempt["terminal_status"] = status
    attempt["wait_message"] = message
    if status == "error":
        transition(ledger, "FAILED", wait_reason=message or "Paseo agent error")
    else:
        transition(
            ledger,
            "WAIT",
            wait_reason=message or f"Paseo attempt ended with {status}; handoff not verified",
        )
    return True


def resolve_ambiguous_correction(
    ledger: dict[str, Any], *, delivered: bool
) -> None:
    attempt = active_attempt(ledger)
    if (
        ledger["state"] != "WAIT"
        or not attempt
        or attempt["kind"] != "correction"
        or attempt["status"] != "dispatching"
    ):
        raise PaseoRuntimeError(
            "Ambiguous correction resolution requires a WAIT correction in dispatching state"
        )
    if delivered:
        agent_id = require_full_id(
            ledger["resources"]["agent"]["id"], "agent_id"
        )
        record_dispatch(ledger, attempt["attempt_id"], agent_id)
        return
    attempt["status"] = "terminal"
    attempt["terminal_at"] = utc_now()
    attempt["terminal_status"] = "error"
    attempt["wait_message"] = (
        "Root confirmed that the ambiguous correction was not delivered"
    )
    ledger["wait_reason"] = attempt["wait_message"]


def event_id(ledger: dict[str, Any], attempt_id: str | None = None) -> str:
    selected = attempt_id or ledger.get("active_attempt_id")
    if not selected:
        raise PaseoRuntimeError("Cannot derive an event ID without an attempt")
    agent_id = ledger["resources"]["agent"]["id"]
    require_full_id(agent_id, "agent_id")
    return f"paseo:{ledger['project_id']}:{ledger['task_id']}:{agent_id}:{selected}"


class PaseoClient:
    """Small argv-only adapter over the tested Paseo CLI."""

    def __init__(self, binary: str = "paseo", *, runner: Runner | None = None):
        self.binary = binary
        self.runner = runner or subprocess.run

    def _run(self, arguments: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            return self.runner(
                [self.binary, *arguments],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            raise PaseoRuntimeError(f"Cannot execute Paseo CLI: {exc}") from exc

    def text(self, arguments: list[str]) -> str:
        result = self._run(arguments)
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
            raise PaseoRuntimeError(f"Paseo command failed: {detail}")
        return result.stdout.strip()

    def json(self, arguments: list[str]) -> Any:
        result = self._run(arguments)
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
            raise PaseoRuntimeError(f"Paseo command failed: {detail}")
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise PaseoRuntimeError(
                f"Paseo command returned malformed JSON: line {exc.lineno}, "
                f"column {exc.colno}: {exc.msg}"
            ) from exc
        if isinstance(value, dict) and isinstance(value.get("error"), dict):
            error = value["error"]
            raise PaseoRuntimeError(
                f"Paseo error {error.get('code', 'UNKNOWN')}: "
                f"{error.get('message', 'unknown error')}"
            )
        return value

    def version(self) -> str:
        return self.text(["--version"])

    def status(self) -> dict[str, Any]:
        value = self.json(["status", "--json"])
        if not isinstance(value, dict):
            raise PaseoRuntimeError("Paseo status must be a JSON object")
        return value

    def provider_models(self, provider: str = "codex") -> list[dict[str, Any]]:
        value = self.json(["provider", "models", provider, "--thinking", "--json"])
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise PaseoRuntimeError("Paseo provider models must be a JSON list")
        return value

    def create_local_workspace(self, path: Path, *, title: str) -> dict[str, Any]:
        value = self.json(
            [
                "workspace",
                "create",
                "--isolation",
                "local",
                "--path",
                str(path.resolve()),
                "--title",
                title,
                "--json",
            ]
        )
        if not isinstance(value, dict):
            raise PaseoRuntimeError("Paseo workspace create must return an object")
        require_full_id(value.get("workspaceId"), "workspaceId")
        return value

    def list_workspaces(self) -> list[dict[str, Any]]:
        value = self.json(["workspace", "ls", "--json"])
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise PaseoRuntimeError("Paseo workspace ls must return a list")
        return value

    def launch(
        self,
        *,
        workspace_id: str,
        model: str,
        thinking: str,
        title: str,
        labels: dict[str, str],
        prompt: str,
    ) -> dict[str, Any]:
        require_full_id(workspace_id, "workspace_id")
        arguments = [
            "run",
            "--workspace",
            workspace_id,
            "--provider",
            "codex",
            "--model",
            model,
            "--thinking",
            thinking,
            "--title",
            title,
        ]
        for key, value in sorted(labels.items()):
            arguments.extend(["--label", f"{key}={value}"])
        arguments.extend(["--background", "--json", prompt])
        value = self.json(arguments)
        if not isinstance(value, dict):
            raise PaseoRuntimeError("Paseo run must return an object")
        require_full_id(value.get("agentId"), "agentId")
        return value

    def inspect_agent(self, agent_id: str) -> dict[str, Any]:
        require_full_id(agent_id, "agent_id")
        value = self.json(["inspect", "--json", agent_id])
        if not isinstance(value, dict):
            raise PaseoRuntimeError("Paseo inspect must return an object")
        require_full_id(value.get("Id"), "inspect.Id")
        return value

    def list_agents(self, *, labels: dict[str, str] | None = None) -> list[dict[str, Any]]:
        arguments = ["ls", "--global"]
        for key, value in sorted((labels or {}).items()):
            arguments.extend(["--label", f"{key}={value}"])
        arguments.append("--json")
        result = self.json(arguments)
        if not isinstance(result, list) or any(not isinstance(item, dict) for item in result):
            raise PaseoRuntimeError("Paseo ls must return a list")
        for item in result:
            require_full_id(item.get("id"), "agent.id")
        return result

    def send_correction(self, agent_id: str, prompt_file: Path) -> dict[str, Any]:
        require_full_id(agent_id, "agent_id")
        value = self.json(
            [
                "send",
                "--no-wait",
                "--prompt-file",
                str(prompt_file.resolve()),
                "--json",
                agent_id,
            ]
        )
        if not isinstance(value, dict):
            raise PaseoRuntimeError("Paseo send must return an object")
        if require_full_id(value.get("agentId"), "send.agentId") != agent_id:
            raise PaseoRuntimeError("Paseo correction was delivered to a different agent")
        return value

    def wait(self, agent_id: str, timeout: int) -> dict[str, Any]:
        require_full_id(agent_id, "agent_id")
        if timeout <= 0:
            raise PaseoRuntimeError("Paseo wait timeout must be positive")
        value = self.json(["wait", "--json", "--timeout", str(timeout), agent_id])
        if not isinstance(value, dict):
            raise PaseoRuntimeError("Paseo wait must return an object")
        if require_full_id(value.get("agentId"), "wait.agentId") != agent_id:
            raise PaseoRuntimeError("Paseo wait resolved a different agent")
        if value.get("status") not in {"idle", "completed", "timeout", "permission", "error"}:
            raise PaseoRuntimeError("Paseo wait returned an unsupported status")
        return value

    def stop(self, agent_id: str) -> dict[str, Any]:
        require_full_id(agent_id, "agent_id")
        value = self.json(["stop", "--json", agent_id])
        if not isinstance(value, dict):
            raise PaseoRuntimeError("Paseo stop must return an object")
        return value

    def archive_agent(self, agent_id: str) -> dict[str, Any]:
        require_full_id(agent_id, "agent_id")
        value = self.json(["archive", "--json", agent_id])
        if not isinstance(value, dict):
            raise PaseoRuntimeError("Paseo archive must return an object")
        if (
            require_full_id(value.get("agentId"), "archive.agentId") != agent_id
            or value.get("status") != "archived"
        ):
            raise PaseoRuntimeError("Paseo archived a different agent or status")
        return value

    def archive_workspace(self, workspace_id: str) -> dict[str, Any]:
        require_full_id(workspace_id, "workspace_id")
        value = self.json(["workspace", "archive", workspace_id, "--json"])
        if not isinstance(value, dict):
            raise PaseoRuntimeError("Paseo workspace archive must return an object")
        if (
            require_full_id(value.get("workspaceId"), "archive.workspaceId")
            != workspace_id
            or value.get("status") != "archived"
        ):
            raise PaseoRuntimeError("Paseo archived a different workspace or status")
        return value


def resolve_thinking_id(
    models: list[dict[str, Any]], model: str, effort: str
) -> str:
    matching_models = [
        item
        for item in models
        if item.get("id") == model or item.get("model") == model
    ]
    if len(matching_models) != 1:
        raise PaseoRuntimeError(
            f"Expected exactly one installed Paseo model match for {model}; "
            f"found {len(matching_models)}"
        )
    raw_options = matching_models[0].get("thinkingOptionIds")
    if not isinstance(raw_options, list) or any(not isinstance(item, str) for item in raw_options):
        raise PaseoRuntimeError(f"Paseo model {model} has no deterministic thinking options")
    exact = [item for item in raw_options if item == effort]
    if len(exact) == 1:
        return exact[0]
    suffix = [
        item
        for item in raw_options
        if item.endswith((f"-{effort}", f"_{effort}", f":{effort}"))
    ]
    if len(suffix) == 1:
        return suffix[0]
    raise PaseoRuntimeError(
        f"Cannot map logical effort {effort} to one thinking ID for {model}"
    )


def assert_live_status(status: dict[str, Any], cli_version: str) -> None:
    if cli_version != TESTED_PASEO_VERSION:
        raise PaseoRuntimeError(
            f"Unsupported Paseo CLI {cli_version}; tested version is {TESTED_PASEO_VERSION}"
        )
    if status.get("localDaemon") != "running" or status.get("connectedDaemon") != "reachable":
        raise PaseoRuntimeError("Paseo daemon is not running and reachable")
    reported_cli_version = status.get("cliVersion")
    if reported_cli_version != cli_version:
        raise PaseoRuntimeError(
            "Paseo status/CLI version mismatch: "
            f"command {cli_version}, status {reported_cli_version}"
        )
    daemon_version = status.get("daemonVersion")
    if daemon_version != cli_version:
        raise PaseoRuntimeError(
            f"Paseo CLI/daemon version mismatch: CLI {cli_version}, daemon {daemon_version}"
        )


def verify_workspace_chain(
    client: PaseoClient,
    *,
    workspace_id: str,
    worktree: Path,
    agent_inspection: dict[str, Any],
) -> dict[str, Any]:
    expected = worktree.resolve()
    matches = [
        item
        for item in client.list_workspaces()
        if item.get("workspaceId") == workspace_id
    ]
    if len(matches) != 1:
        raise PaseoRuntimeError("Expected exactly one active Paseo workspace match")
    workspace = matches[0]
    if workspace.get("isolation") not in {"local", "worktree"}:
        raise PaseoRuntimeError("Paseo workspace has an unsupported classification")
    workspace_cwd = require_absolute_path(workspace.get("cwd"), "workspace.cwd")
    agent_cwd = require_absolute_path(agent_inspection.get("Cwd"), "agent.Cwd")
    if workspace_cwd != expected or agent_cwd != expected:
        raise PaseoRuntimeError("Paseo workspace/agent cwd differs from the task worktree")
    return workspace


def match_local_workspaces(
    workspaces: list[dict[str, Any]], *, worktree: Path, name: str
) -> list[dict[str, Any]]:
    """Find only an exact directory-backed workspace created for this task."""
    expected = worktree.resolve()
    matches: list[dict[str, Any]] = []
    for workspace in workspaces:
        # Paseo 0.2.5 classifies a directory-backed local workspace as
        # `worktree` when its path is already a Git linked worktree. The Chief
        # still owns creation because it validated that path before issuing
        # `workspace create --isolation local`.
        if workspace.get("isolation") not in {"local", "worktree"} or workspace.get("name") != name:
            continue
        try:
            cwd = require_absolute_path(workspace.get("cwd"), "workspace.cwd")
        except PaseoRuntimeError:
            continue
        if cwd == expected:
            require_full_id(workspace.get("workspaceId"), "workspaceId")
            matches.append(workspace)
    return matches


def verify_agent_inspection(
    inspection: dict[str, Any],
    *,
    agent_id: str,
    model: str,
    thinking: str,
    worktree: Path,
    root_agent_id: str | None,
) -> None:
    if require_full_id(inspection.get("Id"), "inspect.Id") != agent_id:
        raise PaseoRuntimeError("Paseo inspection resolved a different agent")
    if inspection.get("Provider") != "codex":
        raise PaseoRuntimeError("Paseo launched a non-Codex provider")
    if inspection.get("Model") != model:
        raise PaseoRuntimeError("Observed Paseo model differs from the task contract")
    if inspection.get("Thinking") != thinking:
        raise PaseoRuntimeError("Observed Paseo thinking route differs from the task contract")
    if require_absolute_path(inspection.get("Cwd"), "inspect.Cwd") != worktree.resolve():
        raise PaseoRuntimeError("Observed Paseo cwd differs from the task worktree")
    observed_parent = inspection.get("ParentAgentId")
    if root_agent_id is None:
        if observed_parent is not None:
            raise PaseoRuntimeError("External Root launch unexpectedly has a Paseo parent")
    elif observed_parent != root_agent_id:
        raise PaseoRuntimeError("Writer parent is not the expected Root agent")
    capabilities = inspection.get("Capabilities")
    if not isinstance(capabilities, dict) or capabilities.get("Persistence") is not True:
        raise PaseoRuntimeError("Codex agent does not report reusable session persistence")


def assert_no_worker_children(client: PaseoClient, worker_agent_id: str) -> None:
    for item in client.list_agents():
        candidate_id = item["id"]
        if candidate_id == worker_agent_id:
            continue
        inspection = client.inspect_agent(candidate_id)
        if inspection.get("ParentAgentId") == worker_agent_id:
            raise PaseoRuntimeError(
                f"Managed worker created a forbidden nested agent: {candidate_id}"
            )


def git_run(repository: Path, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


def git_value(repository: Path, arguments: list[str], description: str) -> str:
    result = git_run(repository, arguments)
    value = result.stdout.strip()
    if result.returncode != 0 or not value:
        detail = result.stderr.strip() or result.stdout.strip()
        raise PaseoRuntimeError(f"Cannot determine {description}: {detail}")
    return value


def validate_task_base(task: dict[str, Any]) -> None:
    repository = Path(task["repository"]).resolve()
    root = git_value(repository, ["rev-parse", "--show-toplevel"], "repository root")
    if Path(root).resolve() != repository:
        raise PaseoRuntimeError("Task repository is not the exact Git root")
    target_head = git_value(
        repository,
        ["rev-parse", "--verify", f"refs/heads/{task['target_branch']}^{{commit}}"],
        "target branch HEAD",
    )
    if target_head != task["base_revision"]:
        raise PaseoRuntimeError("Target branch moved after the task contract was created")
    status = git_run(repository, ["status", "--porcelain"])
    if status.returncode != 0 or status.stdout.strip():
        raise PaseoRuntimeError("Target repository must be clean before writer launch")


def create_task_worktree(
    task: dict[str, Any],
    *,
    worktree: Path,
    branch: str,
) -> None:
    validate_task_base(task)
    repository = Path(task["repository"]).resolve()
    worktree = worktree.resolve()
    if worktree.exists():
        raise PaseoRuntimeError(f"Task worktree path already exists: {worktree}")
    branch_check = git_run(repository, ["show-ref", "--verify", f"refs/heads/{branch}"])
    if branch_check.returncode == 0:
        raise PaseoRuntimeError(f"Task branch already exists: {branch}")
    worktree.parent.mkdir(parents=True, exist_ok=True)
    result = git_run(
        repository,
        ["worktree", "add", "-b", branch, str(worktree), task["base_revision"]],
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise PaseoRuntimeError(f"Cannot create task worktree: {detail}")
    validate_task_worktree(task, worktree=worktree, branch=branch, require_base=True)


def validate_task_worktree(
    task: dict[str, Any],
    *,
    worktree: Path,
    branch: str,
    require_base: bool,
) -> str:
    worktree = worktree.resolve()
    root = git_value(worktree, ["rev-parse", "--show-toplevel"], "worktree root")
    if Path(root).resolve() != worktree:
        raise PaseoRuntimeError("Writer worktree path is not the exact Git root")
    head = git_value(worktree, ["rev-parse", "HEAD"], "worktree HEAD")
    current_branch = git_value(worktree, ["branch", "--show-current"], "worktree branch")
    if current_branch != branch:
        raise PaseoRuntimeError("Writer worktree is on an unexpected branch")
    if require_base and head != task["base_revision"]:
        raise PaseoRuntimeError("Writer worktree HEAD differs from the locked task base")
    status = git_run(worktree, ["status", "--porcelain"])
    if status.returncode != 0 or status.stdout.strip():
        raise PaseoRuntimeError("Writer worktree must be clean")
    return head


def reconcile_lost_launch(
    client: PaseoClient,
    ledger: dict[str, Any],
    *,
    attempt_id: str,
    worktree: Path,
) -> str:
    matches = client.list_agents(labels={"chief.origin_attempt_id": attempt_id})
    exact = [
        item
        for item in matches
        if Path(os.path.expanduser(str(item.get("cwd", "")))).resolve() == worktree.resolve()
    ]
    if len(exact) != 1:
        transition(
            ledger,
            "WAIT",
            wait_reason=(
                "Lost launch response could not be reconciled uniquely; "
                f"found {len(exact)} matching agents"
            ),
        )
        raise PaseoRuntimeError(ledger["wait_reason"])
    return require_full_id(exact[0].get("id"), "recovered agent id")
