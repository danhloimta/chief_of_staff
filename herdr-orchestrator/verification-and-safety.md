# Verification, Safety, Cleanup, and Reporting

Read this reference before accepting managed-agent work, performing cleanup, or reporting completion.

## Verify claims with repository evidence

A managed agent's final message is a claim, not proof.

When the task uses structured artifacts, validate their shape and identity
first:

```bash
python3 herdr-orchestrator/taskctl.py validate /path/to/task.handoff.json
python3 herdr-orchestrator/taskctl.py validate /path/to/task.evidence.json
```

Validation proves that required fields exist and that the handoff is
commit-addressed. It does not prove that the diff is correct or that a reported
command actually ran.

Start with:

```bash
git status --short
git diff --check
git diff --stat
```

Then inspect the changed files and run tests appropriate to the risk.

Confirm that:

- the diff satisfies the original acceptance criteria;
- changes stay inside the delegated scope;
- unrelated user changes remain intact;
- reported tests actually ran and passed;
- no secrets, generated artifacts, dependency churn, or unrelated formatting appeared;
- parallel branches integrate coherently;
- skipped checks and residual risks are explicit.

After inspection, record `ACCEPT`, `REVISE`, or `WAIT` with the evidence Root
personally checked. Only then acknowledge the corresponding attention event.
See [`task-artifacts.md`](./task-artifacts.md) for the decision artifact.

## Step-by-step acceptance example

Suppose an implementer reports that refresh-token reuse is now rejected.

1. Inspect the diff to confirm the consumed token is persisted before issuing the replacement.
2. Inspect the test to confirm it reuses the old token rather than accidentally testing an invalid token.
3. Run the focused auth test and record its exit result.
4. Run `git diff --check` to catch malformed patches.
5. Run broader auth tests to detect changes to the response schema.
6. Only then report the behavior as complete.

The agent's explanation directs inspection, but passing evidence establishes the result.

## Use reviewers correctly

A read-only reviewer can find risks the implementer missed, but reviewer output is also unverified.

For every reported finding:

1. open the referenced file and line;
2. reproduce or reason through the claimed failure;
3. discard false positives;
4. send confirmed findings to the implementer with concrete evidence;
5. re-inspect and rerun tests after correction.

Multiple agents agreeing is not independent proof when they copied the same assumption or inspected the same incomplete evidence.

## Preserve user work

Before editing, integrating, or cleaning up:

```bash
git status --short
```

Treat pre-existing modified and untracked files as user-owned unless proven otherwise. Work around them. Do not reset, overwrite, discard, or silently absorb them into an agent commit.

If required work overlaps a user-modified file and cannot be isolated safely, report the overlap and ask for direction.

## Focus and interaction safety

- Use `--no-focus` for background work.
- Do not use `agent attach --takeover` unless interactive transfer is explicitly desired.
- Do not send `ctrl+c`, approval keys, or destructive commands without authorization for their consequences.
- Do not use `agent focus`, `workspace focus`, or `tab focus` merely to inspect state; read through the CLI.
- Remember that focusing visible completed work can change `done` to `idle` by marking it seen.
- Never stop the Herdr server to finish one agent; it owns all panes in the session.

## Resource ownership and cleanup

Maintain a task-local ledger:

```text
created panes:
created tabs:
created workspaces:
created worktrees and branches:
pre-existing resources touched: none / explicit list
agent launches: name, task, model, reasoning effort
wait subscriptions: readiness, consumption, terminal, diagnostic timeouts
transcript reads: startup, state change, timeout diagnosis
reused panes/worktrees:
context events: milestone status checks, compactions, forks, handoffs and reason
```

The operational counters make waste visible. For example, one writer and one
reviewer should normally need two agent launches and one worktree, not a fresh
pair for every correction hash. A high count of terminal subscriptions with few
real state changes means short timeouts became polling and the lifecycle should
be corrected before the next phase.

Cleanup eligibility:

| Resource | Safe to clean when |
| --- | --- |
| Pane | Created for this task, output collected, no useful process remains |
| Tab | Created for this task and all contained panes are safe to close |
| Workspace | Created for this task and contains no needed panes |
| Worktree | Work preserved, branch handled, checkout clean, task-created |
| Session/server | Only when the user explicitly intends to stop every contained process |

Never close resources merely because their agent is `idle`; it may be waiting for a follow-up and its native session may still be valuable.

Do not force-remove a dirty worktree. Do not delete its branch as an incidental cleanup step.

## Surface blockers to the user

When a managed agent needs a decision outside established authority, read the exact question and provide the user with:

- what the agent is trying to accomplish;
- the concrete decision;
- available evidence and tradeoffs;
- what stops while awaiting the answer.

Optionally raise a Herdr notification:

```bash
herdr notification show 'Agent needs a decision' \
  --body 'auth-implementer is blocked on migration compatibility' \
  --sound request
```

Do not use a notification as a substitute for asking the question in the conversation.

## Final synthesis

Do not forward raw agent transcripts as the result. Produce one coherent report containing:

1. completed outcome;
2. important files, commits, or branches changed;
3. verification commands and results;
4. unresolved risks, disagreements, or skipped checks;
5. model-routing or lifecycle-policy deviations that materially affected cost;
6. Herdr resources intentionally left running.

Concrete example:

```text
Implemented refresh-token rotation in src/auth/refresh.ts with reuse tests in
tests/auth/refresh.test.ts. The focused auth suite and lint passed. I also
verified that the access-token response schema is unchanged. The isolated
agent/api-refresh branch was merged; its Herdr worktree was removed. No agents
or task-created panes remain running.
```

Do not claim completion when an acceptance criterion remains unverified. State the exact gap and why it could not be closed.
