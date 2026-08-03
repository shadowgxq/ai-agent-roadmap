---
name: repair-intake
description: Manual-only repair intake workflow. Use only when the user explicitly invokes $repair-intake or clearly asks to use the repair-intake skill/workflow to register, create, write, or queue a repair item. Do not auto-trigger merely because the user reports a bug, defect, issue, regression, abnormal behavior, or asks a question about repairs. This skill validates that the report is clear enough before writing files; if required details are missing, ask concise follow-up questions until the repair item can meet the project repair format.
---

# Repair Intake

## Purpose

Turn a user's natural-language issue report into a repair item under
`repairs/queue/` and add it to `repairs/list.yaml`.

This skill is intake only. Do not implement the fix. Actual repair execution is
handled by `$repair-runner`.

Manual trigger only: use this workflow only when the latest user message
explicitly invokes `$repair-intake` or clearly asks to use the repair-intake
skill/workflow. Do not auto-trigger from ordinary bug reports or questions.

## Read First

- `repairs/README.md`
- `repairs/repair-template.md`
- `repairs/list.yaml`
- `scripts/repairs/validate_repairs.py` if present

## Clarity Gate

Before writing files, decide whether the report is clear enough.

Required:

- A concrete observed problem or failure.
- Enough context to identify the affected user action, UI surface, workflow, or
  code area; if the user does not know the exact page/module, `scope: unknown`
  is acceptable only when the observed action is concrete.
- An expected outcome, or an expected outcome that can be safely inferred from
  the report and recorded as an assumption.

If required details are missing, do not create a repair file yet. Ask 1-3 short
questions and wait for the user. Keep asking until the required fields can be
filled.

Do not block on recommended details:

- Exact component path
- Exact API endpoint
- Automated verification command
- Regression test strategy
- Screenshot/log link

Use `unknown`, `user report`, manual verification notes, and explicit
assumptions when those details are not available.

Escalate instead of creating a repair item when the report appears to require a
product behavior change, API contract change, schema change, or OpenSpec intent
change.

## Lightweight Code Triage

After the report passes the clarity gate, do a quick read-only code triage
before creating the repair file.

Allowed:

- Use `rg` / `rg --files` to search for user-facing text, route names, feature
  names, button labels, submit handlers, API service names, and likely state
  flags such as `submit`, `onSubmit`, `mutate`, `loading`, `pending`,
  `disabled`, `debounce`, or `request`.
- Read a small number of high-signal files needed to infer likely ownership.
- Infer `scope` as a file path, directory, module, or `unknown`.
- Record the evidence and assumptions in `Notes`.

Not allowed:

- Do not edit source code.
- Do not run dev server, build, test, deploy, publish, or other high-side-effect
  commands unless the user explicitly asks.
- Do not do a broad architecture investigation. If quick search does not locate
  the likely area, use `scope: unknown` and write that triage could not locate a
  specific file.

Suggested triage output to include in `Notes`:

- `Likely scope`: paths or `unknown`
- `Triage evidence`: search terms and files inspected
- `Assumptions`: expected behavior inferred from the report
- `Suggested verification`: manual or automated check for the runner

## Create The Repair

1. Find the next id by scanning `repairs/queue/repair-YYYYMMDD-NNN.md` and
   `repairs/archive/YYYY-MM-DD-repair-YYYYMMDD-NNN.md`.
2. Create `repairs/queue/<repair-id>.md` from `repairs/repair-template.md`.
3. Fill at minimum:
   - `id`
   - `status: todo`
   - `priority` (`medium` by default unless user indicates urgency)
   - `source: user report` unless a source path/link is provided
   - `scope` (`unknown` if not known)
   - `created_at`
   - `updated_at`
   - `regression_test: not_applicable`
4. Write `Repro`, `Expected`, `Actual`, and `Notes` in concise Chinese. Include
   the lightweight triage evidence in `Notes`.
5. Keep `Agent Notes` headings present and empty for the runner.
6. Add the new file path to `repairs/list.yaml` `selected.files`, preserving
   any existing selected files unless the user explicitly asks to replace them.
7. Update `repairs/list.yaml` `updated_at`.
8. Run:

```bash
pnpm repairs:validate -- <new-repair-file>
```

If validation fails, fix the repair file or list and rerun validation.

## Output

Report:

- Created repair file path
- Whether it was added to `repairs/list.yaml`
- Validation command and result
- Any assumptions recorded
- Next action: run `$repair-runner` when ready
