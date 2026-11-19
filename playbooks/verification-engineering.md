# Verification Engineering Playbook

> **Core thesis (`[B]`):** Code generation has become cheap; **verification has not.**
> When ~90% of code is written and reviewed by AI agents, human engineering shifts from *writing code and reading every diff* to **defining "done," building un-gameable verification loops, and reviewing execution evidence (`[B]`, `[C]`).**

---

## 1. Why Verification Is the Parallelism Bottleneck (`[B]`)

Without automated verification, you can only run 1 or 2 coding agents safely because you have to inspect everything yourself. With strong verification loops, teams can safely run dozens or hundreds of agents in parallel (`[B]`).

- Anthropic's internal evaluations on structured file generation showed that separating the worker from a **rubric-based grader** raised task success by **up to 10 points**, with the biggest lift on the hardest tasks (`[B]`).
- Tests, benchmarks, and specs are now **cheap for agents to generate**—and once generated, they execute deterministically as software for almost zero ongoing tokens (`[B]`).

---

## 2. Three High-ROI Test Types Agents Can't Easily Fool (`[B]`)

Before picking test types, avoid two agent-hostile traps (`[B]`):
- **Flaky tests** train agents to keep clicking "retry" instead of fixing bugs.
- **Slow tests** push agents into huge, infrequent batches where pinpointing regressions becomes hard. Run heavy suites before final commit/PR, and run fast targeted checks continuously.

Invest heavily in these three verification layers:

### A. End-to-End (E2E) Runtime Tests — *Priority #1* (`[B]`)
Unit tests can easily pass while the real user flow is completely broken—because unit mocks share the same misunderstandings as the agent that wrote the code (`[B]`). E2E tests exercise the real feature end to end (add item → checkout → confirmation), making them hard to game and giving concrete visual/DOM/API error evidence.

- **Give the agent hands and eyes:** Use Chrome DevTools Protocol (CDP) / browser tools for web UI, mobile MCP simulators for iOS/Android, computer-use for desktop, or local server + real HTTP requests for backends (`[B]`).
- **Feature map rubric:** Maintain a plain user-perspective map (routes, selectors, shortcuts, expected outcomes) so the agent knows what "working" looks like (`[B]`).
- **Codify it in a `verify` skill:** Put repo-local verification instructions in a `verify` skill (e.g., [`skills/verify/SKILL.md`](../skills/verify/SKILL.md)) and stress-test it until booting and smoke-testing the app is fast and rock solid (`[B]`).

### B. Property-Based Tests (`[B]`)
Normal unit tests only check cases the author (or agent) remembered to imagine. Property tests state an invariant that must hold for **any** valid input, then let a library (`fast-check` for TS/JS, `Hypothesis` for Python, `proptest` for Rust) hammer the code with thousands of randomized, agent-independent edge cases (`[B]`):

| Property Pattern | Plain-English Example |
|---|---|
| **Round-trip encoding** | `decode(encode(payload)) == payload` for arbitrary strings/Unicode/nested objects |
| **Invariants** | Account balance is never negative; order total always equals sum of line items |
| **Idempotency** | Running a migration, normalization, or retry handler twice produces the exact same state as once |
| **Equivalence** | New fast/optimized algorithm returns identical output to a simple naive reference implementation |

Property tests are especially high-leverage during rewrites where old specs have drifted from real production behavior (`[B]`).

### C. Differential Tests — *The Old System Is the Oracle* (`[B]`)
For large migrations or refactors where behavior must stay identical:
1. Run **both** the legacy implementation and the new implementation against the same randomized inputs or sampled production traffic (`[B]`).
2. Normalize irrelevant differences (whitespace, generated timestamps/UUIDs).
3. Maintain an explicit allowlist of **approved intentional behavioral changes**; treat any other discrepancy as a bug to fix (`[B]`).

---

## 3. Anti-Gaming Code Review Architecture (`[B]`, `[C]`)

Once agents write most diffs, code review needs hard structural boundaries:

1. **Changes cannot modify their own checks (`[B]`):**
   Always load `REVIEW.md` and review rubrics from the **base / default branch** (e.g., `origin/main`), never from the PR branch being judged. Otherwise a PR could quietly weaken its own grading rules (`[B]`).
2. **Diff-Triggered Reliability Checklists (`[B]`):**
   Instead of dumping a 40-item checklist into every prompt (wasting attention budget `[C]`), attach a **diff-readable trigger** and incident origin to each check.
   - *Anthropic example (`[B]`):* A 39-item checklist includes `"--resume loads old transcripts"`, triggered whenever session storage or message schema files change—asking whether older transcripts missing the new field still load cleanly.
   - The reviewer scans the diff and executes **only the 3–10 matching checks** (`[B]`). See [`templates/REVIEW.md.template`](../templates/REVIEW.md.template).
3. **One Tuned Reviewer Over Stacked Reviewers (`[B]`):**
   Adding a second, more expensive reviewer model rarely beats tuning one primary reviewer with `REVIEW.md`. Run multi-round verification where each round receives prior context and failures instead of starting from scratch (`[B]`).
4. **Review Commits, Not Moving Targets (`[B]`):**
   Never review a branch while edits are still flying in. Run cheap lint/typecheck/unit checks locally first (via hooks or `/goal`), then review fixed commits (`[B]`).
5. **Severity Tagging (`[B]`):**
   Require every finding to be tagged strictly as:
   - `Important` (must fix)
   - `Nit` (optional polish)
   - `Pre-existing` (already broken before this diff; don't block the author on unrelated legacy bugs)
6. **Code Owners Write & Explain Checks (`[B]`):**
   Owners refine checks until they flag what the owner actually cares about—and every check that pages a human reviewer must state *why* so the human doesn't have to reverse-engineer the diff (`[B]`).

---

## 4. Operational Guardrails: 3-Strike Escalation & Safe Gate Rollout (`[B]`, `[C]`)

### The 3-Strike Rule (`[B]`, `[C]`)
If an agent runs its verification loop and fails to repair the issue after **3 rounds** (or hits the exact same failure twice `[C]`), **stop and escalate to a human** (`[B]`, `[C]`). Humans step in on *failure signals*, not every clean line of code (`[B]`).

### Safe Commit Gate Rollout (`off → observe → enforce`) (`[B]`)
Never drop a strict commit block onto a team or agent workflow overnight:
1. **Stamp commits with verification provenance:** Record a trailer on every commit (e.g., `Verified-By: e2e,unit`—and explicitly record `"none"` when unverified so gaps stay measurable) (`[B]`).
2. **Roll out in 3 phases:**
   - `off`: Disabled.
   - `observe`: Logs what *would* have been blocked so you can audit false positives before hurting velocity (`[B]`).
   - `enforce`: Blocks commits lacking `/verify` or `/code-review`, **with a 2-block escape hatch**: an explicit commit-message explanation is allowed, and after 2 blocks in one session, the third attempt passes through so an imperfect agent never deadlocks (`[B]`).

See [`hooks/verify-gate-observe.md`](../hooks/verify-gate-observe.md) for runnable starter snippets.

---

## 5. Treating Verification Like a Production System (`[B]`)

### Evaluate Your Reviewers Against Ground Truth (`[B]`)
Measure review checks on outcomes that matter, not vibes:
- Track **reverted merged PRs**, **maintainer rejections**, and a **size-matched set of clean merged PRs** (controls to catch over-flagging).
- Replay historical incident commits (checkout exact pre-fix repo state + 1-sentence bug key) and measure recall separately at **raw findings**, **post-verification**, and **final review**—if recall drops between stages, your verifier is discarding real bugs (`[B]`).
- Stop tuning recall right before it overfits your historical eval set (`[B]`).

### Turn Missed Bugs Into Rules—With Proof (`[B]`)
Use two disciplined promotion loops instead of knee-jerk prompt additions:
1. **Recurring human feedback / reverts:** Extract patterns that appear in **at least 2 PRs** and are detectable from a diff → have **3 agents try to disprove the rule** → merge via human-approved PR into `REVIEW.md` (`[B]`).
2. **Incident replay:** Run 3 bug finders on an incident PR; if **≥ 2 find the bug** and it was missed on a small diff, codify the rule in `REVIEW.md` (`[B]`).

### Zero Tolerance for Flaky Workarounds & Rule Bloat (`[B]`)
- **Ban skipping, `sleep()`, or retrying flaky tests.** Fix the root cause; if unknown, delete the flaky test and document why (`[B]`).
- **Prune routinely.** Test suites, verification harnesses, and `.md` rules only grow if neglected—schedule regular cleanups so everything left in context earns its tokens (`[B]`, `[G]`).

---

*Related: [`skills/verify/SKILL.md`](../skills/verify/SKILL.md) · [`skills/diff-review/SKILL.md`](../skills/diff-review/SKILL.md) · [`templates/REVIEW.md.template`](../templates/REVIEW.md.template) · [`hooks/verify-gate-observe.md`](../hooks/verify-gate-observe.md)*
