# Agent Lifecycle Operations

Read this reference before starting, naming, messaging, reading, waiting for, or diagnosing an agent.

## Discover the installed command surface

```bash
herdr agent --help
herdr pane --help
herdr wait --help
herdr api --help
herdr workspace --help
herdr tab --help
```

Use the installed syntax even if newer documentation shows additional commands.

## Inventory live state

Prefer the single 0.7.2+ snapshot call:

```bash
herdr api snapshot
```

The response contains the current version and protocol plus all workspaces,
tabs, panes, layouts, agents, and metadata tokens. Parse
`result.snapshot`; do not infer IDs from list order. Use a fresh snapshot at
initial orchestration, after context recovery, or after a structural mutation
whose response did not provide enough current state. Do not use snapshots as a
status-polling loop.

For an older installed CLI without `api snapshot`, fall back to the narrower
commands:

```bash
herdr workspace list
herdr tab list --workspace "$HERDR_WORKSPACE_ID"
herdr pane current --current
herdr pane list --workspace "$HERDR_WORKSPACE_ID"
herdr agent list
```

Read IDs from command JSON. Public handles such as `w8`, `w8:t1`, and `w8:p3` are opaque. A moved pane can receive a different public pane ID, so reread mutation responses.

Record which resources already exist. Later cleanup must not close them.

## Orchestration metadata

Herdr 0.7.4 supports display-only tokens on panes and workspaces. Use them to
make task identity recoverable and visible without opening transcripts.

Recommended stable source and token contract:

```text
source: orchestrator.v1

workspace tokens:
  phase       phase4
  stream      implementation
  base        953455e
  gate        building

pane tokens:
  task_id     phase4-recovery
  role        writer | reviewer
  model       sol | terra | luna
  effort      low | medium | high | xhigh | max
  scope       install-update
  candidate   04a655e
```

Token values are claims made by the Orchestrator. Set `model` and `effort` only
after the startup footer confirms both. Keep values short and non-sensitive;
tokens are visible in UI and API responses and may appear in metadata-focused
diagnostics.

Report stable identity once after launch:

```bash
metadata_source='orchestrator.v1'
metadata_seq=1

herdr pane report-metadata "$helper_pane" \
  --source "$metadata_source" \
  --token task_id=phase4-recovery \
  --token role=writer \
  --token model=sol \
  --token effort=high \
  --token scope=install-update \
  --seq "$metadata_seq"
```

Report a new candidate only when the candidate actually changes:

```bash
metadata_seq=2
herdr pane report-metadata "$helper_pane" \
  --source "$metadata_source" \
  --token candidate=04a655e \
  --seq "$metadata_seq"
```

Use one monotonically increasing `seq` per source and target so an older
asynchronous report cannot overwrite newer context. Use a single stable source;
a pane or workspace accepts only a bounded number of sequenced sources over its
lifetime. A report can patch up to 16 tokens, stored token names are limited to
ASCII letters, digits, `_`, and `-`, and values are capped at 80 characters.

Use `--ttl-ms` only for temporary context such as a deadline. TTL applies to the
token keys updated by that call. Stable identity normally remains until it is
replaced, explicitly cleared, or the pane/workspace closes. When reusing a pane
for a different task, replace or clear obsolete tokens before delegation.

Do not publish a custom `status`, `working`, `blocked`, or `done` token. Herdr's
semantic `agent_status` remains authoritative. Likewise, avoid overriding
`display_agent` or state labels merely to show roles; canonical identity and
state must remain visually recognizable.

After a pane moves or the Orchestrator loses local ID context, reacquire it from
stable metadata in one snapshot:

```bash
herdr api snapshot |
  jq -r '.result.snapshot.panes[]
    | select(.tokens.task_id == "phase4-recovery")
    | select(.tokens.role == "writer")
    | .pane_id'
```

Require exactly one match before sending input. Zero matches means the task
resource is absent or its metadata expired; multiple matches mean identity is
ambiguous and must be diagnosed.

Optional sidebar layout:

```toml
[ui.sidebar.agents]
rows = [
  ["state_icon", "workspace", "$role", "$model", "$effort"],
  ["$task_id", "$scope", "$candidate"],
]

[ui.sidebar.spaces]
rows = [
  ["state_icon", "workspace", "$phase", "$stream"],
  ["branch", "git_status", "$gate"],
]
```

Keep `state_icon`, canonical agent identity, branch, and Git status available.
Metadata improves navigation and recovery; it is never acceptance evidence.

## Task dashboard layout: at most four panes

Group the visible roles for one task in one tab so the user can understand the
whole execution state without switching workspaces. This is presentation only:
each writer still runs in its own required worktree and `cwd`, and pane layout
never relaxes file ownership, sequencing, or verification rules.

Use one pane per real role and keep the smallest useful shape:

| Visible roles | Layout |
| --- | --- |
| 1 | one full-size pane |
| 2 | two equal side-by-side panes |
| 3 | one left pane, two stacked right panes |
| 4 | equal 2x2 grid |

For a high-risk ClassHub task, keep the default one-worker shape when existing
specs already lock the behavior:

```text
Root -> Writer
```

A PO or reviewer is a real role only when a concrete unresolved product choice
or independent risk requires it. Do not launch either role merely because the
task is labeled high-risk, and do not launch extra workers to fill a layout.
If such a role is genuinely required, roles may be sequential rather than
concurrently working; keep completed decision evidence visible through the
current correction loop and close it only during task-owned cleanup.

Build the 2x2 layout from one existing task pane using returned pane IDs:

```bash
dashboard_left_top='<existing-task-pane-id>'

herdr pane split "$dashboard_left_top" \
  --direction right --ratio 0.5 --no-focus
dashboard_right_top='<pane-id returned by the split>'

herdr pane split "$dashboard_right_top" \
  --direction down --ratio 0.5 --no-focus
dashboard_right_bottom='<pane-id returned by the split>'

herdr pane split "$dashboard_left_top" \
  --direction down --ratio 0.5 --no-focus
dashboard_left_bottom='<pane-id returned by the split>'
```

For three roles, stop after the right pane is split down. For two roles, stop
after the first right split. Rename every pane with the task and role, launch
the agent with its exact checkout as `--cwd`, and report the standard metadata.
Always preserve focus with `--no-focus`; structural changes must not interrupt
the user's active pane.

Root counts toward the four-pane cap when it is shown in the task dashboard.
If four managed agents are genuinely required, put those four in a dedicated
task tab and leave Root in its orchestration tab. If more than four visible
roles are justified, use another phase-specific tab instead of creating narrow
panes. The default delegation policy should make this exceptional.

The user can temporarily enlarge any pane without changing the grid:

```bash
herdr pane zoom '<pane-id>' --toggle
```

## Start one interactive agent in a sibling pane

Use this for a single helper in the same checkout, especially reconnaissance or read-only review.

### 1. Choose a usable split

```bash
herdr pane layout --pane "$HERDR_PANE_ID"
```

Split right when the pane is wide and down when it is narrow or tall. Preserve focus:

```bash
herdr pane split --current --direction right --no-focus
```

Read `result.pane.pane_id` from the response:

```bash
helper_pane='<returned-pane-id>'
herdr pane rename "$helper_pane" auth-reviewer
```

### 2. Launch the normal interactive executable

```bash
herdr pane run "$helper_pane" \
  "codex -m gpt-5.6-luna -c 'model_reasoning_effort=\"max\"'"
herdr pane get "$helper_pane"
herdr wait agent-status "$helper_pane" --status idle --timeout 30000
herdr pane read "$helper_pane" --source recent-unwrapped --lines 40
```

Use the requested agent's ordinary executable, such as `codex`, `claude`, `pi`, `opencode`, or `omp`. For Codex, apply the explicit policy from `model-routing-and-context.md`; the example launches the routine default. Do not pass the task as an argv prompt or add non-interactive flags unless requested.

Waiting for `idle` prevents task text from landing in startup output or initialization UI. The one startup read confirms that the requested model and reasoning effort actually launched before the task is delegated.

### 3. Submit and confirm the task

```bash
herdr pane run "$helper_pane" \
  'Review the current diff. Do not edit files. Report actionable findings with file and line references.'
herdr wait agent-status "$helper_pane" --status working --timeout 30000
```

`pane run` sends the prompt and Enter atomically. The transition to `working` confirms that the agent consumed it.

## Start a named agent directly

Use `agent start` when a stable unique name is useful:

```bash
herdr agent start auth-implementer \
  --cwd "$PWD" \
  --split right \
  --no-focus \
  -- codex -m gpt-5.6-luna -c 'model_reasoning_effort="max"'
```

Inspect the returned record instead of assuming the pane ID:

```bash
herdr agent get auth-implementer
```

Take its `pane_id`, wait for readiness, and use `pane run` for its prompt. Agent targets must be unique enough to resolve unambiguously.

## State model

| State | Meaning | Action |
| --- | --- | --- |
| `unknown` | No confident classification | Inspect process and output; confirm launch |
| `working` | Actively processing | Wait; avoid redundant prompts |
| `blocked` | Visible question, approval, or permission UI | Read and answer only within authority |
| `done` | Completed while unseen | Read and verify |
| `idle` | Waiting, or completion has been seen | Read output to distinguish readiness from completion |

`idle` and `done` share completion semantics but differ in attention state. A background unseen completion becomes `done`. Viewing or focusing it marks it seen and changes it to `idle`.

After confirming the agent reached `working`, wait according to visibility:

```bash
# Usually appropriate for a visible pane in the active tab
herdr wait agent-status "$helper_pane" --status idle --timeout 900000

# Usually appropriate for a background tab or workspace
herdr wait agent-status "$helper_pane" --status done --timeout 900000
```

Always confirm current state and read the transcript because either `idle` or `done` can represent completion.

```bash
herdr pane get "$helper_pane"
herdr pane read "$helper_pane" --source recent-unwrapped --lines 160
```

## Event-driven monitoring without polling turns

The timeout is a safety deadline, not a polling interval. Once an agent reaches
`working`, create one long-lived wait sized for the task. Do not issue a fresh
60- or 120-second `herdr wait`, `agent list`, `pane get`, and `pane read` cycle
on every Orchestrator turn.

Cause and effect:

1. `herdr wait` subscribes to Herdr state events; it does not need a model to
   ask whether the state changed.
2. Repeating short waits tears down and recreates subscriptions even when
   nothing happened.
3. Each timeout then causes another reasoning turn, another status query, and
   often another transcript read.
4. Keeping the original wait process alive lets Herdr wake the Orchestrator only
   when the target state arrives or a meaningful deadline expires.

Use these defaults after the `working` transition:

- routine bounded work: one 10- to 15-minute terminal-state watch;
- complex implementation or a broad test suite: one 20- to 30-minute watch;
- known long verification: set the deadline from the command's observed runtime
  plus margin instead of sampling every minute.

For a background agent, completion normally becomes `done`, but the agent may
become `blocked` first. If the execution layer can race processes, start exactly
one subscription for each terminal outcome and stop the loser after one wins:

```bash
(
  herdr wait agent-status "$helper_pane" --status blocked --timeout 900000 &
  blocked_wait_pid=$!
  herdr wait agent-status "$helper_pane" --status done --timeout 900000 &
  done_wait_pid=$!
  wait -n "$blocked_wait_pid" "$done_wait_pid"
  kill "$blocked_wait_pid" "$done_wait_pid" 2>/dev/null || true
)
```

After that watch returns, run one `pane get` and one transcript read to
distinguish completion, a question, and a timeout. If the local execution tool
yields a process or cell ID while the wait is still running, resume that same
process with the tool's local wait/session primitive. Do not launch another
Herdr wait subscription.

A user-facing progress update does not require a Herdr query. Report the last
known state and the active deadline. Query again only after a state event, the
deadline, or new evidence that the detector may be wrong.

Metadata updates follow the same rule. A progress update does not justify a
metadata write. Update tokens only when stable identity, phase, scope, candidate,
or gate context materially changes.

## Choose the correct read source

- `visible`: current rendered viewport.
- `recent`: recent scrollback with terminal soft wraps.
- `recent-unwrapped`: scrollback with soft wraps joined; prefer for transcripts and logs.
- `detection`: live bottom-buffer snapshot used by agent screen detection, when supported by the installed version.
- `--format ansi`: use only when terminal styling is evidence.

## Agents versus ordinary commands

Use semantic state waits for coding agents:

```bash
herdr wait agent-status '<pane-id>' --status blocked --timeout 900000
```

Use output matching for tests, servers, and ordinary commands:

```bash
herdr wait output '<pane-id>' --match 'ready on port 3000' --timeout 120000
```

Inspect existing output before waiting for future output. A wait timeout is a diagnostic event, not permission to resend blindly.

For each normal delegated agent, the expected lifecycle budget is bounded:

```text
1 readiness subscription: idle
1 consumption subscription: working
2 terminal subscriptions at most: blocked and done/idle, raced once
1 transcript read after the terminal event
```

Corrections reuse the same pane and repeat only the consumption and terminal
parts. An unchanged state is not a reason to create more subscriptions.

## Diagnose a timeout or wrong state

```bash
herdr pane get '<pane-id>'
herdr pane process-info --pane '<pane-id>'
herdr pane read '<pane-id>' --source recent-unwrapped --lines 160
herdr agent explain '<pane-id>' --json
```

Concrete diagnoses:

- `blocked` plus a destructive migration question: ask the user.
- `blocked` plus a test-command question answered by repository scripts: answer directly.
- `unknown` plus a foreground shell: the agent probably never launched; relaunch it.
- Screen-detection fallback or unmatched UI: inspect the transcript rather than trusting the status label.

## Integrations and status authority

Check before relying on native session restoration:

```bash
herdr integration status
```

Automatic process and screen detection works without integrations. Integration roles differ:

- Codex, Claude Code, Copilot, Devin, Droid, Qoder, and Cursor integrations primarily report native session identity for restore. Their state still comes from screen detection.
- Pi, OMP, Kimi, OpenCode, Kilo, Hermes, and similar lifecycle integrations can author `idle`, `working`, and `blocked` and may also report session identity.

Installing the Codex integration improves session restoration; it does not replace Codex screen-based state detection. Integration installation is a persistent configuration change and requires user authorization.

## Direct attach and focus

Do not use `agent attach --takeover` for ordinary orchestration because it transfers interactive control. Do not focus a pane, tab, workspace, or agent unless the user asked to view it; focus can also change `done` to `idle` by marking work seen.
