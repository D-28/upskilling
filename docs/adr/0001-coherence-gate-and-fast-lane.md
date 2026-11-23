# ADR-0001: Weekly Coherence Gate (Gemini 4 Neon) and Fail-Closed Fast-Lane

- **Date:** 2026-11-22
- **Status:** Accepted
- **Owners / Deciders:** `D-28`

## Context

In run `#45077480015`, a manual `fast_lane_url` pointing to `x.com` returned only a thin stub. Stage 1 (`gemini-flash-lite-latest`, `LOW`) guessed `ALREADY_COVERED` silently without flagging missing text. Job Summary also hid drop verdicts and input parameters inside a zip artifact. Meanwhile, daily Draft PRs grade articles one by one and miss cross-week contradictions, subsumption, and systemic repo bloat.

## Decision

1. **Fast-Lane Plan B and Fail-Closed Gate:** Before calling any LLM, `build_fast_lane_candidate` runs safe Plan B canonical/oEmbed resolution. If extracted text stays below `600` chars or `100` words, it exits non-zero as `FETCH_INCOMPLETE` at `$0` LLM cost. Login and JS walls fail closed the same way.
2. **Direct Frontier Fast-Lane Routing:** Validated fast-lane articles bypass Stage 1 and route straight to `STAGE3_MODEL` (`gemini-4-neon`, `HIGH` thinking) with `MAX_RUN_COST_USD` raised to `0.50`.
3. **Daily Buffer to Weekly Coherence Gate:** Mon–Sat sweeps buffer local survivors (`score >= 7/10`) in `radar-state/pending-candidates.json` without opening PRs. On Sunday, if buffered items exist, Stage 3 loads the full repo (`~13K` tokens) and score-blind candidates into `gemini-4-neon` (`HIGH`). It audits six systemic poisons and cross-item interactions, emitting `REJECT_ALL` and opening zero PRs on most weeks.

## Alternatives Considered (and Why Rejected)

- **Gemini 4 Argon (`gemini-4-argon`) at Stage 3:** Rejected. Argon caps at `HIGH` (`50.4` index) and doubles to `$4 / $20` per MTok on Dec 1, 2026. Gemini 4 Neon (`gemini-4-neon`) scores higher (`59.6` at `HIGH`, `61.4` at `XHIGH`) and runs faster. Neon stays at `$3 / $15` flat, making it `25%` cheaper after Dec 1.
- **Antigravity Laptop-Only Runtime (`/schedule`):** Deferred to [`todo.md`](../../todo.md). Running unattended feeds on a personal laptop breaks 24/7 cadence and weakens prompt-injection isolation.

## Consequences & Guardrails

- **Enables:** Zero-PR quiet weeks, early detection of contradictory or bloated ideas, and clear GitHub Actions Job Summaries.
- **Costs / Constraints:** Requires `gemini-4-neon` pricing entries in `scripts/radar/config.py`. Revisit Antigravity authenticated fallback only if Plan B repeatedly fails on paywalled links.
