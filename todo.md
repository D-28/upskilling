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
- [x] **Cross-machine installer (`scripts/install-skills.sh`):** Built [`scripts/install-skills.sh`](scripts/install-skills.sh) (macOS/Linux-safe, idempotent) to symlink or `--copy` [`skills/*/`](skills/verify/SKILL.md) into Antigravity (`~/.gemini/jetski/skills` / `.agent/skills`), GitHub Copilot CLI (`~/.copilot/skills` / `.github/skills`), Claude Code (`~/.claude/skills` / `.claude/skills`), and custom `--target` paths (e.g. Codex), with `--dry-run`, `--scope user|repo`, `--force`, `--uninstall`, and automated tests in [`tests/test_install_skills.py`](tests/test_install_skills.py).
- [ ] **Stress-test `/verify` (`[B]`):** Trial [`skills/verify/SKILL.md`](skills/verify/SKILL.md) on a real personal project in Antigravity (using Chrome DevTools MCP or local API checks) and refine a Copilot CLI-friendly adaptation for work repos.
- [ ] **Roll out `observe`-mode commit gate (`[B]`):** Test the `.githooks/commit-msg` starter script from [`hooks/verify-gate-observe.md`](hooks/verify-gate-observe.md) in `observe` mode on a real repo, measure false positives, and test toggling `enforce` with the 2-block escape hatch.
- [x] **Code-Mode-style helper wrappers (`[D]`):** Built stdlib-only [`scripts/diff_context.py`](scripts/diff_context.py) (base-branch `REVIEW.md` diff-trigger matcher + `NO UNDO` workflow detector) and [`scripts/test_summary.py`](scripts/test_summary.py) (bounded pytest / JUnit XML JSON summary wrapper), tested in [`tests/test_wrappers.py`](tests/test_wrappers.py).
- [x] **Runnable property & differential test starters (`[B]`):** Added runnable Python (`Hypothesis`) and copy-paste TypeScript (`fast-check`) starters under [`examples/testing/`](examples/testing/README.md) covering round-trip, idempotency, invariant preservation, and differential legacy-vs-refactored equivalence (wired into CI `pytest`).
- [x] **Base-branch `REVIEW.md` CI workflow example (`[B]`):** Activated root [`REVIEW.md`](REVIEW.md) (wired into [`.github/workflows/radar-ci.yml`](.github/workflows/radar-ci.yml)) and added reusable [`examples/workflows/base-branch-review.yml`](examples/workflows/base-branch-review.yml) loading `REVIEW.md` strictly from `origin/<base_ref>`.

---

## 3. Flagship Build Plan: Automated Signal Ingestion Pipeline

Goal: catch leading-edge agentic engineering shifts within ~24h without X-scrolling noise, alert fatigue, or `radar/` bloat—dogfooding [`playbooks/harness-loop-graph.md`](playbooks/harness-loop-graph.md), [`playbooks/verification-engineering.md`](playbooks/verification-engineering.md), [`playbooks/model-effort-economics.md`](playbooks/model-effort-economics.md), [`playbooks/programmatic-tooling-mcp.md`](playbooks/programmatic-tooling-mcp.md), and [`templates/undo-price-gating.md`](templates/undo-price-gating.md).

### Locked Design Decisions
- [x] **Execution runtime & LLM billing:** GitHub Actions `cron` + billed **Gemini Developer API** key (paid tier for data privacy; defaults to `gemini-flash-lite-latest` (`LOW`) for Stage 1, `gemini-flash-latest` (`HIGH`) for Stage 2, and `gemini-4-neon` (`HIGH`) for Stage 3 over `v1beta` with `response.model_version` trace logging and `$0.50/run` cap, overridable via repo vars `STAGE1_MODEL` / `STAGE2_MODEL` / `STAGE3_MODEL`).
- [x] **Ingestion vs. review cadence:** Mon–Sat daily sweeps buffer survivors (`score >= 7/10`) in `radar-state/pending-candidates.json` (`0` PRs). Sunday runs (or `run_coherence_gate=true`) drain the buffer into the Stage 3 `gemini-4-neon` Coherence Gate, defaulting to `REJECT_ALL` (`weekly-audits.md`, `0` PRs) and opening **one weekly Draft PR** only on `APPROVE_SYNTHESIS` (`high-signal` label if score `>= 9/10`).
- [x] **Source coverage:** Scrape-free primary feeds + **curated aggregators** (HN Algolia API with score/keyword threshold, Simon Willison linklog RSS, Addy Osmani Substack RSS) + **owner-only `workflow_dispatch` fast-lane** with Plan B resolution, `FETCH_INCOMPLETE` fail-closed gate, and direct Stage 3 routing.
- [x] **Feed-list governance:** `radar/feeds.yaml` on `main` is strictly human-edited (never auto-mutated by untrusted web input); recurring unsubscribed domains are surfaced as promotion candidates after **≥ 2 human-merged items**.

### Phase 0 — Harness Contract, Scoring Rubric & Calibration Fixture (`[B]`, `[C]`, `[F]`)
- [x] Define `done_when` contract and deterministic per-run ceilings (`MAX_ITEMS_PER_RUN`, `MAX_HTTP_BYTES`, `MAX_STAGE2_SURVIVORS`, `MAX_ITEM_AGE_DAYS`, USD cost circuit breaker) in [`scripts/radar/config.py`](scripts/radar/config.py).
- [x] Codify the **deterministic 0–10 Signal Rubric** (2 hard gates + 5 discrete `0–2` dimensions summed in Python) in [`scripts/radar/rubric.py`](scripts/radar/rubric.py).
- [x] Create checked-in [`radar/feeds.yaml`](radar/feeds.yaml) covering official blogs/changelogs, GitHub Releases Atom + `CHANGELOG.md` fallback, and curated practitioner/HN feeds.
- [x] Build compact `REPO_INVENTORY` generator in [`scripts/radar/inventory.py`](scripts/radar/inventory.py).
- [x] Create offline **replay calibration fixture** (**A–H** + decoys) in [`tests/radar/fixtures/nov2026_replay.json`](tests/radar/fixtures/nov2026_replay.json).
- [ ] Run live calibration benchmark (`eval-fixture --live`) with `GEMINI_API_KEY` to confirm `gemini-flash-latest` (`HIGH`) meets recall/precision bars (or escalate `STAGE2_MODEL` to `gemini-pro-latest`).

### Phase 1 — Deterministic Stage 0 Fetcher, Sanitizer & State Store (`[C]` 4 Cuts #3, `[D]`)
- [x] Build deterministic Python Stage 0 fetcher, URL canonicalizer, cross-source deduper, patch-release filter, and SSRF-guarded Survivor Enricher in [`scripts/radar/fetcher.py`](scripts/radar/fetcher.py) and [`scripts/radar/security.py`](scripts/radar/security.py).
- [x] Implement backward-compatible `seen.json` & `feed-health.json` persistence on orphan branch `radar-state` in [`scripts/radar/state.py`](scripts/radar/state.py).

### Phase 2 — Zero-Tool Tiered Delta Filter & Prompt-Injection Walls (`[C]`, `[D]`, `[F]`)
- [x] Implement zero-tool batched Stage 1 (`gemini-flash-lite-latest`, `LOW`) and survivor-only Stage 2 (`gemini-flash-latest`, `HIGH`, mandatory `counterargument_to_drop`) with auto `v1beta` routing and `model_version` trace logging in [`scripts/radar/llm.py`](scripts/radar/llm.py).
- [x] Enforce Harness Walls: zero tools on LLM calls, strict JSON Schema + Markdown sanitization, and write restriction to `radar/*.md` only.

### Phase 3 — Fail-Closed Delivery, Safe Rollout (`observe → enforce`) & Fast-Lane Intake (`[B]`, [`templates/undo-price-gating.md`](templates/undo-price-gating.md))
- [x] Add 2-job privilege-separated GitHub Actions workflow ([`.github/workflows/radar-ingest.yml`](.github/workflows/radar-ingest.yml)) + CI workflow ([`.github/workflows/radar-ci.yml`](.github/workflows/radar-ci.yml)) + setup guide ([`docs/radar-setup.md`](docs/radar-setup.md)).
- [x] Configure `GEMINI_API_KEY` secret + *"Allow GitHub Actions to create and approve pull requests"* in GitHub repo settings and seed `radar-state` (`bootstrap` + scheduled/manual runs live).
- [ ] **2-week `observe` rollout (`[B]`):** Audit Actions Job Summaries and `radar-state/weekly-audits.md` for 2 weeks, tune thresholds/keywords if needed, then set repo variable `RADAR_MODE=enforce`.

### Phase 4 — Empirical Feed Health, Promotion & Pruning Loop (`[B]`, `[F]`)
- [x] Implement automated PR merge/close telemetry reconciliation and quarterly prune/≥2-hit promotion report generation ([`scripts/radar/reconcile_prs.py`](scripts/radar/reconcile_prs.py), [`scripts/radar/state.py`](scripts/radar/state.py)).
- [ ] Review first quarterly `feed-health-report.md` on `radar-state` and prune/promote sources manually in `radar/feeds.yaml`.

### Phase 5 — Weekly Coherence Gate (`gemini-4-neon`) & Fail-Closed Fast-Lane (`[C]`, `[G]`)
Spec & vertical tickets: [`docs/specs/coherence-gate-and-fast-lane.md`](docs/specs/coherence-gate-and-fast-lane.md) · [`docs/adr/0001-coherence-gate-and-fast-lane.md`](docs/adr/0001-coherence-gate-and-fast-lane.md) · [`docs/GLOSSARY.md`](docs/GLOSSARY.md).
- [x] **Ticket 1:** Fast-Lane Plan B resolution, `FETCH_INCOMPLETE` fail-closed gate, `force` / non-burning `observe` fast-lane, and rich GitHub Actions Job Summary tables (PR #9).
- [x] **Ticket 2:** Mon–Sat holding buffer (`radar-state/pending-candidates.json`) decoupling daily sweeps from Sunday weekly gate runs (PR #10).
- [x] **Ticket 3:** Stage 3 `gemini-4-neon` (`HIGH`) full-repo Coherence Gate (score-blind de-anchoring, 6 Systemic Poison checks, zero-PR default + `weekly-audits.md`, fast-lane Stage 1 bypass; PR #11 + live stress-test verified in run `#45198504002` + `800`/`500` render-cap polish in PR #12).
- [x] **Source-promotion tracking & pipeline audit hardening (PR #18):** Added Stage 0 hygiene, accurate wall detection, source-promotion domain tracking, full synthesis prose rendering, and workflow hardening.
- [ ] **Future consideration (if needed):** If Plan B repeatedly fails (`FETCH_INCOMPLETE`) on paywalled or X-Article links, add an Antigravity local browser/CLI fallback (`$0` marginal API spend using Google AI Pro/Ultra sub) that evaluates logged-in page text locally against the Coherence Gate.

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
- [x] **Tool evaluation — `https://sous.io/markdown/#/` ([`sous-io/sous`](https://github.com/sous-io/sous)):** Evaluated (`2026-11-20`) — **Skip for now.** It is a pre-flight template compiler (LiquidJS + lockfiles) for agent config, not a runtime harness/loop tool; today it is solo-maintained (3 stars, Linux + Claude Code only), its gitignored outputs break base-branch CI and cloud agents, and global user-scoped skills + runtime discovery already fit personal and customer repos better. *When it (or a Copier-style equivalent) could pay off one day:* governing **10+ org-owned repos** with varying stacks, compliance tiers (e.g., HIPAA), or harnesses—to deterministically strip irrelevant context at build time, push version-pinned rule/hook updates without copy-paste drift, and emit per-harness formats from one source (ideally with **committed rendered outputs + a CI drift check**).

---

## 5. Scheduled Maintenance & Pruning (`[B]`, `[F]`)

- [ ] **Quarterly review (`2027-02-18`):**
  - Re-evaluate [`radar/2026-11-18-digest.md`](radar/2026-11-18-digest.md) — promote proven items into `playbooks/` / `templates/`, archive or delete superseded notes.
  - Refresh the dated *"Snapshot as of November 2026"* model lineup in [`playbooks/model-effort-economics.md`](playbooks/model-effort-economics.md) and Code Mode constraints in [`playbooks/programmatic-tooling-mcp.md`](playbooks/programmatic-tooling-mcp.md).
  - Review `radar-state` feed-health telemetry and `weekly-audits.md` to prune stale, noisy, or broken sources from `radar/feeds.yaml`.
  - Prune unused rules or noisy checklist items across `skills/` and `templates/`.
