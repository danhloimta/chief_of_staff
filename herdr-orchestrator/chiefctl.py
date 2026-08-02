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


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPOSITORY = Path("/Users/danhloi/work/classhub")
DEFAULT_RUNTIME = ROOT / ".runtime" / "classhub"
CLASSHUB_PROFILE = ROOT / "herdr-orchestrator" / "projects" / "classhub.md"
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


def doctor(repository: Path, live: bool) -> tuple[list[dict[str, Any]], bool]:
    checks: list[dict[str, Any]] = []
    herdr = shutil.which("herdr")
    checks.append(check("herdr_binary", bool(herdr), herdr or "not found"))
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

    managed = os.environ.get("HERDR_ENV") == "1"
    checks.append(
        check(
            "herdr_managed_pane",
            managed,
            "HERDR_ENV=1" if managed else "HERDR_ENV is not 1",
            required=live,
        )
    )

    if live:
        if not managed:
            raise ChiefError("live preflight requires a Herdr-managed pane (HERDR_ENV=1)")
        if not herdr:
            raise ChiefError("live preflight requires the herdr executable")
        for name, command in (
            ("herdr_version", [herdr, "--version"]),
            ("herdr_status", [herdr, "status", "--json"]),
            ("herdr_help", [herdr, "--help"]),
        ):
            result = run_command(command)
            detail = result.stdout.strip() or result.stderr.strip()
            checks.append(check(name, result.returncode == 0, detail[:1000]))

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
        "workspace": args.workspace or f"classhub-{args.task_id}",
        "owner": args.owner,
        "objective": args.objective,
        "context": f"ClassHub lane: {args.lane}. {args.context}",
        "requirements": args.requirement,
        "owns": args.owns,
        "does_not_own": excluded,
        "verification": args.verification,
        "authority": {
            "edit": True,
            "commit": True,
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
        "task": str(task_path),
        "prompt": str(prompt_path),
        "next": [
            "Record the ClassHub intake with bin/harness.",
            "Run chiefctl doctor --live inside the Herdr-managed root pane.",
            "Create the writer worktree and submit the rendered prompt through herdr pane run.",
        ],
    }
    print(json.dumps(result, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="ClassHub Engineering Chief of Staff workflow helper."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    doctor_parser = commands.add_parser("doctor", help="check local or live workflow prerequisites")
    doctor_parser.add_argument("--repository", default=str(DEFAULT_REPOSITORY))
    doctor_parser.add_argument("--live", action="store_true", help="run the mandatory Herdr preflight")
    doctor_parser.add_argument("--json", action="store_true")
    doctor_parser.set_defaults(handler=command_doctor)

    prepare = commands.add_parser("prepare-classhub", help="create a ClassHub task and rendered writer prompt")
    prepare.add_argument("--task-id", required=True)
    prepare.add_argument("--lane", choices=("tiny", "normal", "high-risk"), required=True)
    prepare.add_argument("--objective", required=True)
    prepare.add_argument("--context", required=True)
    prepare.add_argument("--requirement", action="append", required=True)
    prepare.add_argument("--owns", action="append", required=True)
    prepare.add_argument("--does-not-own", action="append", default=[])
    prepare.add_argument("--verification", action="append", required=True)
    prepare.add_argument("--done-when", action="append", required=True)
    prepare.add_argument("--dependency", action="append", default=[])
    prepare.add_argument("--instruction-layer", action="append", default=[])
    prepare.add_argument("--owner", default="classhub-writer")
    prepare.add_argument("--workspace")
    prepare.add_argument("--repository", default=str(DEFAULT_REPOSITORY))
    prepare.add_argument("--output-dir")
    prepare.set_defaults(handler=command_prepare_classhub)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.handler(args)
    except (ChiefError, taskctl.ArtifactError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
