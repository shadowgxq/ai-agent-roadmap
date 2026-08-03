# Ralph Manager Runner

You are running one non-interactive Ralph iteration in this frontend repository.

## Goal

Use `$manager-execute-current-batch` to execute the current Manager wave from `manager/plan.yaml`.

Ralph is only a loop wrapper around that skill. Do not reimplement Manager behavior resolution, OpenSpec phase handling, entrypoint selection, required skill selection, parallel rules, checks, or `manager/plan.yaml` backwrite in this prompt.

## Authorization

Run `$manager-execute-current-batch` in non-interactive automation mode.

The normal preview-and-confirmation step in `$manager-execute-current-batch` is pre-confirmed by this Ralph invocation for exactly one non-archive Manager wave. Do not ask the user for confirmation and do not stop after the preview. Continue execution after showing or internally resolving the preview.

This pre-confirmation does not apply to `archive`. If `$manager-execute-current-batch` resolves the selected action to `archive`, do not archive. Stop, record progress if appropriate, and report that explicit user confirmation is required.

## Flow

1. Read and follow `$manager-execute-current-batch`.
2. Let that skill read the required Manager/OpenSpec sources and execute at most one wave.
3. Let that skill decide the behavior, entrypoint, required downstream skill, checks, status updates, and next action.
4. Do not run `pnpm build` unless the user explicitly asked for it.
5. Do not run `git add`, `git commit`, branch switching, OpenSpec archive, or source-control mutation.

## Recovery Contract

If the selected OpenSpec or current wave is already `in-progress`, treat it as a resume from a previous interrupted Ralph run.

- Inspect the existing files, `scripts/ralph/progress.txt`, and `scripts/ralph/logs/latest-transcript.log` before making further changes.
- Continue from the current workspace state when it is coherent; do not delete or revert partial work just to restart.
- If the workspace state is inconsistent or unsafe to continue, mark the affected OpenSpec as `blocked`, write the reason and evidence to `manager/plan.yaml` or `scripts/ralph/progress.txt`, and stop.
- Never perform automatic rollback. Rollback requires an explicit user request after they review the partial work.

## Completion Signal

After `$manager-execute-current-batch` finishes, inspect `manager/plan.yaml` using the same selection rules owned by that skill.

Reply with exactly:

```xml
<promise>COMPLETE</promise>
```

only when there is no executable non-archive Manager wave left.

Do not emit the completion signal when:

- the next Manager action is `archive` and needs explicit user confirmation
- the current wave is blocked
- a check failed
- a product or implementation decision is required
- another non-archive Manager wave can still be executed by a later Ralph iteration
- there are active `change` or `apply` OpenSpec entries that are not covered by any matching `batch.behavior`

## Output

Keep the final response concise:

- summarize the wave executed by `$manager-execute-current-batch`
- list checks run or skipped
- state the next Manager action
- emit `<promise>COMPLETE</promise>` only under the completion rule above
