# Paseo Migration Evidence

## Current release state

The Paseo MVP is active. The default Root is the external Codex CLI opened in
this repository; Paseo is the managed-worker control plane only. Both the
mandatory negative and positive disposable live fixtures passed before the
active startup policy was switched.

## Baseline

- Known-good repository reference inspected: `a0ec522249f6efb79474218b17674456a2551377`.
- Pre-implementation unit baseline: 20 passing tests.
- Installed Paseo CLI: `0.2.5`.
- Local Paseo daemon at implementation time: initially stopped; it was later
  started by the user for the authorized live cutover fixture.
- Root mode: external Codex CLI in this repository by default; an optional
  Paseo-managed Root remains supported.

The implementation did not start, stop, pair, update, expose, or reconfigure
the daemon.

## Implemented proof surfaces

- Durable coordinator ledger with atomic writes, task binding, attempt IDs,
  monotonic dispatch sequence, prompt digests, and validated state transitions.
- Full canonical task digests and per-gate artifact digests prevent contract,
  handoff, verification, or decision replacement after launch or review.
- Exact Git base, branch, worktree, Paseo workspace, agent cwd, parent, model,
  thinking route, and persistence checks.
- Recoverable worktree/workspace provisioning and label-based lost-launch
  recovery without automatic duplicate launch.
- Same-agent corrections with a durable attempt recorded before delivery;
  ambiguous correction delivery enters `WAIT` and is never auto-replayed.
- Worker handoff remains a claim. Candidate and integrated Root verification
  are separate mandatory gates, and `ACCEPT` must reference the exact
  integrated verification.
- Managed worker nested delegation is forbidden in both rendered prompts and
  runtime topology checks.
- Read-only investigation tasks return concrete findings at the unchanged
  locked base and require independent Root investigation verification.
- The minimal runtime rejects high-risk ClassHub launches until its required
  reviewer and PO governance gates are implemented.
- Archive is normally allowed only after `ACCEPTED` and after rechecking
  integrated acceptance evidence. Explicit `--discard-empty` is limited to a
  `WAIT`/`FAILED` task with no artifacts and a clean writer worktree still at
  the locked base.

## Mocked verification

Run:

```bash
python3 -m unittest discover -s tests -v
```

Current result: 52 passing tests. Covered failures include version mismatch,
invalid external Root cwd or managed-Root persistence, malformed JSON, unsafe shell transport,
moving Git base, workspace/cwd/model/parent disagreement, nested agents,
lost worktree/workspace/launch responses, duplicate and stale attempt signals,
gate skipping, unintegrated cleanup, worker-only evidence, and candidate versus
integrated verification.

Post-cutover hardening also covers full-contract mutation, mutable handoff
replacement after candidate verification, protected-file rename scope escape,
ambiguous correction recovery, mutating verification commands, late target
checkout changes before `ACCEPT`, duplicate task identity, and read-only
investigation completion without a commit.

The schema-v4 investigation path was also exercised through the live Paseo
`0.2.5` daemon with Luna `medium`. The first attempt exposed a missing CLI
parser choice and invalid evidence shape; Root kept the task in `WAIT`, fixed
the parser, corrected the same agent, reproduced the finding at the unchanged
locked revision, recorded `ACCEPT`, and archived the task-created agent and
workspace. Final Paseo agent and workspace listings were empty.

## Live cutover result

The disposable fixture passed all cutover gates on Paseo `0.2.5`:

1. External Root live doctor passed from the exact Chief of Staff repository,
   with reachable matching CLI/daemon versions and installed Luna/Terra routes.
2. The negative attempt became `WAIT` when the Luna worker stopped without a
   handoff; no acceptance gate was crossed and the target remained at the
   locked base.
3. A correction was sent to the same full worker ID. The positive attempt
   produced commit `6c3058623bff403cdd886740ae083883e0402207` in the exact
   writer worktree.
4. Root personally inspected the one-file diff, verified the candidate,
   fast-forwarded the unchanged clean disposable target, repeated integrated
   verification, and only then recorded `ACCEPT`.
5. The task-created Paseo agent and workspace were archived. A direct final
   listing showed no remaining live fixture agents or workspaces.

The fixture found two integration defects that mocked tests had not exposed:

- Paseo reports an already-linked Git worktree registered with requested
  `--isolation local` as observed isolation `worktree`. Runtime verification
  now records and accepts only those two exact classifications while retaining
  the requested-local policy and exact cwd/identity checks.
- A worker initially treated the task's protected target `repository` as its
  execution checkout. Every launch and correction now receives a
  Root-controlled boundary naming the exact writer worktree, protected target,
  authorized artifact directory, and linked-worktree commit authority.

The handoff gate now also proves that the candidate is the clean writer
worktree HEAD and that every required evidence command was observed at that
revision in that exact worktree. A target-checkout test result cannot satisfy
the candidate gate.

## Final verification

The final verification completed successfully with 52/52 tests:

```bash
python3 -m compileall -q herdr-orchestrator tests
python3 -m unittest discover -s tests -v
git diff --check
bin/chiefctl doctor --live --json
```

Active startup documentation now routes to `PASEO_ORCHESTRATOR.md`. The legacy
Herdr policy remains only for an already-running legacy task and is not an
active worker entry point.

No ClassHub product code was changed by the migration fixture. The first
separately authorized bounded ClassHub task is still the release-qualification
pilot and must pass the same candidate and integrated Definition of Done.
