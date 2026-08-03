#!/usr/bin/env python3
"""Validate and render Chief task contracts, evidence, and handoffs."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 4
SUPPORTED_SCHEMA_VERSIONS = {2, 3, SCHEMA_VERSION}
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
REVISION_PATTERN = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
TASK_LIST_FIELDS = (
    "requirements",
    "owns",
    "does_not_own",
    "verification",
    "done_when",
    "dependencies",
    "instruction_layers",
)


class ArtifactError(ValueError):
    """Raised when an orchestration artifact is invalid."""


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise ArtifactError(f"Artifact not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ArtifactError(
            f"Invalid JSON in {path}: line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    if not isinstance(value, dict):
        raise ArtifactError(f"Artifact must be a JSON object: {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(value, indent=2, sort_keys=True) + "\n"
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
            temporary.write(rendered)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def require_iso8601_utc(value: str, field: str) -> None:
    if not value.endswith("Z"):
        raise ArtifactError(f"'{field}' must be an ISO-8601 UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ArtifactError(f"'{field}' must be a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ArtifactError(f"'{field}' must be in UTC")


def require_repository_path(path: str, field: str) -> None:
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts or not path.strip():
        raise ArtifactError(f"'{field}' entries must be safe repository-relative paths")


def require_exact_keys(
    artifact: dict[str, Any], required: set[str], optional: set[str] | None = None
) -> None:
    optional = optional or set()
    missing = sorted(required - artifact.keys())
    unknown = sorted(artifact.keys() - required - optional)
    errors = []
    if missing:
        errors.append(f"missing fields: {', '.join(missing)}")
    if unknown:
        errors.append(f"unknown fields: {', '.join(unknown)}")
    if errors:
        raise ArtifactError("; ".join(errors))


def require_string(artifact: dict[str, Any], field: str) -> str:
    value = artifact.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ArtifactError(f"'{field}' must be a non-empty string")
    return value


def require_id(artifact: dict[str, Any], field: str) -> str:
    value = require_string(artifact, field)
    if not ID_PATTERN.fullmatch(value):
        raise ArtifactError(
            f"'{field}' must start with a lowercase letter or digit and contain "
            "only lowercase letters, digits, '.', '_', or '-'"
        )
    return value


def require_string_list(
    artifact: dict[str, Any], field: str, *, allow_empty: bool = False
) -> list[str]:
    value = artifact.get(field)
    if not isinstance(value, list):
        raise ArtifactError(f"'{field}' must be a list of strings")
    if not allow_empty and not value:
        raise ArtifactError(f"'{field}' must contain at least one item")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ArtifactError(f"'{field}' must contain only non-empty strings")
    return value


def validate_identity(artifact: dict[str, Any]) -> None:
    if artifact.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
        versions = " or ".join(str(item) for item in sorted(SUPPORTED_SCHEMA_VERSIONS))
        raise ArtifactError(f"'schema_version' must be {versions}")
    require_id(artifact, "project_id")
    require_id(artifact, "task_id")


def validate_task(task: dict[str, Any], source: Path | None = None) -> None:
    required = {
        "artifact_type",
        "schema_version",
        "project_id",
        "task_id",
        "repository",
        "target_branch",
        "base_revision",
        "lane",
        "workspace",
        "owner",
        "objective",
        "context",
        "requirements",
        "owns",
        "does_not_own",
        "verification",
        "authority",
        "done_when",
        "dependencies",
        "instruction_layers",
    }
    if task.get("schema_version") in {3, SCHEMA_VERSION}:
        required.update({"model", "effort"})
    if task.get("schema_version") == SCHEMA_VERSION:
        required.add("task_kind")
    require_exact_keys(task, required)
    if task.get("artifact_type") != "herdr_task":
        raise ArtifactError("'artifact_type' must be 'herdr_task'")
    validate_identity(task)
    repository = Path(require_string(task, "repository"))
    if not repository.is_absolute():
        raise ArtifactError("'repository' must be an absolute path")
    for field in ("target_branch", "workspace", "owner", "objective", "context"):
        require_string(task, field)
    base_revision = require_string(task, "base_revision")
    if not REVISION_PATTERN.fullmatch(base_revision):
        raise ArtifactError("'base_revision' must be a full 40- or 64-character Git hash")
    if require_string(task, "lane") not in {"tiny", "normal", "high-risk"}:
        raise ArtifactError("'lane' must be tiny, normal, or high-risk")
    if task["schema_version"] in {3, SCHEMA_VERSION}:
        model = require_string(task, "model")
        if model not in {"gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"}:
            raise ArtifactError(
                "'model' must be an explicit GPT-5.6 Luna, Terra, or Sol slug"
            )
        effort = require_string(task, "effort")
        if effort not in {"low", "medium", "high", "xhigh", "max"}:
            raise ArtifactError(
                "'effort' must be low, medium, high, xhigh, or max"
            )
        if (
            task["project_id"] == "classhub"
            and model == "gpt-5.6-sol"
        ):
            raise ArtifactError(
                "ClassHub managed tasks must use Luna or Terra, not Sol"
            )
    if task["schema_version"] == SCHEMA_VERSION:
        task_kind = require_string(task, "task_kind")
        if task_kind not in {"implementation", "investigation"}:
            raise ArtifactError("'task_kind' must be implementation or investigation")
    for field in TASK_LIST_FIELDS:
        require_string_list(
            task,
            field,
            allow_empty=field in {"dependencies", "instruction_layers"},
        )
    authority = task.get("authority")
    if not isinstance(authority, dict):
        raise ArtifactError("'authority' must be an object")
    require_exact_keys(
        authority,
        {"edit", "commit", "network", "external_actions"},
    )
    for field in ("edit", "commit", "network"):
        if not isinstance(authority.get(field), bool):
            raise ArtifactError(f"'authority.{field}' must be a boolean")
    require_string_list(authority, "external_actions", allow_empty=True)
    if authority["commit"] and not authority["edit"]:
        raise ArtifactError("'authority.commit' requires 'authority.edit'")
    if task_kind_of(task) == "investigation" and (
        authority["edit"] or authority["commit"]
    ):
        raise ArtifactError("investigation tasks must not grant edit or commit authority")
    for field in ("owns", "does_not_own"):
        for pattern in task[field]:
            require_repository_path(pattern, field)
    if source:
        for layer in task["instruction_layers"]:
            layer_path = resolve_layer(source, layer)
            if not layer_path.is_file():
                raise ArtifactError(f"instruction layer not found: {layer_path}")
            validate_layer_boundary(task, source, layer_path)


def validate_evidence(evidence: dict[str, Any]) -> None:
    required = {
        "artifact_type",
        "schema_version",
        "project_id",
        "task_id",
        "records",
    }
    require_exact_keys(evidence, required)
    if evidence.get("artifact_type") != "herdr_evidence":
        raise ArtifactError("'artifact_type' must be 'herdr_evidence'")
    validate_identity(evidence)
    records = evidence.get("records")
    if not isinstance(records, list) or not records:
        raise ArtifactError("'records' must contain at least one evidence record")
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ArtifactError(f"evidence record {index} must be an object")
        require_exact_keys(
            record,
            {"command", "exit_code", "observed_at", "revision", "workspace"},
            {"output_digest", "notes"},
        )
        require_string(record, "command")
        exit_code = record.get("exit_code")
        if not isinstance(exit_code, int) or isinstance(exit_code, bool):
            raise ArtifactError(f"evidence record {index} exit_code must be an integer")
        observed_at = require_string(record, "observed_at")
        require_iso8601_utc(observed_at, f"records[{index}].observed_at")
        revision = require_string(record, "revision")
        if not REVISION_PATTERN.fullmatch(revision):
            raise ArtifactError(f"evidence record {index} revision must be a full Git hash")
        workspace = Path(require_string(record, "workspace"))
        if not workspace.is_absolute():
            raise ArtifactError(f"evidence record {index} workspace must be absolute")
        if "output_digest" in record:
            digest = require_string(record, "output_digest")
            if not DIGEST_PATTERN.fullmatch(digest):
                raise ArtifactError(
                    f"evidence record {index} output_digest must be sha256:<64 hex>"
                )
        if "notes" in record:
            require_string(record, "notes")


def validate_handoff(handoff: dict[str, Any]) -> None:
    required = {
        "artifact_type",
        "schema_version",
        "project_id",
        "task_id",
        "result",
        "base_revision",
        "revision",
        "changed_files",
        "evidence",
        "questions",
        "dependencies",
    }
    if handoff.get("schema_version") == SCHEMA_VERSION:
        required.add("findings")
    require_exact_keys(handoff, required)
    if handoff.get("artifact_type") != "herdr_handoff":
        raise ArtifactError("'artifact_type' must be 'herdr_handoff'")
    validate_identity(handoff)
    result = require_string(handoff, "result")
    if result not in {"ready", "blocked", "investigated"}:
        raise ArtifactError("'result' must be ready, blocked, or investigated")
    for field in ("base_revision", "revision"):
        revision = require_string(handoff, field)
        if not REVISION_PATTERN.fullmatch(revision):
            raise ArtifactError(f"'{field}' must be a full 40- or 64-character Git hash")
    changed_files = require_string_list(
        handoff, "changed_files", allow_empty=result in {"blocked", "investigated"}
    )
    for changed_file in changed_files:
        require_repository_path(changed_file, "changed_files")
    evidence_paths = require_string_list(
        handoff, "evidence", allow_empty=result == "blocked"
    )
    require_string_list(handoff, "questions", allow_empty=True)
    require_string_list(handoff, "dependencies", allow_empty=True)
    findings = handoff.get("findings", [])
    if handoff.get("schema_version") == SCHEMA_VERSION:
        require_string_list(
            handoff,
            "findings",
            allow_empty=result != "investigated",
        )
    if result in {"ready", "investigated"} and not evidence_paths:
        raise ArtifactError("a completed handoff must reference evidence")
    if result == "investigated" and not findings:
        raise ArtifactError("an investigated handoff must contain findings")


def validate_decision(decision: dict[str, Any]) -> None:
    required = {
        "artifact_type",
        "schema_version",
        "project_id",
        "task_id",
        "task",
        "handoff",
        "event_id",
        "decision",
        "decided_at",
        "evidence_checked",
        "root_verification",
        "reason",
    }
    require_exact_keys(decision, required)
    if decision.get("artifact_type") != "herdr_decision":
        raise ArtifactError("'artifact_type' must be 'herdr_decision'")
    validate_identity(decision)
    task_path = Path(require_string(decision, "task"))
    handoff_path = Path(require_string(decision, "handoff"))
    if not task_path.is_absolute() or not handoff_path.is_absolute():
        raise ArtifactError("decision task and handoff paths must be absolute")
    require_string(decision, "event_id")
    if require_string(decision, "decision") not in {"ACCEPT", "REVISE", "WAIT"}:
        raise ArtifactError("'decision' must be 'ACCEPT', 'REVISE', or 'WAIT'")
    decided_at = require_string(decision, "decided_at")
    require_iso8601_utc(decided_at, "decided_at")
    require_string_list(decision, "evidence_checked", allow_empty=False)
    root_verification = decision.get("root_verification")
    if decision["decision"] == "ACCEPT":
        if not isinstance(root_verification, str) or not root_verification.strip():
            raise ArtifactError("an ACCEPT decision requires a root_verification path")
    elif root_verification is not None:
        if not isinstance(root_verification, str) or not root_verification.strip():
            raise ArtifactError("'root_verification' must be null or a non-empty string")
    require_string(decision, "reason")
    task = read_json(task_path)
    validate_task(task, task_path)
    handoff = read_json(handoff_path)
    validate_handoff(handoff)
    if decision["schema_version"] != task["schema_version"]:
        raise ArtifactError("decision schema_version must match the task contract")
    if not identity_matches(task, decision) or not identity_matches(task, handoff):
        raise ArtifactError("decision task and handoff identity must match")
    if decision["decision"] == "ACCEPT":
        verification_path = Path(root_verification).resolve()
        verification = read_json(verification_path)
        verify_root_acceptance(task, handoff, verification)


def validate_root_verification(verification: dict[str, Any]) -> None:
    required = {
        "artifact_type",
        "schema_version",
        "project_id",
        "task_id",
        "phase",
        "result",
        "base_revision",
        "revision",
        "target_branch",
        "worktree",
        "checked_at",
        "changed_files",
        "diff_digest",
        "requirements_checked",
        "done_when_checked",
        "commands",
    }
    require_exact_keys(verification, required)
    if verification.get("artifact_type") != "herdr_root_verification":
        raise ArtifactError("'artifact_type' must be 'herdr_root_verification'")
    validate_identity(verification)
    phase = require_string(verification, "phase")
    if phase not in {
        "candidate",
        "integrated",
        "investigation",
    }:
        raise ArtifactError("'phase' must be candidate, integrated, or investigation")
    if require_string(verification, "result") not in {"pass", "fail"}:
        raise ArtifactError("'result' must be pass or fail")
    for field in ("base_revision", "revision"):
        revision = require_string(verification, field)
        if not REVISION_PATTERN.fullmatch(revision):
            raise ArtifactError(f"'{field}' must be a full Git hash")
    require_string(verification, "target_branch")
    worktree = Path(require_string(verification, "worktree"))
    if not worktree.is_absolute():
        raise ArtifactError("'worktree' must be absolute")
    checked_at = require_string(verification, "checked_at")
    require_iso8601_utc(checked_at, "checked_at")
    changed_files = require_string_list(
        verification,
        "changed_files",
        allow_empty=phase == "investigation",
    )
    for changed_file in changed_files:
        require_repository_path(changed_file, "changed_files")
    diff_digest = require_string(verification, "diff_digest")
    if not DIGEST_PATTERN.fullmatch(diff_digest):
        raise ArtifactError("'diff_digest' must be sha256:<64 hex>")
    require_string_list(verification, "requirements_checked")
    require_string_list(verification, "done_when_checked")
    commands = verification.get("commands")
    if not isinstance(commands, list) or not commands:
        raise ArtifactError("'commands' must contain at least one command result")
    for index, record in enumerate(commands):
        if not isinstance(record, dict):
            raise ArtifactError(f"command result {index} must be an object")
        require_exact_keys(
            record,
            {"command", "exit_code", "output_digest", "output_file"},
        )
        require_string(record, "command")
        if not isinstance(record.get("exit_code"), int) or isinstance(
            record.get("exit_code"), bool
        ):
            raise ArtifactError(f"command result {index} exit_code must be an integer")
        digest = require_string(record, "output_digest")
        if not DIGEST_PATTERN.fullmatch(digest):
            raise ArtifactError(f"command result {index} has an invalid output_digest")
        output_file = Path(require_string(record, "output_file"))
        if not output_file.is_absolute():
            raise ArtifactError(f"command result {index} output_file must be absolute")


VALIDATORS = {
    "herdr_task": validate_task,
    "herdr_evidence": validate_evidence,
    "herdr_handoff": validate_handoff,
    "herdr_decision": validate_decision,
    "herdr_root_verification": validate_root_verification,
}


def validate_artifact(artifact: dict[str, Any], source: Path | None = None) -> None:
    artifact_type = artifact.get("artifact_type")
    validator = VALIDATORS.get(artifact_type)
    if not validator:
        raise ArtifactError(
            "'artifact_type' must be one of: " + ", ".join(sorted(VALIDATORS))
        )
    if artifact_type == "herdr_task":
        validate_task(artifact, source)
    else:
        validator(artifact)


def resolve_layer(task_path: Path, layer: str) -> Path:
    candidate = Path(layer)
    if not candidate.is_absolute():
        candidate = task_path.parent / candidate
    return candidate.resolve()


def validate_layer_boundary(task: dict[str, Any], task_path: Path, layer: Path) -> None:
    allowed_roots = [task_path.parent.resolve(), Path(__file__).resolve().parent]
    repository = Path(task["repository"])
    if repository.is_absolute() and repository.is_dir():
        allowed_roots.append(repository.resolve())
    if not any(is_within(layer, root) for root in allowed_roots):
        roots = ", ".join(str(root) for root in allowed_roots)
        raise ArtifactError(
            f"instruction layer is outside the task ledger and repository: {layer}; "
            f"allowed roots: {roots}"
        )


def render_prompt(task: dict[str, Any], task_path: Path) -> str:
    validate_task(task, task_path)
    helper_path = Path(__file__).resolve()
    artifact_dir = task_path.parent
    evidence_path = artifact_dir / f"{task['task_id']}.evidence.json"
    handoff_path = artifact_dir / f"{task['task_id']}.handoff.json"
    helper = f"python3 {shlex.quote(str(helper_path))}"
    quoted_task = shlex.quote(str(task_path))
    sections = ["# Layered instructions"]
    for layer in task["instruction_layers"]:
        layer_path = resolve_layer(task_path, layer)
        validate_layer_boundary(task, task_path, layer_path)
        sections.extend(
            [
                "",
                f"## {layer_path}",
                "",
                layer_path.read_text().rstrip(),
            ]
        )
    authority = task["authority"]
    sections.extend(
        [
            "",
            "# Task",
            "",
            f"project_id: {task['project_id']}",
            f"task_id: {task['task_id']}",
            f"task_kind: {task_kind_of(task)}",
            f"repository: {task['repository']}",
            f"target_branch: {task['target_branch']}",
            f"base_revision: {task['base_revision']}",
            f"lane: {task['lane']}",
            f"model: {task.get('model', 'legacy-unrecorded')}",
            f"effort: {task.get('effort', 'legacy-unrecorded')}",
            f"workspace: {task['workspace']}",
            f"owner: {task['owner']}",
            "",
            "## Objective",
            "",
            task["objective"],
            "",
            "## Context",
            "",
            task["context"],
            "",
            "## Requirements",
            "",
            *[f"- {item}" for item in task["requirements"]],
            "",
            "## Owns",
            "",
            *[f"- {item}" for item in task["owns"]],
            "",
            "## Does not own",
            "",
            *[f"- {item}" for item in task["does_not_own"]],
            "",
            "## Verification",
            "",
            *[f"- {item}" for item in task["verification"]],
            "",
            "## Authority",
            "",
            f"- edit: {str(authority['edit']).lower()}",
            f"- commit: {str(authority['commit']).lower()}",
            f"- network: {str(authority['network']).lower()}",
            "- external actions: "
            + (", ".join(authority["external_actions"]) or "none"),
            "- nested delegation: forbidden; do not create agents, subagents, "
            "schedules, or another orchestration hierarchy",
            "",
            "## Done when",
            "",
            *[f"- {item}" for item in task["done_when"]],
            "",
            "## Dependencies",
            "",
            *(
                [f"- {item}" for item in task["dependencies"]]
                if task["dependencies"]
                else ["- none"]
            ),
            "",
            "## Completion contract",
            "",
            (
                "Return one read-only investigation handoff for this exact project_id "
                "and task_id. Keep revision equal to the locked base, make no source "
                "change, and include concrete findings plus evidence paths."
                if task_kind_of(task) == "investigation"
                else "Return one implementation handoff for this exact project_id and "
                "task_id. Include the full base and candidate revisions, changed "
                "files, evidence artifact paths, questions, and unfinished dependencies."
            ),
            "Status text such as idle or done is not completion evidence.",
            "",
            "Record evidence and construct the handoff with the validated helpers:",
            "",
            "```bash",
            f"{helper} evidence-add \\",
            f"  --task {quoted_task} \\",
            '  --command "<personally observed command>" \\',
            "  --exit-code <exit-code> \\",
            '  --revision "$(git rev-parse HEAD)" \\',
            '  --workspace "$(pwd)" \\',
            f"  --output {shlex.quote(str(evidence_path))}",
            "",
            f"{helper} handoff-create \\",
            f"  --task {quoted_task} \\",
            *(
                ["  --result investigated \\", '  --finding "<concrete finding>" \\']
                if task_kind_of(task) == "investigation"
                else []
            ),
            f"  --base-revision {shlex.quote(task['base_revision'])} \\",
            (
                f"  --revision {shlex.quote(task['base_revision'])} \\"
                if task_kind_of(task) == "investigation"
                else '  --revision "<full candidate commit>" \\'
            ),
            *(
                []
                if task_kind_of(task) == "investigation"
                else ['  --changed-file "<changed path>" \\']
            ),
            f"  --evidence {shlex.quote(str(evidence_path))} \\",
            f"  --output {shlex.quote(str(handoff_path))}",
            "```",
            "",
        ]
    )
    return "\n".join(sections)


def git_revision(repository: Path, revision: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "--verify", f"{revision}^{{commit}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise ArtifactError(
            f"revision does not resolve to a commit in {repository}: {revision}"
        )
    resolved = result.stdout.strip()
    if not REVISION_PATTERN.fullmatch(resolved):
        raise ArtifactError(f"Git returned an unsupported revision hash: {resolved}")
    return resolved


def git_run(repository: Path, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


def verify_repository(repository: Path) -> None:
    if not repository.is_dir():
        raise ArtifactError(f"repository does not exist: {repository}")
    result = git_run(repository, ["rev-parse", "--show-toplevel"])
    if result.returncode:
        raise ArtifactError(f"repository is not a Git checkout: {repository}")
    if Path(result.stdout.strip()).resolve() != repository.resolve():
        raise ArtifactError(
            f"repository must be the Git root, got {repository}; "
            f"root is {result.stdout.strip()}"
        )


def git_changed_files(repository: Path, base: str, revision: str) -> list[str]:
    result = git_run(
        repository,
        ["diff", "--no-renames", "--name-only", "-z", base, revision],
    )
    if result.returncode:
        raise ArtifactError(f"cannot inspect candidate diff: {result.stderr.strip()}")
    return sorted(item for item in result.stdout.split("\0") if item)


def path_matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def semantic_verify_handoff(
    task: dict[str, Any], handoff: dict[str, Any]
) -> dict[str, Any]:
    if not identity_matches(task, handoff):
        raise ArtifactError("handoff project_id/task_id does not match the task")
    if handoff["schema_version"] != task["schema_version"]:
        raise ArtifactError("handoff schema_version must match the task contract")
    task_kind = task_kind_of(task)
    expected_result = "investigated" if task_kind == "investigation" else "ready"
    if handoff["result"] != expected_result:
        raise ArtifactError(
            f"a {task_kind} task requires a {expected_result} handoff"
        )
    if handoff["questions"]:
        raise ArtifactError("a ready handoff cannot contain unresolved questions")
    if handoff["dependencies"]:
        raise ArtifactError("a ready handoff cannot contain unfinished dependencies")
    if task_kind == "implementation" and (
        not task["authority"]["edit"] or not task["authority"]["commit"]
    ):
        raise ArtifactError(
            "a ready implementation handoff requires task authority.edit and "
            "authority.commit"
        )

    repository = Path(task["repository"])
    verify_repository(repository)
    locked_base = git_revision(repository, task["base_revision"])
    base = git_revision(repository, handoff["base_revision"])
    if base != locked_base:
        raise ArtifactError("handoff base_revision does not match the Root-locked task base")
    revision = git_revision(repository, handoff["revision"])
    if task_kind == "implementation" and base == revision:
        raise ArtifactError("candidate revision is identical to the base revision")
    if task_kind == "investigation" and base != revision:
        raise ArtifactError("investigation handoff revision must remain at the locked base")
    ancestry = git_run(repository, ["merge-base", "--is-ancestor", base, revision])
    if ancestry.returncode:
        raise ArtifactError("candidate revision is not a descendant of the recorded base")

    actual_files = git_changed_files(repository, base, revision)
    claimed_files = sorted(set(handoff["changed_files"]))
    if actual_files != claimed_files:
        raise ArtifactError(
            "handoff changed_files do not match Git; "
            f"claimed={claimed_files}, actual={actual_files}"
        )
    for pattern in [*task["owns"], *task["does_not_own"]]:
        require_repository_path(pattern, "scope")
    outside_scope = [
        changed_file
        for changed_file in actual_files
        if not path_matches(changed_file, task["owns"])
    ]
    if outside_scope:
        raise ArtifactError(f"changed files are outside owns: {outside_scope}")
    excluded = [
        changed_file
        for changed_file in actual_files
        if path_matches(changed_file, task["does_not_own"])
    ]
    if excluded:
        raise ArtifactError(f"changed files match does_not_own: {excluded}")

    whitespace = git_run(repository, ["diff", "--check", base, revision])
    if whitespace.returncode:
        details = whitespace.stdout.strip() or whitespace.stderr.strip()
        raise ArtifactError(f"candidate fails git diff --check: {details}")

    latest_evidence: dict[str, int] = {}
    evidence_files: list[str] = []
    for evidence_arg in handoff["evidence"]:
        evidence_path = Path(evidence_arg).resolve()
        evidence = read_json(evidence_path)
        validate_evidence(evidence)
        if not identity_matches(task, evidence):
            raise ArtifactError(
                f"evidence project_id/task_id does not match the task: {evidence_path}"
            )
        if evidence["schema_version"] != task["schema_version"]:
            raise ArtifactError("evidence schema_version must match the task contract")
        evidence_files.append(str(evidence_path))
        for record in evidence["records"]:
            if record["revision"] == revision:
                latest_evidence[record["command"]] = record["exit_code"]

    missing = [command for command in task["verification"] if command not in latest_evidence]
    if missing:
        raise ArtifactError(
            f"worker evidence for the candidate revision is missing: {missing}"
        )
    failed = [
        command
        for command in task["verification"]
        if latest_evidence.get(command) != 0
    ]
    if failed:
        raise ArtifactError(f"required verification did not pass: {failed}")

    return {
        "project_id": task["project_id"],
        "task_id": task["task_id"],
        "base_revision": base,
        "revision": revision,
        "changed_files": actual_files,
        "evidence": evidence_files,
        "verified_commands": task["verification"],
    }


def verification_argv(command: str) -> list[str]:
    if re.search(r"[;&|><`\n\r]|\$\(", command):
        raise ArtifactError("verification commands cannot contain shell operators")
    try:
        arguments = shlex.split(command)
    except ValueError as exc:
        raise ArtifactError(f"invalid verification command: {command}") from exc
    if not arguments:
        raise ArtifactError("verification command cannot be empty")
    executable = arguments[0]
    allowed = executable in {
        "bin/test-safe",
        "bin/test-parallel",
        "bin/dusk-safe",
    }
    if executable == "vendor/bin/pint":
        allowed = "--test" in arguments[1:]
    if executable == "composer":
        allowed = len(arguments) >= 2 and arguments[1] == "test:dusk"
    if executable == "npm":
        allowed = len(arguments) >= 2 and arguments[1] == "test"
    if not allowed:
        raise ArtifactError(
            "verification command is not an allowed ClassHub safe runner: "
            f"{command}"
        )
    return arguments


def require_exact_acknowledgements(
    expected: list[str], observed: list[str], field: str
) -> None:
    if sorted(expected) != sorted(observed):
        raise ArtifactError(
            f"{field} must exactly acknowledge the task contract; "
            f"expected={expected}, observed={observed}"
        )


def root_verify(
    task: dict[str, Any],
    handoff: dict[str, Any],
    *,
    worktree: Path,
    phase: str,
    requirements_checked: list[str],
    done_when_checked: list[str],
    output_dir: Path,
    timeout: int,
) -> dict[str, Any]:
    candidate = semantic_verify_handoff(task, handoff)
    task_kind = task_kind_of(task)
    allowed_phases = (
        {"investigation"}
        if task_kind == "investigation"
        else {"candidate", "integrated"}
    )
    if phase not in allowed_phases:
        raise ArtifactError(f"phase {phase} is invalid for a {task_kind} task")
    if timeout <= 0:
        raise ArtifactError("verification timeout must be positive")
    require_exact_acknowledgements(
        task["requirements"], requirements_checked, "requirements_checked"
    )
    require_exact_acknowledgements(
        task["done_when"], done_when_checked, "done_when_checked"
    )
    verify_repository(worktree)
    repository = Path(task["repository"]).resolve()
    target = task["target_branch"]
    base = candidate["base_revision"]
    revision = candidate["revision"]
    worktree_head = git_revision(worktree, "HEAD")
    if worktree_head != revision:
        raise ArtifactError(
            f"verification worktree HEAD is {worktree_head}, expected candidate {revision}"
        )
    status = git_run(worktree, ["status", "--porcelain"])
    if status.returncode or status.stdout.strip():
        raise ArtifactError("verification worktree must be clean before checks")

    target_head = git_revision(repository, f"refs/heads/{target}")
    if phase in {"candidate", "investigation"}:
        if target_head != base:
            raise ArtifactError(
                "target branch moved after task creation; rebase or recreate the candidate"
            )
    else:
        branch = git_run(worktree, ["branch", "--show-current"])
        if worktree.resolve() != repository or branch.stdout.strip() != target:
            raise ArtifactError(
                "integrated verification must run in the target repository checkout "
                f"on branch {target}"
            )
        if target_head != revision:
            raise ArtifactError(
                "integrated target HEAD must exactly equal the accepted candidate revision"
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    command_results: list[dict[str, Any]] = []
    passed = True
    for index, command in enumerate(task["verification"], start=1):
        arguments = verification_argv(command)
        try:
            result = subprocess.run(
                arguments,
                cwd=worktree,
                capture_output=True,
                check=False,
                timeout=timeout,
            )
            exit_code = result.returncode
            command_output = result.stdout + result.stderr
        except subprocess.TimeoutExpired as exc:
            exit_code = 124
            stdout = exc.stdout or b""
            stderr = exc.stderr or b""
            if isinstance(stdout, str):
                stdout = stdout.encode()
            if isinstance(stderr, str):
                stderr = stderr.encode()
            command_output = stdout + stderr + b"\nTIMEOUT\n"
        digest = hashlib.sha256(command_output).hexdigest()
        output_file = (output_dir / f"command-{index:02d}.log").resolve()
        output_file.write_bytes(command_output)
        command_results.append(
            {
                "command": command,
                "exit_code": exit_code,
                "output_digest": f"sha256:{digest}",
                "output_file": str(output_file),
            }
        )
        if exit_code != 0:
            passed = False

    final_head = git_revision(worktree, "HEAD")
    final_status = git_run(worktree, ["status", "--porcelain"])
    if final_head != revision or final_status.returncode or final_status.stdout.strip():
        passed = False

    verification = {
        "artifact_type": "herdr_root_verification",
        "schema_version": task["schema_version"],
        "project_id": task["project_id"],
        "task_id": task["task_id"],
        "phase": phase,
        "result": "pass" if passed else "fail",
        "base_revision": base,
        "revision": revision,
        "target_branch": target,
        "worktree": str(worktree.resolve()),
        "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "changed_files": candidate["changed_files"],
        "diff_digest": "sha256:"
        + hashlib.sha256(
            git_run(repository, ["diff", "--binary", base, revision]).stdout.encode()
        ).hexdigest(),
        "requirements_checked": requirements_checked,
        "done_when_checked": done_when_checked,
        "commands": command_results,
    }
    validate_root_verification(verification)
    return verification


def verify_root_verification_evidence(
    task: dict[str, Any],
    handoff: dict[str, Any],
    verification: dict[str, Any],
    *,
    phase: str,
) -> None:
    validate_root_verification(verification)
    if verification["schema_version"] != task["schema_version"]:
        raise ArtifactError("root verification schema_version must match the task contract")
    if not identity_matches(task, handoff) or not identity_matches(task, verification):
        raise ArtifactError("task, handoff, and root verification identity must match")
    if verification["phase"] != phase or verification["result"] != "pass":
        raise ArtifactError(f"gate requires a passing {phase} root verification")
    if verification["base_revision"] != task["base_revision"]:
        raise ArtifactError("root verification base does not match the locked task base")
    if verification["revision"] != handoff["revision"]:
        raise ArtifactError("root verification revision does not match the handoff")
    if verification["target_branch"] != task["target_branch"]:
        raise ArtifactError("root verification target branch does not match the task")
    repository = Path(task["repository"])
    diff = git_run(
        repository,
        ["diff", "--binary", task["base_revision"], handoff["revision"]],
    )
    if diff.returncode:
        raise ArtifactError("cannot reproduce the reviewed candidate diff")
    expected_diff_digest = "sha256:" + hashlib.sha256(diff.stdout.encode()).hexdigest()
    if verification["diff_digest"] != expected_diff_digest:
        raise ArtifactError("root verification diff digest does not match the candidate")
    require_exact_acknowledgements(
        task["requirements"], verification["requirements_checked"], "requirements_checked"
    )
    require_exact_acknowledgements(
        task["done_when"], verification["done_when_checked"], "done_when_checked"
    )
    if [item["command"] for item in verification["commands"]] != task["verification"]:
        raise ArtifactError("root verification commands do not match the task contract")
    for item in verification["commands"]:
        if item["exit_code"] != 0:
            raise ArtifactError("root verification contains a failed command")
        output_file = Path(item["output_file"])
        try:
            digest = hashlib.sha256(output_file.read_bytes()).hexdigest()
        except OSError as exc:
            raise ArtifactError(f"cannot read root verification output: {output_file}") from exc
        if item["output_digest"] != f"sha256:{digest}":
            raise ArtifactError(f"root verification output digest changed: {output_file}")


def verify_root_candidate(
    task: dict[str, Any],
    handoff: dict[str, Any],
    verification: dict[str, Any],
    *,
    worktree: Path,
    branch: str,
) -> None:
    """Verify a candidate gate against its exact handoff, logs, and checkout."""
    semantic_verify_handoff(task, handoff)
    verify_root_verification_evidence(
        task,
        handoff,
        verification,
        phase="candidate",
    )
    expected_worktree = worktree.resolve()
    if Path(verification["worktree"]).resolve() != expected_worktree:
        raise ArtifactError("candidate verification used a different task worktree")
    if git_revision(expected_worktree, "HEAD") != handoff["revision"]:
        raise ArtifactError("candidate worktree no longer points at the verified revision")
    status = git_run(expected_worktree, ["status", "--porcelain"])
    branch_result = git_run(expected_worktree, ["branch", "--show-current"])
    if (
        status.returncode
        or status.stdout.strip()
        or branch_result.stdout.strip() != branch
    ):
        raise ArtifactError("candidate worktree must be clean and on its task branch")
    repository = Path(task["repository"])
    if (
        git_revision(repository, f"refs/heads/{task['target_branch']}")
        != task["base_revision"]
    ):
        raise ArtifactError("target branch moved before candidate acceptance")


def verify_root_investigation(
    task: dict[str, Any],
    handoff: dict[str, Any],
    verification: dict[str, Any],
    *,
    worktree: Path,
    branch: str,
) -> None:
    """Verify a read-only investigation against its exact clean checkout."""
    if task_kind_of(task) != "investigation":
        raise ArtifactError("investigation gate requires an investigation task")
    semantic_verify_handoff(task, handoff)
    verify_root_verification_evidence(
        task,
        handoff,
        verification,
        phase="investigation",
    )
    expected_worktree = worktree.resolve()
    if Path(verification["worktree"]).resolve() != expected_worktree:
        raise ArtifactError("investigation verification used a different task worktree")
    if git_revision(expected_worktree, "HEAD") != task["base_revision"]:
        raise ArtifactError("investigation worktree moved from the locked base")
    status = git_run(expected_worktree, ["status", "--porcelain"])
    branch_result = git_run(expected_worktree, ["branch", "--show-current"])
    if (
        status.returncode
        or status.stdout.strip()
        or branch_result.stdout.strip() != branch
    ):
        raise ArtifactError("investigation worktree must be clean and on its task branch")
    repository = Path(task["repository"])
    if (
        git_revision(repository, f"refs/heads/{task['target_branch']}")
        != task["base_revision"]
    ):
        raise ArtifactError("target branch moved before investigation acceptance")


def verify_root_acceptance(
    task: dict[str, Any],
    handoff: dict[str, Any],
    verification: dict[str, Any],
    *,
    check_checkout: bool = False,
) -> None:
    semantic_verify_handoff(task, handoff)
    phase = "investigation" if task_kind_of(task) == "investigation" else "integrated"
    verify_root_verification_evidence(
        task,
        handoff,
        verification,
        phase=phase,
    )

    if check_checkout:
        repository = Path(task["repository"])
        if (
            git_revision(repository, f"refs/heads/{task['target_branch']}")
            != handoff["revision"]
        ):
            raise ArtifactError("target branch no longer points at the verified candidate")
        status = git_run(repository, ["status", "--porcelain"])
        branch = git_run(repository, ["branch", "--show-current"])
        if (
            status.returncode
            or status.stdout.strip()
            or branch.stdout.strip() != task["target_branch"]
        ):
            raise ArtifactError("target checkout must be clean and on the locked target branch")


def identity_matches(task: dict[str, Any], artifact: dict[str, Any]) -> bool:
    return (
        task["project_id"] == artifact.get("project_id")
        and task["task_id"] == artifact.get("task_id")
    )


def task_kind_of(task: dict[str, Any]) -> str:
    return task.get("task_kind", "implementation")


def command_task_create(args: argparse.Namespace) -> None:
    output = Path(args.output).resolve()
    repository = Path(args.repository).resolve()
    verify_repository(repository)
    base_revision = git_revision(repository, args.base_revision)
    target_revision = git_revision(repository, f"refs/heads/{args.target_branch}")
    if base_revision != target_revision:
        raise ArtifactError("base_revision must equal the target branch HEAD")
    status = git_run(repository, ["status", "--porcelain"])
    if status.returncode or status.stdout.strip():
        raise ArtifactError("target repository must be clean when the task base is locked")
    task = {
        "artifact_type": "herdr_task",
        "schema_version": SCHEMA_VERSION,
        "project_id": args.project_id,
        "task_id": args.task_id,
        "repository": str(repository),
        "target_branch": args.target_branch,
        "base_revision": base_revision,
        "lane": args.lane,
        "task_kind": args.task_kind,
        "model": args.model,
        "effort": args.effort,
        "workspace": args.workspace,
        "owner": args.owner,
        "objective": args.objective,
        "context": args.context,
        "requirements": args.requirement,
        "owns": args.owns,
        "does_not_own": args.does_not_own,
        "verification": args.verification,
        "authority": {
            "edit": args.allow_edit,
            "commit": args.allow_commit,
            "network": args.allow_network,
            "external_actions": args.external_action,
        },
        "done_when": args.done_when,
        "dependencies": args.dependency,
        "instruction_layers": args.instruction_layer,
    }
    validate_task(task, output)
    write_json(output, task)
    print(output)


def command_validate(args: argparse.Namespace) -> None:
    path = Path(args.artifact).resolve()
    validate_artifact(read_json(path), path)
    print(f"VALID {path}")


def command_render(args: argparse.Namespace) -> None:
    task_path = Path(args.task).resolve()
    rendered = render_prompt(read_json(task_path), task_path)
    if args.output:
        output = Path(args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered)
        print(output)
    else:
        print(rendered, end="")


def command_evidence_add(args: argparse.Namespace) -> None:
    task_path = Path(args.task).resolve()
    task = read_json(task_path)
    validate_task(task, task_path)
    workspace = Path(args.workspace).resolve()
    verify_repository(workspace)
    revision = git_revision(workspace, args.revision)
    if git_revision(workspace, "HEAD") != revision:
        raise ArtifactError("evidence revision must equal workspace HEAD")
    output = Path(args.output).resolve()
    if output.exists():
        evidence = read_json(output)
        validate_evidence(evidence)
        if not identity_matches(task, evidence):
            raise ArtifactError("evidence project_id/task_id does not match the task")
    else:
        evidence = {
            "artifact_type": "herdr_evidence",
            "schema_version": task["schema_version"],
            "project_id": task["project_id"],
            "task_id": task["task_id"],
            "records": [],
        }
    record: dict[str, Any] = {
        "command": args.command,
        "exit_code": args.exit_code,
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "revision": revision,
        "workspace": str(workspace),
    }
    if args.output_file:
        digest = hashlib.sha256(Path(args.output_file).read_bytes()).hexdigest()
        record["output_digest"] = f"sha256:{digest}"
    if args.notes:
        record["notes"] = args.notes
    evidence["records"].append(record)
    validate_evidence(evidence)
    write_json(output, evidence)
    print(output)


def command_handoff_create(args: argparse.Namespace) -> None:
    task_path = Path(args.task).resolve()
    task = read_json(task_path)
    validate_task(task, task_path)
    repository = Path(task["repository"])
    base_revision = git_revision(repository, args.base_revision)
    if base_revision != git_revision(repository, task["base_revision"]):
        raise ArtifactError("handoff base revision must match the Root-locked task base")
    revision = git_revision(repository, args.revision)
    evidence_paths = []
    for evidence_arg in args.evidence:
        evidence_path = Path(evidence_arg).resolve()
        evidence = read_json(evidence_path)
        validate_evidence(evidence)
        if not identity_matches(task, evidence):
            raise ArtifactError(
                f"evidence project_id/task_id does not match the task: {evidence_path}"
            )
        evidence_paths.append(str(evidence_path))
    handoff = {
        "artifact_type": "herdr_handoff",
        "schema_version": task["schema_version"],
        "project_id": task["project_id"],
        "task_id": task["task_id"],
        "result": args.result,
        "base_revision": base_revision,
        "revision": revision,
        "changed_files": args.changed_file,
        "evidence": evidence_paths,
        "questions": args.question,
        "dependencies": args.dependency,
    }
    if task["schema_version"] == SCHEMA_VERSION:
        handoff["findings"] = args.finding
    validate_handoff(handoff)
    output = Path(args.output).resolve()
    write_json(output, handoff)
    print(output)


def command_verify_handoff(args: argparse.Namespace) -> None:
    task_path = Path(args.task).resolve()
    task = read_json(task_path)
    validate_task(task, task_path)
    handoff_path = Path(args.handoff).resolve()
    handoff = read_json(handoff_path)
    validate_handoff(handoff)
    result = semantic_verify_handoff(task, handoff)
    if args.output:
        output = Path(args.output).resolve()
        write_json(output, result)
        print(output)
    else:
        print(json.dumps(result, indent=2, sort_keys=True))


def command_root_verify(args: argparse.Namespace) -> None:
    task_path = Path(args.task).resolve()
    task = read_json(task_path)
    validate_task(task, task_path)
    handoff = read_json(Path(args.handoff).resolve())
    validate_handoff(handoff)
    output = Path(args.output).resolve()
    verification = root_verify(
        task,
        handoff,
        worktree=Path(args.worktree).resolve(),
        phase=args.phase,
        requirements_checked=args.requirement_checked,
        done_when_checked=args.done_checked,
        output_dir=output.parent / f"{output.stem}.logs",
        timeout=args.timeout,
    )
    write_json(output, verification)
    print(output)
    if verification["result"] != "pass":
        raise ArtifactError("root verification failed; inspect the recorded command outputs")


def command_decision_create(args: argparse.Namespace) -> None:
    task_path = Path(args.task).resolve()
    task = read_json(task_path)
    validate_task(task, task_path)
    handoff_path = Path(args.handoff).resolve()
    handoff = read_json(handoff_path)
    validate_handoff(handoff)
    if not identity_matches(task, handoff):
        raise ArtifactError("handoff project_id/task_id does not match the task")
    root_verification_path: str | None = None
    if args.root_verification:
        root_path = Path(args.root_verification).resolve()
        root_verification = read_json(root_path)
        verify_root_acceptance(
            task, handoff, root_verification, check_checkout=True
        )
        root_verification_path = str(root_path)
    elif args.decision == "ACCEPT":
        raise ArtifactError("ACCEPT requires --root-verification")
    decision = {
        "artifact_type": "herdr_decision",
        "schema_version": task["schema_version"],
        "project_id": handoff["project_id"],
        "task_id": handoff["task_id"],
        "task": str(task_path),
        "handoff": str(handoff_path),
        "event_id": args.event_id,
        "decision": args.decision,
        "decided_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "evidence_checked": args.evidence_checked,
        "root_verification": root_verification_path,
        "reason": args.reason,
    }
    validate_decision(decision)
    output = Path(args.output).resolve()
    write_json(output, decision)
    print(output)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create and validate Herdr orchestration artifacts."
    )
    commands = parser.add_subparsers(dest="command_name", required=True)

    task_parser = commands.add_parser(
        "task-create", help="create a validated task contract"
    )
    task_parser.add_argument("--project-id", required=True)
    task_parser.add_argument("--task-id", required=True)
    task_parser.add_argument("--repository", required=True)
    task_parser.add_argument("--target-branch", required=True)
    task_parser.add_argument("--base-revision", required=True)
    task_parser.add_argument(
        "--lane", choices=("tiny", "normal", "high-risk"), required=True
    )
    task_parser.add_argument(
        "--task-kind",
        choices=("implementation", "investigation"),
        default="implementation",
    )
    task_parser.add_argument(
        "--model",
        choices=("gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"),
        required=True,
    )
    task_parser.add_argument(
        "--effort",
        choices=("low", "medium", "high", "xhigh", "max"),
        required=True,
    )
    task_parser.add_argument("--workspace", required=True)
    task_parser.add_argument("--owner", required=True)
    task_parser.add_argument("--objective", required=True)
    task_parser.add_argument("--context", required=True)
    task_parser.add_argument("--requirement", action="append", required=True)
    task_parser.add_argument("--owns", action="append", required=True)
    task_parser.add_argument("--does-not-own", action="append", required=True)
    task_parser.add_argument("--verification", action="append", required=True)
    task_parser.add_argument("--done-when", action="append", required=True)
    task_parser.add_argument("--dependency", action="append", default=[])
    task_parser.add_argument("--instruction-layer", action="append", default=[])
    task_parser.add_argument("--allow-edit", action="store_true")
    task_parser.add_argument("--allow-commit", action="store_true")
    task_parser.add_argument("--allow-network", action="store_true")
    task_parser.add_argument("--external-action", action="append", default=[])
    task_parser.add_argument("--output", required=True)
    task_parser.set_defaults(handler=command_task_create)

    validate_parser = commands.add_parser("validate", help="validate an artifact")
    validate_parser.add_argument("artifact")
    validate_parser.set_defaults(handler=command_validate)

    render_parser = commands.add_parser(
        "render-prompt", help="render layered instructions and a task contract"
    )
    render_parser.add_argument("--task", required=True)
    render_parser.add_argument("--output")
    render_parser.set_defaults(handler=command_render)

    evidence_parser = commands.add_parser(
        "evidence-add", help="append a personally observed command result"
    )
    evidence_parser.add_argument("--task", required=True)
    evidence_parser.add_argument("--command", required=True)
    evidence_parser.add_argument("--exit-code", required=True, type=int)
    evidence_parser.add_argument("--revision", required=True)
    evidence_parser.add_argument("--workspace", required=True)
    evidence_parser.add_argument("--output-file")
    evidence_parser.add_argument("--notes")
    evidence_parser.add_argument("--output", required=True)
    evidence_parser.set_defaults(handler=command_evidence_add)

    handoff_parser = commands.add_parser(
        "handoff-create", help="create a commit-addressed handoff"
    )
    handoff_parser.add_argument("--task", required=True)
    handoff_parser.add_argument(
        "--result",
        choices=("ready", "blocked", "investigated"),
        default="ready",
    )
    handoff_parser.add_argument("--base-revision", required=True)
    handoff_parser.add_argument("--revision", required=True)
    handoff_parser.add_argument("--changed-file", action="append", default=[])
    handoff_parser.add_argument("--evidence", action="append", default=[])
    handoff_parser.add_argument("--question", action="append", default=[])
    handoff_parser.add_argument("--dependency", action="append", default=[])
    handoff_parser.add_argument("--finding", action="append", default=[])
    handoff_parser.add_argument("--output", required=True)
    handoff_parser.set_defaults(handler=command_handoff_create)

    verify_handoff_parser = commands.add_parser(
        "verify-handoff",
        help="verify handoff identity, Git ancestry, scope, and required evidence",
    )
    verify_handoff_parser.add_argument("--task", required=True)
    verify_handoff_parser.add_argument("--handoff", required=True)
    verify_handoff_parser.add_argument("--output")
    verify_handoff_parser.set_defaults(handler=command_verify_handoff)

    root_verify_parser = commands.add_parser(
        "root-verify",
        help="run Root-owned verification on a candidate or integrated checkout",
    )
    root_verify_parser.add_argument("--task", required=True)
    root_verify_parser.add_argument("--handoff", required=True)
    root_verify_parser.add_argument("--worktree", required=True)
    root_verify_parser.add_argument(
        "--phase",
        choices=("candidate", "integrated", "investigation"),
        required=True,
    )
    root_verify_parser.add_argument(
        "--requirement-checked", action="append", required=True
    )
    root_verify_parser.add_argument("--done-checked", action="append", required=True)
    root_verify_parser.add_argument("--timeout", type=int, default=1800)
    root_verify_parser.add_argument("--output", required=True)
    root_verify_parser.set_defaults(handler=command_root_verify)

    decision_parser = commands.add_parser(
        "decision-create", help="record Root's ACCEPT, REVISE, or WAIT decision"
    )
    decision_parser.add_argument("--task", required=True)
    decision_parser.add_argument("--handoff", required=True)
    decision_parser.add_argument("--root-verification")
    decision_parser.add_argument("--event-id", required=True)
    decision_parser.add_argument(
        "--decision", choices=("ACCEPT", "REVISE", "WAIT"), required=True
    )
    decision_parser.add_argument("--evidence-checked", action="append", required=True)
    decision_parser.add_argument("--reason", required=True)
    decision_parser.add_argument("--output", required=True)
    decision_parser.set_defaults(handler=command_decision_create)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.handler(args)
    except (ArtifactError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
