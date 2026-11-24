---
name: ste-clarity
description: Use when writing or auditing AGENTS.md, SKILL.md, REVIEW.md, or PR descriptions, or when explaining complex code, architecture, or diffs using Karpathy's STE-80 rules and 4-Level Understanding Ladder.
---

# STE-80 Clarity & 4-Level Understanding Ladder (`ste-clarity`)

Use this skill for two tasks. First, audit or rewrite agent instructions (`AGENTS.md`, `SKILL.md`, `REVIEW.md`). Second, structure technical explanations and PR walkthroughs for fast human review. Never apply STE rules to long-form essays or narrative blog posts.

## Core Rules (`STE-80`)

1. **One term per concept:** Use exact canonical names from `GLOSSARY.md`. Never rotate synonyms (such as `config`, `settings`, and `configuration`).
2. **One action per sentence:** Write one instruction per numbered step. Split compound actions into separate steps.
3. **Sentence length caps:** Keep instructions to `<= 20` words. Keep descriptions to `<= 25` words. Exclude code spans and paths from counts.
4. **Split, do not trim:** Divide long sentences into two sentences. Never delete conditions, exceptions, or rationale to meet a word limit.
5. **Condition first:** Put the trigger before the action: *"If the check fails, read the log."*
6. **Imperative mood & active voice:** Write *"Run the linter."* Do not write *"The linter should be run."*
7. **Zero filler:** Remove conversational padding (`"Great question"`, `"It is worth noting"`, `"in order to"`).
8. **Anti-authority-bias guardrail:** Clean prose can mask wrong facts. Tag unverified claims as `UNCONFIRMED` and cite execution evidence.

---

## Mode A: Structure Explanations (The 4-Level Understanding Ladder)

When explaining an architecture, algorithm, bug root cause, or PR diff, match the output format to the comprehension bottleneck:

| Level | Output Format | Use When the Question Involves... | Concrete Deliverable |
|---|---|---|---|
| **1** | **Controlled English (`STE-80`)** | Definitions, procedures, checklists, or PR summaries | Short active sentences, `GLOSSARY.md` terms, numbered steps |
| **2** | **Diagram (`Mermaid` / `SVG`)** | Component topology, data flow, state transitions, or call graphs | Labelled `mermaid` block or SVG instead of paragraphs |
| **3** | **Interactive HTML Artifact** | Parameter sensitivity, trade-off curves, or state exploration | Self-contained, discardable `.html` widget with sliders or toggles |
| **4** | **Procedural Explainer Animation** | Dynamics unfolding over time or spatial transformations | `Manim` or HTML5 Canvas animation script with step narration |

### Escalation Procedure
1. Classify the user's question by its primary comprehension bottleneck (facts, structure, parameters, or time dynamics).
2. Start at the lowest level that transfers understanding without forcing mental reconstruction.
3. If a paragraph describes more than three connected components, replace the paragraph with a Level 2 diagram.
4. If the user asks *"what happens when X changes"*, build a Level 3 throwaway interactive HTML page.
5. Apply `STE-80` rules to all text labels, captions, and summaries across every level.

---

## Mode B: Audit & Rewrite Agent Instructions (`AGENTS.md`, `SKILL.md`)

Unattended agents do not ask follow-up questions on ambiguous rules. They guess a reading and act. Follow this procedure to make instructions deterministically checkable:

### Step 1: Run the Deterministic Baseline Check
Run the bundled STE linter from this skill directory before editing:

```bash
python3 <skill-dir>/scripts/ste_lint.py --stats <target-file>
```

If Python 3 is unavailable, audit the file manually against the 8 Core Rules above.

### Step 2: Rewrite Violations Without Losing Meaning
1. Replace every semicolon outside code spans with a period.
2. Move buried triggers (`if`, `when`, `unless`) to the start of the sentence, followed by a comma.
3. Split compound instructions (`"Do A and then do B"`) into separate numbered steps.
4. Keep policy rationale as a separate descriptive sentence (`<= 25` words) right after the imperative rule.
5. Align all entity, file, and module names with `GLOSSARY.md`.

### Step 3: Verify Diff and Linter Score
1. Re-run `python3 <skill-dir>/scripts/ste_lint.py --stats --check <target-file>` and confirm zero errors.
2. Compare `git diff <target-file>` line by line to confirm no condition, exception, or path was dropped.
