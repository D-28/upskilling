---
name: grill-to-spec
description: Interview the user relentlessly before coding to resolve design ambiguities, persist domain language into GLOSSARY.md and decisions into ADRs, write a self-contained spec, and slice work into vertical tracer-bullet tickets sized for fresh sessions.
---

# Socratic Spec & Tracer-Bullet Slicing (`grill-to-spec`)

Use this skill when starting a new feature, non-trivial refactor, or ambiguous ticket—**before** writing implementation code. Its goal is to resolve all fuzzy requirements up front and save crisp artifacts to disk so implementation sessions stay in the LLM "Smart Zone" (under ~100K–150K tokens of context).

## Principles
1. **No vibe coding on fuzzy requirements.** Surface hidden edge cases, naming conflicts, failure modes, and data-model boundaries through focused questioning first.
2. **Persist decisions to disk.** Context windows are temporary RAM; `GLOSSARY.md`, Architecture Decision Records (ADRs), and written specs are durable disk memory.
3. **Slice vertically ("tracer bullets"), not horizontally.** Never create separate tickets for "build all DB tables", "build all APIs", "build all UI". Every ticket must cut a thin vertical slice end to end (schema + logic + interface + test) so it can be independently verified in one fresh session.

---

## Workflow

### Phase 1: Explore Existing Code & Docs
Before asking questions, inspect the repo briefly (`README`, relevant directories, existing `GLOSSARY.md`, `docs/adr/`, tests) so you do not ask questions the codebase already answers.

### Phase 2: Socratic Grill (One Decision Branch at a Time)
Interview the user systematically—covering **1–3 tightly focused questions per turn**, offering your recommended default when appropriate:
- **Scope & Non-Goals:** What is explicitly *out* of scope for v1?
- **Domain Language:** Are two words being used interchangeably? Pin down exact canonical names.
- **Data Model & Ownership:** Source of truth, invariants, migration/backfill rules, undo/delete behavior.
- **Edge Cases & Failure Modes:** Auth/permissions, empty/error states, concurrency, retries, idempotency.
- **Verification Target (`done_when`):** How will we prove end-to-end that each slice works?

Continue until no major ambiguity remains on the design tree.

### Phase 3: Write Durable Domain & Architecture Artifacts
Ask where docs live in the repo (or propose standard paths such as `docs/GLOSSARY.md`, `docs/adr/`, `docs/specs/`) and persist:
1. **`GLOSSARY.md` updates:** Canonical term, crisp definition, *"Not to be confused with"*, and code/module location.
2. **Lightweight ADR(s):** Context, decision, alternatives rejected, and consequences for non-obvious architectural choices.

### Phase 4: Write a Self-Contained Spec
Create a concise markdown spec containing:
- Goal & Non-Goals
- Key Domain Terms (referencing `GLOSSARY.md`) and ADRs
- Architecture / Data Flow summary
- Explicit invariants & edge-case behavior
- End-to-end `done_when` acceptance criteria

### Phase 5: Slice into Vertical Tracer-Bullet Tickets
Break the spec into ordered, minimal vertical slices (`Ticket 1`, `Ticket 2`, ...):
- Each ticket touches only what is needed to prove one real slice end to end (data → logic → UI/CLI/API → automated test).
- Each ticket must fit comfortably inside **one clean, fresh agent session** (Smart Zone) without needing prior chat history.
- For each ticket, include:
  - **Scope & In-Files**
  - **Out of Scope**
  - **Done When (Verification command / E2E assertion)**

### Phase 6: Context Reset Recommendation
Once the spec and tracer-bullet tickets are saved to disk, explicitly recommend **starting a fresh session / clearing context** before implementing Ticket 1 so the implementation agent begins with a clean attention budget.
