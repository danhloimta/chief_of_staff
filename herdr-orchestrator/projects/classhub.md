# ClassHub Project Profile

Read this file for every task targeting `/Users/danhloi/work/classhub`.

## Identity and sources of truth

- `project_id`: `classhub`
- repository: `/Users/danhloi/work/classhub`
- default integration branch: the branch already checked out by the user;
  never assume or switch it silently
- repository policy: `/Users/danhloi/work/classhub/AGENTS.md`
- durable operational record: `/Users/danhloi/work/classhub/bin/harness`
- orchestration artifact directory:
  `/Users/danhloi/work/chief_of_staff/.runtime/classhub/<task_id>/`

ClassHub specs, repository rules, and source code define product behavior.
ClassHub's `harness.db` records intake, story, decision, proof, trace, and
friction. Herdr metadata and Chief artifacts record only orchestration state.
Neither replaces the other.

## Intake and lane selection

Before delegation, inspect the request and relevant repository evidence, then
choose exactly one lane:

- `tiny`: narrow, unambiguous, low-risk correction or documentation change;
- `normal`: bounded feature or bug fix requiring implementation and focused
  regression coverage;
- `high-risk`: billing, invoice, attendance, session package, authorization,
  tenant isolation, queue/cron/observer behavior, or an API-contract-sensitive
  change.

Record the intake through `bin/harness intake`. Use the ClassHub context rules
for the selected lane. Do not classify a task as tiny merely to skip required
product or verification work.

## Role topology

### Tiny

One writer produces a candidate. Root verifies it. Add no reviewer unless a
specific risk appears.

### Normal

One writer produces and tests a candidate. Root checks scope, spec alignment,
the exact diff, and focused tests. Reuse the same writer for corrections.

### High-risk

1. Use a `po` agent first if a spec is created or behavior changes. Require it
   to lock scope, non-goals, acceptance criteria, compatibility, and rollout
   implications.
2. Give one writer the locked decision and a non-overlapping file scope.
3. After the candidate is stable, give one independent reviewer read-only
   authority with the named business and safety risks.
4. Root reproduces confirmed findings, sends failures to the same writer, and
   re-verifies the next candidate.

Never use additional agents only to create agreement. Evidence, not agent
count, closes the task.

## Context routing

Every managed ClassHub agent must read `AGENTS.md` plus only the relevant
layers it routes:

- backend PHP/Laravel: `.agent/rules/rules-backend.md`;
- Blade, Alpine, or web UI: `.agent/rules/rules-frontend.md`;
- billing, attendance, invoices, or other business rules:
  `.agent/rules/rules-project.md`;
- testing: `.agent/rules/rules-testing.md`;
- React Native: `.agent/rules/rules-mobile.md`;
- matching module spec under `specs/` when available.

Use the lane/phase requirements in `docs/harness-context-rules.md`. Do not copy
the whole repository policy into every task when an ordered instruction layer
can point to the authoritative file.

## Task contract rules

- Root records the current target branch and its full HEAD as `target_branch`
  and `base_revision` before creating a worktree. These values are immutable
  for the task. If the target branch moves, stop and rebase or recreate the
  candidate; never let the worker select a newer base.
- `owns` and `does_not_own` entries must be repository-relative glob patterns
  so the semantic gate can check them mechanically.
- `verification` entries must be exact safe commands, not prose descriptions.
- Always include `/Users/danhloi/work/classhub/AGENTS.md` as the first ClassHub
  instruction layer, followed by routed rules, relevant specs, and any role
  layer.
- The writer may edit and create a local candidate commit. It may not push,
  deploy, open a PR, modify production data, bypass a safe runner, or alter the
  user's base checkout.
- Verification commands must use the ClassHub safe runners accepted by
  `taskctl.py`. They are executed as argv without a shell, so command chaining,
  redirection, and shell expansion are prohibited.

## Verification gate

Root must check all of the following before `ACCEPT`:

1. The candidate is based on the Root-locked base revision and the target
   branch has not moved.
2. Git-derived changed files exactly match the handoff.
3. Every changed file matches `owns` and none matches `does_not_own`.
4. The candidate contains no whitespace errors or unrelated changes.
5. Worker evidence references the exact candidate revision, but remains only a
   claim. Root runs every exact verification command itself in the clean
   candidate worktree and records a `herdr_root_verification` artifact.
6. ClassHub spec-first, tenant isolation, safe-test, harness story, and trace
   requirements are satisfied for the selected lane.
7. Root explicitly acknowledges every `requirements` and `done_when` entry
   after personally inspecting the relevant behavior and diff.
8. The destination checkout is clean, on the locked target branch, and still
   points at the locked base. Preserve all pre-existing user changes.
9. Root fast-forwards the target branch to the candidate, then reruns the same
   verification in the target checkout. Only a passing `integrated` Root
   verification can support `ACCEPT`.

Use `taskctl.py verify-handoff` only to inspect the worker claim. Use
`taskctl.py root-verify` for the authoritative candidate and integrated gates.
Neither replaces Root's business review.

## Minimal Definition of Done

A ClassHub implementation is done only when all of these are true:

1. Root locked the lane, target branch, base revision, requirements, non-goals,
   ownership, verification commands, and `done_when` before delegation.
2. Required spec/PO decisions exist for the selected lane.
3. The candidate is committed and its worktree is clean.
4. Root inspected the exact locked-base-to-candidate diff and acknowledged each
   requirement and `done_when` item.
5. Root-owned candidate verification passed with the correct safe runner.
6. Required high-risk review findings were independently confirmed and closed.
7. ClassHub harness story/proof requirements for the lane are complete.
8. The unchanged target branch was fast-forwarded to the candidate.
9. Root-owned integrated verification passed in the clean target checkout.
10. A decision referencing that exact integrated verification records
    `ACCEPT`; only then may Root report completion.

## Correction and completion

Send exact failed evidence to the same writer pane and keep the original scope.
After three materially identical failed correction loops, stop and ask the
user with the concrete business blocker and attempted resolutions.

The final user report must follow ClassHub's business-level format. Internally,
record the appropriate ClassHub harness trace before reporting completion.
