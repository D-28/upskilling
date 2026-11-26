# Automated Signal Ingestion Pipeline — Setup & Operations Guide

This guide covers enabling the two-job GitHub Actions pipeline (`.github/workflows/radar-ingest.yml`) safely on `D-28/upskilling`.

---

## 1. One-Time GitHub Repository Settings (2 Steps)

1. **Add your billed Gemini Developer API key:**
   - Go to **Settings → Secrets and variables → Actions → Secrets** and create `GEMINI_API_KEY`.
   - Use a **paid/billing-enabled** Google AI Studio API key so prompts and outputs stay excluded from model training. Daily runs cost pennies per month and are capped deterministically at `$0.50/run`.
2. **Allow GitHub Actions to open Draft PRs:**
   - Go to **Settings → Actions → General → Workflow permissions** and check **"Allow GitHub Actions to create and approve pull requests"**.
   - Automation **never** auto-merges to `main` and only writes to the orphan `radar-state` branch or `radar/*.md` inside Draft PRs.

---

## 2. Optional Repository Variables (No Code Edits to Tune Models or Mode)

Configure under **Settings → Secrets and variables → Actions → Variables**:

| Variable | Default | Purpose |
|---|---|---|
| `RADAR_MODE` | `observe` | Rollout gate (`observe` writes Job Summary only; flip to `enforce` after 2-week calibration to open weekly Draft PRs). |
| `STAGE1_MODEL` | `gemini-flash-lite-latest` | Fast/cheap dynamic alias for batched Stage 1 triage (auto-routed to `v1beta`). |
| `STAGE1_THINKING` | `LOW` | Thinking level for Stage 1 (`LOW` keeps triage fast and cheap). |
| `STAGE2_MODEL` | `gemini-flash-latest` | Dynamic alias for Stage 2 deep delta rubric (survivors only; override with `gemini-pro-latest` or a pinned ID if needed). |
| `STAGE2_THINKING` | `HIGH` | Thinking level for Stage 2 deep delta evaluation. |
| `STAGE3_MODEL` | `gemini-4-neon` | Frontier model for the Sunday Stage 3 Coherence Gate and direct fast-lane audits (`tools=None`, `v1beta`). |
| `STAGE3_THINKING` | `HIGH` | Thinking level for Stage 3 full-repo coherence and Systemic Poison checks. |

Every run logs `response.model_version` in the Actions Job Summary. Check this log to inspect the exact backend snapshot resolved behind `-latest` aliases.

---

## 3. Recommended Rollout Sequence (`bootstrap → observe → enforce`)

1. **Day 1 — Seed `radar-state` at `$0` LLM cost (`bootstrap`):**
   - Go to **Actions → Automated Signal Radar Ingestion → Run workflow** and run with `mode = bootstrap`.
   - This step creates the orphan `radar-state` branch and marks current feed history as seen. Day 2 then processes only genuinely new posts.
2. **Weeks 1–2 — Calibrate in `observe` mode:**
   - Leave `RADAR_MODE` unset (defaults to `observe`). The pipeline logs Stage 0/1/2/3 verdicts, resolved models, and estimated costs into the Actions Job Summary without opening PRs.
   - Optional local benchmark against the ground-truth replay fixture (`tests/radar/fixtures/nov2026_replay.json`):
     ```bash
     # Verify 0% false-positive bloat with all current playbooks present
     GEMINI_API_KEY=... uv run python -m scripts.radar.cli eval-fixture --live

     # Verify high recall when a playbook is withheld
     GEMINI_API_KEY=... uv run python -m scripts.radar.cli eval-fixture --live \
       --withhold playbooks/verification-engineering.md
     ```
3. **Week 3+ — Enable `enforce` mode:**
   - Set repository variable `RADAR_MODE = enforce`.
   - Mon–Sat runs buffer Stage 2 survivors (`>= 7/10`) in `radar-state/pending-candidates.json` and open `0` PRs.
   - Sunday runs (or `workflow_dispatch` with `run_coherence_gate = true`) drain the buffer into Stage 3 (`gemini-4-neon`, `HIGH`). Stage 3 loads the full repo baseline with de-anchored inputs and checks all six Systemic Poisons.
   - Stage 3 defaults to `REJECT_ALL`, logs every audit to `radar-state/weekly-audits.md`, and opens `0` PRs on quiet weeks. If Stage 3 emits `APPROVE_SYNTHESIS`, Job 2 opens or updates one weekly Draft PR (`radar/weekly-YYYY-Www`).

---

## 4. Manual Fast-Lane Triage (Ad-Hoc X / Blog Links)

When you spot a high-signal X thread, GitHub file, or article manually, trigger `workflow_dispatch` with `fast_lane_url = https://...`. Plan B resolves canonical links, raw GitHub `blob/` text, or public oEmbed text and enforces `>= 600` chars and `>= 100` words. If a page hits a login or paywall banner, the run exits non-zero as `FETCH_INCOMPLETE` at `$0` LLM cost. Verified articles bypass Stage 1 directly into Stage 3 (`gemini-4-neon`, `HIGH`). Use `force = true` to re-evaluate a URL already present in `seen.json`. Access stays restricted to repository maintainers.

---

## 5. Operational Notes & Quarterly Maintenance

- **GitHub Actions 60-day inactivity limit:** GitHub disables `schedule` triggers on public repositories with no commits for 60 days. Merging any PR or running `workflow_dispatch` resets the clock.
- **Stage 3 audit log & Job Summaries:** Every Stage 3 run logs full approved synthesis prose in Job Summaries and `weekly-audits.md` on `radar-state`. Mid-week updates to an open weekly Draft PR also post a PR comment.
- **Feed health, pruning & source promotion:** Job 2 reconciles weekly Draft PRs and writes `feed-health-report.md` onto `radar-state`. Active prune or promotion candidates also append to Job 2's Step Summary. Unsubscribed sources with `>= 2` merged or Stage 3-approved items in `90` days show up with passive RSS/Atom hints. Job Summaries also emit a `Source Consideration` callout for unsubscribed serial publishers (`1` fast-lane or `>= 2` aggregator hits). Automation never edits [`radar/feeds.yaml`](../radar/feeds.yaml).
