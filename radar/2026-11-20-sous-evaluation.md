# Tool Evaluation: `sous-io/sous` (Compiled Agent Configuration)

- **Captured:** `2026-11-20`
- **Revisit / Prune By:** `2027-02-18` (90 days — aligned with quarterly review in [`todo.md`](../todo.md))
- **Target Evaluated:** [`sous-io/sous`](https://github.com/sous-io/sous) (`@sous-io/sous` v1.1.2, Apache-2.0). Docs live at `https://sous.io/markdown/#/` and recipes at [`sous-io/sous-recipes`](https://github.com/sous-io/sous-recipes).
- **Status:** **Evaluated — Skip CLI adoption and hold 3 durable concepts in `radar/`.** Do **not** edit `playbooks/`, `skills/`, or `templates/` until real workflow friction validates these patterns.

---

## 1. Executive Verdict

- **Adopt the CLI today?** **No (`Skip / Watch`).** As of Nov 2026, `sous` is a **3-star, single-maintainer** tool (`1` contributor, `39` packages, `Node >= 22`). It has only **one production-tested harness** (Claude Code on Linux). Its Codex plugin is marked *"Untested"*, Windows is unsupported, and **GitHub Copilot CLI / Antigravity are not supported**. Its default of gitignoring compiled outputs also conflicts with cloud agents and base-branch CI checks.
- **Strict Signal Calibration (`todo.md` §3 rubric):** **5/10 overall.** It shows high engineering craft and zero hype. However, it is solo-maintained with no external production case studies or empirical agent evals.
- **Why it still earns a `radar/` note:** It highlights a real **org-scale Staff SWE problem** that frontier models do not eliminate. Teams still must distribute, parameterize, and version-pin agent configuration across dozens of repositories. It also clarifies where configuration tooling fits inside our **Harness / Loop / Graph** architecture.

---

## 2. Where `sous` Sits in the Harness / Loop / Graph Architecture

To avoid confusion about `sous`, first note what it is **not**. It is **not** a runtime agent, **not** a verification **Loop**, and **not** an orchestration **Graph**.

It sits **outside and before** the runtime stack as a **Layer 0: Pre-Flight Harness Provisioner**. It builds and validates Layer 1 (*Harness*) files on disk *before* any coding agent session starts:

```text
LAYER 0: PRE-FLIGHT HARNESS PROVISIONING  ◀── WHERE `sous` (OR COPIER / INSTALLERS) LIVES
  Runs at repo clone, setup, or template-upgrade time — ZERO involvement once agent starts.
  Inputs:  Central template/recipe repo + lockfile + repo vars + machine-local .env.local
  Outputs: Rendered Map (AGENTS.md/.claude/rules/), Skills (SKILL.md), Walls (settings.json)
                                      │
                                      ▼  (Hands off ordinary files on disk)
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│ LAYER 1: HARNESS (Environment — what the agent CAN do)                                    │
│   Contract (done_when) · Map (AGENTS.md) · Tools (<=10, TTY-free)                         │
│   Disk Memory (PROGRESS.md/git) · Walls (settings/hooks/permissions) · Traces             │
│   ┌─────────────────────────────────────────────────────────────────────────────────────┐ │
│   │ LAYER 2: LOOP (Evidence — verify, EXPECTED vs SAW, 3-strike / dead-end exits)       │ │
│   └─────────────────────────────────────────────────────────────────────────────────────┘ │
│   LAYER 3: GRAPH (Coordination — parallel isolated nodes ONLY when one loop breaks)       │
└───────────────────────────────────────────────────────────────────────────────────────────┘
```

### Feature-by-Feature Mapping Onto Our Harness

| `sous` Feature | Harness Component Touched | When It Runs | Practical Role |
|---|---|---|---|
| **LiquidJS `.tpl.md` + `@include`** | **Map** (`AGENTS.md` / `.claude/rules/`) & **Skills** (`SKILL.md`) | Build / provision time (Layer 0) | Strips irrelevant stack/compliance branches at compile time and injects repo-specific variables (`jiraKey`, `serviceName`, paths). |
| **`sous.lock.json` + recipe repos** | **Harness Supply Chain** | Provision / PR upgrade time (Layer 0) | Pins exact versions + SHA-256 content hashes of shared org skills/hooks so upstream updates arrive as reviewable PR diffs. |
| **`editor.edits` (surgical patches)** | **Walls** (`.claude/settings.json` permissions/hooks, `.gitignore`, `.mcp.json`) | Build / provision time (Layer 0) | Declaratively adds/removes specific JSON paths or marker-bounded blocks without clobbering repo-local settings; rolls back cleanly on unsubscribe. |
| **`assert: { maxBytes, maxTokens }`** | **Map** (*Write It Twice* CI gate) | Build / CI time (Layer 0) | Enforces hard byte/token ceilings on generated instruction files before bloat silently degrades sessions or hits harness truncation caps. |
| **CLI Law `L4` (non-interactive parity)** | **Tools** (Layer 1) | Agent runtime (Layer 1) | Ensures every interactive CLI prompt has a deterministic flag/arg and fails fast without a TTY instead of hanging the agent on stdin. |

---

## 3. Practical Use Cases: The 3-Tier Multi-Repo Scaling Ladder

Compile-time templating (`LiquidJS`, `Jinja`, `Copier`) helps in some multi-repo setups and hurts in others. The right choice depends on **repo ownership** and **combinatorial variance**:

| Tier | Practical Context | Best Approach | Why |
|---|---|---|---|
| **Tier 1 — Solo / FDE Hopping** | You touch 20+ repos you **don't fully own** (customer repos, partner services, OSS). | **User-scoped global skills** (`~/.claude/skills/`, `~/.copilot/skills/`, Antigravity global skills) + thin repo `AGENTS.md` + runtime discovery. | Zero repo footprint (you can't drop `.sous/` into customer repos). Modern models read `package.json` / `Makefile` / `AGENTS.md` in 1 tool call without needing `{{ testCommand }}` pre-compiled. |
| **Tier 2 — Small Team Sharing** | 1 team sharing static skills/review checklists across 2–10 owned repos. | **Synced plain `SKILL.md`** via a lightweight idempotent installer (`scripts/install-skills.sh`) or git-pinned copy. | Open `SKILL.md` works natively across Antigravity, Copilot CLI, Claude Code, and Codex with zero build step or indirection tax. |
| **Tier 3 — Org / Platform Scale** | Staff SWE / Platform team governing **dozens of owned repos** with high variance (**stack × compliance tier × harness format**). | **Compile-time templated config** (LiquidJS / Copier / Jinja) with **committed rendered outputs + CI drift check** (`--check`) + automated PR rollouts. | Strips irrelevant branches deterministically (`{% if compliance == 'hipaa' %}`), fans out security/review updates centrally without copy-paste drift, and emits per-harness paths from one source. |

### Concrete Day-in-the-Life Examples

1. **FDE onboarding onto a customer's legacy Python repo (Tier 1):**
   - *Do:* Clone the repo and immediately run your user-scoped `/grill-to-spec` and `/verify` skills. Let the agent discover `pytest` / `pyproject.toml` at runtime.
   - *Don't:* Introduce a template compiler or `.sous/` config into a repo you don't own long-term.
2. **Staff SWE rolling out a new Go + HIPAA diff-review rule across 35 microservices (Tier 3):**
   - *Do:* Maintain a central org template repo parameterized by `{ stack, compliance, serviceName }`. Render committed `AGENTS.md`, `REVIEW.md`, and `.github/skills/` across matching repos via automated PRs. Add a CI drift check so nobody forks generated sections silently. Non-Go / non-HIPAA repos never pay context tokens for rules that don't apply to them.
   - *Don't:* Gitignore the rendered files (breaks GitHub web browsing, cloud agents, and base-branch CI `REVIEW.md` loading).
3. **Developer noticing `AGENTS.md` creeping to 40 KB or an internal CLI hanging agents (Any Tier):**
   - *Do:* Add a 3-line CI byte-size check on `AGENTS.md` / `REVIEW.md` and add `--yes` / flag parity to internal CLIs. You get the value directly without adopting `sous`.

---

## 4. Highest-Signal Takeaways (Held for Future Promotion)

Keep these **in reserve** here rather than adding speculative prose to `playbooks/` or `templates/` today:

1. **The 3-Tier Multi-Repo Scaling Ladder + "Commit Rendered Outputs" Rule:**
   - Start with global self-adapting skills (Tier 1) or plain synced `SKILL.md` files (Tier 2). Use templated org config with **committed outputs and a CI drift check** at org scale (Tier 3).
2. **Automated Size/Token Budget Assertions on Context Files (`Write It Twice` for `AGENTS.md`):**
   - Pair *"keep root `AGENTS.md` short"* with a deterministic CI byte or token cap. Context bloat then fails CI before pushing sessions into the Dumb Zone.
   - *Concrete harness quirks documented by `sous` (snapshot as of Nov 2026):*
     - **Codex** silently truncates combined project instruction files at **32 KiB** (`project_doc_max_bytes`).
     - **Claude Code** loads `.claude/rules/*.md` alongside `CLAUDE.md` without silencing `AGENTS.md`. Adding a root `CLAUDE.md`, however, causes Claude Code to ignore `AGENTS.md`.
3. **Non-Interactive / TTY-Free CLI Parity for Agent Tools (`L4`):**
   - Give every interactive prompt in a tool or wrapper script a flag or argument equivalent. If run without a TTY, fail fast and print the exact non-interactive command. This prevents silent `stdin` hangs in agent loops.

---

## 5. Patterns Explicitly Rejected (Conflicts With This Repo)

| `sous` Pattern | Why We Reject It |
|---|---|
| **Gitignoring compiled `AGENTS.md` / `CLAUDE.md` / skills** | Breaks base-branch anti-gaming review (`REVIEW.md` read from `origin/main` in [`playbooks/verification-engineering.md`](../playbooks/verification-engineering.md)), GitHub code search, and cloud agents that clone without running local `post-checkout` Husky hooks. |
| **Monolithic always-loaded memories (`@memories/**/*.md` + `@#memories/**/*.md`)** | Encourages prompt bloat and fights progressive disclosure (*Map, Not a Manual* + *Smart Zone*). |
| **Repo-wide unsandboxed trust (`L6` warn-only posture)** | Trusting an external recipe repo authorizes arbitrary build handlers and scripts with full user permissions—conflicts with enterprise/FDE **Harness Walls** unless strictly internal, code-reviewed, and hash-pinned. |
| **Rigid `Laws > Goals > Specs > ADRs` auto-precedence** | Heavy solo-refactor ceremony; silently letting a higher doc tier override a lower one is riskier than our existing rule in [`templates/AGENTS.md.template`](../templates/AGENTS.md.template) (*flag contradictions explicitly to a human*). |
| **Indirection tax for solo/small-team repos** | Agents repeatedly try to edit generated files directly (forcing `sous` to inject a mandatory `core/sous-skills` bundle into every repo just to explain itself). |

---

## 6. Revisit & Promotion Triggers (`2027-02-18`)

- **Promote the 3 reserve patterns into `playbooks/` or `templates/` only if real work triggers them.** Examples include an agent hanging on an interactive CLI, `AGENTS.md` bloating past a cap, or managing 10+ owned repos.
- **Re-evaluate `@sous-io/sous` only if it adds multi-harness support** (`Copilot CLI`, tested `Codex`, `macOS/Windows`). Also require a committed-output CI mode and broader production adoption.
- **Otherwise:** Prune or archive this note during the `2027-02-18` quarterly review.
