# Automated Signal Ingestion Pipeline — Setup & Operations Guide

This guide covers enabling the two-job GitHub Actions pipeline (`.github/workflows/radar-ingest.yml`) safely on `D-28/upskilling`.

---

## 1. One-Time GitHub Repository Settings (2 Steps)

1. **Add your billed Gemini Developer API key:**
   - Go to **Settings → Secrets and variables → Actions → Secrets** and create `GEMINI_API_KEY`.
   - Use a **paid/billing-enabled** Google AI Studio API key so prompts and outputs are excluded from model training. At this pipeline's volume, daily runs typically cost pennies per month (capped deterministically at `$0.25/run`).
2. **Allow GitHub Actions to open Draft PRs:**
   - Go to **Settings → Actions → General → Workflow permissions** and check **"Allow GitHub Actions to create and approve pull requests"**.
   - Automation **never** auto-merges to `main` and only ever writes to the orphan `radar-state` branch or `radar/*.md` inside Draft PRs.

---

## 2. Optional Repository Variables (No Code Edits to Tune Models or Mode)

Configure under **Settings → Secrets and variables → Actions → Variables**:

| Variable | Default | Purpose |
|---|---|---|
| `RADAR_MODE` | `observe` | Rollout gate (`observe` writes Job Summary only; flip to `enforce` after 2-week calibration to open rolling weekly Draft PRs). |
| `STAGE1_MODEL` | `gemini-flash-lite-latest` | Fast/cheap dynamic alias for batched Stage 1 triage (auto-routed to `v1beta`). |
| `STAGE1_THINKING` | `LOW` | Thinking level for Stage 1 (`LOW` keeps triage fast and cheap). |
| `STAGE2_MODEL` | `gemini-flash-latest` | Dynamic alias for Stage 2 deep delta rubric (survivors only; override with `gemini-pro-latest` or a pinned ID if needed). |
| `STAGE2_THINKING` | `HIGH` | Thinking level for Stage 2 deep delta evaluation. |

Every run logs `response.model_version` in the Actions Job Summary. Check this log to inspect the exact backend snapshot resolved behind `-latest` aliases.

---

## 3. Recommended Rollout Sequence (`bootstrap → observe → enforce`)

1. **Day 1 — Seed `radar-state` at `$0` LLM cost (`bootstrap`):**
   - Go to **Actions → Automated Signal Radar Ingestion → Run workflow** and run with `mode = bootstrap`.
   - This step creates the orphan `radar-state` branch and marks current feed history as seen. Day 2 then processes only genuinely new posts.
2. **Weeks 1–2 — Calibrate in `observe` mode:**
   - Leave `RADAR_MODE` unset (defaults to `observe`). The daily cron logs Stage 0/1/2 verdicts, resolved models, and estimated costs into the Actions Job Summary without opening PRs.
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
   - Quiet weeks stay silent (`0` PRs opened). If `>= 1` survivor scores `>= 6/10`, the job opens or updates one rolling weekly Draft PR (`radar/weekly-YYYY-Www`). If any item scores `>= 9/10`, the job adds the `high-signal` label.

---

## 4. Manual Fast-Lane Triage (Ad-Hoc X / Blog Links)

When you spot a high-signal X thread or article manually, trigger `workflow_dispatch` with `fast_lane_url = https://...`. Access is restricted to repository maintainers. Public GitHub `issues` are never wired to prevent external abuse.

---

## 5. Operational Notes & Quarterly Maintenance

- **GitHub Actions 60-day inactivity limit:** GitHub automatically disables `schedule` triggers on public repositories with no commits for 60 days. Merging any PR or running `workflow_dispatch` resets the clock.
- **Quarterly feed health & pruning:** Job 2 reconciles merged and closed weekly Draft PRs and writes `feed-health-report.md` onto the `radar-state` branch. The report flags dead or noisy feeds to prune. It also lists unsubscribed domains with `>= 2` human-merged items in `90` days for manual promotion to [`radar/feeds.yaml`](../radar/feeds.yaml).
