---
name: repair-runner
description: Run the project Markdown-driven repair pipeline from repairs/. Use when the user asks to execute, continue, automate, process, or run repair tasks, selected repair files, user verification, verified repair archival, or a /goal loop for repair work. The skill reads repairs/list.yaml plus one-file-per-repair items from repairs/queue/, dispatches one subagent per independent repair item when parallel work is safe, writes status back to each repair file, maintains repairs/list.yaml, and stops before archive unless the user explicitly asks to archive verified repairs.
---

# Repair Runner

## Overview

Coordinate the project-level repair queue under `repairs/`. This skill is the
control plane for repair automation: selected list intake, status backwrite,
subagent dispatch, user verification state, and archive movement.

This workflow is separate from `manager/plan.yaml` and OpenSpec. Use it for
small, independently verifiable fixes only. If a repair item changes product
requirements, API contracts, schema, or OpenSpec intent, stop and escalate it
to the Manager/OpenSpec workflow.

## Sources

Read first:

- `repairs/README.md`
- `repairs/list.yaml`
- `repairs/queue/`
- `repairs/archive/`
- `package.json`
- `scripts/repairs/validate_repairs.py` if present

Read each selected repair file before claiming it. Inspect code only as needed
to judge scope, parallel safety, and verification.

## Queue Shape

Active repair items live in `repairs/queue/repair-*.md`. Their YAML `status`
field is the per-item source of truth:

- `todo`: ready to be picked up
- `processing`: claimed or currently being repaired
- `fixed`: agent fix and engineering verification completed; waiting for user
  verification
- `verified`: user confirmed the fix; waiting for explicit archive
- `blocked`: cannot continue without new information, a decision, or external
  state
- `archived`: closed record after the file has moved to `repairs/archive/`

`repairs/list.yaml` is the run list and execution index. It records the selected
files, current processing set, fixed items waiting for user verification,
verified items waiting for archive, blocked items, archived items, and history.

## Modes

### Automated Repair

Use this mode for generic "run repairs", "continue repair tasks", selected
repair file lists, or `/goal` requests.

1. Read `repairs/list.yaml`.
2. Determine the selected repair files in this order:
   - Explicit repair files or ids named in the latest user request or goal text.
   - `repairs/list.yaml` `selected.files`.
   - All `repairs/queue/repair-*.md` files when neither of the above is set.
3. Read selected repair files and parse each file's YAML status.
4. If `scripts/repairs/validate_repairs.py` exists, run read-only validation
   against the selected files before claiming work. If validation fails, report
   the errors and emit `<promise>BLOCKED</promise>`.
5. Create or update `repairs/list.yaml` with `current_run.run_id`, mode
   (`selected_files`, `list_selected`, or `queue_scan`), `max_subagents`,
   `started_at`, `selected.files`, and `updated_at`. Once the parallel groups
   are decided (step 10), also persist them under `current_run.schedule` (see
   Scheduling) so the file reflects the same parallel/serial decision shown in
   the queue preview. Canonical shape:

   ```yaml
   current_run:
     run_id: run-YYYYMMDD-NN
     mode: list_selected            # selected_files | list_selected | queue_scan
     max_subagents: 3
     started_at: YYYY-MM-DD
     schedule:                      # one entry per wave/group; filled at step 10
       - group: wave1
         execution: parallel        # parallel | serial | bundle
         reason: <why these run together / in this order>
         items:
           - repairs/queue/repair-YYYYMMDD-NNN.md
   ```

   `current_run.schedule` records the grouping; the top-level `processing` list
   stays a flat list of all currently-claimed files.
6. If there are no selected files with `status: todo`:
   - Report `fixed`, `verified`, and `blocked` counts for the selected scope.
   - If fixed items exist, say they require user verification.
   - If verified items exist, say archive requires an explicit request.
   - Emit `<promise>COMPLETE</promise>`.
7. If selected files with `status: processing` already exist:
   - Inspect them first.
   - Continue only when they clearly belong to the current interrupted run and
     can be safely resolved.
   - Treat missing `claimed_by`, `claimed_at`, or `run_id` as ambiguous unless
     the surrounding Agent Notes and workspace state make ownership clear.
   - Otherwise report the ambiguity and emit `<promise>BLOCKED</promise>`.
8. Select up to `max_subagents` files with `status: todo`; default is `3`.
9. Claim selected files by setting their status to `processing`, updating
   `updated_at`, filling `claimed_by`, `claimed_at`, and `run_id`, and updating
   `repairs/list.yaml` `processing`.
10. Decide parallel groups using the Parallel Rules below.
11. Dispatch at most one worker subagent per repair item in the current parallel
    group.
12. Review worker outputs, inspect diffs as needed, and run final checks
    relevant to the combined changes.
13. For each successful repair item, record summary, changed files,
    verification evidence, and regression test disposition, then set
    `status: fixed` and add it to `repairs/list.yaml`
    `fixed_waiting_user_verification`.
14. For each failed or ambiguous repair item, record a clear blocker and set
    `status: blocked`.
15. Update `repairs/list.yaml` `processing`,
    `fixed_waiting_user_verification`, `verified_waiting_archive`, and
    `blocked`.
16. End the turn with next queue status. In a `/goal` loop, do not emit
    `COMPLETE` if executable `status: todo` files remain.

### User Verification

Enter this mode when the user's latest request explicitly confirms one or more
fixed repair items as verified, accepted, user-tested, or ready to archive.

1. Read `repairs/list.yaml` and selected repair files.
2. Select explicitly named repair ids if provided; otherwise select all
   `status: fixed` repair files from `fixed_waiting_user_verification`.
3. Preview selected repair ids.
4. Set each selected repair file to `status: verified`, update `updated_at`,
   and fill `user_verified_by` and `user_verified_at` when those fields exist.
5. Move each selected item in `repairs/list.yaml` from
   `fixed_waiting_user_verification` to `verified_waiting_archive`.
6. Do not move files to archive in this mode.

### Manual Archive

Enter this mode only when the user's latest request explicitly asks to archive,
prune, or clean up completed verified repair items.

1. Read `repairs/list.yaml` and selected repair files.
2. Select files with `status: verified`.
3. Select explicitly named repair ids if provided; otherwise select all
   `verified_waiting_archive` items.
4. Preview selected repair ids and archive paths.
5. Move each selected file to
   `repairs/archive/YYYY-MM-DD-<repair-id>.md`.
6. Set `status: archived`, update `updated_at`, and fill `archive_reason`.
7. Update `repairs/list.yaml` `verified_waiting_archive`, `archived`, and
   `history`.
8. Do not change code or run implementation checks in archive-only mode.

### Goal Loop

`/goal` is only the outer loop. The skill remains responsible for list intake,
queue reads, claiming, parallel decisions, worker handoff, final verification,
`repairs/list.yaml`, and per-repair status backwrite.

Goal may pre-authorize processing `status: todo` repair items after the queue
preview, but it never pre-authorizes user verification or archive. Stop when
there are no executable `status: todo` repair items in the selected scope. If
only `fixed`, `verified`, or `blocked` items remain, report that `fixed` items
wait for user verification, `verified` items wait for explicit archive, and
`blocked` items wait for human input.

## Scheduling: Conflict Graph, Bundles, Waves

Default `max_subagents` is `3`. Respect a lower limit if the user gives one.

Do not decide parallel-vs-serial from a vague feel. The common failure is
treating items that share files as if "one worker per item" makes them safe:
two workers then edit the same page entry / api / mutations and either conflict
or one worker silently does the other's job and leaves it half-wired. Build a
conflict graph first, then schedule.

### 1. Predict each item's file-set

From each repair item's `scope` plus the lightweight triage in its `Notes`,
list the files it will likely create or edit, including shared modules (types,
api, mutations, hooks, route config, page entry, page-level or global CSS,
fixtures). If a file-set cannot be predicted, treat the item as conflicting
with everything and serialize it.

### 2. Build the conflict graph

Two items are coupled when their predicted file-sets intersect, or when one
depends on the other (declared via `depends_on:` in the repair YAML, or evident
from triage — e.g. one reuses a component the other introduces).

### 3. Schedule

- **Independent** (disjoint file-sets, no dependency): same wave, one worker
  each, in parallel up to `max_subagents`.
- **Coupled, no ordering** — items that share most of their file-set and have
  no prerequisite between them (e.g. an add dialog and an edit dialog that both
  edit the same page entry, api, mutations, and reuse one form): prefer a
  single **Repair Bundle** handled by one worker in one coherent pass, instead
  of separate serial workers that reload the same context and risk a half-wired
  tree. Bundle only when the items are small and their file-sets mostly
  overlap.
- **Dependent** (one needs the other's output): order across waves; the
  dependent item's worker starts only after its prerequisite is `fixed` and
  coordinator-verified.
- **Config / cross-cutting** — build or dependency config, shared API contract,
  OpenSpec, Manager state, routing, global CSS: serialize against anything else
  in its file-set.

### 4. Parallel despite overlap (opt-in, advanced)

If items are logically independent but their file-sets overlap only loosely
(different regions of shared files), you may run their workers in parallel with
per-worker git worktree isolation, then merge serially and re-run the combined
checks, resolving conflicts. Use only when the speedup outweighs the merge
cost. Never run parallel workers over the same working tree when their
file-sets intersect.

When the schedule is still unclear after this analysis, serialize.

Record the chosen schedule — waves, bundles, parallel/serial, and the reason —
in the queue preview so the decision is visible before any worker is dispatched,
and persist the same grouping to `current_run.schedule` in `repairs/list.yaml`
(shape defined in Automated Repair step 5) so the file reflects what ran in
parallel, not just the chat preview.

### 5. Coordinator verification is mandatory

Never trust a worker's self-reported "all checks pass". After each worker or
bundle returns, the coordinator independently runs the relevant checks
(`typecheck`, `lint`, `test`, and any scope-specific check) against the real
working tree before marking anything `fixed`. If the checks fail, finish the
small wiring yourself or reassign, and keep the item `processing`/`blocked`
with the failure evidence — do not mark it `fixed` on the worker's word.

## Worker Handoff

Every worker receives either one repair item, or one Repair Bundle of
tightly-coupled items that share files (see Scheduling). A bundle worker owns
all listed items and must finish them as one coherent, fully-wired change.

The handoff must include:

```yaml
repair_file: repairs/queue/<repair-id>.md   # single item
repair_id: <repair-id>
# Bundle form — replace the two fields above with the coupled set:
# repair_files:
#   - repairs/queue/<repair-id-a>.md
#   - repairs/queue/<repair-id-b>.md
scope: <declared scope>
selected_files:
  - repairs/queue/<repair-id>.md
parallel_group: <serial|parallel|bundle>
queue_owner: repair-runner
run_id: <current-run-id>
list_file: repairs/list.yaml
may_edit_repair_queue: false
may_git_add: false
may_archive: false
```

Tell the worker:

- You are not alone in the codebase; do not revert or overwrite edits made by
  the user or other workers.
- Fix only the assigned repair item(s); do not bleed into other items' scope. A
  bundle worker must fully wire every item it owns (no half-finished feature
  left behind).
- Keep changes minimal and consistent with the project.
- Do not edit `repairs/**`, `manager/plan.yaml`, or OpenSpec archive files.
- Run the project checks yourself, and report changed files, summary, exact
  verification commands/results, and blockers. Do not claim success without
  having run the checks — the coordinator re-runs them independently.

## File Updates

Prefer structured, small edits. At minimum keep these fields accurate in each
repair file YAML block:

- `status`
- `updated_at`
- `scope` if the real scope is discovered
- `claimed_by`
- `claimed_at`
- `run_id`
- `regression_test`
- `user_verified_by`
- `user_verified_at`

Append execution evidence under `Agent Notes`:

- claimed by coordinator
- summary
- changed files
- verification
- regression test disposition
- user verification
- blocker
- archive reason

When archiving, preserve the repair id in the filename and prefix it with the
current date: `YYYY-MM-DD-repair-*.md`.

## Guardrails

- Do not use `manager/plan.yaml` as the repair queue.
- Do not run OpenSpec archive from this skill.
- Do not archive fixed items directly; archive only verified items unless the
  latest user message explicitly overrides this guardrail.
- Do not mark items `verified` unless the latest user message explicitly
  confirms user verification.
- Do not dispatch more workers than `max_subagents`.
- Do not dispatch parallel workers over the same working tree for overlapping
  or unclear scope; bundle them into one worker, serialize, or isolate each in
  its own git worktree and merge serially.
- Do not mark an item `fixed` on a worker's self-reported success; the
  coordinator must independently re-run the checks against the real working
  tree first.
- Do not let workers modify repair queue or `repairs/list.yaml` state directly.
- Do not run `git add`, `git commit`, or `git push`.
- Do not continue from ambiguous `processing` ownership during a goal loop.
- If a check fails after worker success, keep affected items as
  `status: processing` or change them to `status: blocked` with failure
  evidence.

## Output

Before execution, show a concise queue preview:

```md
| Repair | Status | Scope | Execution | Reason |
| --- | --- | --- | --- | --- |
| `repair-id` | `todo` | `<scope>` | `parallel|serial|blocked` | `<why>` |
```

After execution, report:

- items set to `status: fixed`
- items set to `status: verified`
- items set to `status: blocked`
- changed files
- checks run or skipped
- remaining `todo`, `fixed`, `verified`, and `blocked` counts
- `repairs/list.yaml` updates
- next action

For `/goal` loops:

- emit `<promise>COMPLETE</promise>` only when no executable `status: todo`
  repair items remain
- if `fixed`, `verified`, or `blocked` items remain, still emit `COMPLETE` only
  in the sense that no automatic repair work remains, and state the remaining
  manual action
- emit `<promise>BLOCKED</promise>` when the queue cannot safely continue
  without human input
