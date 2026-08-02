# GPT-5.6 Model Routing and Context Continuity

Read this reference before selecting a Codex model or reasoning effort, changing
either one, compacting or forking a Codex conversation, or handing work to
another agent.

## Authority and installed capability

OpenAI's current Codex guidance defines three GPT-5.6 roles: Sol for complex
open-ended work, Terra for everyday agentic work, and Luna for clear repeatable
work. Treat the installed Codex catalog and startup footer as authoritative for
what this machine can actually launch.

Before relying on a model or effort that has not yet been verified in the
current environment:

```bash
codex --version
codex debug models | jq '[.models[]
  | select((.slug // "") | test("^gpt-5\\.6-(sol|terra|luna)$"))
  | {slug, supported_reasoning_levels, context_window}]'
```

Do not copy API context limits into Codex orchestration policy. Use the local
catalog and `/status` for the effective Codex session budget. Always specify
both model and effort at launch; a global default can otherwise change cost and
behavior without appearing in the task prompt.

## Route by work shape

| Work shape | Starting model | Starting effort | Examples |
| --- | --- | --- | --- |
| Clear, repeatable, high-volume | `gpt-5.6-luna` | `low` or `medium` | extraction, classification, transformation, structured summary, mechanical checklist |
| Everyday agentic work | `gpt-5.6-terra` | `medium` | repository mapping, read-heavy scans, documentation, bounded implementation |
| Complex, ambiguous, or high-value | `gpt-5.6-sol` | `medium` or `high` | orchestration, architecture, cross-cutting change, difficult debugging, security review |

Default roles:

| Role | Model and effort | Escalate when |
| --- | --- | --- |
| Orchestrator | Sol `medium` | architecture or integration judgment requires Sol `high` |
| Explorer | Terra `low` or `medium` | discovery becomes ambiguous or requires a design decision |
| Routine bounded writer | Terra `medium` | work crosses subsystem contracts or becomes high risk |
| Complex writer | Sol `high` | use `xhigh` or `max` only after a representative evaluation shows a material gain |
| Independent correctness or security reviewer | Sol `high` | use `max` only for an exceptional quality-first case with a clear evaluation contract |
| Mechanical acceptance gate | Luna `medium`; Luna `high` for a long or subtle fixed checklist | unexpected behavior requires open-ended investigation |

Concrete routing examples:

```text
Find every installer entry point and return paths and symbols.
  -> Terra medium

Implement one documented CLI flag in two files with focused tests.
  -> Terra medium

Redesign recovery across installer, updater, state storage, and rollback.
  -> Sol high

Extract pass/fail results for 80 explicit acceptance criteria.
  -> Luna medium

Look for security failures the acceptance checklist did not anticipate.
  -> Sol high
```

If `rg`, `jq`, Git, or a test runner can produce the exact answer
deterministically, use that tool instead of spawning Luna merely to execute a
mechanical operation. Use a model when interpretation, synthesis, or judgment
remains.

## Choose reasoning effort separately

- `low`: quick, well-scoped work where speed matters and little planning is
  required.
- `medium`: normal default for Terra and Luna, and the balanced starting point
  for Sol.
- `high`: complex logic, multiple sources or subsystems, security review,
  difficult edge cases, or important validation.
- `xhigh` and `max`: evaluation-only escalation for the hardest single-agent
  work. Do not infer that a long checklist needs `max`; clarity and difficulty
  are different properties.
- `ultra`: prohibited inside a Herdr-managed Codex pane unless the user
  explicitly chooses nested orchestration for a named experiment.

Before increasing effort, check whether the actual failure is missing context,
an unclear success criterion, a wrong tool route, stale assumptions, or absent
validation. More reasoning does not repair an underspecified contract.

`ultra` can create Codex subagents. Running it below Herdr creates two control
planes, hides resource ownership from the Herdr ledger, and can multiply model
and tool work. If Ultra is ever evaluated, it replaces Herdr fan-out for that
bounded experiment; never nest both orchestration strategies by default.

## Launch and verify explicitly

```bash
# Routine bounded work
codex -m gpt-5.6-terra -c 'model_reasoning_effort="medium"'

# Complex implementation or independent judgment-heavy review
codex -m gpt-5.6-sol -c 'model_reasoning_effort="high"'

# Clear repeatable extraction or mechanical gate
codex -m gpt-5.6-luna -c 'model_reasoning_effort="medium"'
```

After readiness, read the startup footer once. Confirm the actual model and
effort before delegation, then report separate `model` and `effort` metadata
tokens as described in `agent-lifecycle.md`. If the requested model is missing
or a fallback launched, stop that delegation and surface the mismatch.

Do not use GPT-5.4, GPT-5.3, older models, or a family alias for managed agents
unless the user changes this policy. Explicit family member slugs keep routing
observable.

## Stay, compact, fork, or hand off

| Situation | Action | Cause and effect |
| --- | --- | --- |
| Same objective, role, checkout, and valid assumptions | Stay in the same pane | Native conversation and tool context make corrections cheaper and more precise |
| Same work, but old logs and completed phases dominate context | Compact after a stable milestone | Keeps decisions while reducing transcript pressure |
| Testing an alternate approach that should inherit history | Fork only when the installed surface supports it | Preserves the original path, but inherited assumptions mean it is not an independent review |
| Role changes, independent review begins, or the current model is materially mismatched | Hand off to a new pane | Gives the destination a clean role and explicit model without discarding source evidence |
| Objective or foundational assumptions changed | Start a fresh conversation with a handoff packet | Compaction can retain stale framing; a fresh thread makes the new contract explicit |

Send evidence-backed correction findings to the same writer pane. Do not create
a new writer or reviewer for each candidate hash. A handoff is not a way to
hide a repeated blocker; after the same material blocker survives three
correction loops, follow the escalation rule in `delegation.md`.

## Compact only at milestones

Codex compaction summarizes older history so the same task can continue. It is
not a completion signal, a verification step, or a substitute for a handoff.
Treat compacted items as opaque state and keep the task contract functionally
consistent afterward.

Use `/status` at a phase boundary or after unusually large tool output, not as
a polling command. Starting heuristic, to be tuned from real runs:

- above roughly 35% context remaining: continue without intervention;
- at or below roughly 35% after a stable milestone: compact before the next
  phase when substantial work remains;
- at or below roughly 20% during active work: reach the smallest safe
  checkpoint, preserve evidence, then compact;
- do not compact while the agent is editing, diagnosing a fresh failure,
  waiting on a decision, or holding unpreserved work.

At an idle milestone:

```bash
herdr pane run "$agent_pane" '/status'
herdr pane read "$agent_pane" --source recent-unwrapped --lines 50

# Only when the displayed budget and next phase justify it
herdr pane run "$agent_pane" '/compact'
```

Observe the resulting state/output once using the lifecycle rules in
`agent-lifecycle.md`. Do not loop over `/status`, and do not customize Codex's
compaction prompt unless a representative trace demonstrates that required
state is being lost.

Before compaction, ensure the stable milestone already has durable evidence:

- exact objective and remaining acceptance criteria;
- checkout, branch, base, and candidate commit when applicable;
- changed scope and file ownership;
- important decisions and rejected alternatives;
- commands run and exact results;
- unresolved risks, questions, and next action.

The agent's milestone response, Git state, tests, and the Orchestrator's
task-local ledger provide this evidence. Herdr metadata is only a navigation
index.

## Hand off through evidence

Use this compact packet rather than pasting a raw transcript:

```text
Objective: Complete Phase 4 recovery behavior.

Checkout: /absolute/path/to/worktree
Branch: phase4-recovery
Base: 953455e
Candidate: 04a655e

Changed:
- src/install/update.ts
- tests/install/update.test.ts

Verified:
- pnpm test install/update: passed
- pnpm typecheck: passed

Decisions:
- Preserve the current rollback format.
- Do not change public CLI output.

Open risk:
- Interrupted Windows replacement is not covered.

Next task:
- Independently review candidate 04a655e for rollback and interruption bugs.

Authority:
- Read-only. Do not edit.
```

Handoff sequence:

1. Stop at a stable Git state; preserve uncommitted work or create the planned
   candidate commit.
2. Verify the source agent's claimed candidate and tests before relaying them.
3. Choose the destination role, model, effort, checkout, scope, and authority.
4. Keep the source pane alive until the destination has accepted the packet and
   confirmed the candidate it sees.
5. Report destination metadata with `task_id`, `role`, `model`, `effort`,
   `scope`, and `candidate`.
6. Send a self-contained prompt containing the handoff packet and the normal
   delegation fields from `delegation.md`.
7. Require the destination to verify Git status and the candidate before using
   prior claims as evidence.

For reviewer findings, independently confirm the evidence and send confirmed
failures back to the same writer. Reuse the same reviewer to inspect the next
candidate; a new hash does not require a new conversation.

## Keep context lean before it needs compaction

- Keep durable repository rules in `AGENTS.md` and progressive references; do
  not paste the whole runbook into every task.
- State each task instruction once. Include outcome, relevant context,
  acceptance criteria, scope, authority, validation, and output contract.
- Leave raw exploration output, stack traces, and long test logs in the worker
  pane. Return distilled findings and exact evidence locations.
- Read transcripts at readiness, real state changes, and diagnostic deadlines;
  do not copy unchanged scrollback into the Orchestrator context.
- Preserve stable prompt prefixes. Add task-specific data as a short suffix
  instead of repeatedly rewriting large instruction blocks.
- Use a new conversation rather than compaction when old reasoning is no longer
  relevant to the new objective.

## Evaluate routing changes

Do not promote a model or effort because one answer looked good. Compare
representative tasks with the same prompt, checkout, acceptance criteria, and
verification:

```text
routine exploration: Terra medium vs Sol medium
bounded implementation: Terra medium vs Sol medium
complex implementation: Sol medium vs Sol high
fixed gate: Luna medium vs Luna high
exceptional hard case: Sol high vs Sol xhigh/max
```

Measure acceptance success, correction turns, wall time, model usage, context
growth, tool calls, and verification evidence. Lower latency or usage wins only
when the result still passes the same quality bar. Record any policy deviation
and its measured reason in the task-local ledger.

## Official sources

- [Codex models](https://learn.chatgpt.com/docs/models)
- [Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [Codex developer commands](https://learn.chatgpt.com/docs/developer-commands?surface=cli)
- [GPT-5.6 model guide](https://developers.openai.com/api/docs/guides/latest-model)
- [GPT-5.6 prompting guidance](https://developers.openai.com/api/docs/guides/prompt-guidance-gpt-5p6)
