# Paseo Control-Plane Migration Design

## Status

Implemented and active for new tasks. The disposable negative and positive
cutover fixtures passed on Paseo `0.2.5`; the first separately authorized,
bounded ClassHub task remains the release-qualification pilot.

This design replaces Herdr with Paseo while retaining the Engineering Chief of
Staff trust model and ClassHub Definition of Done.

This document defines the intended architecture and safety invariants. The
step-by-step delivery contract is in
[`paseo-migration-implementation-plan.md`](./paseo-migration-implementation-plan.md).

## Objective

Replace Herdr as the managed-agent execution and observation layer with Paseo.
Keep the Chief of Staff responsible for intake, decomposition, authority,
model routing, Git trust anchors, verification, integration, acceptance, and
the final user report.

The migration must not weaken the rule that worker output is an untrusted
claim. A task is complete only after Root independently verifies the exact
candidate, integrates it safely, and repeats verification in the clean target
checkout.

## Target architecture

```text
User request
    -> Chief of Staff intake and task contract
    -> lock target branch and exact base commit
    -> create task-owned Git worktree from the locked commit
    -> register/select Paseo workspace
    -> launch an explicitly routed Codex worker through Paseo
    -> monitor with Paseo and reuse the same agent for corrections
    -> receive commit-addressed evidence and handoff
    -> Root candidate diff/scope/test verification
    -> fast-forward unchanged target branch
    -> Root integrated diff/scope/test verification
    -> ACCEPT, REVISE, or WAIT
    -> concise business-level report
```

### Responsibility boundary

Paseo owns:

- agent and workspace lifecycle;
- provider/model launch transport;
- follow-up delivery;
- activity, status, logs, and user-visible sessions;
- session cancellation and workspace archival.

Chief of Staff owns:

- requirement intake and risk classification;
- task contracts, ownership, exclusions, and authority;
- target branch and exact base-revision locking;
- writer/reviewer topology;
- model and reasoning-effort policy;
- evidence and handoff semantics;
- direct Git and diff inspection;
- candidate and integrated verification;
- corrections and acceptance decisions;
- preservation of user work and safe cleanup;
- the final report.

## MVP decisions

### 1. Use the Paseo CLI as the initial integration surface

Root invokes the installed `paseo` CLI and consumes structured output where
available. The implementation must inspect the installed CLI help and version
before relying on syntax because the public command surface can change.

Do not make injected Paseo MCP tools a requirement for the MVP. CLI-first
control keeps the tool catalog out of managed-worker context and makes command
and output handling easier to test.

The initial implementation is characterized against Paseo CLI `0.2.5`. Treat
that version as the first tested capability baseline, not as a permanent syntax
promise. Live preflight must fail closed when the CLI and daemon versions are
incompatible or a required command/output field is unavailable.

Use JSON only from commands that explicitly support it. In the tested command
surface, `run`, `send`, `wait`, `inspect`, workspace operations, provider
discovery, and agent listing expose structured output. `logs` is a curated
human-readable transcript and must never be parsed to advance a machine gate.

`run --output-schema` cannot be combined with background execution in the
tested CLI. The MVP therefore keeps the task-local evidence and handoff files
as the authoritative worker result rather than treating provider structured
output as the handoff transport.

### 2. Root is the only orchestrator

Managed workers must not create Paseo agents, schedules, heartbeats, or nested
agent teams. Do not inject Paseo orchestration tools into workers for the MVP.
Worker prompts must also explicitly forbid nested delegation.

The permitted topology is one managed level:

```text
Root Chief of Staff
    -> writer
    -> optional reviewer for a named risk
```

A writer or reviewer creating any child agent is a policy violation. For the
default external Root, the writer has no Paseo parent. When Root was optionally
launched through Paseo, the writer parent must equal that exact Root ID.

### 3. Chief of Staff retains exact Git worktree control

For the first release, Chief of Staff creates each writer worktree itself from
the locked full commit hash, then makes that checkout available to Paseo.

Register that existing checkout as a directory-backed Paseo workspace:

```bash
paseo workspace create \
  --isolation local \
  --path '<absolute-task-worktree>' \
  --json
```

Do not use `--isolation worktree` or `paseo run --new-workspace worktree` in
the MVP. Those modes ask Paseo to create and own another worktree and would
break the Chief-owned exact-base and cleanup boundary.

Do not rely only on a moving branch name passed as Paseo's worktree base. If a
later implementation proves that the installed Paseo version accepts and
preserves an exact commit anchor, native Paseo worktrees can be evaluated in a
separate release.

Required checks before worker launch:

- the target repository is the expected repository;
- the locked base is a full Git commit hash;
- the target branch still points at the locked base when required by the task;
- the worktree path is task-owned and explicit;
- worktree `HEAD` equals the locked base;
- concurrent writers have separate worktrees and non-overlapping ownership.

### 4. Preserve artifact types while versioning their safety contract

The release retains legacy artifact type names such as `herdr_task` and
`herdr_handoff`. Schema v4 adds immutable task-kind and investigation fields
without renaming those compatibility identifiers.

Runtime-neutral artifact names can be introduced later with an explicit schema
version and backward-compatibility policy.

### 5. Keep current ClassHub model policy

- bounded routine work starts with `gpt-5.6-luna`;
- tiny work may use Luna `medium`;
- normal work defaults to Luna `max`; high-risk work is fail-closed in the MVP;
- increase Luna effort before escalating providers;
- use `gpt-5.6-terra` only for a concrete judgment or architecture need, or
  after an evidence-backed Luna limitation;
- never use Sol for a managed ClassHub task;
- never use an effort that enables an untracked nested agent hierarchy.

Root must confirm the model and effort that actually launched. Requested
settings are not proof that the provider accepted them. The task contract may
retain the logical name `effort`, but the Paseo adapter must map it to an exact
installed `--thinking` ID and record both the requested effort and observed
thinking route.

### 6. Keep ClassHub Dusk as the browser release gate

Paseo browser automation is out of MVP scope. When added later, it may provide
read-only exploratory evidence, reproduction steps, screenshots, console logs,
and network observations. It does not replace Root's candidate and integrated
Laravel Dusk runs through ClassHub's safe runner.

### 7. Exclude autonomous scheduling from the MVP

Do not enable Paseo schedules, heartbeats, long-running loops, automatic push,
deployment, pull-request creation, or production operations as part of this
migration.

## Runtime mapping

The implementation must confirm exact installed syntax, but the conceptual
mapping is:

| Current responsibility | Paseo target |
| --- | --- |
| Register task checkout | `paseo workspace create --isolation local --path <absolute-path> --json` |
| Start managed worker | `paseo run --workspace <full-id> --provider codex --model <model> --thinking <id> --label <key=value> --background --json <prompt>` |
| Confirm actual runtime | `paseo inspect --json <full-agent-id>` |
| Send a correction | `paseo send --no-wait --prompt-file <path> --json <full-agent-id>` |
| Wait for current attempt | `paseo wait --json --timeout <seconds> <full-agent-id>` |
| Inspect recent activity | `paseo logs --tail <n> <full-agent-id>` for human diagnosis only |
| Stream for diagnosis | `paseo attach <agent-id>` only when needed |
| Cancel current run | `paseo stop --json <full-agent-id>` while preserving the session |
| Retire one agent | `paseo archive --json <full-agent-id>` |
| Retire task-created workspace | `paseo workspace archive <full-workspace-id> --json` after safe cleanup gates |

Every returned agent and workspace ID is opaque. Capture it from structured
output, store it in the task-local resource ledger, and never guess it from
display order or a truncated ID.

The tested `inspect` output exposes the agent cwd but not its Paseo workspace
ID. Verify the complete chain instead of assuming it:

```text
ledger workspace ID
    -> structured workspace listing reports the expected absolute cwd
    -> structured agent inspection reports the same cwd
    -> Git inspection proves that cwd is the task-owned checkout
```

## Orchestration lifecycle

### Preflight

Root must verify:

1. the `paseo` binary is installed;
2. the installed version and relevant command help are readable;
3. the daemon is reachable;
4. Root is running with an unambiguous Paseo identity/workspace context;
5. Codex is configured and authenticated;
6. the required Luna/Terra model and effort routes are available;
7. no policy-forbidden worker orchestration injection is enabled;
8. the target repository and ClassHub safe-test prerequisites are present.

For this ClassHub MVP, the default Root is the Codex CLI process the user opens
directly in the Chief of Staff repository. `PASEO_AGENT_ID` is not required.
Every worker operation still supplies an explicit workspace and full agent ID;
the worker's expected Paseo parent is `null`.

An optionally Paseo-managed Root remains supported. In that mode its full
`PASEO_AGENT_ID`, cwd, provider, and session persistence are inspected, and the
worker parent must equal that Root ID. In both modes the CLI rejects a Root
running outside the exact Chief of Staff repository.

### Launch

Root must:

1. create and validate the task contract;
2. lock target branch and full base revision;
3. create and validate the task-owned worktree;
4. create or select an explicit Paseo workspace for that path;
5. create and persist the initial attempt identity;
6. launch exactly one writer by default with the self-contained prompt;
7. capture the agent/workspace IDs and atomically attach them to the attempt;
8. confirm actual provider, model, thinking route, checkout, session
   persistence, and readiness with structured inspection;
9. confirm the worker consumed the task without treating that acknowledgment
   as implementation evidence.

### Monitoring

Use one meaningful wait for the active run. Do not create a model-driven
short-polling loop. A completed wait means only that the current run ended or
changed state; it does not prove a valid handoff or correct implementation.

After a terminal event or meaningful deadline, read only the relevant activity
and inspect the expected artifact location.

`idle`, `completed`, timeout, permission, and error are attempt signals only.
They must be recorded against the currently active attempt before Root examines
the handoff. A stale or duplicate signal for an older attempt is idempotently
ignored and cannot replace a newer task state.

### Correction

Send exact failed evidence back to the same writer agent. Preserve the agent's
conversation, checkout, and scope. Start a replacement only when the role,
provider, authority, or checkout must materially change.

Create a new Root-owned attempt identity before every correction, even though
the Paseo agent ID stays the same. Send the correction with `--no-wait`, then
perform one explicit wait for that attempt. If session persistence is not
available, fail closed rather than silently launching a context-free
replacement.

### Acceptance

`ACCEPT` remains forbidden unless all of the following hold:

- the handoff matches the task, owner, locked base, and exact candidate commit;
- the candidate worktree is clean and points at the candidate;
- actual changed files satisfy `owns` and `does_not_own`;
- Root personally inspects the diff and checks every requirement and
  `done_when` item;
- Root's candidate verification passes;
- the target branch is still safe to fast-forward from the locked base;
- integration completes without overwriting user work;
- Root repeats verification in the clean target checkout;
- integrated verification passes and is the evidence referenced by the
  decision.

Paseo status, logs, structured output, and reviewer agreement are supporting
claims only.

### Cleanup

Archive only resources created for the task. Preserve a dirty worktree, an
unintegrated candidate, an unanswered handoff, or a session needed for a
correction. Never make Paseo workspace archival the only copy of recoverable
work.

Archiving a Paseo workspace also retires the agents and terminals it owns. Only
archive a workspace when the ledger proves it was created for this task and no
session is still needed. Never archive a pre-existing workspace as task
cleanup; archive only the task-created agent in that case.

Because MVP worktrees are Chief-created and registered in Paseo's local
isolation mode, Paseo archival and Git worktree removal are separate actions.
Root must
run the Git cleanliness, integration, and recoverability gates again before
removing the Chief-owned worktree.

## Resource ledger

Each task must record at least:

- project and task IDs;
- target repository;
- target branch and locked base revision;
- task-owned branch and worktree path;
- Paseo workspace ID;
- Paseo agent ID, provider, model, effort, and role;
- created versus pre-existing resources;
- wait and correction events;
- candidate revision;
- evidence, handoff, Root verification, and decision paths;
- cleanup outcome and any intentionally retained resources.

### Durable attempt identity

Paseo `wait` does not provide a stable completion identity in the tested CLI,
so Chief of Staff owns it. Before each launch or correction, atomically append
an attempt containing at least:

- a Root-generated `attempt_id` and monotonic `dispatch_sequence`;
- agent ID and expected workspace ID;
- role, model, thinking route, and prompt digest;
- dispatch and terminal timestamps;
- terminal signal and observed agent metadata;
- linked handoff, candidate revision, and correction evidence when present.

Label newly launched agents with project ID, task ID, role, and initial attempt
ID for recovery and diagnosis. Labels aid reconciliation but never replace the
full IDs stored in the ledger.

Persist the initial attempt in `dispatching` state before launch and include
its ID as an agent label. If launch succeeds but Root loses the response before
recording the agent ID, reconcile with a global structured agent query filtered
by that full attempt label and the exact cwd. Exactly one match may be adopted;
zero or multiple matches must enter `WAIT` for explicit recovery and must not
trigger an automatic duplicate launch.

### Coordinator state machine

The minimal durable state machine is:

```text
PREPARED
    -> WORKTREE_READY
    -> RUNNING
    -> HANDOFF_RECEIVED
    -> CANDIDATE_VERIFIED
    -> INTEGRATED
    -> INTEGRATED_VERIFIED
    -> ACCEPTED
```

`WAIT`, `REVISE`, `FAILED`, and `RETAINED` are explicit non-accepting states.
`REVISE -> RUNNING` requires a new persisted attempt. `WAIT -> RUNNING`
requires a reconciled existing attempt or a new persisted attempt, depending
on whether the worker run actually continued. `ACCEPTED` is terminal. Every
transition must be validated and atomically recorded. On restart, Root must
reconcile the ledger with Paseo inspection, workspace identity, Git HEAD,
cleanliness, artifacts, and target-branch position before sending, integrating,
accepting, archiving, or removing anything.

No Paseo status can skip `HANDOFF_RECEIVED`, candidate verification,
integration, or integrated verification.

## Cutover and rollback boundary

The release uses one active runtime after cutover, but the operational change
is staged:

1. record a known-good Chief revision;
2. stop accepting new Herdr tasks;
3. let existing Herdr tasks finish under Herdr without translating live IDs;
4. implement and verify Paseo on a branch or unreleased revision;
5. pass unit and disposable positive/negative fixture tests;
6. switch active instructions and runtime entry points to Paseo, retaining
   Herdr names only as clearly inactive compatibility/history;
7. run a separately authorized low-risk ClassHub pilot;
8. mark the release qualified and archive inactive legacy documentation only
   after the pilot gate passes.

This is not permanent dual-backend support. A task is owned by exactly one
control plane for its entire lifetime. Rollback preserves unfinished work and
returns new task intake to the known-good revision.

## Security and authority

- A worker may edit only the task-owned checkout and declared scope.
- Implementation authority does not authorize push, deploy, PR creation,
  production data mutation, global configuration changes, or unsafe tests.
- Root must not automatically approve an external or destructive permission
  request merely because a worker is blocked.
- Keep remote Paseo access, relay, browser cookies, and authenticated sessions
  outside MVP scope unless separately authorized and reviewed.
- Do not expose repository credentials or secrets in prompts, labels, logs, or
  task metadata.

## Token-efficiency requirements

- Use CLI control rather than injecting the entire Paseo MCP catalog into
  workers.
- Start one writer; add a reviewer only for a named risk.
- Reuse the writer for corrections.
- Use Luna before Terra according to the routing policy.
- Use one long-lived wait rather than repeated status polling.
- Read a bounded log tail after meaningful state changes.
- Store evidence in files and pass exact failed evidence instead of replaying
  full transcripts.
- Do not launch agents merely to populate a dashboard.

## Deferred capabilities

The following are valuable but intentionally deferred:

- native Paseo-managed worktree creation and teardown;
- `paseo.json` setup hooks, per-worktree services, ports, and reverse proxy;
- Paseo browser tester;
- schedules and heartbeats;
- mobile or remote approval workflows;
- automatic PR creation or Git integration actions;
- artifact schema rename from `herdr_*` to runtime-neutral names;
- automatic pane/grid layout management.

Each deferred feature requires its own authority, cleanup, and verification
review before adoption.

## Migration success criteria

The control-plane migration is complete only when:

- Chief of Staff can run without a Herdr binary or server;
- one task can travel from contract through Paseo delegation to integrated
  Root verification and decision;
- the requested Luna/Terra route is confirmed at runtime;
- managed workers cannot create nested agents through the provided tools;
- worker completion without a valid handoff cannot advance the gate;
- worker-declared tests cannot replace Root tests;
- candidate success cannot replace integrated verification;
- correction reuses the intended Paseo agent;
- task cleanup preserves user work and unintegrated candidates;
- Root can restart and reconcile an in-progress task without guessing an ID or
  replaying a completed correction;
- duplicate or stale attempt signals cannot create contradictory decisions;
- the repository unit suite and positive/negative end-to-end fixture tasks
  pass.

The implementation is complete when the disposable fixture gates pass. The
release is qualified for normal ClassHub use only after a separately authorized
low-risk ClassHub pilot also satisfies the existing Definition of Done.
