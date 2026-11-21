# Programmatic Tooling, MCP & Managed Runtimes

> **Core shift (`[D]`, `[E]`, `[G]`):** Stop forcing LLMs to act as slow, expensive JSON pipes between tools. Let the agent write small **programs** (or call deterministic helpers) that execute, filter, and aggregate locally *outside* the context window (`[D]`, `[G]`), and decouple reasoning from sandboxed execution in production (`[E]`).

---

## 1. The Tool-Result Bloat Problem (`[D]`, `[G]`)

In traditional turn-by-turn tool use, every intermediate output lands directly in the model's context window:

```text
BEFORE: Sequential Turn-by-Turn Tool Calls (Burns Smart Zone & Latency) [D, G]
  Turn 1: rg "retryPolicy" src/        ──▶ dumps 400 lines into context
  Turn 2: read_file(fileA)             ──▶ dumps 600 lines into context
  Turn 3: read_file(fileB)             ──▶ dumps 500 lines into context
  Turn 4: mcp.github.list_prs()        ──▶ dumps 40KB JSON into context
  Turn 5: edit_file(...)               ──▶ model is now drifting in the Dumb Zone [G]

AFTER: Programmatic Tool Execution [D]
  Turn 1: Agent writes 1 JS/Python script in REPL/workflow:
            - runs searches & reads in parallel
            - calls MCP endpoints & filters/aggregates locally
            - performs edits or computes concise summary
          ──▶ ONLY the 12-line distilled summary enters model context!
```

Earlier features like **Tool Search** solved *schema bloat* (not loading 100 MCP tool definitions upfront). **Programmatic tool calling solves *output accumulation bloat*** (`[D]`).

---

## 2. Claude Code "Code Mode" — Architecture & Constraints (`[D]`)

Launched experimentally on **Nov 17, 2026** (`Claude Code v2.1.323+`, opt-in via `CLAUDE_CODE_EXPERIMENTAL_CODE_MODE=1` or `~/.claude/settings.json`):

- **How it runs:** Claude writes a single JavaScript script executed in a local REPL that chains `Bash`, `Read`, `Edit`, and MCP tools, fans out parallel work, and returns filtered output (`[D]`).
- **Background work:** In `auto` / `bypassPermissions` mode, Code Mode scripts can run in the background for **up to 2 hours** while you continue interacting (`[D]`). (Press `Ctrl+O` in the CLI to inspect collapsed generated code blocks.)
- **Sweet spots:** Multi-file bug tracing, repo-wide migrations/edits, and noisy MCP queries (`[D]`). No benefit on simple 1-file edits.

### Crucial Enterprise & Surface Caveats (`[D]` — Snapshot as of Nov 2026)
If you work in regulated or IDE-based environments, know what Code Mode does **not** support yet:
1. **Interactive terminal CLI only:** Not supported in VS Code panels, Desktop app, `-p` (print mode), Agent SDK, or cloud sessions (`[D]`).
2. **Feature conflicts:** Incompatible with **Agent Teams** (must be disabled in settings), and disables Remote Control, Claude in Chrome, and computer use (`[D]`).
3. **Enterprise / compliance blocks:** Cannot initialize under **HIPAA** or **Zero Data Retention (ZDR)** configs, nor via **AWS Bedrock, GCP Vertex, or Microsoft Foundry** gateways (`[D]`).

---

## 3. Security & Hook Implications (`[D]`, `[C]`)

Programmatic tool calling fundamentally changes how guardrails must be built:

1. **Naive `PreToolUse` shell hooks miss wrapped commands (`[D]`):**
   If your hook only inspects `Bash` command strings, a script generated in Code Mode wraps commands inside JavaScript. Hooks must inspect `tool_input.code` (or rely on script-level safety classifiers and OS/container sandboxing) (`[D]`).
2. **MCP prompt-injection & exfiltration blast radius (`[D]`):**
   When an agent can chain external MCP data sources (Jira, Slack, GitHub, internal DBs) inside an executable script, an untrusted payload from one MCP tool can manipulate script logic to aggregate and leak data to another (`[D]`).
   - **Mitigations (`[D]`, `[C]`):** Enforce **Harness Walls** outside the model (`[C]`)—enterprise MCP allowlists/gateways, least-privilege read/write scopes, network egress caps, and explicit human approval for `NO UNDO` actions (`[C]`, `[D]`).

---

## 4. Production Managed Runtimes (`[E]`, `[C]`)

On a developer laptop, the harness wraps local git and shell tools. In customer-facing production systems (e.g., Anthropic's **Claude Managed Agents** pattern from Isabella He's workshop `[E]`), three architectural primitives matter:

1. **Decoupled Brain and Hands (`[E]`):** Keep reasoning + orchestration separate from ephemeral, sandboxed execution containers.
2. **External Append-Only Session Event Log (`[E]`, `[C]`):** Persist every action, tool response, and state transition *outside* both the model context and container filesystem—so if a worker crashes mid-run, a new container replays/resumes cleanly without losing progress (`[E]`).
3. **Managed Credential Vaults (`[E]`):** Inject auth tokens at the tool/sandbox boundary so raw secrets never enter the LLM context window.

---

## 5. Cross-Tool Translation (Apply Today Without Waiting)

You do not need an experimental flag to capture 80% of Code Mode's context savings today:

| Environment | How to Apply Programmatic Tooling Now |
|---|---|
| **Antigravity (personal)** | Use **`run_workflow`** (Python scripts orchestrating parallel `call_tool` / `agent` calls and aggregating in Python) and **`swarm`** for isolated parallel worker contexts (`[C]`, `[D]`). |
| **GitHub Copilot CLI (professional)** | Wrap noisy multi-step repo/API queries in small deterministic helper scripts (`scripts/*.sh` or Python, e.g., [`scripts/ste_lint.py --json`](../scripts/ste_lint.py)) that emit crisp JSON/markdown summaries, pair with custom agents (`.github/agents/*.agent.md`), and enforce boundaries via lifecycle hooks (`[C]`, `[D]`). |
| **Claude Code** | Enable `CLAUDE_CODE_EXPERIMENTAL_CODE_MODE=1` in non-HIPAA/non-Bedrock personal CLI sessions for repo-wide sweeps; keep deterministic repo helper scripts for CI and enterprise setups (`[D]`). |

---

*Related: [`hooks/verify-gate-observe.md`](../hooks/verify-gate-observe.md) · [`scripts/ste_lint.py`](../scripts/ste_lint.py) · [`playbooks/harness-loop-graph.md`](harness-loop-graph.md) · [`playbooks/model-effort-economics.md`](model-effort-economics.md)*
