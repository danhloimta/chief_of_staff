# Delegation and Prompt Design

Read this reference when deciding whether to delegate, defining task boundaries, or writing any managed-agent prompt.

## Decide whether delegation adds value

Delegate only work with a clear boundary and a useful independent result.

Good delegation:

- read-only repository reconnaissance;
- an independent implementation in an isolated worktree;
- focused test-failure diagnosis;
- security, API, or migration review after implementation;
- documentation work whose files do not overlap another writer.

Keep work in the Orchestrator pane when it is tiny, tightly coupled, or requires continuous shared judgment. Starting an agent adds launch, context-transfer, monitoring, and verification cost.

## Default team shape

Start with the smallest team that closes the evidence loop:

```text
Orchestrator
  -> one writer for the bounded implementation
  -> one independent reviewer after the candidate is stable
  -> Orchestrator verifies the diff and tests
```

Add another agent only when it owns a genuinely independent deliverable or a
named specialist risk that the default reviewer cannot cover. Do not launch two
reviewers merely to obtain agreement. Agreement is not proof, while each extra
agent adds startup, context-transfer, wait, verification, and cleanup cost.

Before launching a Codex agent, read
[`model-routing-and-context.md`](./model-routing-and-context.md). Select the
GPT-5.6 model and reasoning effort from the work shape, make both explicit at
launch, and record the choice. Model routing, escalation, compaction, and
handoff policy live only in that reference so they can evolve without making
every delegation prompt load model research.

## Assign ownership before launching

For every delegated task, state what the agent owns and what it must not change.

```text
API writer owns: src/auth/** and tests/auth/**
Docs writer owns: docs/** only
Shared files: package.json and lockfiles; neither writer changes them without a follow-up
```

Cause and effect:

1. A named boundary lets each agent make local decisions without asking about every file.
2. Explicit exclusions prevent opportunistic refactors and dependency churn.
3. Separate ownership reduces logical merge conflicts even when writers use separate worktrees.

Do not assign two concurrent writers the same file. If overlap is unavoidable, make the tasks sequential.

For meaningful delegated implementation, review, or integration work, prefer a
validated task contract over repeatedly hand-formatting these fields. The
contract's `owns` and `does_not_own` lists make positive and negative ownership
equally explicit. Ordered instruction layers provide shared engineering,
project, and role guidance before the task-specific prompt. Follow
[`task-artifacts.md`](./task-artifacts.md) to render and validate the contract.

Keep tiny read-only reconnaissance inline when creating an artifact would add
more ceremony than control.

## Required prompt fields

Every initial prompt must contain:

1. **Objective** — the concrete outcome.
2. **Context** — relevant behavior, paths, issue, or failing command.
3. **Requirements** — observable acceptance criteria.
4. **Scope** — files or subsystem it may change.
5. **Exclusions** — files and decisions owned elsewhere.
6. **Verification** — exact tests, build, lint, or inspection expected.
7. **Authority** — whether it may edit, commit, access the network, or only report.
8. **Completion contract** — what its final response must contain.

## Implementation prompt example

```text
Implement refresh-token rotation in this checkout.

Requirements:
- Reject reuse of a consumed refresh token.
- Preserve the current access-token response schema.
- Add focused tests for successful rotation and reuse rejection.

Scope: src/auth/** and tests/auth/**.
Do not modify package.json, lockfiles, deployment files, or unrelated formatting.
Run the focused auth tests, then the existing lint command if it is available.
You may edit files in this checkout. Do not push, deploy, or open a PR.

When finished, report:
1. changed files and behavior,
2. commands run and results,
3. unresolved risks or blockers.
```

The prompt speaks directly because the managed agent experiences it as coming from the user. It contains enough context to work without the Orchestrator's hidden conversation.

## Read-only reviewer prompt example

```text
Review the current uncommitted diff for correctness and regressions. Do not edit files.
Focus on authentication bypasses, token reuse, races, and missing tests.
Report only actionable findings, ordered by severity, with file and line references.
If there are no findings, say so explicitly and list any residual test gap.
```

The explicit `Do not edit files` converts a broad review request into read-only authority. Without it, a coding agent may decide to fix findings itself.

## Questions from managed agents

When an agent asks a question, classify the source of the answer.

Answer directly when evidence already determines it:

- The user named the target framework or behavior.
- Repository conventions clearly choose a test command or file location.
- The delegated requirements already exclude an option.

Ask the user when the answer requires new authority or preference:

- destructive migration or data loss;
- public API compatibility choice;
- new paid service or dependency;
- deploy, push, PR, message, or other external side effect;
- security tradeoff not settled by existing requirements.

Send the eventual answer directly. Do not write `The user says...`; for example:

```text
Preserve backward compatibility. Add the new field as optional and do not migrate existing records in this task.
```

Never fabricate approval just to keep an agent working.

## Follow-up prompt design

Reuse the existing pane and provide concrete failed evidence:

```text
The focused test still fails in tests/auth/refresh.test.ts at the reuse case.
Diagnose that failure, change only the auth implementation or focused test, rerun it,
and report the exact result. Do not broaden the refactor.
```

Cause and effect:

1. Reusing the pane preserves native conversation and checkout context.
2. Naming the failure prevents broad rediscovery.
3. Restating scope prevents correction work from expanding.
4. Requiring an exact test result closes the loop with evidence.

If the same material blocker repeats through three correction loops, stop paraphrasing the same request. Bring the concrete blocker and attempted resolutions to the user.

## Expected result format

For meaningful work using a task contract, require one validated
`herdr_handoff` artifact containing the exact project and task IDs, full base
and candidate revisions, changed files, evidence artifact paths, questions, and
unfinished dependencies.

For tiny inline tasks, require:

```text
Outcome:
Changed files:
Verification performed:
Remaining risks or blockers:
Commit hash: (only when commits were requested)
```

This format makes the response easy to verify, but it does not replace independent inspection.
