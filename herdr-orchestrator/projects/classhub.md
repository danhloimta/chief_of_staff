# ClassHub Project Profile

Read this file for every task targeting the resolved ClassHub checkout.

## Identity and sources of truth

- `project_id`: `classhub`
- repository: `CLASSHUB_REPOSITORY` when set, otherwise the sibling
  `../classhub` checkout
- default integration branch: the branch already checked out by the user;
  never assume or switch it silently
- repository policy: `<classhub>/AGENTS.md`
- durable operational record: `<classhub>/bin/harness`
- orchestration artifact directory: `.runtime/classhub/<task_id>/` in this
  Chief of Staff checkout

ClassHub specs, repository rules, and source code define product behavior.
ClassHub's `harness.db` records intake, story, decision, proof, trace, and
friction. Paseo metadata and Chief artifacts record only orchestration state.
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

The minimal Paseo runtime accepts only `tiny` and `normal`. If intake is
`high-risk`, stop and ask the user; do not downgrade it or launch a worker.

Record the intake through `bin/harness intake`. Use the ClassHub context rules
for the selected lane. Do not classify a task as tiny merely to skip required
product or verification work.

## Role topology

Every writer contract records an explicit model and effort. Defaults are:

| Lane | Writer default | Adjustment |
| --- | --- | --- |
| `tiny` | Luna `medium` | Luna `low` for pure lookup/transformation; raise Luna effort when the checklist is subtle |
| `normal` | Luna `max` | lower to Luna `high` for very clear work; use Terra only for demonstrated ambiguity or cross-subsystem judgment |
| `high-risk` | Not supported in MVP | stop before delegation; governance must be implemented first |

The normal ClassHub writer path accepts only `gpt-5.6-luna` and
`gpt-5.6-terra`. Do not route a concrete bug fix or bounded implementation to
Sol because it spans several files, has a long checklist, or is labeled
high-risk. Sol is reserved for Root and is prohibited for every managed
ClassHub task. A managed exception requires the user to change this policy.

Luna-first escalation is `medium -> high -> xhigh -> max`. Prefer Luna `max`
for quality-sensitive bounded implementation, review, and browser checklists.
Route directly to Terra when intake evidence shows the task requires product or
architecture judgment, a broad ambiguous investigation, or cross-subsystem
design. Otherwise move from Luna to Terra only after one evidence-backed
correction shows a reasoning-capability mismatch; do not escalate for missing
context, an unclear contract, or a failing test that already identifies the
bug.

### Tiny

One writer produces a candidate. Root verifies it. If a specific risk requires
reviewer or PO governance, stop instead of adding another managed role.

### Normal

One writer produces and tests a candidate. Root checks scope, spec alignment,
the exact diff, and focused tests. Reuse the same writer for corrections.

### High-risk

Not executable in the minimal release. Do not simulate the required PO,
reviewer, or governance gates with prose acknowledgements.

Never use additional agents only to create agreement. Evidence, not agent
count, closes the task.

## Browser tester and Dusk

Use Laravel Dusk as the only browser-testing surface for the minimal release.
Do not install or route work through Realbrowser, ad-hoc Chrome automation, or a
second browser framework.

When browser behavior is in a supported `tiny` or `normal` task, Root runs the
exact focused `bin/dusk-safe` command on the candidate and after integration.
The MVP does not launch a separate browser tester. Never invoke `php artisan
dusk` directly or bypass a refusal from `bin/dusk-safe`.

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

- Use `task_kind: implementation` for a feature or fix and
  `task_kind: investigation` for read-only bug discovery. An investigation has
  no edit/commit authority, remains at the locked base, and must return
  non-empty findings.
- The ledger binds the canonical full task digest. Reusing a task ID or editing
  any contract field after launch is forbidden and fails closed.
- A new feature or behavior change that requires a new/updated spec is outside
  this one-worker MVP because ClassHub requires a PO agent first. Stop and ask
  the user rather than bypassing that rule.
- Root records the current target branch and its full HEAD as `target_branch`
  and `base_revision` before creating a worktree. These values are immutable
  for the task. If the target branch moves, stop and rebase or recreate the
  candidate; never let the worker select a newer base.
- Root records `model` and `effort` in the task contract and launches that exact
  pair. A startup mismatch or fallback stops delegation.
- `owns` and `does_not_own` entries must be repository-relative glob patterns
  so the semantic gate can check them mechanically.
- `verification` entries must be exact safe commands, not prose descriptions.
- Always include the resolved `<classhub>/AGENTS.md` as the first ClassHub
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
   When browser coverage is required, this includes the exact focused
   `bin/dusk-safe` command selected in the contract.
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
6. The task remained `tiny` or `normal`; high-risk work never entered this flow.
7. ClassHub harness story/proof requirements for the lane are complete.
8. The unchanged target branch was fast-forwarded to the candidate.
9. Root-owned integrated verification passed in the clean target checkout.
10. A decision referencing that exact integrated verification records
    `ACCEPT`; only then may Root report completion.

A read-only investigation replaces items 3–10 with: unchanged clean locked
base, non-empty findings, Root reproduction of the exact evidence, passing
investigation verification, and an `ACCEPT` decision. It never integrates a
commit.

## Correction and completion

Send exact failed evidence to the same writer pane and keep the original scope.
After three materially identical failed correction loops, stop and ask the
user with the concrete business blocker and attempted resolutions.

The final user report must follow ClassHub's business-level format. Internally,
record the appropriate ClassHub harness trace before reporting completion.
