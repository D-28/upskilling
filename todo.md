# Upskilling Backlog & Research Roadmap

A living tracker for ideas, hands-on experiments, toolkit upgrades, and Staff SWE / FDE-FDSE research angles to explore next.

---

## 1. Immediate Next Sessions (Start Here Fresh)

- [ ] Read [`README.md`](README.md) → [`radar/2026-11-18-digest.md`](radar/2026-11-18-digest.md) → [`playbooks/`](playbooks/harness-loop-graph.md) with fresh eyes.
- [ ] Pick **1–2 deep-dive topics** to unpack interactively and turn into concrete personal/work workflows.
- [ ] Watch targeted segments of Matt Pocock's walkthrough (`[G]`, `https://www.youtube.com/watch?v=jVBlkOF8sHk`), especially:
  - `0:04:42–0:25:36` — Socratic grilling → `GLOSSARY.md` + ADRs
  - `0:40:15` — Smart Zone vs. Dumb Zone context discipline
  - `0:48:30–0:57:50` — Splitting massive AI changes into reviewable stacked PRs
- [ ] Watch Anthropic's *"Ship your first Managed Agent"* talk by Isabella He (`[E]`) to inspect the Brain/Hands separation and append-only session event log model.

---

## 2. Repo & Toolkit Backlog (Concrete Builds)

- [x] **Two-way `STE-80` clarity skill & deterministic linter (`[H]`, `[C]`, `[D]`):** Built [`skills/ste-clarity/SKILL.md`](skills/ste-clarity/SKILL.md) (Karpathy's 4-Level Understanding Ladder + `STE-80` instruction audit) and [`scripts/ste_lint.py`](scripts/ste_lint.py) (`--stats`, `--check`, `--json`), refactoring all `skills/*/SKILL.md` and `templates/*` to `100%` STE compliance (`0` errors, `0` warnings).
- [ ] **Cross-machine installer (`scripts/install-skills.sh`):** Build an idempotent script that symlinks or copies [`skills/`](skills/verify/SKILL.md) into Antigravity, GitHub Copilot CLI (`.github/skills/` or `~/.copilot/skills/`), Claude Code (`.claude/skills/`), and Codex on any personal or work laptop.
- [ ] **Stress-test `/verify` (`[B]`):** Trial [`skills/verify/SKILL.md`](skills/verify/SKILL.md) on a real personal project in Antigravity (using Chrome DevTools MCP or local API checks) and refine a Copilot CLI-friendly adaptation for work repos.
- [ ] **Roll out `observe`-mode commit gate (`[B]`):** Test the `.githooks/commit-msg` starter script from [`hooks/verify-gate-observe.md`](hooks/verify-gate-observe.md) in `observe` mode on a real repo, measure false positives, and test toggling `enforce` with the 2-block escape hatch.
- [ ] **Code-Mode-style helper wrappers (`[D]`):** Create lightweight deterministic wrapper scripts (`scripts/`, extending the `--json` pattern in [`scripts/ste_lint.py`](scripts/ste_lint.py)) that aggregate/filter noisy git, test, and API/MCP outputs into crisp JSON summaries—capturing [`playbooks/programmatic-tooling-mcp.md`](playbooks/programmatic-tooling-mcp.md) savings inside enterprise GitHub Copilot CLI environments where experimental Code Mode isn't available.
- [ ] **Runnable property & differential test starters (`[B]`):** Add minimal copy-paste examples of:
  - Property-based tests (`fast-check` for TS/JS, `Hypothesis` for Python) covering round-trip, invariant, idempotency, and equivalence.
  - Differential test harness comparing legacy vs. migrated implementations on sampled inputs.
- [ ] **Base-branch `REVIEW.md` CI workflow example (`[B]`):** Add a GitHub Actions workflow template demonstrating fetching `REVIEW.md` strictly from `origin/main` (never PR head) and running diff-triggered checks cleanly.

---

## 3. Flagship Build Plan: Automated Signal Ingestion Pipeline

Goal: catch leading-edge agentic engineering shifts within ~24h without X-scrolling noise, alert fatigue, or `radar/` bloat—dogfooding [`playbooks/harness-loop-graph.md`](playbooks/harness-loop-graph.md), [`playbooks/verification-engineering.md`](playbooks/verification-engineering.md), [`playbooks/model-effort-economics.md`](playbooks/model-effort-economics.md), [`playbooks/programmatic-tooling-mcp.md`](playbooks/programmatic-tooling-mcp.md), and [`templates/undo-price-gating.md`](templates/undo-price-gating.md).

### Locked Design Decisions
- [x] **Execution runtime & LLM billing:** GitHub Actions `cron` + billed **Gemini Developer API** key (paid tier for data privacy; models parameterized via repo vars `STAGE1_MODEL` / `STAGE2_MODEL`).
- [x] **Ingestion vs. review cadence:** Daily sweep updating **one rolling weekly Draft PR** (silent no-op on null weeks; `high-signal` label if score ≥ 9/10).
- [x] **Source coverage:** Scrape-free primary feeds + **1–2 curated aggregators** (HN Algolia API with score/keyword threshold, Simon Willison linklog RSS, Addy Osmani Substack RSS) + **owner-only `workflow_dispatch` fast-lane** for ad-hoc X links.
- [x] **Feed-list governance:** `feeds.yaml` on `main` is strictly human-edited (never auto-mutated by untrusted web input); recurring unsubscribed domains are surfaced as promotion candidates after **≥ 2 human-merged items**.

### Phase 0 — Harness Contract, Scoring Rubric & Calibration Fixture (`[B]`, `[C]`, `[F]`)
- [ ] Define `done_when` contract and deterministic per-run ceilings (`MAX_ITEMS_PER_RUN`, `MAX_BYTES_PER_ITEM`, `MAX_STAGE2_SURVIVORS`, token/cost cap).
- [ ] Codify the **deterministic 0–10 Signal Rubric** (2 hard gates + 5 discrete `0–2` dimensions summed in Python, never free-form LLM vibes):
  - *Hard Gates (fail = instant drop):* **Net-New Delta** (not already covered in repo) + **Substance** (concrete code, evals, release diff, failure mode, or workflow primitive—not hype/opinion).
  - *Scored Dimensions (0–2 each):* **Delta Novelty**, **Durability / Tool-Agnosticism**, **Actionability** (maps to a concrete `playbooks/` / `templates/` / `skills/` / `hooks/` edit), **Evidence Quality**, and **Staff SWE / FDE-FDSE Career Leverage**.
  - *Thresholds:* `< 6` DROP · `6–8` STAGE into rolling Draft PR · `9–10` STAGE + `high-signal` label.
- [ ] Create checked-in `feeds.yaml` covering official engineering blogs/changelogs (Anthropic/`claude.dev`, GitHub/Copilot CLI, OpenAI/Codex, Google/Antigravity), GitHub `releases.atom` feeds, YouTube channel Atom feeds, and 2–4 curated practitioner RSS/HN feeds.
- [ ] Build a compact `REPO_INVENTORY` generator (~1.5–2K tokens summarizing existing coverage across `playbooks/`, `templates/`, `skills/`, and `todo.md`) so Stage 1 gets a stable, high-hit-rate prompt cache prefix without dumping the whole repo into context (`[F]`, `[G]`).
- [ ] Create an offline **replay calibration fixture** from [`radar/2026-11-18-digest.md`](radar/2026-11-18-digest.md) (**A–H**) + 3–5 known hype/redundant articles: verify 0% false-positive bloat against current `playbooks/`, high recall when a playbook is withheld, and benchmark **Gemini Flash (high thinking)** vs. **Gemini Pro** on Stage 2 (`[B]`, `[F]`).

### Phase 1 — Deterministic Stage 0 Fetcher, Sanitizer & State Store (`[C]` 4 Cuts #3, `[D]`)
- [ ] Build a deterministic Python Stage 0 script (0 LLM tokens) to fetch feeds with pinned URLs, strict HTTP timeouts, response size limits, HTML-to-text stripping, URL canonicalization (strip UTM/tracking params), and cross-source deduplication (`canonical_url` + content/title hash).
- [ ] Add deterministic release-noise filtering: drop patch-only bumps unless release notes match architectural keywords (`hook`, `MCP`, `skill`, `sandbox`, `code mode`, `effort`, `eval`, `agent`).
- [ ] Store deduplication and feed telemetry (`seen.json`, `feed-health.json`) on a dedicated **orphan `radar-state` branch** so `main` stays branch-protected and free of bot commit churn.

### Phase 2 — Zero-Tool Tiered Delta Filter & Prompt-Injection Walls (`[C]`, `[D]`, `[F]`)
- [ ] **Stage 1 (`STAGE1_MODEL`: Gemini Flash, Low Thinking, Zero Tools):** Triage bounded item excerpts against the cached `REPO_INVENTORY` prefix using strict JSON Schema verdicts (`ALREADY_COVERED:<file>`, `MODEL_RELEASE_FLUFF`, `MARKETING_REBRAND`, `NO_WORKFLOW_DELTA`, or `SURVIVOR`). Keep effort fixed across the batch to preserve prompt caching (`[F]`).
- [ ] **Stage 2 (`STAGE2_MODEL`: Gemini Flash High Thinking — escalate to Gemini Pro only if Phase 0 fixture shows a capability ceiling; Survivors Only, Zero Tools):** Pass bounded clean text + *only* the relevant playbook/template file(s); require a mandatory `counterargument_to_drop` falsification field before emitting the five `0–2` rubric scores (summed in Python), exact net-new gap, suggested ≤5-line refinement or `radar/` note, and Staff SWE / FDE takeaway.
- [ ] **Enforce Harness Walls (`[C]`, `[D]`):** Zero tools/shell/MCP enabled on any LLM call touching untrusted web content; strict JSON Schema validation + markdown/HTML sanitization in Python; restrict automated file writes strictly to `radar/` (never directly mutate `playbooks/`, `skills/`, `feeds.yaml`, `.github/workflows/`, or `main`).

### Phase 3 — Fail-Closed Delivery, Safe Rollout (`observe → enforce`) & Fast-Lane Intake (`[B]`, [`templates/undo-price-gating.md`](templates/undo-price-gating.md))
- [ ] Add headless GitHub Actions workflow (`schedule` + owner-only `workflow_dispatch` for ad-hoc X/URL triage—never allow untrusted public `issues` or `pull_request_target` triggers) with SHA-pinned actions and minimal `permissions`. Account for GitHub Actions' 60-day inactivity auto-disable.
- [ ] **Fail-closed staging (`CLEANUP UNDO`):** Open or update **one rolling Draft PR** only when ≥1 survivor scores ≥ 6/10; on null weeks, write a 1-line summary to the Actions Job Summary and update `radar-state` without opening any PR. Never auto-merge to `main`.
- [ ] **2-week `observe` rollout (`[B]`):** Run triage into Actions Job Summary only (no Draft PRs) for 2 weeks, inspect false positives/negatives, and tune thresholds before enabling Draft PR staging.

### Phase 4 — Empirical Feed Health, Promotion & Pruning Loop (`[B]`, `[F]`)
- [ ] Track per-feed outcome telemetry in `radar-state` (`items_fetched`, `stage1_survivors`, `stage2_accepted`, `human_merged`, `human_closed_rejected`, `consecutive_fetch_errors`, plus `unsubscribed_domain_hits` from aggregators/fast-lane merges).
- [ ] Generate a quarterly feed-health report flagging:
  - **Prune candidates:** feeds with **0 human-merged items in 90 days**, **>90% rejection rate**, or **≥3 consecutive fetch failures**.
  - **Promote candidates:** unsubscribed domains/authors with **≥ 2 human-merged items in 90 days** for optional manual addition to `feeds.yaml`.

---

## 4. Research Angles by Career Track

### A. Staff SWE Track (Org-Wide Engineering Leverage)
- [ ] **Verification at scale (`[B]`, `[H]`):** How to roll out base-branch `REVIEW.md` + diff-triggered reliability checklists + `STE-80` PR summaries across multi-team monorepos without slowing down senior reviewers.
- [ ] **Empirical reviewer evals (`[B]`):** Design a lightweight metric loop tracking reverted PRs, maintainer rejections, and size-matched clean controls—plus the ≥2-PR / 3-agent-disprove rule promotion pipeline.
- [ ] **"Write It Twice" enforcement (`[C]`, `[H]`):** Catalog high-value architectural invariants (import boundaries, PII log redaction, test-skip bans, `scripts/ste_lint.py` checks on `AGENTS.md`/`SKILL.md`) that should move out of prose into deterministic lint/CI checks.
- [ ] **Stacked diffs for high-velocity AI PRs (`[G]`):** Evaluate stacked-PR workflows (`gh` / Graphite / git worktrees) to keep human review manageable when agents write large slices.

### B. FDE / FDSE Track (Production Customer Systems)
- [ ] **Decoupled production agent runtimes (`[E]`, `[C]`):** Deep-dive Brain/Hands isolation, append-only external session event logs for crash recovery, and credential vaults keeping raw secrets out of model context.
- [ ] **Customer migration differential harnesses (`[B]`):** Standardize a reusable differential-testing playbook for customer legacy-to-modern migrations (output normalization + approved-diff tracking).
- [ ] **Enterprise governance & MCP security (`[D]`, `[C]`):** Study MCP gateway allowlists, script-aware `PreToolUse` inspection (`tool_input.code`), and Undo-Price Gating (`NO UNDO` human-in-the-loop approvals) inside regulated environments (HIPAA, ZDR, Bedrock/Vertex/Foundry).
- [ ] **Unit economics & SLA tuning (`[F]`):** Benchmark Model × Effort × Prompt-Cache hit rates across realistic FDE workloads (planning on heavy/frontier tiers vs. delegating subagents to fast tiers).

### C. Landscape Radar (Nov 2026 → Q1 2027)
- [ ] Track whether programmatic tool execution (**Code Mode** `[D]`) exits experimental status, expands beyond interactive CLI to IDE/SDK/Bedrock/Vertex/ZDR, or sees first-party adoption in GitHub Copilot CLI and Codex.
- [ ] Evaluate real-world reliability of long-running background loops (`/loop` `[C]`, `/goal`, Code Mode background scripts `[D]`) vs. structured `run_workflow` / `swarm` graphs.
- [ ] Watch for open standards converging around `SKILL.md`, hooks, and MCP tool-output filtering.
- [ ] **Tool evaluation — `https://sous.io/markdown/#/`:** Research what problem it solves and assess whether it offers practical merit or is redundant given late-2026 model capabilities and modern agent harnesses.

---

## 5. Scheduled Maintenance & Pruning (`[B]`, `[F]`)

- [ ] **Quarterly review (`2027-02-18`):**
  - Re-evaluate [`radar/2026-11-18-digest.md`](radar/2026-11-18-digest.md) — promote proven items into `playbooks/` / `templates/`, archive or delete superseded notes.
  - Refresh the dated *"Snapshot as of November 2026"* model lineup in [`playbooks/model-effort-economics.md`](playbooks/model-effort-economics.md) and Code Mode constraints in [`playbooks/programmatic-tooling-mcp.md`](playbooks/programmatic-tooling-mcp.md).
  - Review `radar-state` feed-health telemetry (once live) and prune stale, noisy, or broken sources from `feeds.yaml`.
  - Prune unused rules or noisy checklist items across `skills/` and `templates/`.
