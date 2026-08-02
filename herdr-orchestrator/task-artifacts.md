# Herdr Task Artifacts

Use these artifacts for meaningful delegated implementation, review, or
integration work. Tiny read-only reconnaissance may remain inline when an
artifact would add more ceremony than control.

The artifacts improve prompt consistency and evidence packaging. They do not
create another transport: submit rendered prompts and attention through Herdr,
inspect the named repository yourself, and acknowledge an attention event only
after Root records `ACCEPT`, `REVISE`, or `WAIT`.

## Artifact lifecycle

```text
task contract
  -> rendered layered prompt
  -> worker evidence claims
  -> commit-addressed handoff
  -> Root candidate verification
  -> safe integration
  -> Root integrated verification
  -> Root decision
  -> acknowledge Herdr attention event
```

`project_id` and `task_id` must match at every step. Evidence from another
project or task is rejected even if its command passed.

Keep each project's artifacts in its own task-local ledger, outside tracked
source or under an ignored runtime directory. Do not put secrets, credentials,
private keys, or raw sensitive command output in these artifacts.

## Task contract

A task contract makes ownership and exclusions explicit. See
[`examples/login-refresh.task.json`](./examples/login-refresh.task.json).

Required groups:

- identity: project, task, repository, workspace, and owner;
- outcome: objective, requirements, and done conditions;
- boundary: `owns` and `does_not_own`;
- authority: edit, commit, network, and allowed external actions;
- verification and dependencies;
- ordered instruction layers.
- Root-locked lane, target branch, and full base revision.

For machine-enforced implementation gates, write `owns` and `does_not_own` as
repository-relative glob patterns and write `verification` entries as exact
commands. Prose scope or verification descriptions can be rendered for a
worker, but they cannot be checked deterministically.

Instruction paths are relative to the task file unless absolute. Rendering
embeds them in order, followed by the task-specific contract:

```bash
python3 herdr-orchestrator/taskctl.py render-prompt \
  --task herdr-orchestrator/examples/login-refresh.task.json \
  --output /tmp/login-refresh.prompt.md
```

Send the resulting prompt with `herdr pane run`; do not execute it as a shell
script.

## Evidence

Record commands personally observed by the artifact's owner:

```bash
python3 herdr-orchestrator/taskctl.py evidence-add \
  --task /path/to/login-refresh.task.json \
  --command "npm test -- auth" \
  --exit-code 0 \
  --revision "$(git rev-parse HEAD)" \
  --workspace "$(pwd)" \
  --output-file /tmp/auth-test-output.txt \
  --output /path/to/login-refresh.evidence.json
```

When `--output-file` is present, the helper stores its SHA-256 digest rather
than copying potentially large or sensitive command output. An evidence record
is still a claim until Root independently runs the verification command. Each
record is tied to the worker's exact revision and worktree.

## Handoff

Create a handoff only from full Git commit hashes:

```bash
python3 herdr-orchestrator/taskctl.py handoff-create \
  --task /path/to/login-refresh.task.json \
  --base-revision "$base_revision" \
  --revision "$candidate_revision" \
  --changed-file src/auth/refresh.ts \
  --changed-file tests/auth/refresh.test.ts \
  --evidence /path/to/login-refresh.evidence.json \
  --output /path/to/login-refresh.handoff.json
```

The helper verifies that both revisions resolve to commits in the task's
repository and that every evidence artifact has the same project and task IDs.
It does not decide whether the diff is correct.

Before Root considers a ready implementation handoff, run the semantic gate:

```bash
python3 herdr-orchestrator/taskctl.py verify-handoff \
  --task /path/to/login-refresh.task.json \
  --handoff /path/to/login-refresh.handoff.json
```

The claim-inspection gate requires the Root-locked base, a descendant candidate
commit, derives changed files from
Git, compares them with the handoff, checks `owns`/`does_not_own`, runs
`git diff --check`, and requires the latest evidence for every exact
verification command to have a candidate-revision evidence claim. It rejects
unresolved questions or dependencies. A pass here is not acceptance evidence.

Root then runs every verification command itself in the clean candidate
worktree and explicitly acknowledges every requirement and done condition:

```bash
python3 herdr-orchestrator/taskctl.py root-verify \
  --task /path/to/task.json \
  --handoff /path/to/handoff.json \
  --worktree /path/to/writer-worktree \
  --phase candidate \
  --requirement-checked "<exact task requirement>" \
  --done-checked "<exact done_when item>" \
  --output /path/to/candidate.root-verification.json
```

After that passes, Root confirms that the target checkout is clean and still at
the locked base, fast-forwards it to the candidate, and repeats `root-verify`
with `--phase integrated` and `--worktree` set to the target repository. The
runner executes only allowlisted ClassHub safe commands, without a shell, and
stores command-output digests plus the exact reviewed diff digest under the
task ledger.

## Root decision

After inspecting the handoff, diff, and repository evidence, record the
decision before acknowledging the attention event:

```bash
python3 herdr-orchestrator/taskctl.py decision-create \
  --task /path/to/login-refresh.task.json \
  --handoff /path/to/login-refresh.handoff.json \
  --root-verification /path/to/integrated.root-verification.json \
  --event-id evt_01J... \
  --decision ACCEPT \
  --evidence-checked "npm test -- auth (exit 0)" \
  --evidence-checked "git diff --check (exit 0)" \
  --reason "The diff stays in scope and both acceptance checks passed." \
  --output /path/to/login-refresh.decision.json
```

For `REVISE`, send the failed evidence back through the same Herdr pane. For
`WAIT`, state the missing evidence or decision. The decision file is the
durable judgment; Herdr agent status and metadata remain operational hints.
`ACCEPT` is rejected unless the referenced Root verification is passing,
integrated, matches the locked task and candidate, has intact command-output
digests, and the target checkout still points at that exact clean revision.

## Validation

Validate any artifact independently:

```bash
python3 herdr-orchestrator/taskctl.py validate /path/to/artifact.json
```

The CLI uses only the Python standard library and writes deterministic,
human-readable JSON apart from generated UTC timestamps. JSON replacement is
atomic. Evidence timestamps must be ISO-8601 UTC and output digests, when
present, must use `sha256:<64 lowercase hex>`.
