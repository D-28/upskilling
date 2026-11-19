# Commit Verification Gate & Hook Recipes (`off → observe → enforce`)

> **Why this pattern works (`[B]`):** Requiring every commit to prove how it was verified prevents unverified AI code from piling up—while rolling out via `observe` mode and a 2-block escape hatch keeps engineers and agents from getting deadlocked.

---

## 1. The Three-Phase Rollout Strategy (`[B]`)

1. **Stamp every commit with provenance:**
   Add a Git trailer such as:
   - `Verified-By: e2e,unit` (or `lint,typecheck,unit`)
   - `Verified-By: none` (explicitly recorded when skipped, so unverified changes remain searchable in `git log` `[B]`)
2. **Phase 1 — `off`:** Disabled while configuring repo commands and `/verify` skills.
3. **Phase 2 — `observe`:** Hook inspects commits and **logs** what *would* have been blocked (without failing `git commit`) so you can measure false positives before gating anyone `[B]`.
4. **Phase 3 — `enforce` (with 2-block escape hatch `[B]`):**
   - Blocks commits missing a `Verified-By:` stamp (or missing `/verify` / `/code-review` evidence in the session).
   - Allows an explicit bypass reason in the commit message (`Verified-Bypass: <reason>`).
   - Tracks blocks per session/branch: after **2 blocks**, the 3rd attempt is allowed through with a warning so an imperfect agent never gets permanently stuck `[B]`.

---

## 2. Starter Git `commit-msg` Gate Script (Portable Across Any CLI / Editor)

Save as `.githooks/commit-msg` (and activate via `git config core.hooksPath .githooks`):

```bash
#!/usr/bin/env bash
set -euo pipefail

MSG_FILE="$1"
MODE="${VERIFY_GATE_MODE:-observe}" # off | observe | enforce
STATE_FILE="${GIT_DIR:-.git}/verify_gate_blocks"
LOG_FILE="${GIT_DIR:-.git}/verify_gate.log"

[ "$MODE" = "off" ] && exit 0

# Accept either a concrete Verified-By trailer or an explicit bypass explanation
if grep -Eq '^Verified-By:\s*(.+)$' "$MSG_FILE"; then
  rm -f "$STATE_FILE"
  exit 0
fi

if grep -Eq '^Verified-Bypass:\s*\S{8,}' "$MSG_FILE"; then
  printf '[%s] BYPASS (%s): %s\n' "$(date -u +%FT%TZ)" "$MODE" "$(head -n1 "$MSG_FILE")" >> "$LOG_FILE"
  rm -f "$STATE_FILE"
  exit 0
fi

# Missing verification metadata
if [ "$MODE" = "observe" ]; then
  printf '[%s] WOULD_BLOCK: %s\n' "$(date -u +%FT%TZ)" "$(head -n1 "$MSG_FILE")" >> "$LOG_FILE"
  echo "[verify-gate:observe] Tip: add 'Verified-By: <checks|none>' trailer (logged only; not blocking)." >&2
  exit 0
fi

# Enforce mode with 2-block escape hatch [B]
BLOCKS=0
[ -f "$STATE_FILE" ] && BLOCKS="$(cat "$STATE_FILE" 2>/dev/null || echo 0)"
NEXT_BLOCKS=$((BLOCKS + 1))

if [ "$BLOCKS" -ge 2 ]; then
  printf '[%s] ESCAPE_HATCH_ALLOW after %s blocks: %s\n' "$(date -u +%FT%TZ)" "$BLOCKS" "$(head -n1 "$MSG_FILE")" >> "$LOG_FILE"
  echo "[verify-gate:enforce] Allowing commit after $BLOCKS blocks so session does not wedge. Add verification next!" >&2
  rm -f "$STATE_FILE"
  exit 0
fi

echo "$NEXT_BLOCKS" > "$STATE_FILE"
printf '[%s] BLOCKED (%s/2): %s\n' "$(date -u +%FT%TZ)" "$NEXT_BLOCKS" "$(head -n1 "$MSG_FILE")" >> "$LOG_FILE"
echo "[verify-gate:enforce] Blocked ($NEXT_BLOCKS/2): run /verify and add 'Verified-By: <checks>' (or 'Verified-Bypass: <reason>')." >&2
exit 1
```

---

## 3. Adapting to Agent CLI Lifecycle Hooks

### GitHub Copilot CLI (`.github/hooks/hooks.json` or lifecycle hooks)
- Use `preToolUse` hooks to block destructive `NO UNDO` actions outside approved scopes (`[C]`), and `postToolUse` / `sessionEnd` (or pre-PR scripts) to run cheap deterministic checks (`lint`, `typecheck`, `unit`) before opening a PR (`[B]`).
- Pair with `.githooks/commit-msg` above so every commit created by Copilot CLI automatically picks up the `observe → enforce` provenance check.

### Claude Code (`PreToolUse` + Code Mode Warning `[D]`)
Standard `PreToolUse` hooks often parse `tool_input.command` for `Bash` calls. **Important Nov 2026 caveat (`[D]`):** when **Code Mode** (`CLAUDE_CODE_EXPERIMENTAL_CODE_MODE=1`) is enabled, Claude batches tools inside generated JavaScript executed in a REPL—so naive `Bash`-only string checks will not fire on inner calls!

To cover both standard `Bash` tool calls and programmatic Code Mode scripts:
1. Inspect **`tool_input.code`** (for Code Mode / REPL tool calls) as well as **`tool_input.command`** (for direct shell calls) (`[D]`).
2. Never rely *only* on regex matching inside hooks for `NO UNDO` security boundaries—back them up with **OS/container permissions, git hooks, CI checks ("Write It Twice" `[C]`), and MCP allowlists (`[D]`)**.

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash|Code|REPL",
        "hooks": [
          {
            "type": "command",
            "command": "python3 -c 'import json,sys,re; d=json.load(sys.stdin).get(\"tool_input\",{}); txt=(d.get(\"command\",\"\")+\"\\n\"+d.get(\"code\",\"\")); sys.exit(2 if re.search(r\"rm\\s+-rf|git\\s+push\\s+--force|DROP\\s+TABLE\", txt, re.I) else 0)'"
          }
        ]
      }
    ]
  }
}
```
*(Exit code `2` blocks the tool call in Claude Code hook conventions; treat regex checks as a first-line tripwire backed by sandbox permissions and git/CI walls.)*
