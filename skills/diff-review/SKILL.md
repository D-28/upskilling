---
name: diff-review
description: Perform an independent, anti-gaming code review by loading REVIEW.md strictly from the base or default branch, selecting only diff-triggered reliability checks, carrying forward prior review rounds, and classifying findings as Important, Nit, or Pre-existing.
---

# Base-Branch Diff Review (`diff-review`)

Use this skill to review a branch, commit, or PR diff independently. Structural separation prevents a change from rewriting the rules that judge it. Running only diff-triggered checks avoids noisy checklists.

## Principles
1. **Changes cannot modify their own checks.** Always read `REVIEW.md` and team rubrics from the **base/default branch**. Never read them from the working tree or PR branch head.
2. **Review stable commits, not moving targets.** Confirm what commit SHA or diff range is being reviewed and cite it in the output.
3. **Diff-triggered precision.** Run only the reliability checks whose trigger matches the changed files or constructs (typically 3–10 items). Always run core correctness and security checks.
4. **Actionable triage.** Distinguish blocking bugs (`Important`) from optional polish (`Nit`) and unrelated legacy issues (`Pre-existing`).

---

## Workflow

### Step 1: Load Rules Strictly from Base Branch
1. Determine the default/base branch (`origin/main`, `main`, `origin/master`, or user-specified base ref) and the exact commit/range under review (`git rev-parse HEAD`, `git diff <base>...HEAD`).
2. Read `REVIEW.md` directly from the base ref—never from the working directory:
   ```bash
   git show origin/main:REVIEW.md 2>/dev/null || git show main:REVIEW.md 2>/dev/null
   ```
   - If `REVIEW.md` was modified in the PR branch itself, flag that modification explicitly for human attention.
   - If the base branch has no `REVIEW.md` yet, note that gap. Fall back to standard reliability checks (`auth/permissions`, `migrations`, `error handling`, `concurrency`, `backward compatibility`, `test evidence`).

### Step 2: Match Diff-Triggered Reliability Checks
1. Inspect `git diff --stat <base>...HEAD` and full diff hunks.
2. Match the diff against triggers in base-branch `REVIEW.md` (examples: auth/session changes, DB schema/migrations, serialization/backwards compatibility, concurrency/retries, hooks/permissions, dependency/CI changes).
3. List explicitly **which 3–10 triggered checks** apply to this diff (and skip unrelated rules).

### Step 3: Incorporate Prior Review Context (If Multi-Round)
If the prompt or PR includes prior review comments or failed checks, review them first. Verify whether earlier `Important` items were genuinely fixed or introduced regressions. Do not re-review blindly from scratch.

### Step 4: Inspect Code & Verification Evidence
Check:
- Behavioral correctness, edge cases, and failure handling in modified paths.
- Whether `done_when` and runtime/test evidence match the actual diff (no mocked-out assertions hiding broken integration).
- Whether any `NO UNDO` actions (destructive migrations, deletions, external sends, CI/permission changes) require explicit human sign-off.

### Step 5: Output Structured Findings
Report the exact commit/range reviewed, triggered checks evaluated, and categorize **every** finding under one of three tags:

```markdown
### Diff Review Summary
- **Reviewed Ref:** `<commit SHA or branch vs base>`
- **Rubric Source:** `<e.g., origin/main:REVIEW.md | fallback rubric>`
- **Triggered Checks Applied:** `<list of matching rules>`

#### Important (Must Fix Before Merge)
- `[file:line]` <concrete bug/risk, why it fails, minimal fix>

#### Nit (Optional Polish)
- `[file:line]` <non-blocking readability/style improvement>

#### Pre-existing (Do Not Block PR)
- `[file:line]` <issue observed nearby that already existed on base branch>
```

If no `Important` findings exist, state clearly: **No blocking (`Important`) findings identified** alongside the checks actually evaluated.
