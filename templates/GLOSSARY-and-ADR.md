# Domain Artifacts: Glossary, ADRs & Tracer-Bullet Tickets

> **Why these exist (`[G]`, `[C]`):** Context windows degrade past ~100K–150K tokens of noisy history (*the Dumb Zone*). Writing agreed domain terms, architecture decisions, and vertical slices to disk lets any fresh agent session implement cleanly from the **Smart Zone** without guessing or re-litigating decisions (`[G]`).

---

## 1. `GLOSSARY.md` Template (`[G]`)

Use this to prevent agents (and teammates) from calling the same concept three different names across schema, API, and UI.

```markdown
# Project Glossary

| Canonical Term | Definition | Not To Be Confused With | Code / Schema Location |
|---|---|---|---|
| **Workspace** | Isolated tenant boundary owning billing, members, and repos | **Project** (a repo/folder inside a Workspace) | `src/domain/workspace.ts` |
| **Verification Stamp** | Commit trailer (`Verified-By: ...`) recording checks run pre-commit | **CI Status** (remote GitHub check run after push) | `hooks/verify-gate-observe` |
| `<Term>` | `<1-sentence unambiguous definition>` | `<Near-synonym to forbid>` | `<File / table / module>` |
```

---

## 2. Lightweight ADR Template (`docs/adr/NNN-short-title.md`) (`[G]`)

Keep Architecture Decision Records to **one screen**—capture *why* a path was chosen so future agent sessions stop suggesting rejected alternatives.

```markdown
# ADR-NNN: <Short Decision Title>

- **Date:** YYYY-MM-DD
- **Status:** Proposed | Accepted | Superseded by ADR-XXX
- **Owners / Deciders:** <Names or roles>

## Context
<2-4 sentences describing the concrete constraint, trade-off, or problem forcing a choice.>

## Decision
<1-3 sentences stating clearly what we decided to do.>

## Alternatives Considered (and Why Rejected)
- **Option A:** <Brief summary> — Rejected because <concrete downside>.
- **Option B:** <Brief summary> — Rejected because <concrete downside>.

## Consequences & Guardrails
- **Enables:** <What gets simpler or faster>
- **Costs / Constraints:** <What we accept or must enforce via lint/test>
```

---

## 3. Vertical "Tracer-Bullet" Ticket Template (`[G]`, `[C]`)

Instead of horizontal tickets (*"Create all DB tables" → "Build all API routes" → "Build UI"*), slice **vertically** so every ticket cuts thin end to end, fits inside **one fresh session**, and has an unambiguous `done_when` check.

```markdown
# Ticket <N>: <Thin End-to-End Slice Title>

- **Parent Spec:** `<link to spec or ADR>`
- **Undo Tier:** `ONE-CLICK UNDO` | `CLEANUP UNDO` | `NO UNDO`

## Scope (What This Slice Proves)
<1-2 sentences describing the smallest real user/system slice from input -> persistence -> output.>

## In Scope (Allowed Fence)
- Schema / model: `<exact file(s)>`
- Logic / handler: `<exact file(s)>`
- Interface (UI / CLI / API): `<exact file(s)>`
- Tests: `<exact test file(s)>`

## Explicitly Out of Scope
- `<Feature, edge case, or UI polish deferred to Ticket N+1>`

## Done When (Verification Contract)
- [ ] Failing check/test written first reproducing target behavior `[C]`
- [ ] Deterministic checks pass: `<lint / typecheck / unit command>`
- [ ] End-to-end runtime verification passes: `<exact E2E / curl / CLI command + expected result>` `[B]`
```
