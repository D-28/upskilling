# Model & Effort Economics Playbook

> **Core takeaway (`[F]`, `[G]`):** Stop treating "switch to a smarter model" as your first button. Separate **capability ceiling (Model)** from **thinking budget (Effort)**, keep sessions in the **Smart Zone**, protect **prompt caches**, and delegate mechanical subagents down the cost curve.

---

## 1. Two Orthogonal Dials: Model vs. Effort (`[F]`)

| Dial | What It Controls | Cost / Latency Impact |
|---|---|---|
| **Model Tier** | Frozen weights: reasoning ceiling, world knowledge, long-horizon coherence | Changes per-token price & baseline speed |
| **Effort Level** (`low` → `medium` → `high` → `xhigh` → `max`) | Dynamic compute allocated to internal thinking, tool calls, and self-checks on a single turn | Scales thinking tokens & wall-clock time without switching weights |

**Rule of thumb (`[F]`):** Adjusting **effort** is usually a better *first* lever than swapping models.

---

## 2. Failure Diagnosis Decision Tree (`[F]`, `[G]`)

When an agent underperforms, diagnose *why* before burning retries on a bigger model:

```text
Agent output is unsatisfactory
  │
  ├──▶ Session already bloated (> ~100K-150K tokens of tool logs & dead turns)? [G]
  │      └─▶ YES: "Dumb Zone" drift -> Write state/spec to disk & RESET into a fresh session.
  │               (A bigger model in a polluted context still forgets constraints.)
  │
  ├──▶ Simple task, but model over-engineered, over-planned, or wrote bloat? [F]
  │      └─▶ YES: Turn EFFORT DOWN on the same model before downgrading tiers.
  │
  ├──▶ Right neighborhood, but rushed, skipped edge cases, or shallow plan? [F]
  │      └─▶ YES: Turn EFFORT UP one notch (e.g., medium -> high) on the same model.
  │
  └──▶ High/max effort still hits a conceptual wall on deep/ambiguous reasoning? [F]
         └─▶ YES: Upgrade MODEL TIER (e.g., Sonnet -> Opus -> Frontier).
```

---

## 3. Role-Based Tiered Routing Pattern (`[F]`, `[G]`)

Never lock a multi-step engineering workflow onto a single expensive model (`[F]`). Route by **ambiguity and blast radius**:

| Workflow Role | Recommended Tier | Typical Effort | Why |
|---|---|---|---|
| **Escalated Architect / Incident Commander** | Top Frontier Tier | High / Max | Open-ended, ambiguous problems where the daily driver hit a ceiling (`[F]`) |
| **Primary Planner & Complex Refactorer** | Heavy Reasoning Tier | Medium / High | Grilling, ADRs, multi-file architecture, long-horizon coding (`[F]`, `[G]`) |
| **Scoped Ticket Implementer & Reviewer** | Balanced Daily Driver | Medium | Implementing crisp vertical tracer-bullet specs & TDD loops (`[F]`, `[G]`) |
| **Mechanical Subagents** | Fast / Low-Cost Tier | Low / Medium | Repo search, log triage, extraction, classification, routing (`[F]`) |

### Snapshot as of November 2026 — Anthropic Lineup (`[F]`)

> *Dated reference block (captured `2026-11-18`; model names and prices evolve quarterly—keep the role table above durable and refresh this block when needed).*

- **Claude Fable 5.2** (~USD 8 / USD 40 per MTok): Frontier reasoning tier for highly ambiguous, long-horizon agentic work when Opus hits a wall (`[F]`). *(Restricted **Mythos 5.2** shares the architecture for specialized programs.)*
- **Claude Opus 5.5:** Recommended enterprise default starting point for complex software engineering and multi-step planning (`[F]`).
- **Claude Sonnet 5.5:** Balanced everyday coding workhorse against clear specifications (`[F]`).
- **Claude Haiku 5.5:** High-throughput, low-latency, low-cost tier for mechanical subagents and extraction pipelines (`[F]`).

---

## 4. Prompt Cache Hygiene (`[F]`, `[G]`)

1. **Don't toggle effort mid-session (`[F]`):** Depending on the provider/model, flipping effort settings inside an active thread can **invalidate your prompt cache**, silently turning cheap cached input reads into full-price re-prefills. Pick an effort setting intentionally at session start.
2. **Pair model/effort switches with phase boundaries (`[G]`, `[F]`):**
   - Phase 1 (Heavy tier + High effort): Run `grill-to-spec` → write `GLOSSARY.md`, ADRs, and tracer-bullet tickets to disk (`[G]`).
   - **Reset session** (stay in the Smart Zone `[G]`, fresh cache prefix).
   - Phase 2 (Balanced tier + Medium effort): Execute each ticket cleanly with `/verify` (`[B]`, `[G]`).
3. **Keep noisy outputs out of the cached prefix:** Large raw tool outputs poison both attention (`[G]`) and cache reuse—filter them externally (`[D]`).

---

## 5. Career Application Checklist

- **Staff SWE (Team Defaults):** Establish shared defaults so engineers don't burn quota running frontier tiers on mechanical search/formatting, while ensuring architectural specs use high-reasoning passes before ticket fan-out (`[F]`, `[G]`).
- **FDE / FDSE (Production Economics):** Instrument cost-per-resolved-task across Model × Effort pairs, keep prompt caches warm with stable system prefixes, and push subagent/extraction calls onto fast models before optimizing prompts (`[F]`).

---

*Related: [`playbooks/programmatic-tooling-mcp.md`](programmatic-tooling-mcp.md) · [`skills/grill-to-spec/SKILL.md`](../skills/grill-to-spec/SKILL.md)*
