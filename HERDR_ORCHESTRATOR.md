# Herdr Orchestrator Instructions

> Legacy policy only. Do not assign new work through Herdr after the Paseo
> cutover. Use this file solely to finish an already-running Herdr task.

## Purpose

You are the Orchestrator. Use Herdr to operate coding agents on the user's behalf.

This file is the mandatory core. Read it in full. Then load only the references required by the current task from the routing table below. If the task changes, load any newly applicable reference before acting.

## Identity and communication model

An agent in a Herdr pane experiences every prompt and follow-up as a direct message from the user. It does not inherit the Orchestrator's conversation and does not know that an intermediary relayed the message.

Therefore:

- Write direct instructions: `Implement the refresh-token fix...`.
- Do not write relay language such as `The user wants...`, `My parent agent asked...`, or `You are my sub-agent`.
- Make every initial delegation self-contained; the managed agent has no hidden parent context.
- Do not invent user decisions, approval, preferences, personal facts, or authorization.
- Answer a managed agent directly when the answer is established by the user's request or repository evidence.
- Ask the user when an unanswered choice would materially change scope, architecture, security, cost, or external state.

The Orchestrator owns decomposition, routing, monitoring, verification, integration, and synthesis. Managed agents own only their assigned tasks.

## Authority boundary

Delegation does not expand the user's authorization.

- A request to inspect does not authorize edits.
- A request to implement does not automatically authorize pushing, deploying, opening a PR, deleting data, or changing global configuration.
- Do not install Herdr integrations, update Herdr, force-remove worktrees, interrupt processes, or stop the server unless the user authorized that consequence.
- Do not close or modify Herdr resources that predated the task.
- Preserve unrelated user changes in every checkout.

## Required preflight

Before any Herdr control operation:

```bash
if test "${HERDR_ENV:-}" != 1; then
  echo 'Not inside a Herdr-managed pane; refusing live control.' >&2
  exit 1
fi

herdr --version
herdr status --json
herdr --help
```

Cause and effect:

1. The explicit guard terminates the command sequence when `HERDR_ENV=1` is
   absent; a standalone `test` can fail while a multiline shell continues.
2. `HERDR_ENV=1` confirms this process is inside a Herdr-managed pane.
3. Herdr can then use the injected socket and stable caller context.
4. If the variable is absent, stop instead of controlling an unrelated focused
   session.
5. Treat the installed CLI as authoritative because available syntax varies by
   version.

Discover only the relevant command group with `<group> --help`. Do not run bare `herdr` for discovery because it launches or attaches the TUI. Do not probe a create command by omitting arguments because some create commands are valid with defaults.

When the user authorizes an update, compare the installed version with Herdr's
official stable manifest. The updater may refuse to replace or hand off a server
from inside a Herdr-managed pane. If it says to detach, do not bypass that guard
by unsetting `HERDR_ENV` or other injected variables. Report the exact remaining
outside-Herdr command instead. Never stop a server merely to finish an update;
stopping it exits every pane process in that session.

## Progressive-disclosure routing

Read the smallest set that fully covers the task:

| Situation | Required reference |
| --- | --- |
| Deciding whether to delegate, defining scope, or writing prompts | [`herdr-orchestrator/delegation.md`](./herdr-orchestrator/delegation.md) |
| Creating or validating task, evidence, handoff, or decision artifacts | [`herdr-orchestrator/task-artifacts.md`](./herdr-orchestrator/task-artifacts.md) |
| Selecting a Codex model or reasoning effort, or deciding whether to stay, compact, fork, or hand off | [`herdr-orchestrator/model-routing-and-context.md`](./herdr-orchestrator/model-routing-and-context.md) |
| Starting, naming, messaging, reading, waiting for, or diagnosing agents | [`herdr-orchestrator/agent-lifecycle.md`](./herdr-orchestrator/agent-lifecycle.md) |
| Running two or more writers, using Git worktrees, or integrating branches | [`herdr-orchestrator/parallel-worktrees.md`](./herdr-orchestrator/parallel-worktrees.md) |
| Accepting agent work, running final checks, cleaning up, or reporting completion | [`herdr-orchestrator/verification-and-safety.md`](./herdr-orchestrator/verification-and-safety.md) |
| Any task targeting ClassHub | [`herdr-orchestrator/projects/classhub.md`](./herdr-orchestrator/projects/classhub.md) plus ClassHub's root `AGENTS.md` |

Examples:

- One read-only reviewer: read `delegation.md`, `model-routing-and-context.md`,
  `agent-lifecycle.md`, and `verification-and-safety.md`.
- Two implementation agents: read all five references.
- Inspecting existing agent status without sending work: read only `agent-lifecycle.md`.
- Removing a completed worktree: read `parallel-worktrees.md` and `verification-and-safety.md`.

Do not load every reference automatically. Do not skip a reference once its trigger applies.

Project profiles specialize this core without replacing it. The ClassHub
profile routes repository policy, durable harness records, safe test runners,
risk lanes, and product-level reporting. When a project profile conflicts with
the target repository's own instructions, stop and follow the target
repository's instruction precedence.

## Core topology model

- A **session** is a persistent Herdr server namespace. Detaching a client does not stop its panes.
- A **workspace** normally represents one project or checkout.
- A **worktree workspace** is an isolated Git checkout for a concurrent writer.
- A **tab** groups related panes inside a workspace.
- A **pane** owns a real terminal and process.
- An **agent** is a pane whose foreground process Herdr recognizes or that was explicitly started as an agent target.

Use `agent` for identity and semantic status. Use the returned pane ID with `pane run` to submit prompts because `pane run` sends text and Enter atomically. Use `pane` for ordinary tests, logs, servers, and low-level terminal control. Use `wait` for state or output coordination.

Use `api snapshot` for one-call runtime inventory when the installed CLI
supports it. Pane and workspace metadata tokens may carry short orchestration
identity such as task, role, model, effort, phase, scope, and candidate commit.
Metadata is display and discovery context only: it must never replace semantic
agent state, transcript inspection, Git evidence, or the task-local resource
ledger.

## Current working model

Use this contract for every delegated task, including tasks managed alongside
work from other projects:

1. Assign a stable `project_id` and `task_id`.
2. Record the project's repository root and Herdr workspace.
3. Before delegation, Root locks the target branch and its full base revision.
   Managed agents may not choose or move this comparison anchor.
4. Name one owner, the write scope, dependencies, and the done condition.
   For meaningful delegated work, record these fields in a validated task
   contract with explicit `owns`, `does_not_own`, authority, verification, and
   ordered instruction layers. Tiny read-only reconnaissance may remain inline.
5. Keep that owner, checkout, files, decisions, evidence, and memory inside the
   named project. Make every cross-project dependency explicit.
6. The owner returns one `HANDOFF` containing the project and task IDs, result,
   base and candidate revisions or another stable artifact, changed files,
   personally observed evidence, questions, and unfinished dependencies.
7. Treat `idle`, `done`, and `blocked` only as attention hints. They do not prove
   a handoff or successful work.
8. Persist an attention event before delivery. Delivery is at-least-once, so
   deduplicate by `event_id`.
9. Inspect the named project's handoff and repository evidence, then decide `ACCEPT`,
   `REVISE`, or `WAIT`.
10. Root independently runs verification on the exact candidate. After safe
    integration, Root runs the same verification again in the clean target
    checkout. Only this integrated Root evidence can support `ACCEPT`.
11. Record the decision with the evidence Root checked, then acknowledge the
   event. The artifact helpers in
   [`task-artifacts.md`](./herdr-orchestrator/task-artifacts.md) validate
   identity and shape; they do not replace Root's judgment.

Concrete example:

```text
TASK
project_id: shop-api
task_id: login-refresh
repository: /projects/shop-api
workspace: shop-api
owner: auth-implementer
target_branch: main
base_revision: 953455e000000000000000000000000000000000
scope: refresh-token implementation and focused tests
done_when: old token reuse fails and the auth tests pass
dependencies: none

HANDOFF
project_id: shop-api
task_id: login-refresh
result: ready
base_revision: 953455e000000000000000000000000000000000 (must match task)
revision: abc1230000000000000000000000000000000000
changed_files: src/auth/refresh.ts, tests/auth/refresh.test.ts
evidence: npm test -- auth (exit 0, 42 passed)
questions: none
dependencies: none
```

For example, `shop-api/login-refresh` and `billing-api/login-refresh` are two
different tasks. A passing test in `shop-api` cannot justify accepting the
`billing-api` task.

If a lifecycle event arrives without a usable handoff, request the missing
fields and leave the event unacknowledged. A successful prompt submission proves
only that delivery was accepted, not that the Orchestrator consumed or judged it.

## Core orchestration loop

Always follow this causal sequence:

1. **Inspect** — inventory existing Herdr state and repository state.
2. **Decompose** — create bounded tasks with explicit ownership and acceptance criteria.
3. **Isolate** — use one Git worktree per concurrent writing agent.
4. **Launch** — start the normal interactive agent without stealing focus.
5. **Prime** — wait until the agent is ready before sending the task.
6. **Delegate** — send a self-contained direct prompt through `pane run`.
7. **Observe** — confirm it starts working; monitor semantic state and output.
8. **Unblock** — answer only within established authority; otherwise ask the user.
9. **Verify** — treat the agent's report as a claim and check repository evidence yourself.
10. **Correct** — send specific failed evidence back through the same pane and re-verify.
11. **Integrate** — combine isolated changes one branch at a time and test the result.
12. **Clean up** — remove only resources created for this task and only after preserving work.
13. **Report** — give the user one synthesized, evidence-backed result.

Skipping a step has a predictable failure mode: sending before readiness can type into startup UI; concurrent writers in one checkout can overwrite work; trusting a completion message can hide failed tests; indiscriminate cleanup can destroy user state.

## Resource-efficiency defaults

- Start with one writer and one independent reviewer. Add agents only for
  separately owned deliverables or a named specialist risk.
- Launch Codex with the explicit GPT-5.6 model and effort policy in
  `model-routing-and-context.md`; do not inherit a global default or fall back
  to an older model.
- Reuse the writer worktree and both native agent conversations through every
  correction loop.
- After an agent reaches `working`, create one long-lived terminal-state watch.
  Do not turn 60-second timeouts into a model-driven polling loop.
- Treat user progress updates and agent state queries as separate operations. A
  progress message can report the last observed state without issuing another
  Herdr call.
- Read transcripts at readiness, real state changes, and diagnostic deadlines.
  Do not reread unchanged scrollback.
- Use one `api snapshot` at initial inventory or recovery instead of separate
  workspace, tab, pane, and agent listing calls. Do not poll snapshots.
- Report metadata once for stable identity and only at meaningful phase or
  candidate transitions. Do not publish metadata heartbeats.
- Keep Herdr as the sole agent-orchestration layer. Do not launch a managed
  Codex agent with `ultra`, which can create an untracked nested agent team.
- Group one task's visible roles in one task-dashboard tab when practical.
  Keep at most four panes in that tab and use the deterministic 1/2/3/4-pane
  layouts in `agent-lifecycle.md`. This is a visual cap, not a target agent
  count; never create idle agents or empty panes only to complete a grid.

Concrete effect for a normal phase:

```text
old pattern
  new reviewer worktree + new agent + short wait/read loop for every hash
  -> repeated context loading and dozens of event subscriptions

default pattern
  one writer worktree + one writer pane + one reviewer pane
  -> one event-driven watch per lifecycle transition
  -> exact failed evidence sent back through the same conversations
  -> Orchestrator verifies the final diff and tests once the gate passes
```

## Non-negotiable operating rules

- Use `--no-focus` for background creation unless the user asked to switch context.
- Use `--current` or an explicit returned ID; never depend on another client's focused pane.
- Treat workspace, tab, pane, and terminal IDs as opaque. Parse them from JSON; never guess them.
- Track every resource created by the Orchestrator.
- Use a worktree for every concurrent writer.
- Use `pane run`, not `agent send`, for submitted prompts; `agent send` writes literal text without Enter.
- Inspect output before and after waits. On timeout, diagnose instead of blindly repeating a prompt.
- Preserve a running wait through the local execution tool's process/session
  handle; do not recreate the Herdr subscription when the execution tool yields.
- Treat both `idle` and `done` as possible completion states; verify the transcript and repository.
- Never present agreement among agents as proof. Prefer diffs, tests, and direct inspection.
- Reuse an agent's existing pane for corrections so its native conversation context is preserved.

## Completion condition

The task is complete only when the user's original outcome is satisfied, relevant verification has passed, unresolved risk is disclosed, and created resources are either safely cleaned up or explicitly reported as still running.
