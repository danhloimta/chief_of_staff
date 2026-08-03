# Parallel Writers and Worktrees

Read this reference before running concurrent writing agents, creating or removing worktrees, or integrating their branches.

## Isolation rule

Use one Git worktree per concurrent writer.

Cause and effect:

1. Two writers in one checkout see the same partially edited files.
2. Either writer can overwrite, reformat, stage, or test against the other's incomplete work.
3. Separate worktrees give each writer an independent filesystem and branch.
4. File ownership is still required because isolated branches can conflict during integration.

Read-only reviewers and command panes may share a checkout with its one writer if their instructions explicitly forbid edits.

## Default writer-reviewer topology

For one implementation stream, create one writer worktree and keep it for the
whole correction loop. When the writer has produced a stable candidate and is
no longer editing, start one read-only reviewer pane in that same worktree.

```text
writer pane, task-created worktree
  -> produces and verifies candidate commit
  -> pauses
reviewer pane, same worktree
  -> reviews exact HEAD without editing
  -> reports evidence
writer pane, same worktree and native conversation
  -> fixes confirmed findings
reviewer pane, same worktree and native conversation
  -> re-reviews the new exact HEAD
```

This is safe because only one pane has write authority and writing and review
are sequential. It also avoids creating a new worktree, agent process, and full
repository-context session for every candidate hash.

Create a separate reviewer worktree only when the reviewer must run while the
writer is still changing files, must hold a different checkout state, or needs
isolation for a concrete risky command. State that reason in the resource
ledger. Do not create two review worktrees by default for "behavior" and
"security"; give one capable reviewer both named acceptance areas, or reserve
one Luna `max` phase gate for a mechanical fixed acceptance checklist. Use
Terra `high` or `max` only when review requires novel, open-ended correctness
or security judgment. Never use Sol for a managed ClassHub reviewer. Follow
`model-routing-and-context.md`.

Keep the writer and reviewer panes alive through corrections. Reuse them with a
direct follow-up that names the new commit and the exact failed or closed
evidence. Their retained native context makes a repeated full launch slower and
less reliable, not more independent.

## Plan branch and file ownership

Before creating worktrees, write down:

```text
api-writer
  branch: agent/api-refresh
  owns: src/auth/**, tests/auth/**
  excludes: docs/**, package.json, lockfiles

docs-writer
  branch: agent/auth-docs
  owns: docs/**
  excludes: src/**, tests/**, package.json, lockfiles
```

If tasks require the same shared file, run them sequentially or reserve that file for the Orchestrator's integration pass.

## Create isolated worktree workspaces

```bash
herdr worktree --help

herdr worktree create \
  --cwd "$PWD" \
  --branch agent/api-refresh \
  --base HEAD \
  --label api-refresh \
  --no-focus \
  --json

herdr worktree create \
  --cwd "$PWD" \
  --branch agent/auth-docs \
  --base HEAD \
  --label auth-docs \
  --no-focus \
  --json
```

Each command creates or checks out the branch in a separate path and opens that checkout as a Herdr workspace. Capture the returned workspace ID, path, and branch. Never infer them.

## Start one writer in each workspace

```bash
herdr agent start api-writer \
  --workspace '<api-workspace-id>' \
  --cwd '<api-worktree-path>' \
  --no-focus \
  -- codex -m gpt-5.6-luna -c 'model_reasoning_effort="max"'

herdr agent start docs-writer \
  --workspace '<docs-workspace-id>' \
  --cwd '<docs-worktree-path>' \
  --no-focus \
  -- codex -m gpt-5.6-luna -c 'model_reasoning_effort="max"'
```

These examples use the Luna-first routine default. Keep bounded work on Luna
through `max`; use Terra only for demonstrated ambiguity or architecture-heavy
judgment as defined in `model-routing-and-context.md`. Never route a managed
ClassHub writer to Sol.

For each returned agent:

1. capture its pane ID;
2. wait for `idle` readiness;
3. send its self-contained prompt with `pane run`;
4. confirm `working`;
5. monitor it independently.

Tell a writer to commit on its current branch only if commits are part of the integration plan. Do not authorize push or PR creation implicitly.

## Inspect after events without stealing focus

After a terminal-state event or a meaningful deadline, inspect each affected
agent once:

```bash
herdr agent get api-writer
herdr agent get docs-writer
herdr pane read '<api-pane-id>' --source recent-unwrapped --lines 120
herdr pane read '<docs-pane-id>' --source recent-unwrapped --lines 120
```

Do not start one agent's long-lived watch only after another agent finishes if
they are intentionally parallel. Start their watches together and address
whichever becomes blocked or done first. Do not send one writer another
writer's unverified claim as fact.

Use the long-lived event subscriptions in `agent-lifecycle.md`. A periodic loop
over `agent get` and `pane read` is not monitoring; it is polling. For multiple
intentional agents, create their terminal-state watches once and let the local
execution layer wait for whichever watch finishes first.

## Inspect each result before integration

An agent's success message is insufficient. In each worktree:

```bash
git status --short
git diff --check
git diff --stat
git log -1 --oneline
```

Inspect the actual diff and rerun task-specific tests. Confirm the branch contains only its assigned scope.

If an agent left uncommitted work when a commit was required, preserve it and send a direct follow-up. Do not force-remove the worktree.

## Integrate one branch at a time

For each completed branch:

1. verify the destination checkout is clean enough to integrate without overwriting user work;
2. merge or cherry-pick the branch using the chosen project workflow;
3. inspect the combined diff;
4. run focused tests;
5. run broader tests proportional to risk;
6. resolve conflicts from the user's requirements, not whichever agent wrote last;
7. only then integrate the next branch.

Sequential integration isolates the cause if a branch introduces failure. Integrating everything first makes regressions and conflicts harder to attribute.

## Remove a completed worktree safely

Before removal, confirm:

- its useful work is committed or otherwise preserved;
- its branch has been integrated or intentionally retained;
- the checkout has no unreviewed changes;
- the workspace was created for this task.

Then:

```bash
herdr worktree remove --workspace '<created-workspace-id>' --json
```

`workspace close` closes only Herdr state. `worktree remove` invokes Git worktree removal and does not delete the branch.

Do not add `--force` to bypass dirty work. If Git refuses removal, inspect and preserve the changes or ask the user.

## When not to remove

Leave the worktree running and report it when:

- the user asked to inspect the result interactively;
- tests or agents are still running;
- integration is deferred;
- unresolved changes have not been preserved;
- removing it would exceed the requested scope.
