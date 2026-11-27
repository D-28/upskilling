# REVIEW.md

> **Critical Invariant:** Load `REVIEW.md` strictly from `origin/main`. Never read it from the pull request head. If a PR edits `REVIEW.md`, require explicit human code-owner approval.

## 1. Review Principles
1. **Review fixed commits.** Always cite the reviewed commit SHA and base ref.
2. **Tag every finding:**
   - **`Important`** — Must fix before merge (bug, security flaw, data loss, broken compatibility, missing verification).
   - **`Nit`** — Optional polish. Never block merge on a `Nit`.
   - **`Pre-existing`** — Issue already present on `origin/main`. Track separately without blocking this PR.
3. **Carry forward prior rounds.** Check previous review comments first instead of re-reviewing blindly.
4. **Gate `NO UNDO` changes.** Require explicit human sign-off on CI workflows, permissions, or destructive changes.

## 2. Diff-Triggered Reliability Checklist

Scan changed paths first (`python3 scripts/diff_context.py --base origin/main --json`). Run only matching checks.

| # | Diff Trigger | Required Check |
|---|---|---|
| 1 | `scripts/radar/models.py`, `scripts/radar/state.py` | **Backward-compat load & idempotency:** Confirm old persisted records deserialize safely (`extra="ignore"`, safe defaults) and retries produce identical state. |
| 2 | `scripts/radar/fetcher.py`, `scripts/radar/security.py` | **SSRF & budget walls:** Confirm SSRF guards, per-HTTP-request `MAX_PLAN_B_FETCHES` cap, fail-closed walls, and `$0` LLM / `0` extra HTTP for source discovery. |
| 3 | `scripts/radar/rubric.py` | **Marker round-trip & sanitization:** Confirm hidden marker round-trip parsing and `@mention`/HTML sanitization on untrusted text. |
| 4 | `.github/workflows/*.yml` | **Privilege separation (`NO UNDO`):** Confirm two-job permission isolation, `tools=None` on LLM calls, and explicit human sign-off. |
| 5 | `skills/*/SKILL.md`, `templates/*`, `docs/*.md`, `REVIEW.md` | **STE-80 & token baseline:** Confirm `scripts/ste_lint.py --check` passes and Stage 3 baseline globs stay lean. |
| 6 | `tests/**` | **No fake green:** Reject newly added `.skip`, arbitrary `sleep()`, weakened assertions, or mock-only tests hiding broken integration. |

## 3. Promotion & Pruning Policy
Add a rule here only after it appears in `>= 2` real PRs or an incident replay. Prune rules quarterly when CI enforces them deterministically or when they stop triggering.
