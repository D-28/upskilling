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

- [ ] **Cross-machine installer (`scripts/install-skills.sh`):** Build an idempotent script that symlinks or copies [`skills/`](skills/verify/SKILL.md) into Antigravity, GitHub Copilot CLI (`.github/skills/` or `~/.copilot/skills/`), Claude Code (`.claude/skills/`), and Codex on any personal or work laptop.
- [ ] **Stress-test `/verify` (`[B]`):** Trial [`skills/verify/SKILL.md`](skills/verify/SKILL.md) on a real personal project in Antigravity (using Chrome DevTools MCP or local API checks) and refine a Copilot CLI-friendly adaptation for work repos.
- [ ] **Roll out `observe`-mode commit gate (`[B]`):** Test the `.githooks/commit-msg` starter script from [`hooks/verify-gate-observe.md`](hooks/verify-gate-observe.md) in `observe` mode on a real repo, measure false positives, and test toggling `enforce` with the 2-block escape hatch.
- [ ] **Code-Mode-style helper wrappers (`[D]`):** Create lightweight deterministic wrapper scripts (`scripts/`) that aggregate/filter noisy git, test, and API/MCP outputs into crisp JSON summaries—capturing [`playbooks/programmatic-tooling-mcp.md`](playbooks/programmatic-tooling-mcp.md) savings inside enterprise GitHub Copilot CLI environments where experimental Code Mode isn't available.
- [ ] **Runnable property & differential test starters (`[B]`):** Add minimal copy-paste examples of:
  - Property-based tests (`fast-check` for TS/JS, `Hypothesis` for Python) covering round-trip, invariant, idempotency, and equivalence.
  - Differential test harness comparing legacy vs. migrated implementations on sampled inputs.
- [ ] **Base-branch `REVIEW.md` CI workflow example (`[B]`):** Add a GitHub Actions workflow template demonstrating fetching `REVIEW.md` strictly from `origin/main` (never PR head) and running diff-triggered checks cleanly.

---

## 3. Research Angles by Career Track

### A. Staff SWE Track (Org-Wide Engineering Leverage)
- [ ] **Verification at scale (`[B]`):** How to roll out base-branch `REVIEW.md` + diff-triggered reliability checklists across multi-team monorepos without slowing down senior reviewers.
- [ ] **Empirical reviewer evals (`[B]`):** Design a lightweight metric loop tracking reverted PRs, maintainer rejections, and size-matched clean controls—plus the ≥2-PR / 3-agent-disprove rule promotion pipeline.
- [ ] **"Write It Twice" enforcement (`[C]`):** Catalog high-value architectural invariants (import boundaries, PII log redaction, test-skip bans) that should move out of prose `AGENTS.md` into deterministic lint/CI checks.
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

---

## 4. Scheduled Maintenance & Pruning (`[B]`, `[F]`)

- [ ] **Quarterly review (`2027-02-18`):**
  - Re-evaluate [`radar/2026-11-18-digest.md`](radar/2026-11-18-digest.md) — promote proven items into `playbooks/` / `templates/`, archive or delete superseded notes.
  - Refresh the dated *"Snapshot as of November 2026"* model lineup in [`playbooks/model-effort-economics.md`](playbooks/model-effort-economics.md) and Code Mode constraints in [`playbooks/programmatic-tooling-mcp.md`](playbooks/programmatic-tooling-mcp.md).
  - Prune unused rules or noisy checklist items across `skills/` and `templates/`.
