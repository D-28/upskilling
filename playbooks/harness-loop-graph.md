# Harness, Loop, Graph: The Three-Layer Agent Architecture

> **Core axiom (`[C]`):** *"Environment, then feedback, then flow."*
> Stop fixing agent failures by rewriting prompts or adding `IMPORTANT` in ALL CAPS. Most failures belong to a specific infrastructure layer around the model (`[C]`, `[A]`).

---

## 1. Plain-English Overview

Prompt engineering, context engineering, skills, hooks, MCP, memory, subagents, and orchestration are not twelve separate hobbies—they collapse cleanly into **three architectural layers** (`[C]`):

```text
┌─────────────────────────────────────────────────────────────────────────┐
│ 3. GRAPH  (Coordination — what happens NEXT) [A, C]                     │
│    Multiple bounded nodes + real dependency edges + handoff state       │
│    (Only introduce when a single loop breaks!)                          │
│                                                                         │
│   ┌───────────────────────────────────────────────────────────────────┐ │
│   │ 2. LOOP  (Evidence — how the agent knows it's RIGHT) [C]          │ │
│   │    Trigger ─▶ Goal ─▶ Action ─▶ Real Check ─▶ Expected vs Saw     │ │
│   │    Exit on pass, retry cap, or same dead-end twice                │ │
│   │                                                                   │ │
│   │   ┌─────────────────────────────────────────────────────────────┐ │ │
│   │   │ 1. HARNESS  (Environment — what the agent CAN do) [C, E]    │ │ │
│   │   │    Contract (done_when) · Map (AGENTS.md) · <=10 Tools      │ │ │
│   │   │    Disk Memory (PROGRESS.md/git) · External Walls · Traces  │ │ │
│   │   │    (In prod: decoupled Brain vs sandboxed Hands + event log)│ │ │
│   │   └─────────────────────────────────────────────────────────────┘ │ │
│   └───────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

- **Harness (`environment`):** Everything left if you erase the LLM from your diagram. It makes the agent **capable** (`[C]`).
- **Loop (`evidence`):** The work-and-verification cycle with real pass/fail checks and hard exits. It makes the agent **honest** (`[C]`).
- **Graph (`coordination`):** How multiple bounded tasks/loops coordinate, parallelize, and isolate context. It makes multi-step work **organized** (`[A]`, `[C]`).

---

## 2. Layer 1 — Harness (Environment)

OpenAI hit slow early progress building a product with Codex and zero hand-written code—not because the model was weak, but because the environment was underspecified (`[C]`). Give the exact same weights a terminal, tests, project memory, and hard permissions, and output changes dramatically.

### The 6 Parts of a Real Harness (`[C]`)
1. **Contract (`done_when` first):** Turn every request into a finish line before acting.
   ```yaml
   goal:        fix login redirect loop (#482)
   inputs:      issue description, repo, error logs
   output:      reviewable pull request
   constraints: no schema changes; touch only auth/
   done_when:   new test reproduces the bug,
                same test passes after fix,
                full test suite exits 0
   ```
   Without `done_when`, an agent will quietly solve an easier version of the task and declare victory (`[C]`).
2. **Map (Not a Manual):** Root instruction files (`AGENTS.md` / `CLAUDE.md`) must stay short and route to deeper docs (`docs/architecture.md`, `docs/testing.md`, `docs/security.md`). **Context is an attention budget, not storage** (`[C]`). See [`templates/AGENTS.md.template`](../templates/AGENTS.md.template).
3. **Tools (≤ 10 Narrow Tools Beat 40 Overlapping Ones):** Every overlapping tool creates another way for the model to choose wrong. Each tool needs one crisp schema, a predictable return shape, an explicit failure state, and a permission tier (`READ FILES`, `RUN TESTS`, `WRITE FILES`, `NETWORK`, `DEPLOY`, `DELETE DATA`).
4. **Memory (Context Is RAM; Files & Git Are Disk):** Write current goal, failed attempts, known facts, next step, and a `"never"` list to `PROGRESS.md` and git commits so crashes, compaction, or handoffs preserve real state instead of blurry chat summaries (`[C]`).
5. **Walls (Permissions Enforced Outside the Model):** `"Please don't touch migrations/"` is a wish; a file permission or hook blocking writes to `migrations/` is a wall. **Never let the same component invent the plan, approve the risk, and execute the side effect** (`[C]`).
6. **Traces:** Log what context was loaded, which tools ran, diffs produced, tests executed, retries, and cost so failures become debugging inputs instead of mysteries.

### The "Write It Twice" Tactic (`[C]`)
Prose rules work until the day an agent ignores them. Write every critical invariant **twice**:
- **`GUIDE` (in `AGENTS.md`):** *"UI code must never query the database directly—call a service in `src/services/`."* (Explains *why* so the agent cooperates.)
- **`CHECK` (in CI / linter):** *Lint fails if `src/ui/**` imports `src/db/**`.* (Cannot be talked past.)

Over time, past incidents turn into permanent infrastructure that future agents (and newer models) cannot accidentally violate (`[C]`).

---

## 3. Layer 2 — Loop (Evidence)

Every tool-using agent already has an implicit `model → tool → result` loop. **Loop engineering** designs that cycle deliberately (`[C]`, `[A]`):

- **`TRIGGER`:** What starts it (failing test, ticket, `/loop` schedule)
- **`GOAL`:** Concrete target state (never `"keep improving"`)
- **`STATE`:** What survives into the next attempt (`dead_ends`, diff, trace)
- **`ACTION`:** Bounded edits/commands the agent may execute
- **`EVIDENCE`:** How correctness is proven
- **`FEEDBACK`:** Diagnostic delta explaining *why* it failed
- **`STOP`:** Hard exits regardless of model optimism

### The Evidence Hierarchy (`[C]`)
*"Don't loop on confidence, loop on evidence."* A loop is only as trustworthy as the weakest proof it accepts:

1. **Deterministic (Strongest):** Test suite exits `0`, typechecker/linter passes, schema validates, build succeeds.
2. **Observable:** Execution trace proves the real command/E2E flow actually ran (not mocked or skipped).
3. **Independent:** A reviewer or grader in a **separate context window** verifies against a rubric (`[B]`, `[C]`).
4. **Self-report (Weakest — Reject):** *"Looks good," "I'm confident," "All tests should pass now."*

Write the failing check **before** touching implementation code—if you cannot specify what red vs. green looks like, you do not understand the task yet (`[C]`).

### Structured Feedback & Hard Exits (`[C]`)
Never return just `"Red"` or a 400-line stack trace. Return actionable structure:

```text
FAILED     test_expired_session_redirect
EXPECTED   302 -> /login
SAW        302 -> /dashboard (auth/refresh.py:61)
FENCE      auth/refresh.py only
DEAD ENDS  middleware reorder (already failed)
```

And enforce **two exit conditions** (`[C]`, `[B]`):
1. **Retry cap** (e.g., max **3 repair rounds** `[B]`).
2. **Same-result-twice exit:** If `evidence.saw` matches an entry already in `state.dead_ends`, **break immediately and escalate to a human**. Getting the identical failure twice means the loop has stopped learning—either the agent is missing visibility in the Harness or the question itself is wrong.

---

## 4. Layer 3 — Graph (Coordination)

### When NOT to Use a Graph (`[A]`, `[C]`)
A loop is simply a **1-node graph with a self-edge** (`[A]`, `[C]`). Reaching for a multi-node graph too early doubles debugging complexity without improving capability (`[A]`), and putting a broken loop inside a graph just creates a more expensive broken system (`[A]`, `[C]`). **If you can collapse 5 nodes into 1 verified loop and lose nothing, do it (`[C]`).**

### When a Graph Earns Its Keep (`[A]`, `[C]`)
Reach for a graph only when one loop demonstrably breaks because:
1. Independent tracks should run **in parallel** rather than serially (`[A]`, `[C]`).
2. Sub-tasks need **isolated contexts, memory, or permissions** (e.g., separating writer from reviewer so the second step doesn't just echo the first step's assumptions) (`[A]`, `[C]`).
3. You need explicit, auditable handoffs and partial-retry gates (`[A]`, `[C]`).

### Two Concrete Graph Design Heuristics (`[C]`)
- **The Early-Start Test:** For every arrow `A → B` in your design, ask: *"What breaks if `B` starts before `A` finishes?"* If the answer is *"nothing"*, delete the arrow and parallelize. Example: auditing billing code can run in parallel with fixing the auth bug; opening the PR cannot (`[C]`).
- **The 4 Cuts:**
  1. **Split where things fail separately** (steps that break for different reasons deserve separate nodes).
  2. **Give every worker its own context** (four roles in one chat window is just one agent wearing four hats).
  3. **If the answer should never vary, make it deterministic code, not an LLM** (merging, sorting, deduping, counting, schema checks).
  4. **Freeze what passed** (mark passed node outputs read-only; if step 4 fails, rerun *only* step 4 with feedback—never rerun good work).

### Bridging to Production Runtimes (`[E]`)
When moving a graph/harness from a laptop CLI into production (e.g., Anthropic's **Claude Managed Agents** pattern `[E]`):
- **Decouple Brain from Hands:** Run reasoning/orchestration separately from ephemeral execution sandboxes.
- **Externalize Session State as an Append-Only Event Log:** Store every tool request/result outside both the model and sandbox container so long-horizon jobs survive crashes and resume cleanly (`[E]`, `[C]`).
- **Use Credential Vaults:** Inject secrets at the execution boundary so raw API keys never enter model context (`[E]`).

---

## 5. Risk Governance: Undo-Price Gating (`[C]`)

Never gate high-stakes actions on an LLM confidence score (`0.95`, `0.99`). Gate on **how expensive it is to undo a mistake** (`[C]`):

| Tier | Typical Changes | Required Gate |
|---|---|---|
| **`ONE-CLICK UNDO`** | Docs, unit tests, isolated single function | Ships on green deterministic checks |
| **`CLEANUP UNDO`** | Shared helpers, auth logic, schemas | Green checks + execution trace + independent second-context review |
| **`NO UNDO`** | Prod DB migrations, deletes, customer emails, money | **Mandatory human sign-off** (never an LLM confidence threshold) |

See [`templates/undo-price-gating.md`](../templates/undo-price-gating.md) for a copy-paste team/customer policy template.

---

## 6. Failure-to-Layer Diagnostic Matrix (`[C]`)

Check symptoms **from top to bottom** and fix the first matching layer:

| Symptom | Broken Layer | Concrete Fix |
|---|---|---|
| You copy-paste logs/commands between chat and terminal | **Harness (Tools)** | Give agent direct read-only tool / CLI access |
| Agent repeats approaches it already tried earlier | **Harness (Memory)** | Persist dead ends & state in `PROGRESS.md` / disk |
| Agent says `"Done!"` when feature/tests are broken | **Loop (Check)** | Require deterministic/E2E check before completion |
| Retries burn tokens repeating the exact same error | **Loop (Feedback + Exits)** | Emit `EXPECTED vs SAW`, cap retries at 3, add same-result-twice exit |
| Every step works, but the whole run takes forever | **Graph (Shape)** | Run the Early-Start Test and parallelize independent edges |
| One late failure forces everything to rerun from scratch | **Graph (Gates)** | Freeze passed node outputs as read-only; rerun only failed node |
| The exact same class of mistake returns every week | **All Layers (Learning)** | Turn the lesson into a Harness wall/tool, CI check, or Graph gate—never just a prompt sentence |

### 5 Mistakes That Kill Agent Systems (`[C]`)
1. **Building the graph too early** (draw 12 boxes before watching 1 loop succeed once).
2. **Same model/context writes and grades** (shared blind spots).
3. **"Keep trying" as a loop without exits** (an open tab on your token budget).
4. **Treating the harness as a junk drawer** (40 noisy tools instead of 10 crisp ones).
5. **Blaming the model** instead of fixing stale state, missing visibility, or missing exits.

---

## 7. Pre-Flight Checklist (`[C]`)

- **Harness:** `done_when` defined? Root `AGENTS.md` is a short map? Tools narrow with explicit failure states? State saved on disk/git? Running in sandbox/worktree? Tool calls traced?
- **Loop:** Failing check written before code? Feedback shows `EXPECTED` vs `SAW`? Retry cap & token budget enforced? Same-result-twice triggers human escalation?
- **Graph:** Tried single loop first? Every edge passed Early-Start Test? Each worker has isolated context? Passed nodes frozen? Gates priced by undo cost?

---

*Related: [`playbooks/verification-engineering.md`](verification-engineering.md) · [`templates/AGENTS.md.template`](../templates/AGENTS.md.template) · [`templates/undo-price-gating.md`](../templates/undo-price-gating.md)*
