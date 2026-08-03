# Paseo Migration Implementation Plan

## Purpose

This is the delivery contract for replacing Herdr with Paseo as the Chief of
Staff control plane. Read
[`paseo-migration-design.md`](./paseo-migration-design.md) first. Its trust and
authority rules are mandatory.

The implementer is authorized to modify this repository, run its focused tests,
and create local commits when requested by the task owner. This plan does not
authorize push, deployment, pull-request creation, ClassHub product changes,
production operations, global Paseo configuration changes, or destructive
cleanup.

## Outcome

Deliver a minimal Paseo-backed Chief of Staff that preserves the current task
contract, Git scope gate, candidate verification, integrated verification,
correction, and acceptance behavior.

Do not add browser automation, schedules, heartbeats, or native Paseo service
management. Safety-compatible schema versioning is allowed while retaining the
existing artifact type names.

## Required preparation

Before editing:

1. Read the repository `AGENTS.md` and all instruction files it routes.
2. Inspect the current worktree and preserve unrelated user changes.
3. Run the current unit suite and record the baseline.
4. Inspect the installed Paseo command surface rather than relying only on
   public documentation:

   ```bash
   paseo --version
   paseo --help
   paseo daemon --help
   paseo daemon status --help
   paseo workspace --help
   paseo workspace create --help
   paseo run --help
   paseo send --help
   paseo wait --help
   paseo inspect --help
   paseo agent update --help
   paseo logs --help
   paseo stop --help
   paseo archive --help
   paseo provider models --help
   ```

5. Determine which commands support JSON or another deterministic output
   format. Never parse `paseo logs` to drive coordinator state or acceptance.
6. Record the CLI and daemon versions and fail closed when they are incompatible
   or outside the tested capability range.
7. Do not start, stop, pair, reconfigure, update, or remotely expose the Paseo
   daemon without explicit authorization.

If Paseo is not installed, complete the code and mocked tests that do not
require it, report the missing live dependency, and do not install it
implicitly.

## Delivery strategy

Use a staged hard switch to Paseo. Do not build and maintain permanent parallel
Herdr and Paseo backends. Before cutover, stop assigning new Herdr tasks and let
already-running Herdr tasks finish on Herdr. Never translate an active Herdr
pane/session ID into a Paseo agent ID.

Implement and test the Paseo runtime before changing active startup policy.
Switch `AGENTS.md`, user entry points, and active examples only after the unit
suite and disposable positive/negative fixture gates pass. Preserve rollback
through Git history or a pre-migration tag.

Keep legacy artifact type strings for compatibility in this release. Remove
active Herdr runtime requirements and active Herdr command examples.

## Work package 1: Baseline and characterization

### Work

- Run `python3 -m unittest discover -s tests -v`.
- Record current passing/failing tests in the task evidence.
- Identify every runtime Herdr dependency with `rg`.
- Separate runtime coupling from compatibility-only names.
- Confirm the current artifact schema version and backward-reading policy.

### Done when

- The baseline is recorded.
- Every Herdr reference is classified as runtime, documentation, test fixture,
  or compatibility identifier.
- Existing unrelated changes are identified and preserved.

## Work package 2: Paseo preflight and doctor

### Primary files

- `herdr-orchestrator/chiefctl.py`
- `tests/test_chiefctl.py`
- `bin/chiefctl` only if its entry-point behavior must change.

### Work

- Replace Herdr binary and environment checks with Paseo checks.
- Keep the non-live doctor useful when the daemon is absent.
- Make live preflight verify the installed CLI, daemon reachability, and
  unambiguous Root execution context.
- Discover Codex provider/model capabilities through the installed Paseo
  surface when available.
- Emit actionable failures without starting or changing daemon state.
- Ensure `prepare-classhub` renders Paseo-oriented next steps.
- Preserve explicit Luna/Terra and effort restrictions.

### Tests

- Paseo binary missing.
- Paseo binary present but daemon unreachable.
- Live preflight outside the Chief repository, plus the optional managed-Root
  context.
- Valid mocked Paseo responses.
- Unsupported or missing Luna/Terra route.
- CLI/daemon version mismatch or missing required capability.
- Codex route without reusable session persistence.
- Malformed JSON/command failure.
- No subprocess command is constructed through an unsafe shell string.

### Done when

- `doctor` no longer requires Herdr.
- `doctor --live` fails closed on ambiguous or unavailable Paseo state.
- No doctor operation starts, stops, pairs, updates, or reconfigures Paseo.

## Work package 3: Durable coordinator runtime

### Primary files

- `herdr-orchestrator/paseo_runtime.py` as a compatibility-path MVP module;
- `herdr-orchestrator/chiefctl.py` for user-facing orchestration commands;
- `tests/test_paseo_runtime.py`;
- task-local runtime files under `.runtime/<project-id>/<task-id>/`.

The legacy directory name may remain for this release to avoid combining the
control-plane change with a broad file-layout migration. The new module and its
active documentation must be explicitly Paseo-oriented.

### Work

- Implement one deterministic subprocess boundary that always uses argv lists,
  never a shell string.
- Add typed parsing for structured `workspace create`, `run`, `inspect`,
  `send`, `wait`, `stop`, and archive results.
- Treat `logs` and `attach` as human diagnostic operations only.
- Create an atomic JSON resource ledger before the first mutable operation.
- Generate a unique `attempt_id`, monotonic `dispatch_sequence`, and prompt
  digest before initial launch and every correction.
- Persist the initial attempt as `dispatching`, pass its identity as a launch
  label, then attach the returned full agent ID atomically.
- Record expected and observed provider, model, thinking route, workspace,
  checkout, parent, persistence capability, and terminal signal.
- Add a validated state machine:

  ```text
  PREPARED -> WORKTREE_READY -> RUNNING -> HANDOFF_RECEIVED
      -> CANDIDATE_VERIFIED -> INTEGRATED
      -> INTEGRATED_VERIFIED -> ACCEPTED
  ```

- Support explicit `WAIT`, `REVISE`, `FAILED`, and `RETAINED` states.
- Reconcile ledger, Paseo, artifacts, and Git on restart before performing a
  send, integration, acceptance, archive, or Git worktree removal.
- Make stale and duplicate attempt signals idempotent.
- Label created agents with project ID, task ID, role, and attempt ID, while
  retaining full opaque IDs in the ledger.
- If Root loses the launch response, reconcile with a global structured agent
  query filtered by the full attempt label and exact cwd. Adopt exactly one
  match; enter `WAIT` on zero or multiple matches and do not auto-relaunch.

### Required failure tests

- Process exits successfully but emits malformed or incomplete JSON.
- A short or ambiguous agent/workspace ID is returned.
- Launch succeeds but Root exits before recording the returned agent ID.
- A duplicate terminal signal is delivered for the active attempt.
- A stale signal arrives after a newer correction was dispatched.
- Root restarts while the agent is running, idle, waiting on permission, or
  between candidate and integrated verification.
- Ledger and Paseo disagree about agent, workspace, checkout, model, or parent.
- An invalid state transition attempts to skip handoff or either Root
  verification phase.
- Atomic ledger update fails before a mutable Paseo or Git action.

### Done when

- Every mutable orchestration action is tied to one durable task and attempt.
- Root can resume without guessing identities or replaying a completed action.
- No Paseo lifecycle signal can directly create `ACCEPT`.

## Work package 4: Deterministic worktree ownership

### Primary files

- the orchestration instruction set;
- `herdr-orchestrator/chiefctl.py` if deterministic helpers belong there;
- focused unit tests for command construction and validation.

### Work

- Lock the target branch and full base revision before workspace creation.
- Create task-owned Git branches/worktrees from the exact hash using safe,
  explicit arguments.
- Validate repository identity, worktree path, branch, `HEAD`, and cleanliness.
- Register or select the exact checkout as a Paseo workspace without allowing
  Paseo to silently choose another directory.
- Register a Chief-created worktree only with:

  ```bash
  paseo workspace create \
    --isolation local \
    --path '<absolute-task-worktree>' \
    --json
  ```

- Reject `--isolation worktree`, `--new-workspace worktree`, an omitted
  isolation mode, or any implicit cwd-based workspace selection in the MVP.
- Capture the Paseo workspace ID from structured output.
- Verify the chain from ledger workspace ID, to the structured workspace cwd,
  to the agent's structured inspected cwd, to Git's exact task-owned checkout.
- Maintain a resource ledger distinguishing created and pre-existing resources.
- Define non-destructive cleanup behavior.

### Required failure tests

- Target branch moved after the contract was created.
- Worktree `HEAD` differs from the locked base.
- Workspace path differs from the task-owned worktree.
- Paseo reports a worktree-isolated or Paseo-owned workspace instead of the
  expected local directory-backed workspace.
- Worktree already exists and is not task-owned.
- Dirty worktree during cleanup.
- Candidate exists but has not been integrated.

### Done when

- No writer can start from a moving or unverified base.
- Concurrent writers cannot share a checkout.
- Cleanup cannot remove or archive the only recoverable candidate.

## Work package 5: Paseo agent lifecycle

### Primary files

- replace `HERDR_ORCHESTRATOR.md` with an active Paseo equivalent;
- replace or rewrite `herdr-orchestrator/agent-lifecycle.md`;
- update delegation, model-routing, parallel-worktree, and safety references;
- add focused command/output parsing code only where deterministic helpers add
  value.

### Work

- Launch a writer in an explicit Paseo workspace and background mode.
- Discover the installed Codex model/thinking IDs and map the contract's
  logical model/effort route to an exact `--model` and `--thinking` pair.
- Capture a full, unambiguous agent ID.
- Immediately confirm actual provider, model, thinking route, checkout,
  permitted Root parent, session persistence, and readiness with
  `paseo inspect --json`.
- Stop and fail closed before accepting worker output if the observed route or
  checkout differs from the contract.
- Deliver a self-contained prompt.
- Wait without short polling.
- Inspect bounded recent logs after meaningful events for diagnosis only.
- Before every correction, persist a new attempt identity; send the correction
  to the same full agent ID with `--no-wait --prompt-file ... --json`, then run
  one explicit `wait --json` for that attempt.
- Prefer canceling a current run over destroying a reusable session.
- Archive only task-created Paseo resources after the cleanup gate passes.

### Worker restrictions

- No injected Paseo orchestration tools.
- No nested agents.
- No schedules or heartbeats.
- No push, deploy, PR, production mutation, or global configuration.
- No source editing for a read-only reviewer or browser tester.

### Required failure tests

- Launch returns no agent ID or ambiguous output.
- Requested model differs from observed model.
- Agent exits without a handoff.
- Agent is blocked on a decision outside established authority.
- Correction is addressed to a different agent.
- Correction is sent before its attempt is durably recorded.
- Wait times out.
- Logs are malformed or incomplete; they cannot advance or corrupt state.
- A human-readable log line contradicts structured state; the log cannot
  advance the gate.
- The external-Root writer has no parent; the optional managed-Root writer has
  Root as parent; an actual child whose parent is the writer is rejected.
- Worker attempts nested delegation.

### Done when

- A writer can be launched, observed, corrected, and reused through Paseo.
- Lifecycle completion alone cannot advance acceptance.
- The resource ledger contains every created Paseo resource.

## Work package 6: Runtime-neutral evidence linkage

### Primary files

- `herdr-orchestrator/taskctl.py`
- `tests/test_taskctl.py`
- example artifacts.

### Work

- Keep existing artifact semantics and schema compatibility.
- Treat `workspace` as the verified absolute checkout path, not a Herdr object.
- Record Paseo workspace and agent identity in compatible metadata or a
  backward-compatible optional field.
- Replace Herdr-specific attention-event assumptions with a runtime-neutral
  task event identity.
- Event identity is derived from project ID, task ID, the full Paseo agent ID,
  and Chief's Root-generated `attempt_id`. Do not depend on Paseo exposing a
  run/completion ID, and do not use a mutable display name or timestamp as the
  only key.
- Keep evidence tied to exact Git revision and observed workspace.
- Keep integrated Root verification mandatory for `ACCEPT`.

### Required compatibility tests

- Existing v2/v3 artifacts continue to validate according to current policy.
- New Paseo-linked artifacts validate.
- Wrong agent/workspace/task/base/candidate is rejected.
- Duplicate event delivery cannot create contradictory decisions silently.
- A structured Paseo result without repository evidence cannot create
  `ACCEPT`.

### Done when

- Task gates no longer require live Herdr semantics.
- Compatibility identifiers do not cause a Herdr runtime dependency.
- Exact candidate and integrated verification remain authoritative.

## Work package 7: Acceptance-gate regression coverage

Add or retain tests proving that `ACCEPT` is impossible when:

- the worker merely reports completion;
- the handoff is absent or malformed;
- the handoff points at the wrong candidate;
- actual changed files violate `owns` or `does_not_own`;
- the worker-declared test passes but Root's candidate test fails;
- the candidate worktree is dirty;
- the target branch moved away from the locked base;
- integration is not a safe fast-forward;
- integrated verification fails;
- Root did not acknowledge every requirement and `done_when` item;
- the verification artifact does not match the task and candidate;
- the worker used a forbidden model or nested agent path;
- a stale or duplicate attempt signal is received;
- coordinator state was not reconciled after restart.

### Done when

- The full unit suite passes.
- Each trust-boundary failure is represented by a focused regression test.

## Work package 8: End-to-end smoke test

Use a disposable fixture repository before ClassHub.

### Scenario

1. Create a small repository with one failing behavior and focused test.
2. Prepare a task contract and lock the base commit.
3. Create the task-owned worktree.
4. Launch a Luna worker through Paseo.
5. Use a deterministic hidden acceptance check or controlled fail-once verifier
   to force one Root-discovered failure, then send that exact evidence as a
   correction on the same agent.
6. Require a candidate commit and handoff.
7. Run Root candidate verification.
8. Fast-forward the clean target branch.
9. Run Root integrated verification.
10. Create `ACCEPT` only from integrated evidence.
11. Archive task-owned Paseo state and remove the worktree only after the
    cleanup gate passes.

Also exercise one negative path in which the worker reports success but Root's
test fails; the expected decision is `REVISE` and no integration occurs.
Assert that the target branch did not move and no `ACCEPT` artifact exists.

### Done when

- Both fixture paths behave as specified.
- The Paseo runtime path used by the fixture requires no Herdr process or
  command.

## Work package 9: Active policy and documentation cutover

### Primary files

- `AGENTS.md`
- `README.md`
- new `PASEO_ORCHESTRATOR.md`
- orchestration references under the current directory structure;
- `herdr-orchestrator/projects/classhub.md`;
- examples.

### Work

- Perform this package only after the unit suite and disposable positive and
  negative fixture gates pass.
- Route mandatory startup to the Paseo orchestrator instructions.
- Remove active requirements to run inside a Herdr pane.
- Replace active Herdr commands with verified Paseo commands.
- Keep task contracts, authority, model routing, worktree isolation, candidate
  verification, integrated verification, and reporting rules unchanged.
- State clearly that workers cannot use Paseo to create agents.
- State clearly that Paseo completion/status/logs are claims.
- Document how to start the external Root Chief of Staff directly in this
  repository; Paseo manages only the workers.
- Document exact smoke-test usage for the user.
- Leave legacy names only where required for compatibility, labeled as such.

### Done when

- A new Root reads one unambiguous active control-plane policy.
- No active workflow instruction or runtime entry point requires Herdr.
- User instructions are sufficient to start and test the Paseo-backed flow.

The implementation is complete at this point. Release qualification for normal
ClassHub use is a separate gate.

## Release qualification: ClassHub pilot

The migration implementation authorizes no ClassHub product change. After the
implementation is complete, obtain a separate explicit task/authorization for
one low-risk, bounded ClassHub pilot using the repository's safe test commands.
Do not choose a migration, payment-impacting change, tenant-boundary change, or
broad browser flow for the first pilot.

The Paseo release is qualified for normal ClassHub use only when that pilot
satisfies its task contract and existing integrated Definition of Done.

## Verification commands

At minimum:

```bash
python3 -m unittest discover -s tests -v
```

Also run any new focused tests and a read-only search confirming that active
instructions no longer invoke Herdr. Compatibility strings may remain only
when explicitly documented.

For the ClassHub pilot, use only commands routed by ClassHub's `AGENTS.md` and
safe runners. Browser verification remains Laravel Dusk through `bin/dusk-safe`
when the task requires it.

## Non-goals

- No Paseo installation or update without authorization.
- No daemon restart, pairing, relay enablement, or remote exposure.
- No browser automation in this release.
- No schedules, heartbeats, autonomous loops, or unattended recurring work.
- No native Paseo worktree/service automation yet.
- No push, deployment, PR creation, or production changes.
- No ClassHub feature or bug change as part of the control-plane refactor.
- No artifact schema rename unless a blocker makes compatibility impossible.
- No extra agents merely for visual layout.

## Rollback

Before implementation, record a known-good commit or tag. Stop assigning new
Herdr tasks and allow existing Herdr-owned tasks to finish without migration.
If the live Paseo smoke test cannot meet the trust invariants:

1. preserve all unintegrated worktrees and artifacts;
2. archive only task-created Paseo sessions that are safe to archive;
3. revert new-task intake to the known-good Chief of Staff revision through
   normal Git history without changing ownership of an in-flight task;
4. report the exact failed invariant and evidence;
5. do not weaken the Definition of Done to complete the migration.

## Final handoff requirements

The implementing agent must return:

- summary of the operational change;
- exact changed files;
- installed Paseo version and command surface used, if live-tested;
- baseline and final unit-test evidence;
- positive and negative end-to-end smoke evidence;
- ClassHub pilot evidence, if authorized and performed;
- confirmation that model routing and nested-agent restrictions were checked;
- compatibility names intentionally retained;
- unresolved risks or deferred capabilities;
- cleanup state and any retained worktree/session;
- exact candidate commit.

Do not report the migration complete if the fixture smoke test or integrated
acceptance gate remains unverified.
