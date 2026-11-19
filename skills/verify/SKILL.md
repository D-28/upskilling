---
name: verify
description: Run end-to-end runtime verification against the actual running application or interface, enforce structured failure tracking and the 3-strike escalation limit, and emit concrete execution evidence before committing or claiming completion.
---

# Runtime Verification (`verify`)

Use this skill whenever a code change is ready to verify, before opening a PR, or when asked to confirm a feature or bug fix actually works. Do **not** rely on self-report ("looks good", "should pass") or unit mocks alone.

## Principles
1. **Verification means running the real change.** Static unit tests can pass while the user-facing feature is broken. Boot the service, drive the UI/CLI/API end to end, and inspect real outputs.
2. **Loop on evidence, not confidence.** Every claim must cite a command run, exit code, observed output, or visual/DOM inspection.
3. **Hard exits prevent token burn.** Stop and escalate to a human after **3 failed repair attempts** or as soon as the **exact same failure repeats twice** (`dead_ends`).
4. **Never fake green.** Never add `sleep()`, skip flaky tests, or weaken assertions to make a check pass. If a test is genuinely flaky and its root cause cannot be found, remove or quarantine it only with explicit human confirmation and document why.

---

## Workflow

### Step 1: Inspect the Diff & Define `done_when`
1. Check `git status` and `git diff` (plus `git diff --cached` if staged) to see what files and user flows changed.
2. Identify the concrete `done_when` criteria before running checks:
   - What user flow, API contract, or invariant must hold?
   - If fixing a bug: verify you have a check/repro that **fails without the fix** and **passes with it**.

### Step 2: Run Cheap Deterministic Checks First
Run the repository's fast checks (typecheck, lint, build, targeted unit/property tests) before spinning up heavier E2E harnesses. Fix obvious syntax/type errors immediately.

### Step 3: Execute End-to-End Runtime Verification
Pick the runtime harness matching the change:
- **Web UI:** Boot the dev/preview server and drive the real user flow via browser tooling / Chrome DevTools Protocol (CDP), checking console errors, network status, and rendered state.
- **Backend / API:** Start the local server cleanly (or use an ephemeral test harness) and send real HTTP/RPC requests asserting status codes, payloads, and persisted side effects.
- **CLI / Library:** Execute the actual CLI binary/entrypoint against realistic inputs and inspect exit codes, stdout/stderr, and generated files.
- **Data / Migrations / Rewrites:** Run **property-based tests** (`fast-check`, `Hypothesis`, `proptest` — round-trip, invariants, idempotency, equivalence) and/or **differential checks** comparing old vs. new output on identical sampled inputs.

### Step 4: Repair Loop with Structured Feedback (Max 3 Rounds)
Track a `dead_ends` list across attempts. On any failure, record:

```text
FAILED      <test or user flow name>
EXPECTED    <exact expected behavior / output>
SAW         <exact observed error / output / screenshot summary>
FENCE       <files/modules allowed to change>
DEAD ENDS   <approaches already tried that failed>
```

**Stop & Escalate Immediately if:**
- You hit **3 failed repair rounds** on the same issue, OR
- `SAW` matches an entry already in `DEAD ENDS` (same failure twice).

When escalating, stop editing code and report the exact `FAILED / EXPECTED / SAW / DEAD ENDS` state plus what missing tool, visibility, or human decision is blocking progress.

### Step 5: Emit Verification Evidence
Output a concise evidence summary (never just "all tests pass"):

```markdown
### Verification Evidence
- **Checks Executed:** `<exact commands / E2E flows run>`
- **Result:** `<pass/fail + key observed output>`
- **Scope Verified:** `<user journeys / endpoints / invariants checked>`
- **Gaps / Not Verified:** `<anything skipped or needing human sign-off, e.g. prod migration>`
- **Suggested Commit Trailer:** `Verified-By: <e.g., e2e,unit | lint,unit | none>`
```
