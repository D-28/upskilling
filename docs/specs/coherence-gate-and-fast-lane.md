# Spec: Weekly Coherence Gate & Fail-Closed Fast-Lane

- **Related Glossary:** [`docs/GLOSSARY.md`](../GLOSSARY.md)
- **Related ADR:** [`docs/adr/0001-coherence-gate-and-fast-lane.md`](../adr/0001-coherence-gate-and-fast-lane.md)
- **Baseline Playbooks:** [`playbooks/harness-loop-graph.md`](../../playbooks/harness-loop-graph.md), [`playbooks/verification-engineering.md`](../../playbooks/verification-engineering.md), [`playbooks/model-effort-economics.md`](../../playbooks/model-effort-economics.md)

---

## 1. Goals & Non-Goals

### Goals
- Make every GitHub Actions Job Summary self-contained with inputs, extracted text length, Stage 1/2/3 decisions, and drop reasons.
- Resolve linked blog articles or public oEmbed text on `fast_lane_url` runs before calling any LLM.
- Fail closed (`FETCH_INCOMPLETE`, non-zero exit on manual dispatch, `$0` LLM spend) when a fast-lane link hits a login or paywall.
- Route verified fast-lane articles directly past Stage 1 into `STAGE3_MODEL` (`gemini-4-neon`, `HIGH`).
- Buffer Mon–Sat feed survivors silently and run one Sunday `gemini-4-neon` (`HIGH`) Coherence Gate across the full repository.
- Default to zero PRs opened most weeks unless a synthesis clears all six Systemic Poison checks.

### Non-Goals
- No CAPTCHA solving, anti-bot evasion, or storing X/Substack session cookies in GitHub Secrets.
- No automated Antigravity browser integration in v1 (captured in [`todo.md`](../../todo.md) if repeated `FETCH_INCOMPLETE` failures occur).
- No automated edits to `playbooks/`, `skills/`, `templates/`, or `main`.

---

## 2. Architecture & Data Flow

```mermaid
flowchart TD
    FL["Manual Fast-Lane URL"] --> PB["Plan B Fetcher + Content Gate (>=600ch, >=100w)"]
    PB -->|Blocked or Stub| FAIL["Exit 1: FETCH_INCOMPLETE ($0 LLM, not marked seen)"]
    PB -->|Full Text OK| S3

    SCHED["Mon-Sat Daily Cron (11 Feeds)"] --> S0["Stage 0 + Stage 1 (flash-lite, LOW) + Stage 2 (flash, HIGH)"]
    S0 -->|score >= 7/10| BUF[("radar-state/pending-candidates.json")]

    SUN["Sunday Weekly Gate (or workflow_dispatch gate=true)"] --> S3["Stage 3 Coherence Gate (gemini-4-neon, HIGH, Zero Tools)<br/>Full Repo (~13K tok) + Score-Blind Candidates"]
    BUF --> S3
    S3 -->|REJECT_ALL (Default)| AUDIT["Write audit log to radar-state/weekly-audits.md (0 PRs)"]
    S3 -->|APPROVE_SYNTHESIS| PR["Open 1 Weekly Draft PR in radar/YYYY-Www-digest.md"]
```

---

## 3. Systemic Poison Taxonomy (Stage 3 Rubric)

Stage 3 evaluates every buffered candidate or synthesis against six failure modes:

1. **Attention-Budget Poison:** Purely additive prose that bloats context without replacing or sharpening an invariant.
2. **Prompt-Wish Poison:** Asking the model to "remember X" instead of enforcing it via lint, script, or hook ("Write It Twice").
3. **Verification-Weakening Poison:** Same-context self-grading, LLM confidence thresholds, or weakening base-branch `REVIEW.md`.
4. **Orchestration-Tax Poison:** Multi-agent graph complexity where one loop or deterministic script suffices.
5. **Cache & Smart-Zone Poison:** Mid-session effort toggles or raw tool dumps breaking prompt-cache reuse.
6. **Cross-File Disharmony:** Direct contradictions with existing playbooks, subsumption across candidates, or unpropagated skill/template updates.

---

## 4. Invariants & Edge Cases

- **Job Summary & Audit Observability:** Every run prints mode, `fast_lane_url`, `force`, extracted `title` + `body_chars`, every Stage 1/2/3 verdict row, and full sanitized Stage 3 synthesis prose (in both Job Summaries and `weekly-audits.md`).
- **SSRF-Safe Plan B & Accurate Wall Detection:** Every Plan B URL (`og:url`, `canonical`, external link, oEmbed, raw GitHub `blob/`) passes SSRF checks with at most `3` extra fetches. Wall detection ignores `<script>`/`<noscript>`/`<template>`, enforces paywall-truncation banners at any length, and gates interstitial/CAPTCHA stubs only on thin pages or wall `<title>`s.
- **Stage 0 Hygiene:** Pre-release tags (`filter_prereleases: true`) drop before Stage 1 or `seen_content_hashes`, Atom/RSS scanning reads past filtered bursts (`max(max_items * 5, 50)`), and single-word keywords use exact `\b...\b` boundaries.
- **No `seen.json` Burn or False Prune Flags on Non-Enforce Runs:** Manual `observe` fast-lane runs and `FETCH_INCOMPLETE` failures never burn `seen.json` or `stage2_staged`. `bootstrap` never inflates `items_fetched`, and `"0 human-merged items in window"` requires `>= 4` reconciled PRs or `>= 30` `enforce`-mode fetches.
- **Two-Tier Source Promotion (`$0` LLM, `0` Extra HTTP):** Scoped source keys (`github.com/<owner>/<repo>`, `x.com/@<handle>`, `medium.com/@<author>`, etc.), `source_domains` aliases, and passive `<link rel="alternate">` feed hints feed both `feed-health-report.md` (`>= 2` distinct merged or Stage 3-approved items in `90`d) and ephemeral Job Summary `Source Consideration` callouts (unsubscribed `serial_publisher`s at `1` fast-lane hit or `>= 2` aggregator hits). Automation never edits `radar/feeds.yaml`.
- **De-Anchored Stage 3 Input:** Python strips Stage 2 numeric scores and badges before building the Stage 3 prompt.
- **Cost & Zero-Tool Walls:** `tools=None` on Stage 3. `MAX_RUN_COST_USD` is `0.50` with `neon` pricing (`$3.00 / $0.15 / $15.00`) in `scripts/radar/config.py`.
- **Artifact & State Compatibility:** `pending-candidates.json`, `weekly-audits.md`, `feed-health.json`, and `seen.json` live on orphan branch `radar-state` with backward-compatible defaults (`extra="ignore"`).

---

## 5. Vertical Tracer-Bullet Tickets

### Ticket 1: Fast-Lane Plan B, `FETCH_INCOMPLETE` Gate & Rich Job Summary
- **Undo Tier:** `CLEANUP UNDO`
- **Scope:** Resolve `og:url` / `canonical` / external links + `publish.twitter.com/oembed` in `build_fast_lane_candidate`. Enforce `>= 600` chars and `>= 100` words, failing closed (`FETCH_INCOMPLETE`, exit `1` on dispatch) before LLM calls. Enrich `build_job_summary_markdown` with inputs, extracted sizes, and all Stage 1/2 verdict rows. Add `force` input and stop burning `seen.json` on `observe` fast-lane runs.
- **In Scope:** `scripts/radar/fetcher.py`, `scripts/radar/models.py`, `scripts/radar/state.py`, `scripts/radar/cli.py`, `.github/workflows/radar-ingest.yml`, `tests/radar/test_fetcher.py`, `tests/radar/test_pipeline_e2e.py`.
- **Out of Scope:** Weekly buffer persistence and Stage 3 Coherence Gate (`Tickets 2–3`).
- **Done When:**
  - `uv run ruff check scripts tests` and `uv run pytest -v` exit `0`.
  - An X stub with an embedded blog link follows Plan B to full text in offline tests.
  - A pure login wall exits non-zero as `FETCH_INCOMPLETE` with `0` LLM calls and `0` `seen.json` writes.
  - Job Summary markdown includes `fast_lane_url`, `body_chars`, and Stage 1 drop reasons.

### Ticket 2: Daily Holding Buffer (`pending-candidates.json`) & Weekly Cadence Split
- **Undo Tier:** `CLEANUP UNDO`
- **Scope:** Decouple Mon–Sat daily runs from PR creation. Daily runs buffer items scoring `>= 7/10` into `radar-state/pending-candidates.json` (zero PRs opened). Sunday runs (or `workflow_dispatch` with `run_coherence_gate=true`) drain the buffer into the weekly gate and clear it afterward.
- **In Scope:** `scripts/radar/models.py`, `scripts/radar/state.py`, `scripts/radar/cli.py`, `.github/workflows/radar-ingest.yml`, `tests/radar/test_pipeline_e2e.py`.
- **Out of Scope:** Stage 3 `gemini-4-neon` LLM prompt and systemic poison schema (`Ticket 3`).
- **Done When:**
  - `uv run ruff check scripts tests` and `uv run pytest -v` exit `0`.
  - Simulated Mon–Sat runs buffer `2` candidates cleanly in `pending-candidates.json` and open `0` PRs.
  - The Sunday run drains and clears the buffer.

### Ticket 3: Stage 3 Systemic Coherence Gate (`gemini-4-neon`, `HIGH`) & Fast-Lane Bypass
- **Undo Tier:** `CLEANUP UNDO`
- **Scope:** Implement `STAGE3_MODEL=gemini-4-neon` (`HIGH` thinking, `tools=None`, `MAX_RUN_COST_USD=0.50`, full-repo loader `~13K` tokens). Build score-blind Stage 3 prompt + Pydantic schema (`SUBSUMED_BY`, `CONFLICTS_WITH`, `COMPOUNDS_WITH`, `REJECT_ENTROPY`, `APPROVE_SYNTHESIS`, plus 6 Systemic Poison booleans). Route verified fast-lane URLs directly past Stage 1 into Stage 3. Write rejection audits to `radar-state/weekly-audits.md` and open a Draft PR only on `APPROVE_SYNTHESIS`.
- **In Scope:** `scripts/radar/config.py`, `scripts/radar/inventory.py`, `scripts/radar/models.py`, `scripts/radar/llm.py`, `scripts/radar/rubric.py`, `scripts/radar/cli.py`, `.github/workflows/radar-ingest.yml`, `docs/radar-setup.md`, `tests/radar/test_pipeline_e2e.py`, `tests/radar/fixtures/nov2026_replay.json`.
- **Out of Scope:** Antigravity local browser skill (deferred to [`todo.md`](../../todo.md)).
- **Done When:**
  - `uv run ruff check scripts tests`, `uv run pytest -v`, and `scripts/ste_lint.py` exit `0`.
  - E2E fixture test proves Stage 3 receives de-anchored inputs (no `7/10` strings) and full repo context.
  - Stage 3 rejects a "Prompt-Wish Poison" candidate with `0` PRs and logs to `weekly-audits.md`.
  - Stage 3 merges two compounding items into one unified synthesis Draft PR.
