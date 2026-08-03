#!/usr/bin/env python3
"""Prepare and diagnose the ClassHub Engineering Chief of Staff workflow."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import taskctl
import paseo_runtime


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUNTIME = ROOT / ".runtime" / "classhub"
CLASSHUB_PROFILE = ROOT / "herdr-orchestrator" / "projects" / "classhub.md"
PASEO_POLICY = ROOT / "PASEO_ORCHESTRATOR.md"
PROTECTED_PATTERNS = (
    ".env",
    ".env.*",
    "AGENTS.md",
    ".agent/**",
    ".codex/**",
    ".github/**",
    "harness.db",
    "harness/**",
    "bin/**",
    "composer.json",
    "composer.lock",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "vendor/**",
    "node_modules/**",
)


class ChiefError(RuntimeError):
    """Raised when a Chief workflow command cannot proceed safely."""


def default_repository(environment: dict[str, str] | None = None) -> Path:
    """Resolve ClassHub portably, with an explicit environment override."""
    current_environment = os.environ if environment is None else environment
    override = current_environment.get("CLASSHUB_REPOSITORY", "").strip()
    if override:
        return Path(override).expanduser()
    return ROOT.parent / "classhub"


CLASSHUB_MODELS = ("gpt-5.6-luna", "gpt-5.6-terra")
CLASSHUB_EFFORTS = ("low", "medium", "high", "xhigh", "max")
CLASSHUB_ROUTE_DEFAULTS = {
    "tiny": ("gpt-5.6-luna", "medium"),
    "normal": ("gpt-5.6-luna", "max"),
    "high-risk": ("gpt-5.6-luna", "max"),
}


def route_classhub_model(
    lane: str, model: str | None, effort: str | None
) -> tuple[str, str]:
    default_model, default_effort = CLASSHUB_ROUTE_DEFAULTS[lane]
    selected_model = model or default_model
    selected_effort = effort or default_effort
    if selected_model not in CLASSHUB_MODELS:
        raise ChiefError(
            "ClassHub writers must use gpt-5.6-luna or gpt-5.6-terra; "
            "Sol is not allowed on any managed ClassHub path"
        )
    if selected_effort not in CLASSHUB_EFFORTS:
        raise ChiefError(
            "ClassHub writer effort must be low, medium, high, xhigh, or max"
        )
    return selected_model, selected_effort


def run_command(command: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def check(name: str, ok: bool, detail: str, *, required: bool = True) -> dict[str, Any]:
    return {"name": name, "ok": ok, "required": required, "detail": detail}


def doctor(
    repository: Path,
    live: bool,
    *,
    client: paseo_runtime.PaseoClient | None = None,
    environment: dict[str, str] | None = None,
    current_cwd: Path | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    checks: list[dict[str, Any]] = []
    paseo = shutil.which("paseo")
    checks.append(check("paseo_binary", bool(paseo), paseo or "not found"))
    checks.append(check("repository", repository.is_dir(), str(repository)))

    git_result = run_command(["git", "-C", str(repository), "rev-parse", "--show-toplevel"])
    git_ok = git_result.returncode == 0 and Path(git_result.stdout.strip()).resolve() == repository.resolve()
    checks.append(
        check(
            "git_root",
            git_ok,
            git_result.stdout.strip() or git_result.stderr.strip() or str(repository),
        )
    )
    checks.append(check("classhub_policy", (repository / "AGENTS.md").is_file(), str(repository / "AGENTS.md")))
    harness = repository / "bin" / "harness"
    checks.append(check("classhub_harness", harness.is_file() and os.access(harness, os.X_OK), str(harness)))
    safe_test = repository / "bin" / "test-safe"
    checks.append(check("safe_test_runner", safe_test.is_file() and os.access(safe_test, os.X_OK), str(safe_test)))
    checks.append(check("chief_policy", (ROOT / "AGENTS.md").is_file(), str(ROOT / "AGENTS.md")))
    checks.append(check("classhub_profile", CLASSHUB_PROFILE.is_file(), str(CLASSHUB_PROFILE)))
    checks.append(check("paseo_policy", PASEO_POLICY.is_file(), str(PASEO_POLICY)))

    current_environment = environment if environment is not None else os.environ
    root_agent_id = current_environment.get("PASEO_AGENT_ID", "").strip()
    managed = bool(root_agent_id)
    execution_cwd = (current_cwd or Path.cwd()).resolve()
    external = not managed and execution_cwd == ROOT.resolve()
    checks.append(
        check(
            "paseo_root_mode",
            managed or external,
            (
                f"managed:PASEO_AGENT_ID={root_agent_id}"
                if managed
                else f"external:cwd={execution_cwd}"
            ),
            required=live,
        )
    )

    if paseo:
        paseo_client = client or paseo_runtime.PaseoClient(paseo)
        try:
            version = paseo_client.version()
            checks.append(
                check(
                    "paseo_version",
                    version == paseo_runtime.TESTED_PASEO_VERSION,
                    f"installed={version}; tested={paseo_runtime.TESTED_PASEO_VERSION}",
                )
            )
        except paseo_runtime.PaseoRuntimeError as exc:
            checks.append(check("paseo_version", False, str(exc)))
            version = "unknown"
        try:
            status = paseo_client.status()
            reachable = (
                status.get("localDaemon") == "running"
                and status.get("connectedDaemon") == "reachable"
            )
            checks.append(
                check(
                    "paseo_daemon",
                    reachable,
                    json.dumps(
                        {
                            "localDaemon": status.get("localDaemon"),
                            "connectedDaemon": status.get("connectedDaemon"),
                            "cliVersion": status.get("cliVersion"),
                            "daemonVersion": status.get("daemonVersion"),
                        },
                        sort_keys=True,
                    ),
                    required=live,
                )
            )
        except paseo_runtime.PaseoRuntimeError as exc:
            status = {}
            checks.append(check("paseo_daemon", False, str(exc), required=live))

        if live:
            try:
                if not managed and not external:
                    raise paseo_runtime.PaseoRuntimeError(
                        "external Root must run from the Chief of Staff repository"
                    )
                if managed:
                    paseo_runtime.require_full_id(root_agent_id, "PASEO_AGENT_ID")
                paseo_runtime.assert_live_status(status, version)
                models = paseo_client.provider_models("codex")
                required_routes = {
                    (model, effort)
                    for model in CLASSHUB_MODELS
                    for effort in ("medium", "max")
                }
                resolved = {
                    (model, effort): paseo_runtime.resolve_thinking_id(
                        models, model, effort
                    )
                    for model, effort in required_routes
                }
                checks.append(
                    check(
                        "paseo_codex_routes",
                        True,
                        json.dumps(
                            {
                                f"{model}/{effort}": thinking
                                for (model, effort), thinking in sorted(resolved.items())
                            },
                            sort_keys=True,
                        ),
                    )
                )
                if managed:
                    root = paseo_client.inspect_agent(root_agent_id)
                    root_cwd = paseo_runtime.require_absolute_path(
                        root.get("Cwd"), "Root inspect.Cwd"
                    )
                    capabilities = root.get("Capabilities")
                    root_ok = (
                        root.get("Provider") == "codex"
                        and root_cwd == ROOT.resolve()
                        and isinstance(capabilities, dict)
                        and capabilities.get("Persistence") is True
                    )
                    root_detail = {
                        "mode": "managed",
                        "id": root.get("Id"),
                        "provider": root.get("Provider"),
                        "cwd": root.get("Cwd"),
                        "persistence": capabilities.get("Persistence")
                        if isinstance(capabilities, dict)
                        else None,
                    }
                else:
                    root_ok = external
                    root_detail = {
                        "mode": "external",
                        "id": None,
                        "cwd": str(execution_cwd),
                        "worker_parent_expected": None,
                    }
                checks.append(
                    check(
                        "paseo_root_context",
                        root_ok,
                        json.dumps(root_detail, sort_keys=True),
                    )
                )
            except paseo_runtime.PaseoRuntimeError as exc:
                checks.append(check("paseo_live_capabilities", False, str(exc)))

    ready = all(item["ok"] for item in checks if item["required"])
    return checks, ready


def command_doctor(args: argparse.Namespace) -> None:
    checks, ready = doctor(Path(args.repository).resolve(), args.live)
    if args.json:
        print(json.dumps({"ready": ready, "checks": checks}, indent=2, sort_keys=True))
    else:
        for item in checks:
            status = "PASS" if item["ok"] else ("WARN" if not item["required"] else "FAIL")
            print(f"{status:4} {item['name']}: {item['detail']}")
        print("READY" if ready else "NOT READY")
    if not ready:
        raise ChiefError("doctor found one or more required failures")


def command_prepare_classhub(args: argparse.Namespace) -> None:
    repository = Path(args.repository).resolve()
    if args.lane == "high-risk":
        raise ChiefError(
            "The minimal Paseo release supports only tiny and normal tasks; "
            "high-risk ClassHub work requires governance gates not implemented yet"
        )
    task_kind = getattr(args, "task_kind", "implementation")
    model, effort = route_classhub_model(
        args.lane, getattr(args, "model", None), getattr(args, "effort", None)
    )
    taskctl.verify_repository(repository)
    branch_result = taskctl.git_run(repository, ["branch", "--show-current"])
    target_branch = branch_result.stdout.strip()
    if branch_result.returncode or not target_branch:
        raise ChiefError("ClassHub must be on a named target branch before task creation")
    status_result = taskctl.git_run(repository, ["status", "--porcelain"])
    if status_result.returncode or status_result.stdout.strip():
        raise ChiefError(
            "ClassHub target checkout must be clean before locking a task base; "
            "preserve or finish existing user changes first"
        )
    base_revision = taskctl.git_revision(repository, "HEAD")
    for command in args.verification:
        taskctl.verification_argv(command)
    output_dir = (
        Path(args.output_dir).resolve()
        if args.output_dir
        else (DEFAULT_RUNTIME / args.task_id).resolve()
    )
    task_path = output_dir / f"{args.task_id}.task.json"
    prompt_path = output_dir / f"{args.task_id}.prompt.md"
    ledger_path = output_dir / f"{args.task_id}.paseo-ledger.json"
    existing = [path for path in (task_path, prompt_path, ledger_path) if path.exists()]
    if existing:
        raise ChiefError(
            "Refusing to overwrite an existing task identity: "
            + ", ".join(str(path) for path in existing)
        )
    layers = [str(repository / "AGENTS.md"), *args.instruction_layer]
    excluded = list(dict.fromkeys([*PROTECTED_PATTERNS, *args.does_not_own]))
    task = {
        "artifact_type": "herdr_task",
        "schema_version": taskctl.SCHEMA_VERSION,
        "project_id": "classhub",
        "task_id": args.task_id,
        "repository": str(repository),
        "target_branch": target_branch,
        "base_revision": base_revision,
        "lane": args.lane,
        "task_kind": task_kind,
        "model": model,
        "effort": effort,
        "workspace": args.workspace or f"classhub-{args.task_id}",
        "owner": args.owner
        or (
            "classhub-investigator"
            if task_kind == "investigation"
            else "classhub-writer"
        ),
        "objective": args.objective,
        "context": f"ClassHub lane: {args.lane}. {args.context}",
        "requirements": args.requirement,
        "owns": args.owns,
        "does_not_own": excluded,
        "verification": args.verification,
        "authority": {
            "edit": task_kind == "implementation",
            "commit": task_kind == "implementation",
            "network": False,
            "external_actions": [],
        },
        "done_when": args.done_when,
        "dependencies": args.dependency,
        "instruction_layers": layers,
    }
    taskctl.validate_task(task, task_path)
    taskctl.write_json(task_path, task)
    prompt = taskctl.render_prompt(task, task_path)
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt, encoding="utf-8")
    result = {
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "lane": args.lane,
        "model": model,
        "effort": effort,
        "task": str(task_path),
        "prompt": str(prompt_path),
        "next": [
            "Record the ClassHub intake with bin/harness.",
            "Run chiefctl doctor --live from the external Root in this repository.",
            "Run chiefctl paseo-launch with this task and rendered prompt; "
            f"the adapter maps {model}/{effort} to an installed Paseo thinking ID.",
            (
                "Use chiefctl paseo-wait for one terminal watch, then reproduce "
                "the locked-revision investigation findings independently."
                if task_kind == "investigation"
                else "Use chiefctl paseo-wait for one terminal watch, then verify "
                "the commit-addressed handoff independently."
            ),
        ],
    }
    print(json.dumps(result, indent=2, sort_keys=True))


def task_context(
    task_argument: str,
    ledger_argument: str | None,
) -> tuple[Path, dict[str, Any], Path, dict[str, Any]]:
    task_path = Path(task_argument).resolve()
    task = taskctl.read_json(task_path)
    taskctl.validate_task(task, task_path)
    ledger_path = (
        Path(ledger_argument).resolve()
        if ledger_argument
        else (task_path.parent / f"{task['task_id']}.paseo-ledger.json").resolve()
    )
    ledger = paseo_runtime.read_json(ledger_path)
    paseo_runtime.assert_ledger_task_binding(ledger, task, task_path)
    return task_path, task, ledger_path, ledger


def paseo_client() -> paseo_runtime.PaseoClient:
    binary = shutil.which("paseo")
    if not binary:
        raise ChiefError("paseo executable is not installed")
    return paseo_runtime.PaseoClient(binary)


def require_live_client() -> paseo_runtime.PaseoClient:
    client = paseo_client()
    version = client.version()
    status = client.status()
    paseo_runtime.assert_live_status(status, version)
    return client


def current_root_agent_id() -> str | None:
    root_agent_id = os.environ.get("PASEO_AGENT_ID", "").strip()
    if not root_agent_id:
        return None
    return paseo_runtime.require_full_id(root_agent_id, "PASEO_AGENT_ID")


def verify_root_context(
    client: paseo_runtime.PaseoClient, root_agent_id: str | None
) -> None:
    if root_agent_id is None:
        if Path.cwd().resolve() != ROOT.resolve():
            raise ChiefError(
                "external Root must run from the Chief of Staff repository"
            )
        return
    root = client.inspect_agent(root_agent_id)
    capabilities = root.get("Capabilities")
    if (
        root.get("Provider") != "codex"
        or paseo_runtime.require_absolute_path(root.get("Cwd"), "Root inspect.Cwd")
        != ROOT.resolve()
        or not isinstance(capabilities, dict)
        or capabilities.get("Persistence") is not True
    ):
        raise ChiefError(
            "live operation requires the persistent Codex Root in this repository"
        )


def verify_task_resources(
    client: paseo_runtime.PaseoClient,
    task: dict[str, Any],
    ledger: dict[str, Any],
    *,
    root_agent_id: str | None,
) -> tuple[dict[str, Any], str]:
    worktree = Path(ledger["resources"]["worktree"]["path"]).resolve()
    branch = ledger["resources"]["worktree"]["branch"]
    root = paseo_runtime.git_value(
        worktree, ["rev-parse", "--show-toplevel"], "writer worktree root"
    )
    current_branch = paseo_runtime.git_value(
        worktree, ["branch", "--show-current"], "writer worktree branch"
    )
    if Path(root).resolve() != worktree or current_branch != branch:
        raise ChiefError("writer worktree identity differs from the ledger")
    agent_id = paseo_runtime.require_full_id(
        ledger["resources"]["agent"]["id"], "agent_id"
    )
    thinking = ledger["resources"]["agent"]["thinking"]
    if not thinking:
        thinking = paseo_runtime.resolve_thinking_id(
            client.provider_models("codex"), task["model"], task["effort"]
        )
    inspection = client.inspect_agent(agent_id)
    paseo_runtime.verify_agent_inspection(
        inspection,
        agent_id=agent_id,
        model=task["model"],
        thinking=thinking,
        worktree=worktree,
        root_agent_id=root_agent_id,
    )
    workspace_id = paseo_runtime.require_full_id(
        ledger["resources"]["workspace"]["id"], "workspace_id"
    )
    observed_workspace = paseo_runtime.verify_workspace_chain(
        client,
        workspace_id=workspace_id,
        worktree=worktree,
        agent_inspection=inspection,
    )
    ledger["resources"]["workspace"]["observed_isolation"] = (
        observed_workspace.get("isolation")
    )
    paseo_runtime.assert_no_worker_children(client, agent_id)
    return inspection, thinking


def execution_prompt(
    prompt: str,
    *,
    task: dict[str, Any],
    task_path: Path,
    worktree: Path,
) -> str:
    return "\n".join(
        [
            "# Root-controlled Paseo execution boundary",
            "",
            f"Authoritative execution checkout: {worktree.resolve()}",
            f"Target trust-anchor repository: {Path(task['repository']).resolve()}",
            f"Authorized artifact directory: {task_path.parent.resolve()}",
            "",
            "Run every edit, Git command, and verification command only in the ",
            "authoritative execution checkout. The task `repository` field is ",
            "the protected target checkout; never edit files there, run Git with ",
            "that checkout as cwd, or move its target branch. You are explicitly ",
            "authorized to run `git add` and `git commit` from the authoritative ",
            "execution worktree on its task branch. A linked-worktree commit may ",
            "update its own metadata and task-branch ref in the repository's ",
            "shared Git common directory; that is expected and is not a target ",
            "checkout mutation. First verify that `pwd` and ",
            "`git rev-parse --show-toplevel` ",
            "both equal the authoritative execution checkout. Writing only the ",
            "rendered evidence and handoff paths inside the authorized artifact ",
            "directory is an explicitly authorized local orchestration action. ",
            "If any path or Git identity differs, stop without editing and report ",
            "the mismatch. Do not create agents or subagents.",
            "",
            prompt,
        ]
    )


def verify_handoff_checkout(
    task: dict[str, Any], handoff: dict[str, Any], ledger: dict[str, Any]
) -> None:
    paseo_runtime.validate_task_base(task)
    worktree_resource = ledger["resources"]["worktree"]
    worktree = Path(worktree_resource["path"]).resolve()
    head = paseo_runtime.validate_task_worktree(
        task,
        worktree=worktree,
        branch=worktree_resource["branch"],
        require_base=False,
    )
    if head != handoff["revision"]:
        raise ChiefError(
            "handoff revision is not the exact clean writer-worktree HEAD"
        )
    observed: dict[str, set[Path]] = {}
    for evidence_argument in handoff["evidence"]:
        evidence = taskctl.read_json(Path(evidence_argument))
        taskctl.validate_evidence(evidence)
        for record in evidence["records"]:
            if record["revision"] == handoff["revision"]:
                observed.setdefault(record["command"], set()).add(
                    Path(record["workspace"]).resolve()
                )
    wrong = [
        command
        for command in task["verification"]
        if observed.get(command) != {worktree}
    ]
    if wrong:
        raise ChiefError(
            "handoff evidence was not observed in the exact writer worktree: "
            f"{wrong}"
        )


def command_paseo_launch(args: argparse.Namespace) -> None:
    task_path = Path(args.task).resolve()
    task = taskctl.read_json(task_path)
    taskctl.validate_task(task, task_path)
    if task.get("schema_version") != taskctl.SCHEMA_VERSION:
        raise ChiefError("new Paseo launches require the current task schema")
    if task["project_id"] == "classhub" and task["lane"] == "high-risk":
        raise ChiefError(
            "The minimal Paseo release cannot launch high-risk ClassHub tasks"
        )
    prompt_path = (
        Path(args.prompt).resolve()
        if args.prompt
        else (task_path.parent / f"{task['task_id']}.prompt.md").resolve()
    )
    try:
        prompt = prompt_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ChiefError(f"cannot read rendered task prompt: {prompt_path}") from exc
    if not prompt.strip():
        raise ChiefError("rendered task prompt is empty")
    worktree = (
        Path(args.worktree).resolve()
        if args.worktree
        else (task_path.parent / "worktree").resolve()
    )
    branch = args.branch or f"chief/{task['project_id']}/{task['task_id']}"
    ledger_path = (
        Path(args.ledger).resolve()
        if args.ledger
        else (task_path.parent / f"{task['task_id']}.paseo-ledger.json").resolve()
    )
    ledger_preexisting = ledger_path.exists()
    ledger = paseo_runtime.create_ledger(
        task,
        task_path,
        ledger_path,
        worktree_path=worktree,
        worktree_branch=branch,
    )
    if ledger["state"] not in {"PREPARED", "WORKTREE_READY"}:
        raise ChiefError(
            "paseo-launch can provision only PREPARED or WORKTREE_READY state; "
            f"ledger is {ledger['state']}"
        )
    root_agent_id = current_root_agent_id()
    client = require_live_client()
    verify_root_context(client, root_agent_id)
    models = client.provider_models("codex")
    thinking = paseo_runtime.resolve_thinking_id(
        models, task["model"], task["effort"]
    )
    prompt = execution_prompt(
        prompt,
        task=task,
        task_path=task_path,
        worktree=worktree,
    )

    if ledger["state"] == "PREPARED":
        if ledger_preexisting and worktree.exists():
            paseo_runtime.validate_task_base(task)
            paseo_runtime.validate_task_worktree(
                task,
                worktree=worktree,
                branch=branch,
                require_base=True,
            )
        else:
            paseo_runtime.create_task_worktree(
                task,
                worktree=worktree,
                branch=branch,
            )
        ledger["resources"]["worktree"]["created"] = True
        paseo_runtime.transition(ledger, "WORKTREE_READY")
        paseo_runtime.save_ledger(ledger_path, ledger)

    workspace_resource = ledger["resources"]["workspace"]
    workspace_title = workspace_resource["name"]
    workspace_id = workspace_resource["id"]
    if workspace_id is None:
        matches = paseo_runtime.match_local_workspaces(
            client.list_workspaces(),
            worktree=worktree,
            name=workspace_title,
        )
        if len(matches) > 1:
            paseo_runtime.transition(
                ledger,
                "WAIT",
                wait_reason=(
                    "Workspace provisioning is ambiguous; multiple Paseo "
                    "workspaces match the exact task name and cwd"
                ),
            )
            paseo_runtime.save_ledger(ledger_path, ledger)
            raise ChiefError(ledger["wait_reason"])
        if matches:
            workspace_id = paseo_runtime.require_full_id(
                matches[0].get("workspaceId"), "recovered workspaceId"
            )
        else:
            workspace = client.create_local_workspace(
                worktree,
                title=workspace_title,
            )
            workspace_id = workspace["workspaceId"]
        workspace_resource["id"] = workspace_id
        workspace_resource["created"] = True
        paseo_runtime.save_ledger(ledger_path, ledger)

    attempt = paseo_runtime.new_attempt(ledger, prompt, kind="launch")
    paseo_runtime.save_ledger(ledger_path, ledger)
    labels = {
        "chief.project_id": task["project_id"],
        "chief.task_id": task["task_id"],
        "chief.role": task["owner"],
        "chief.origin_attempt_id": attempt["attempt_id"],
    }
    try:
        launched = client.launch(
            workspace_id=workspace_id,
            model=task["model"],
            thinking=thinking,
            title=f"{task['task_id']}:{task['owner']}",
            labels=labels,
            prompt=prompt,
        )
    except paseo_runtime.PaseoRuntimeError:
        paseo_runtime.save_ledger(ledger_path, ledger)
        raise
    agent_id = launched["agentId"]
    paseo_runtime.record_dispatch(ledger, attempt["attempt_id"], agent_id)
    paseo_runtime.save_ledger(ledger_path, ledger)
    try:
        inspection = client.inspect_agent(agent_id)
        paseo_runtime.verify_agent_inspection(
            inspection,
            agent_id=agent_id,
            model=task["model"],
            thinking=thinking,
            worktree=worktree,
            root_agent_id=root_agent_id,
        )
        observed_workspace = paseo_runtime.verify_workspace_chain(
            client,
            workspace_id=workspace_id,
            worktree=worktree,
            agent_inspection=inspection,
        )
    except paseo_runtime.PaseoRuntimeError as exc:
        try:
            client.stop(agent_id)
        finally:
            paseo_runtime.record_terminal_signal(
                ledger,
                attempt["attempt_id"],
                status="error",
                message=f"launch verification failed: {exc}",
            )
            paseo_runtime.save_ledger(ledger_path, ledger)
        raise
    agent = ledger["resources"]["agent"]
    agent["thinking"] = thinking
    agent["parent_agent_id"] = inspection.get("ParentAgentId")
    agent["persistence"] = inspection["Capabilities"]["Persistence"]
    workspace_resource["observed_isolation"] = observed_workspace.get("isolation")
    ledger["last_reconciled_at"] = paseo_runtime.utc_now()
    paseo_runtime.save_ledger(ledger_path, ledger)
    print(
        json.dumps(
            {
                "task": str(task_path),
                "ledger": str(ledger_path),
                "worktree": str(worktree),
                "workspace_id": workspace_id,
                "agent_id": agent_id,
                "attempt_id": attempt["attempt_id"],
                "model": task["model"],
                "effort": task["effort"],
                "thinking": thinking,
            },
            indent=2,
            sort_keys=True,
        )
    )


def command_paseo_wait(args: argparse.Namespace) -> None:
    task_path, task, ledger_path, ledger = task_context(args.task, args.ledger)
    attempt = paseo_runtime.active_attempt(ledger)
    if not attempt or attempt["status"] != "running":
        raise ChiefError("paseo-wait requires one active running attempt")
    agent_id = paseo_runtime.require_full_id(
        ledger["resources"]["agent"]["id"], "agent_id"
    )
    root_agent_id = current_root_agent_id()
    client = require_live_client()
    verify_root_context(client, root_agent_id)
    verify_task_resources(client, task, ledger, root_agent_id=root_agent_id)
    result = client.wait(agent_id, args.timeout)
    paseo_runtime.record_terminal_signal(
        ledger,
        attempt["attempt_id"],
        status=result["status"],
        message=str(result.get("message", "")),
    )
    ledger["last_reconciled_at"] = paseo_runtime.utc_now()
    paseo_runtime.save_ledger(ledger_path, ledger)
    try:
        paseo_runtime.assert_no_worker_children(client, agent_id)
    except paseo_runtime.PaseoRuntimeError as exc:
        if ledger["state"] != "FAILED":
            paseo_runtime.transition(
                ledger,
                "FAILED",
                wait_reason=f"Managed worker topology violation: {exc}",
            )
        else:
            ledger["wait_reason"] = f"Managed worker topology violation: {exc}"
        paseo_runtime.save_ledger(ledger_path, ledger)
        raise
    handoff_path = (
        Path(args.handoff).resolve()
        if args.handoff
        else (task_path.parent / f"{task['task_id']}.handoff.json").resolve()
    )
    handoff_status = "absent"
    if result["status"] in {"idle", "completed"} and handoff_path.is_file():
        try:
            handoff = taskctl.read_json(handoff_path)
            taskctl.validate_handoff(handoff)
            if not taskctl.identity_matches(task, handoff):
                raise taskctl.ArtifactError("handoff identity does not match the task")
            taskctl.semantic_verify_handoff(task, handoff)
            verify_handoff_checkout(task, handoff, ledger)
            paseo_runtime.bind_artifact(ledger, "handoff", handoff_path)
            paseo_runtime.transition(ledger, "HANDOFF_RECEIVED")
            handoff_status = "verified-claim"
        except (
            taskctl.ArtifactError,
            ChiefError,
            paseo_runtime.PaseoRuntimeError,
        ) as exc:
            ledger["wait_reason"] = f"handoff claim failed validation: {exc}"
            handoff_status = "invalid"
    paseo_runtime.save_ledger(ledger_path, ledger)
    print(
        json.dumps(
            {
                "task": str(task_path),
                "ledger": str(ledger_path),
                "attempt_id": attempt["attempt_id"],
                "event_id": paseo_runtime.event_id(ledger, attempt["attempt_id"]),
                "status": result["status"],
                "state": ledger["state"],
                "handoff": handoff_status,
                "message": result.get("message"),
            },
            indent=2,
            sort_keys=True,
        )
    )


def command_paseo_correct(args: argparse.Namespace) -> None:
    task_path, task, ledger_path, ledger = task_context(args.task, args.ledger)
    prompt_file = Path(args.prompt_file).resolve()
    try:
        prompt = prompt_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise ChiefError(f"cannot read correction prompt: {prompt_file}") from exc
    if not prompt.strip():
        raise ChiefError("correction prompt is empty")
    agent_id = paseo_runtime.require_full_id(
        ledger["resources"]["agent"]["id"], "agent_id"
    )
    root_agent_id = current_root_agent_id()
    client = require_live_client()
    verify_root_context(client, root_agent_id)
    verify_task_resources(client, task, ledger, root_agent_id=root_agent_id)
    paseo_runtime.validate_task_base(task)
    prompt = execution_prompt(
        prompt,
        task=task,
        task_path=task_path,
        worktree=Path(ledger["resources"]["worktree"]["path"]),
    )
    if ledger["state"] in {"WAIT", "HANDOFF_RECEIVED", "CANDIDATE_VERIFIED"}:
        paseo_runtime.transition(ledger, "REVISE")
    attempt = paseo_runtime.new_attempt(ledger, prompt, kind="correction")
    effective_prompt_path = (
        ledger_path.parent / f"{task['task_id']}.{attempt['attempt_id']}.prompt.md"
    ).resolve()
    paseo_runtime.atomic_write_text(effective_prompt_path, prompt)
    paseo_runtime.save_ledger(ledger_path, ledger)
    try:
        result = client.send_correction(agent_id, effective_prompt_path)
    except paseo_runtime.PaseoRuntimeError as exc:
        paseo_runtime.transition(
            ledger,
            "WAIT",
            wait_reason=(
                "Correction delivery outcome is unknown; reconcile the existing "
                f"agent and do not resend automatically: {exc}"
            ),
        )
        paseo_runtime.save_ledger(ledger_path, ledger)
        raise
    paseo_runtime.record_dispatch(ledger, attempt["attempt_id"], result["agentId"])
    paseo_runtime.save_ledger(ledger_path, ledger)
    print(
        json.dumps(
            {
                "ledger": str(ledger_path),
                "agent_id": agent_id,
                "attempt_id": attempt["attempt_id"],
                "state": ledger["state"],
            },
            indent=2,
            sort_keys=True,
        )
    )


def command_paseo_reconcile(args: argparse.Namespace) -> None:
    _, task, ledger_path, ledger = task_context(args.task, args.ledger)
    root_agent_id = current_root_agent_id()
    client = require_live_client()
    verify_root_context(client, root_agent_id)
    worktree = Path(ledger["resources"]["worktree"]["path"]).resolve()
    branch = ledger["resources"]["worktree"]["branch"]
    root = paseo_runtime.git_value(
        worktree, ["rev-parse", "--show-toplevel"], "writer worktree root"
    )
    current_branch = paseo_runtime.git_value(
        worktree, ["branch", "--show-current"], "writer worktree branch"
    )
    if Path(root).resolve() != worktree or current_branch != branch:
        raise ChiefError("writer worktree identity differs from the ledger")
    attempt = paseo_runtime.active_attempt(ledger)
    if not attempt:
        raise ChiefError("ledger has no attempt to reconcile")
    agent_id = ledger["resources"]["agent"]["id"]
    if agent_id is None and attempt["status"] == "dispatching":
        try:
            agent_id = paseo_runtime.reconcile_lost_launch(
                client,
                ledger,
                attempt_id=attempt["attempt_id"],
                worktree=worktree,
            )
        except paseo_runtime.PaseoRuntimeError:
            paseo_runtime.save_ledger(ledger_path, ledger)
            raise
        paseo_runtime.record_dispatch(ledger, attempt["attempt_id"], agent_id)
    elif attempt["status"] == "dispatching" and attempt["kind"] == "correction":
        if ledger["state"] != "WAIT":
            paseo_runtime.transition(
                ledger,
                "WAIT",
                wait_reason=(
                    "Correction delivery is ambiguous after Root restart; "
                    "inspect the existing agent and do not resend automatically"
                ),
            )
        paseo_runtime.save_ledger(ledger_path, ledger)
    agent_id = paseo_runtime.require_full_id(agent_id, "agent_id")
    inspection, thinking = verify_task_resources(
        client, task, ledger, root_agent_id=root_agent_id
    )
    agent = ledger["resources"]["agent"]
    agent["thinking"] = thinking
    agent["parent_agent_id"] = inspection.get("ParentAgentId")
    agent["persistence"] = inspection["Capabilities"]["Persistence"]
    ledger["last_reconciled_at"] = paseo_runtime.utc_now()
    paseo_runtime.save_ledger(ledger_path, ledger)
    print(
        json.dumps(
            {
                "ledger": str(ledger_path),
                "agent_id": agent_id,
                "attempt_id": attempt["attempt_id"],
                "agent_status": inspection.get("Status"),
                "state": ledger["state"],
            },
            indent=2,
            sort_keys=True,
        )
    )


def command_paseo_record_gate(args: argparse.Namespace) -> None:
    _, task, ledger_path, ledger = task_context(args.task, args.ledger)
    artifact_path = Path(args.artifact).resolve() if args.artifact else None
    if args.gate == "handoff":
        if not artifact_path:
            raise ChiefError("handoff gate requires --artifact")
        attempt = paseo_runtime.active_attempt(ledger)
        if not attempt or attempt["status"] != "terminal":
            raise ChiefError("handoff gate requires a terminal recorded attempt")
        handoff = taskctl.read_json(artifact_path)
        taskctl.validate_handoff(handoff)
        if not taskctl.identity_matches(task, handoff):
            raise ChiefError("handoff identity does not match the task")
        taskctl.semantic_verify_handoff(task, handoff)
        verify_handoff_checkout(task, handoff, ledger)
        paseo_runtime.bind_artifact(ledger, "handoff", artifact_path)
        paseo_runtime.transition(ledger, "HANDOFF_RECEIVED")
    elif args.gate == "candidate":
        if taskctl.task_kind_of(task) != "implementation":
            raise ChiefError("candidate gate requires an implementation task")
        if not artifact_path:
            raise ChiefError("candidate gate requires --artifact")
        handoff = paseo_runtime.read_bound_artifact(ledger, "handoff")
        verification = taskctl.read_json(artifact_path)
        taskctl.verify_root_candidate(
            task,
            handoff,
            verification,
            worktree=Path(ledger["resources"]["worktree"]["path"]),
            branch=ledger["resources"]["worktree"]["branch"],
        )
        paseo_runtime.bind_artifact(ledger, "candidate_verification", artifact_path)
        paseo_runtime.transition(ledger, "CANDIDATE_VERIFIED")
    elif args.gate == "investigation-verified":
        if taskctl.task_kind_of(task) != "investigation":
            raise ChiefError("investigation gate requires an investigation task")
        if not artifact_path:
            raise ChiefError("investigation-verified gate requires --artifact")
        handoff = paseo_runtime.read_bound_artifact(ledger, "handoff")
        verification = taskctl.read_json(artifact_path)
        taskctl.verify_root_investigation(
            task,
            handoff,
            verification,
            worktree=Path(ledger["resources"]["worktree"]["path"]),
            branch=ledger["resources"]["worktree"]["branch"],
        )
        paseo_runtime.bind_artifact(ledger, "integrated_verification", artifact_path)
        paseo_runtime.transition(ledger, "INVESTIGATION_VERIFIED")
    elif args.gate == "integrated":
        if taskctl.task_kind_of(task) != "implementation":
            raise ChiefError("integrated gate requires an implementation task")
        handoff = paseo_runtime.read_bound_artifact(ledger, "handoff")
        candidate_verification = paseo_runtime.read_bound_artifact(
            ledger, "candidate_verification"
        )
        taskctl.validate_handoff(handoff)
        taskctl.semantic_verify_handoff(task, handoff)
        taskctl.verify_root_verification_evidence(
            task,
            handoff,
            candidate_verification,
            phase="candidate",
        )
        repository = Path(task["repository"]).resolve()
        head = taskctl.git_revision(
            repository, f"refs/heads/{task['target_branch']}"
        )
        branch = taskctl.git_run(repository, ["branch", "--show-current"])
        status = taskctl.git_run(repository, ["status", "--porcelain"])
        if (
            head != handoff["revision"]
            or branch.stdout.strip() != task["target_branch"]
            or status.returncode
            or status.stdout.strip()
        ):
            raise ChiefError("integrated checkout is not the exact clean candidate")
        paseo_runtime.transition(ledger, "INTEGRATED")
    elif args.gate == "integrated-verified":
        if not artifact_path:
            raise ChiefError("integrated-verified gate requires --artifact")
        if taskctl.task_kind_of(task) != "implementation":
            raise ChiefError("integrated-verified gate requires an implementation task")
        handoff = paseo_runtime.read_bound_artifact(ledger, "handoff")
        verification = taskctl.read_json(artifact_path)
        taskctl.verify_root_acceptance(
            task, handoff, verification, check_checkout=True
        )
        paseo_runtime.bind_artifact(ledger, "integrated_verification", artifact_path)
        paseo_runtime.transition(ledger, "INTEGRATED_VERIFIED")
    else:
        if not artifact_path:
            raise ChiefError("accepted gate requires --artifact")
        decision = taskctl.read_json(artifact_path)
        taskctl.validate_decision(decision)
        if (
            not taskctl.identity_matches(task, decision)
            or decision["decision"] != "ACCEPT"
        ):
            raise ChiefError("accepted gate requires a matching ACCEPT decision")
        if Path(decision["task"]).resolve() != Path(ledger["task"]).resolve():
            raise ChiefError("ACCEPT decision does not reference the recorded task")
        expected_handoff = ledger["artifacts"]["handoff"]
        if not expected_handoff or Path(decision["handoff"]).resolve() != Path(
            expected_handoff
        ).resolve():
            raise ChiefError("ACCEPT decision does not reference the recorded handoff")
        expected_verification = ledger["artifacts"]["integrated_verification"]
        if not expected_verification or Path(decision["root_verification"]).resolve() != Path(
            expected_verification
        ).resolve():
            raise ChiefError("ACCEPT decision does not reference the recorded integrated verification")
        handoff = paseo_runtime.read_bound_artifact(ledger, "handoff")
        verification = paseo_runtime.read_bound_artifact(
            ledger, "integrated_verification"
        )
        taskctl.verify_root_acceptance(
            task, handoff, verification, check_checkout=True
        )
        if decision["event_id"] != paseo_runtime.event_id(ledger):
            raise ChiefError("ACCEPT decision event does not match the active attempt")
        paseo_runtime.bind_artifact(ledger, "decision", artifact_path)
        paseo_runtime.transition(ledger, "ACCEPTED")
    paseo_runtime.save_ledger(ledger_path, ledger)
    print(
        json.dumps(
            {"ledger": str(ledger_path), "state": ledger["state"]},
            indent=2,
            sort_keys=True,
        )
    )


def command_paseo_archive(args: argparse.Namespace) -> None:
    _, task, ledger_path, ledger = task_context(args.task, args.ledger)
    accepted = ledger["state"] == "ACCEPTED"
    discard_empty = getattr(args, "discard_empty", False)
    if not accepted:
        if not discard_empty or ledger["state"] not in {"WAIT", "FAILED"}:
            raise ChiefError(
                "paseo-archive requires ACCEPTED state unless --discard-empty "
                "proves a WAIT/FAILED checkout has no candidate"
            )
        if any(ledger["artifacts"].values()):
            raise ChiefError("--discard-empty refuses a task with recorded artifacts")
        worktree_resource = ledger["resources"]["worktree"]
        paseo_runtime.validate_task_worktree(
            task,
            worktree=Path(worktree_resource["path"]),
            branch=worktree_resource["branch"],
            require_base=True,
        )
    root_agent_id = current_root_agent_id()
    client = require_live_client()
    verify_root_context(client, root_agent_id)
    verify_task_resources(client, task, ledger, root_agent_id=root_agent_id)
    if accepted:
        handoff = paseo_runtime.read_bound_artifact(ledger, "handoff")
        verification = paseo_runtime.read_bound_artifact(
            ledger, "integrated_verification"
        )
        taskctl.verify_root_acceptance(
            task, handoff, verification, check_checkout=True
        )
    else:
        ledger["cleanup"]["retained_reason"] = (
            "No candidate existed; task-created Paseo resources archived by "
            "explicit --discard-empty cleanup"
        )
    workspace = ledger["resources"]["workspace"]
    agent = ledger["resources"]["agent"]
    if workspace["created"] and workspace["id"]:
        client.archive_workspace(workspace["id"])
        ledger["cleanup"]["workspace_archived"] = True
        ledger["cleanup"]["agent_archived"] = True
    elif agent["created"] and agent["id"]:
        client.archive_agent(agent["id"])
        ledger["cleanup"]["agent_archived"] = True
    paseo_runtime.save_ledger(ledger_path, ledger)
    print(json.dumps({"ledger": str(ledger_path), "cleanup": ledger["cleanup"]}, indent=2, sort_keys=True))


def command_paseo_show(args: argparse.Namespace) -> None:
    _, _, _, ledger = task_context(args.task, args.ledger)
    print(json.dumps(ledger, indent=2, sort_keys=True))


def command_paseo_resolve_attempt(args: argparse.Namespace) -> None:
    _, task, ledger_path, ledger = task_context(args.task, args.ledger)
    root_agent_id = current_root_agent_id()
    client = require_live_client()
    verify_root_context(client, root_agent_id)
    verify_task_resources(client, task, ledger, root_agent_id=root_agent_id)
    paseo_runtime.resolve_ambiguous_correction(
        ledger,
        delivered=args.outcome == "delivered",
    )
    paseo_runtime.save_ledger(ledger_path, ledger)
    print(
        json.dumps(
            {
                "ledger": str(ledger_path),
                "state": ledger["state"],
                "attempt": paseo_runtime.active_attempt(ledger),
            },
            indent=2,
            sort_keys=True,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="ClassHub Engineering Chief of Staff workflow helper."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    doctor_parser = commands.add_parser("doctor", help="check local or live workflow prerequisites")
    doctor_parser.add_argument("--repository", default=str(default_repository()))
    doctor_parser.add_argument("--live", action="store_true", help="run the mandatory Paseo preflight")
    doctor_parser.add_argument("--json", action="store_true")
    doctor_parser.set_defaults(handler=command_doctor)

    prepare = commands.add_parser("prepare-classhub", help="create a ClassHub task and rendered writer prompt")
    prepare.add_argument("--task-id", required=True)
    prepare.add_argument("--lane", choices=("tiny", "normal"), required=True)
    prepare.add_argument(
        "--task-kind",
        choices=("implementation", "investigation"),
        default="implementation",
    )
    prepare.add_argument("--model", choices=CLASSHUB_MODELS)
    prepare.add_argument("--effort", choices=CLASSHUB_EFFORTS)
    prepare.add_argument("--objective", required=True)
    prepare.add_argument("--context", required=True)
    prepare.add_argument("--requirement", action="append", required=True)
    prepare.add_argument("--owns", action="append", required=True)
    prepare.add_argument("--does-not-own", action="append", default=[])
    prepare.add_argument("--verification", action="append", required=True)
    prepare.add_argument("--done-when", action="append", required=True)
    prepare.add_argument("--dependency", action="append", default=[])
    prepare.add_argument("--instruction-layer", action="append", default=[])
    prepare.add_argument("--owner")
    prepare.add_argument("--workspace")
    prepare.add_argument("--repository", default=str(default_repository()))
    prepare.add_argument("--output-dir")
    prepare.set_defaults(handler=command_prepare_classhub)

    launch = commands.add_parser(
        "paseo-launch",
        help="create the task worktree and launch its writer through Paseo",
    )
    launch.add_argument("--task", required=True)
    launch.add_argument("--prompt")
    launch.add_argument("--ledger")
    launch.add_argument("--worktree")
    launch.add_argument("--branch")
    launch.set_defaults(handler=command_paseo_launch)

    wait = commands.add_parser(
        "paseo-wait", help="wait once for the active Paseo attempt"
    )
    wait.add_argument("--task", required=True)
    wait.add_argument("--ledger")
    wait.add_argument("--handoff")
    wait.add_argument("--timeout", type=int, default=900)
    wait.set_defaults(handler=command_paseo_wait)

    correct = commands.add_parser(
        "paseo-correct", help="send evidence-backed correction to the same writer"
    )
    correct.add_argument("--task", required=True)
    correct.add_argument("--ledger")
    correct.add_argument("--prompt-file", required=True)
    correct.set_defaults(handler=command_paseo_correct)

    reconcile = commands.add_parser(
        "paseo-reconcile", help="reconcile durable task state with Paseo and Git"
    )
    reconcile.add_argument("--task", required=True)
    reconcile.add_argument("--ledger")
    reconcile.set_defaults(handler=command_paseo_reconcile)

    gate = commands.add_parser(
        "paseo-record-gate", help="record a verified Root-owned task gate"
    )
    gate.add_argument("--task", required=True)
    gate.add_argument("--ledger")
    gate.add_argument(
        "--gate",
        choices=(
            "handoff",
            "candidate",
            "integrated",
            "integrated-verified",
            "investigation-verified",
            "accepted",
        ),
        required=True,
    )
    gate.add_argument("--artifact")
    gate.set_defaults(handler=command_paseo_record_gate)

    archive = commands.add_parser(
        "paseo-archive", help="archive only task-created Paseo resources"
    )
    archive.add_argument("--task", required=True)
    archive.add_argument("--ledger")
    archive.add_argument(
        "--discard-empty",
        action="store_true",
        help="archive WAIT/FAILED resources only when the writer checkout is clean at base",
    )
    archive.set_defaults(handler=command_paseo_archive)

    show = commands.add_parser("paseo-show", help="show the durable Paseo ledger")
    show.add_argument("--task", required=True)
    show.add_argument("--ledger")
    show.set_defaults(handler=command_paseo_show)

    resolve = commands.add_parser(
        "paseo-resolve-attempt",
        help="resolve an ambiguous correction after Root inspects the existing agent",
    )
    resolve.add_argument("--task", required=True)
    resolve.add_argument("--ledger")
    resolve.add_argument(
        "--outcome",
        choices=("delivered", "not-delivered"),
        required=True,
    )
    resolve.set_defaults(handler=command_paseo_resolve_attempt)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.handler(args)
    except (
        ChiefError,
        paseo_runtime.PaseoRuntimeError,
        taskctl.ArtifactError,
        OSError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
