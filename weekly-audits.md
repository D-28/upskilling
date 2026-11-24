# Weekly Coherence Gate Audit Log

Append-only log of Stage 3 (`gemini-4-neon`, `HIGH`) systemic coherence decisions, poison rejections, and approved syntheses on orphan branch `radar-state`.

---
<!-- radar-audit: 2026-W48 run_at: 2026-11-23T14:50:32.885825+00:00 -->
## 2026-W48 — `REJECT_ALL` (2026-11-23)

- **Run Timestamp:** `2026-11-23T14:50:32.885825+00:00` · **Mode:** `observe` · **Route:** `fast-lane`
- **Executive Summary:** Stage 3 rejects the sole candidate and approves zero repository changes. The DevArch landing page presents commercial marketing copy without code, benchmarks, or novel mechanics. Existing playbooks and templates already cover harness engineering, disk memory, ADRs, and Write It Twice guardrails. Adopting its 10-agent and 19-skill lifecycle wrapper adds orchestration tax and bloats our attention...

| Item ID | Title | Verdict | Systemic Poisons | Related IDs | Affected Files | Rationale |
|---|---|---|---|---|---|---|
| `fb48fc1ec835` | DevArch: AI-Assisted Development, Disciplined | `REJECT_ENTROPY` | `attention_budget_poison, orchestration_tax_poison, cross_file_disharmony` | `-` | `playbooks/harness-loop-graph.md, playbooks/verification-engineering.md, templates/AGENTS.md.template, templates/GLOSSARY-and-ADR.md` | This commercial landing page lacks implementation code, benchmarks, or actionable architecture beyond marketing summaries. Our baseline already covers harness engineering, Write It Twice checks, disk summaries, and AD... |

---

<!-- radar-audit: 2026-W48 run_at: 2026-11-24T03:37:42.670478+00:00 -->
## 2026-W48 — `REJECT_ALL` (2026-11-24)

- **Run Timestamp:** `2026-11-24T03:37:42.670478+00:00` · **Mode:** `observe` · **Route:** `fast-lane`
- **Executive Summary:** Reject all candidates. Item 042d9c07e588 pitches a paywalled product-management skill bundle using textbook first-principles analogies. It provides zero code, deterministic checks, evaluations, or engineering mechanisms. Adopting it triggers attention-budget bloat, prompt-wish reliance, and overlap with existing spec-grilling workflows. No repository files require changes.

| Item ID | Title | Verdict | Systemic Poisons | Related IDs | Affected Files | Rationale |
|---|---|---|---|---|---|---|
| `042d9c07e588` | George from 🕹prodmgmt.world on X: "/first-principles: the key skill for PMs" / X | `REJECT_ENTROPY` | `attention_budget_poison, prompt_wish_poison, cross_file_disharmony` | `-` | `skills/grill-to-spec/SKILL.md, playbooks/harness-loop-graph.md` | This promotional post sells a paywalled bundle of 200+ product-management skills with zero concrete implementation or verification. Asking an agent to apply first principles via prose triggers prompt_wish_poison and attention_budget_poison. Constraint decomposition already belongs in skills/grill-to-spec/SKILL.md. Bundling 200+ skills contradicts the narrow-tool discipline in playbooks/harness-loop-graph.md. |

---

<!-- radar-audit: 2026-W48 run_at: 2026-11-24T15:52:32.876838+00:00 -->
## 2026-W48 — `REJECT_ALL` (2026-11-24)

- **Run Timestamp:** `2026-11-24T15:52:32.876838+00:00` · **Mode:** `observe` · **Route:** `fast-lane`
- **Executive Summary:** Stage 3 rejects the single fast-lane candidate and approves zero repository changes. The submitted URL points to the Uber Engineering homepage index instead of a specific technical article. Its marketing copy, hiring banners, and two-sentence teasers lack concrete architectures, failure modes, or enforceable invariants. Submit individual article URLs for MCP Gateway or Software Factory economics to evaluate concrete patterns.

| Item ID | Title | Verdict | Systemic Poisons | Related IDs | Affected Files | Rationale |
|---|---|---|---|---|---|---|
| `1fdab550328d` | Uber Engineering — Where the Digital World Meets the Physical One | `REJECT_ENTROPY` | `attention_budget_poison` | `-` | `playbooks/programmatic-tooling-mcp.md, playbooks/model-effort-economics.md` | This page is a landing directory containing job postings, marketing copy, and two-sentence post summaries. Mentions of MCP Gateway, Code Mode, and prompt caching lack concrete architecture details or failure modes. Existing playbooks already cover Code Mode, MCP gateways, and cache hygiene in greater depth. Adopting claims from teaser blurbs triggers attention budget poison without sharpening any repository invariant. |

---

<!-- radar-audit: 2026-W48 run_at: 2026-11-24T16:14:24.446419+00:00 -->
## 2026-W48 — `REJECT_ALL` (2026-11-24)

- **Run Timestamp:** `2026-11-24T16:14:24.446419+00:00` · **Mode:** `observe` · **Route:** `fast-lane`
- **Executive Summary:** Stage 3 rejects the single fast-lane candidate and approves zero syntheses. The T3 Code tutorial adds heavy multi-agent orchestration tax and relies on prompt-only guardrails. It also promotes self-judged goals and conflicts with existing playbooks and ADR-0001.

| Item ID | Title | Verdict | Systemic Poisons | Related IDs | Affected Files | Rationale |
|---|---|---|---|---|---|---|
| `5cb0b0021d6c` | Codez on X: "T3 Code: build ai agent teams with all frontier models (Full-Course)" / X | `REJECT_ENTROPY` | `attention_budget_poison, prompt_wish_poison, verification_weakening_poison, orchestration_tax_poison, cross_file_disharmony` | `-` | `playbooks/harness-loop-graph.md, playbooks/verification-engineering.md, playbooks/programmatic-tooling-mcp.md, templates/AGENTS.md.template, docs/adr/0001-coherence-gate-and-fast-lane.md` | This T3 Code tutorial triggers five Systemic Poisons. It mandates a five-agent team on every project instead of proving one loop first. It enforces read-only review and file fences through prompt wishes rather than hooks or sandboxes. Its /goal command lets agents self-judge completion. Adding TEAM.md and exposing a laptop MCP server to a cloud bot also contradicts existing playbooks and ADR-0001. |

---

<!-- radar-audit: 2026-W48 run_at: 2026-11-24T18:32:29.520736+00:00 -->
## 2026-W48 — `REJECT_ALL` (2026-11-24)

- **Run Timestamp:** `2026-11-24T18:32:29.520736+00:00` · **Mode:** `observe` · **Route:** `fast-lane`
- **Executive Summary:** Reject candidate c04b8ea7540c because the repository baseline already captures its full architecture. Playbooks and templates already contain the three-layer model, bug #482 examples, Early-Start Test, and Undo-Price Gating. Merging this duplicate material would bloat the context attention budget without adding a new invariant. Keep the baseline unchanged. Open no pull request.

| Item ID | Title | Verdict | Systemic Poisons | Related IDs | Affected Files | Rationale |
|---|---|---|---|---|---|---|
| `c04b8ea7540c` | m4lka on X: "Harness, Loops, Graphs: What Each Layer Fixes and What It Breaks" / X | `SUBSUMED_BY` | `attention_budget_poison` | `-` | `playbooks/harness-loop-graph.md, templates/undo-price-gating.md` | The repository baseline already covers every concept and example in this article. playbooks/harness-loop-graph.md contains the exact bug #482 contract, structured feedback template, Early-Start Test, 4 Cuts, and 7-row diagnostic matrix. templates/undo-price-gating.md already enforces Undo-Price Gating outside the model. Adding the article's 7-level labels would repeat existing rules and waste attention budget. |

---
