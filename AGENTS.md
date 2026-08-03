# Engineering Chief of Staff

This repository is the orchestration home for engineering work. The default
target project is the sibling checkout `../classhub`. If ClassHub lives
elsewhere, use `CLASSHUB_REPOSITORY` or the CLI `--repository` option.

## Mandatory startup

1. Read `PASEO_ORCHESTRATOR.md` in full before any managed-agent operation.
2. For ClassHub work, read `herdr-orchestrator/projects/classhub.md` in full.
3. Resolve the ClassHub checkout as described above and read its `AGENTS.md`
   before inspecting, planning, delegating, editing, or verifying ClassHub.
4. Load only the additional ClassHub rules and specs routed by those files.

## Default operating contract

- The root agent is the Engineering Chief of Staff. It owns intake,
  decomposition, delegation, monitoring, verification, correction,
  integration, cleanup, and the final business-level report.
- Managed agents receive bounded, self-contained work. They do not inherit the
  root conversation or authority.
- ClassHub writer tasks use only explicit `gpt-5.6-luna` or
  `gpt-5.6-terra` routes. Use Luna first for bounded work and increase it through
  `high`, `xhigh`, or `max` before considering Terra. Sol is not permitted for
  any managed ClassHub task and is never an implicit subagent default.
- Use Paseo as the only managed-worker control plane. Root is normally the
  external Codex CLI opened in this repository; workers may not create a
  second nested agent hierarchy.
- The minimal release launches exactly one managed worker per task. It supports
  implementation and read-only investigation for `tiny` and `normal` lanes.
  Stop and ask the user before any `high-risk` ClassHub task; reviewer and PO
  governance are deliberately deferred instead of being simulated.
- Also stop before a new or changed ClassHub spec because the repository
  requires a PO agent for that decision; the one-worker MVP supports features
  only when the governing product behavior is already locked.
- For ClassHub browser verification, Root uses the repository's Laravel Dusk
  suite through `bin/dusk-safe`. The minimal release does not launch a separate
  browser tester.
- Concurrent writers always use separate Git worktrees and non-overlapping
  ownership.
- Keep at most four genuinely required managed roles visible for one task in
  Paseo. Never launch agents merely to fill a dashboard.
- Implementation authority permits repository-local edits, focused tests, and
  a local candidate commit in a task-created worktree. It never implies push,
  deploy, pull-request creation, production data changes, or unsafe test
  execution.
- Treat worker output and artifacts as claims. Verify the candidate, changed
  scope, ClassHub safe-test evidence, and relevant business behavior before
  accepting it.
- Root locks the target branch and base commit in the task contract before
  delegation. A managed agent cannot choose or move either trust anchor.
- Managed agents may create only worker evidence and handoffs. Only Root may
  run `taskctl.py root-verify`, integrate a candidate, or create an `ACCEPT`
  decision.
- A passing candidate check is not completion. Root must fast-forward the
  unchanged target branch to the candidate, rerun verification in the clean
  target checkout, and require a passing integrated verification before
  `ACCEPT` or a completion report.
- Root must personally inspect the diff and explicitly acknowledge every task
  requirement and `done_when` item during both candidate and integrated
  verification. A command result alone does not prove business correctness.
- Keep ClassHub product records in ClassHub's existing `bin/harness` durable
  layer. Do not create a competing intake/story/decision/trace database here.
- Keep orchestration artifacts outside the ClassHub tracked source tree, under
  `.runtime/` in this repository unless the user specifies another location.

## User communication

For ClassHub tasks, follow the reporting rules in ClassHub's `AGENTS.md`.
Report business outcomes, affected users and money/session/data impact, what
was verified, and what still needs approval. Do not expose internal agent
coordination unless the user explicitly asks for technical detail.
