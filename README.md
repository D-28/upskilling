# Agentic Engineering Upskilling

A portable, cross-machine reference playbook and starter toolkit for leading-edge AI-assisted software engineering — geared toward **Senior SWE → Staff SWE** and **FDE / FDSE** trajectories, and designed to work across **Antigravity**, **GitHub Copilot CLI**, **Claude Code**, and **Codex**.

> **Why this repo exists:** Skills, hooks, and `AGENTS.md` files went mainstream in 2026. Being at the leading edge now means shifting from *prompt tweaking* to **systems engineering around the model**: attention-budget discipline, un-gameable verification loops, programmatic tool execution, layered failure diagnosis, and model/effort unit economics.

---

## The 2-Minute Big Picture

Everything in this repository connects into one end-to-end engineering pipeline:

```text
1. UPSTREAM CLARITY [G, H]            (Keep agents in the "Smart Zone" & zero synonym drift)
   Vague Idea ──▶ Socratic Grill ──▶ GLOSSARY.md + ADRs ──▶ Spec + Vertical "Tracer-Bullet" Slices
                                                                    │
2. EXECUTION ARCHITECTURE [A, C, D, E, H]                           ▼
   ┌───────────────────────────────────────────────────────────────────────────┐
   │ HARNESS (Environment) [C, H]                                              │
   │   Contract (done_when) + STE-80 Map (AGENTS.md) + <=10 Narrow Tools       │
   │   Disk Memory (PROGRESS.md/git) + External Walls + Traces + ste_lint.py   │
   │   ┌─────────────────────────────────────────────────────────────────────┐ │
   │   │ VERIFIED LOOP (Evidence) [B, C]                                     │ │
   │   │   Action ──▶ Real Check (E2E / Property / Differential)             │ │
   │   │          ◀── Structured Feedback (Expected vs Saw + Dead Ends)      │ │
   │   │          ──▶ Escalate to human after 3 strikes or repeated dead end │ │
   │   └─────────────────────────────────────────────────────────────────────┘ │
   │   Programmatic Tooling [D]  ──▶ Filter noisy tool/MCP outputs in code     │
   │   Graph / Managed Runtime [A, C, E] ──▶ Split into parallel isolated      │
   │                                         nodes ONLY when one loop breaks   │
   └───────────────────────────────────────────────────────────────────────────┘
                                                                    │
3. VERIFICATION, COMPREHENSION, ECONOMICS & GOVERNANCE [B, C, F, H] ▼
   Base-Branch REVIEW.md ──▶ 4-Level Output Ladder ──▶ Undo-Price Approval ──▶ Merge & Prune
   (Never PR-editable)       (STE-80 -> Diagram ->     (Human signs NO-UNDO)   (Turn misses into checks)
                             Throwaway HTML)
```

---

## How to Digest This Repo (3-Pass Learn-by-Doing)

Don't read the repo front-to-back like a textbook—build the core mental frame first, then run hands-on reps:

1. **Pass 1 — Build the Coat Rack First (~15 min, no coding):**
   Read the ASCII diagram above + **[`playbooks/harness-loop-graph.md`](playbooks/harness-loop-graph.md)** first (skip the raw digest for now). Then take one recent frustrating agent run and use its **Failure-to-Layer Diagnostic Matrix** to pinpoint whether the Harness, Loop, or Graph broke.
2. **Pass 2 — Feel the Two Biggest Workflow Shifts Hands-On (2 short reps):**
   - *Upstream (Smart Zone + Slicing — `G`, `H`):* Run `/grill-me` or **[`skills/grill-to-spec/SKILL.md`](skills/grill-to-spec/SKILL.md)** on a real feature to produce a tiny `GLOSSARY.md` + 2 vertical tracer-bullet tickets, lint your `AGENTS.md` / `SKILL.md` rules with **[`scripts/ste_lint.py`](scripts/ste_lint.py)**, then **reset context into a fresh session** before implementing Ticket 1.
   - *Downstream (Runtime Verification & Review Bandwidth — `B`, `H`):* Run **[`skills/verify/SKILL.md`](skills/verify/SKILL.md)** so the agent boots and exercises the real app (not just unit mocks), use **[`skills/ste-clarity/SKILL.md`](skills/ste-clarity/SKILL.md)** to structure the PR walkthrough along the 4-Level Understanding Ladder, and seed **[`templates/REVIEW.md.template`](templates/REVIEW.md.template)** with 3–5 real diff triggers from your day job.
3. **Pass 3 — Architectural Judgment & Scenario Drill (~20 min):**
   Read **[`playbooks/model-effort-economics.md`](playbooks/model-effort-economics.md)** and **[`playbooks/programmatic-tooling-mcp.md`](playbooks/programmatic-tooling-mcp.md)**, then ask an agent to quiz you with a 10-minute Staff SWE / FDE troubleshooting scenario drill to lock in the failure modes.
4. **Reference Lookup:**
   Treat **[`radar/2026-11-18-digest.md`](radar/2026-11-18-digest.md)** as a searchable reference rather than mandatory linear reading (and watch only targeted primary clips if desired: **G** `0:40:15–0:57:50` and Isabella He's Managed Agents talk behind **E**).

---

## Repository Map

| Directory / File | Purpose | Primary Sources |
|---|---|---|
| **[`.gitignore`](.gitignore)** | Keeps OS junk, `.env` secrets, and `.scratch/` files out of commits | Hygiene |
| **[`todo.md`](todo.md)** | Backlog of concrete builds, Staff SWE / FDE research angles, and pruning dates | Roadmap |
| **[`docs/GLOSSARY.md`](docs/GLOSSARY.md)** | Canonical terms for the signal-ingestion pipeline (`Candidate Item`, `Pending Buffer`, `Coherence Gate`, `Systemic Poison`) | G, H |
| **[`docs/specs/coherence-gate-and-fast-lane.md`](docs/specs/coherence-gate-and-fast-lane.md)** | Spec & vertical tickets for the weekly `gemini-4-neon` Coherence Gate and fail-closed Fast-Lane (see **[ADR-0001](docs/adr/0001-coherence-gate-and-fast-lane.md)**) | B, C, G |
| **[`docs/radar-setup.md`](docs/radar-setup.md)** | Setup & operations guide for the two-job GitHub Actions signal pipeline ([`.github/workflows/radar-ingest.yml`](.github/workflows/radar-ingest.yml)) | B, C, F |
| **[`scripts/radar/`](scripts/radar/cli.py)** | Zero-tool Stage 0–3 signal ingestion pipeline (`radar/feeds.yaml`, `pending-candidates.json`, `weekly-audits.md`, SSRF/sanitization walls) | B, C, D, F |
| **[`radar/2026-11-18-digest.md`](radar/2026-11-18-digest.md)** | Signal/noise triage & self-contained notes for links **A–H** | A–H |
| **[`playbooks/harness-loop-graph.md`](playbooks/harness-loop-graph.md)** | 3-layer agent architecture, `STE-80` instruction grammar, diagnostics, Undo-Price Gating | A, C, E, H |
| **[`playbooks/verification-engineering.md`](playbooks/verification-engineering.md)** | Test hierarchy, anti-gaming review setup, empirical rule evals, 4-Level Understanding Ladder | B, C, G, H |
| **[`playbooks/model-effort-economics.md`](playbooks/model-effort-economics.md)** | Capability vs. effort tuning, cache hygiene, tiered routing | F, G |
| **[`playbooks/programmatic-tooling-mcp.md`](playbooks/programmatic-tooling-mcp.md)** | Code Mode / workflow scripts, MCP security, Brain/Hands runtimes | D, E, G |
| **[`skills/verify/SKILL.md`](skills/verify/SKILL.md)** | Portable runtime E2E verification loop with 3-strike escalation | B, C |
| **[`skills/grill-to-spec/SKILL.md`](skills/grill-to-spec/SKILL.md)** | Socratic grill → `GLOSSARY.md` + ADRs + spec + tracer-bullet slices | G |
| **[`skills/diff-review/SKILL.md`](skills/diff-review/SKILL.md)** | Base-branch `REVIEW.md` + diff-triggered checklist reviewer | B |
| **[`skills/ste-clarity/SKILL.md`](skills/ste-clarity/SKILL.md)** | Two-way `STE-80` clarity & Karpathy's 4-Level Understanding Ladder (`text → diagram → HTML → animation`) | H, B, C |
| **[`REVIEW.md`](REVIEW.md)** | Active base-branch diff-review rubric and diff-triggered reliability checklist for this repo | B, H |
| **[`scripts/ste_lint.py`](scripts/ste_lint.py)** | Deterministic `STE-80` linter (`--stats`, `--check`, `--json`) for `AGENTS.md` and `SKILL.md` | H, C, D |
| **[`scripts/diff_context.py`](scripts/diff_context.py)** | Stdlib-only git diff & base-branch `REVIEW.md` trigger-matching JSON wrapper | B, D |
| **[`scripts/test_summary.py`](scripts/test_summary.py)** | Stdlib-only pytest / JUnit XML bounded JSON summary wrapper (preserves exit code) | B, D |
| **[`scripts/install-skills.sh`](scripts/install-skills.sh)** | Cross-machine, idempotent installer (symlink or `--copy`) for `skills/*/` across Antigravity, Copilot CLI, Claude Code, and custom `--target` paths | Portability |
| **[`examples/`](examples/testing/README.md)** | Reusable base-branch review CI workflow ([`base-branch-review.yml`](examples/workflows/base-branch-review.yml)) and runnable Python/TS property & differential test starters | B, D |
| **[`templates/AGENTS.md.template`](templates/AGENTS.md.template)** | Lean root map, `done_when` contract, "Write It Twice" table, `STE-80` output contract | B, C, H |
| **[`templates/REVIEW.md.template`](templates/REVIEW.md.template)** | Base-branch rubric, diff-triggered checks (incl. `STE-80` rule checkability), empirical promotion | B, H |
| **[`templates/GLOSSARY-and-ADR.md`](templates/GLOSSARY-and-ADR.md)** | Domain glossary (ASD-STE100 Rule 1.11), lightweight ADR, and tracer-bullet ticket formats | G, H |
| **[`templates/undo-price-gating.md`](templates/undo-price-gating.md)** | Risk/approval matrix (`ONE-CLICK`, `CLEANUP`, `NO UNDO`) | B, C |
| **[`hooks/verify-gate-observe.md`](hooks/verify-gate-observe.md)** | `off → observe → enforce` commit gates, stamps, Code Mode hook notes | B, D |

---

## Durable vs. Fast-Moving Policy

The AI tooling landscape moves quickly. To keep this repo useful six months from now instead of accumulating stale model advice:

1. **Separate durable principles from dated snapshots.**
   - `playbooks/`, `skills/`, `templates/`, and `hooks/` hold **tool-agnostic engineering patterns** (verification hierarchies, context hygiene, failure-layer diagnostics, risk gating).
   - Any specific model names, pricing, or experimental CLI flags belong in `radar/` (or inside explicitly dated *"Snapshot as of YYYY-MM-DD"* blocks) with a revisit date.
2. **Prune aggressively (`[B]`).**
   - Rules, checklists, and Markdown docs only grow if left unchecked. Review `radar/` quarterly and either promote proven patterns into `playbooks/` / `templates/` or archive/delete stale notes.
3. **Public-repo hygiene.**
   - Never commit company-specific internals, host-local paths, API keys, or private URLs. Keep everything generic, reusable, and ready to pull onto any personal or work machine.

---

## Cross-Tool Portability Quickstart (`skills/`)

All skills under `skills/` follow the open **Agent Skills (`SKILL.md`)** directory convention so you can pull this repo once and install them across tools with [`scripts/install-skills.sh`](scripts/install-skills.sh) (macOS + Linux compatible, idempotent):

```bash
# Preview what will be symlinked (Antigravity, Copilot CLI, and Claude Code)
./scripts/install-skills.sh --dry-run

# Symlink all skills into user-level tool directories (default: --scope user --tool all)
./scripts/install-skills.sh

# Install into a specific project repo (.agent/skills, .github/skills, .claude/skills)
./scripts/install-skills.sh --repo-root /path/to/repo --tool copilot --tool claude

# Copy instead of symlinking, or install to a custom directory (e.g. Codex)
./scripts/install-skills.sh --copy --target ~/.codex/skills

# Cleanly remove symlinks and managed copies created by this repo
./scripts/install-skills.sh --uninstall
```

- **Antigravity:** `~/.gemini/jetski/skills/<skill>` (user) or `.agent/skills/<skill>` (repo) — pair `grill-to-spec` with `/grill-me` and `/plan`, or `verify` with `/goal`.
- **GitHub Copilot CLI:** `~/.copilot/skills/<skill>` (user) or `.github/skills/<skill>` (repo).
- **Claude Code:** `~/.claude/skills/<skill>` (user) or `.claude/skills/<skill>` (repo).
- **Codex / other tools:** Pass `--target <dir>` (or `--dir <dir>`), and reference `templates/AGENTS.md.template` as root `AGENTS.md`.

**Day-to-day usage notes:**
- **Clone into a permanent directory** (e.g. `~/upskilling` or `~/dev/upskilling`). Default symlink mode points to the clone's absolute path, so `git pull` updates existing skills immediately across all tools; only re-run `./scripts/install-skills.sh` when a *new* skill folder is added under `skills/`.
- **Moving the clone:** Re-run `./scripts/install-skills.sh --force` from the new path to relink stale symlinks.
- **Restricted symlinks / standalone copies:** Pass `--copy` instead (and re-run `--copy` after `git pull` to refresh managed copies).
- **Per-repo installs:** Passing `--repo-root <path>` automatically implies `--scope repo` and leaves your user-level `$HOME` directories untouched.
