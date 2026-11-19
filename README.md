# Agentic Engineering Upskilling

A portable, cross-machine reference playbook and starter toolkit for leading-edge AI-assisted software engineering — geared toward **Senior SWE → Staff SWE** and **FDE / FDSE** trajectories, and designed to work across **Antigravity**, **GitHub Copilot CLI**, **Claude Code**, and **Codex**.

> **Why this repo exists:** Skills, hooks, and `AGENTS.md` files went mainstream in 2026. Being at the leading edge now means shifting from *prompt tweaking* to **systems engineering around the model**: attention-budget discipline, un-gameable verification loops, programmatic tool execution, layered failure diagnosis, and model/effort unit economics.

---

## The 2-Minute Big Picture

Everything in this repository connects into one end-to-end engineering pipeline:

```text
1. UPSTREAM CLARITY [G]               (Keep agents in the "Smart Zone")
   Vague Idea ──▶ Socratic Grill ──▶ GLOSSARY.md + ADRs ──▶ Spec + Vertical "Tracer-Bullet" Slices
                                                                    │
2. EXECUTION ARCHITECTURE [A, C, D, E]                              ▼
   ┌───────────────────────────────────────────────────────────────────────────┐
   │ HARNESS (Environment) [C]                                                 │
   │   Contract (done_when) + Map (AGENTS.md) + <=10 Narrow Tools              │
   │   Disk Memory (PROGRESS.md/git) + External Walls + Traces                 │
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
3. VERIFICATION, ECONOMICS & GOVERNANCE [B, C, F]                   ▼
   Base-Branch REVIEW.md ──▶ Observe->Enforce Gates ──▶ Undo-Price Approval ──▶ Merge & Prune
   (Never PR-editable)       (Commit verify stamps)     (Human signs NO-UNDO)    (Turn misses into checks)
```

---

## Suggested Reading Order (Start Here)

If you are opening this fresh without having read the original articles or watched the video, read in this order:

1. **[November 18, 2026 Digest (`radar/2026-11-18-digest.md`)](radar/2026-11-18-digest.md)** — Self-contained summaries and signal/noise verdicts for sources **A–G**, plus how they map to Staff SWE vs. FDE/FDSE work and Antigravity vs. GitHub Copilot CLI.
2. **[Harness, Loop, Graph (`playbooks/harness-loop-graph.md`)](playbooks/harness-loop-graph.md)** — The 3-layer mental model (**A, C, E**), "Write It Twice" enforcement, Early-Start Test, and the failure-to-layer diagnostic table.
3. **[Verification Engineering (`playbooks/verification-engineering.md`)](playbooks/verification-engineering.md)** — Why ~90% AI-authored code shifts humans to defining "done" and reviewing evidence (**B**): E2E, property, and differential tests, base-branch `REVIEW.md`, `observe → enforce` gates, and revert-based rule evals.
4. **[Model & Effort Economics (`playbooks/model-effort-economics.md`)](playbooks/model-effort-economics.md)** — Separating model choice from reasoning effort, failure diagnosis, prompt-cache hygiene, and tiered planner/subagent routing (**F, G**).
5. **[Programmatic Tooling, MCP & Managed Runtimes (`playbooks/programmatic-tooling-mcp.md`)](playbooks/programmatic-tooling-mcp.md)** — How Code Mode / workflow scripts eliminate tool-result bloat, MCP & hook security implications, enterprise limits, and decoupled Brain/Hands runtimes (**D, E, G**).
6. **Drop-in assets** — Copy or adapt `skills/`, `templates/`, and `hooks/` into real repositories.

---

## Repository Map

| Directory / File | Purpose | Primary Sources |
|---|---|---|
| **[`.gitignore`](.gitignore)** | Keeps OS junk, `.env` secrets, and `.scratch/` files out of commits | Hygiene |
| **[`radar/2026-11-18-digest.md`](radar/2026-11-18-digest.md)** | Signal/noise triage & self-contained notes for links **A–G** | A–G |
| **[`playbooks/harness-loop-graph.md`](playbooks/harness-loop-graph.md)** | 3-layer agent architecture, diagnostics, and Undo-Price Gating | A, C, E |
| **[`playbooks/verification-engineering.md`](playbooks/verification-engineering.md)** | Test hierarchy, anti-gaming review setup, empirical rule evals | B, C, G |
| **[`playbooks/model-effort-economics.md`](playbooks/model-effort-economics.md)** | Capability vs. effort tuning, cache hygiene, tiered routing | F, G |
| **[`playbooks/programmatic-tooling-mcp.md`](playbooks/programmatic-tooling-mcp.md)** | Code Mode / workflow scripts, MCP security, Brain/Hands runtimes | D, E, G |
| **[`skills/verify/SKILL.md`](skills/verify/SKILL.md)** | Portable runtime E2E verification loop with 3-strike escalation | B, C |
| **[`skills/grill-to-spec/SKILL.md`](skills/grill-to-spec/SKILL.md)** | Socratic grill → `GLOSSARY.md` + ADRs + spec + tracer-bullet slices | G |
| **[`skills/diff-review/SKILL.md`](skills/diff-review/SKILL.md)** | Base-branch `REVIEW.md` + diff-triggered checklist reviewer | B |
| **[`templates/AGENTS.md.template`](templates/AGENTS.md.template)** | Lean root map, `done_when` contract, "Write It Twice" table | B, C |
| **[`templates/REVIEW.md.template`](templates/REVIEW.md.template)** | Base-branch rubric, diff-triggered checks, empirical promotion policy | B |
| **[`templates/GLOSSARY-and-ADR.md`](templates/GLOSSARY-and-ADR.md)** | Domain glossary, lightweight ADR, and tracer-bullet ticket formats | G |
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

All skills under `skills/` follow the open **Agent Skills (`SKILL.md`)** directory convention so you can pull this repo once and reuse them across tools:

- **Antigravity:** Copy or symlink `skills/<skill-name>` into your project's skills directory or global agent skills directory (and pair `grill-to-spec` concepts with `/grill-me` and `/plan`, or `verify` with `/goal`).
- **GitHub Copilot CLI:** Copy or symlink `skills/<skill-name>` into `.github/skills/<skill-name>` (repo-scoped) or `~/.copilot/skills/<skill-name>` (user-scoped).
- **Claude Code:** Copy or symlink `skills/<skill-name>` into `.claude/skills/<skill-name>` (repo-scoped) or `~/.claude/skills/<skill-name>` (user-scoped).
- **Codex:** Reference `templates/AGENTS.md.template` as root `AGENTS.md` and load skills from your local skills directory.
