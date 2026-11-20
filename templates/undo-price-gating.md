# Undo-Price Gating Policy Template

> **Core rule (`[C]`):** Do **not** gate autonomous agent actions on LLM confidence scores (`0.95`, `0.99`). A model cannot reliably self-grade blind spots. Gate autonomy on **how expensive it is to undo a mistake (`[C]`, `[B]`)**.

---

## 1. The Three Undo Tiers (`[C]`)

| Tier | Undo Cost | Typical Examples | Required Verification & Approval Gate |
|---|---|---|---|
| **Tier 1: `ONE-CLICK UNDO`** | Trivial (`git revert`, zero external side effects) | Docs, comments, isolated unit/property tests, single pure helper function, feature-flagged inactive code | Green deterministic checks (lint, typecheck, unit/E2E) → can merge/ship cleanly (`[B]`, `[C]`) |
| **Tier 2: `CLEANUP UNDO`** | Moderate (reversing takes coordinated code/state cleanup) | Shared internal helpers, auth middleware refactors, public API contracts, backward-compatible schema additions, `AGENTS.md` updates | Green deterministic + E2E/property checks + recorded execution trace + **independent second-context review** against base-branch `REVIEW.md` (`[B]`, `[C]`) |
| **Tier 3: `NO UNDO`** | High / Irreversible (data loss, external blast radius, financial/security impact) | Production DB destructive migrations or drops, bulk data deletes, sending external emails/webhooks, billing/money movement, modifying CI/security gates or `REVIEW.md` (`[B]`, `[C]`) | **Mandatory explicit human sign-off** (dual human sign-off for CI/security gates `[B]`) + dry-run / differential test evidence where applicable. **Zero exceptions based on model confidence (`[C]`).** |

---

## 2. How to Apply This in Two Contexts

### A. Inside Engineering Teams (Staff SWE / Org Playbook) (`[B]`, `[C]`)
- **Stop treating a typo fix and a billing migration with the same ceremony (`[C]`).** Reviewing `ONE-CLICK UNDO` diffs line-by-line wastes senior bandwidth; direct human review energy toward `CLEANUP UNDO` trace audits and `NO UNDO` sign-offs (`[B]`, `[C]`).
- **Enforce separation of duties (`[C]`):** Never allow the agent that planned and wrote a `Tier 2` or `Tier 3` change to approve its own risk or modify its own `REVIEW.md` / CI checks (`[B]`, `[C]`).

### B. Inside Customer-Facing Production Agents (FDE / FDSE Playbook) (`[C]`, `[E]`)
Map every tool exposed to your production agent to one of the three tiers *before* writing prompts:
- **Read / Compute tools** → `ONE-CLICK UNDO` (allowed automatically inside sandbox).
- **Draft / Stage tools** (create draft PR, stage draft email, write to isolated staging table) → `CLEANUP UNDO` (allowed with validation + trace).
- **Commit / Send / Mutate Prod tools** (send customer message, issue refund, run destructive SQL, trigger deploy) → `NO UNDO` (enforced by **Harness Walls** outside the model `[C]`: tool returns a pending approval request that pauses until a human clicks approve).

### C. Unattended / Scheduled Runs (Fail-Closed Staging)
When a background or scheduled agent encounters a gated side effect with no human available, it must **fail closed**—never hang waiting for interactive approval and never bypass the gate. Deny the execution, write the prepared draft, diff, or payload to a staging/review queue, and surface it in the next interactive summary for explicit human sign-off.
