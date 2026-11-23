# Project Glossary

Canonical terms for the `D-28/upskilling` signal-ingestion pipeline ([`templates/GLOSSARY-and-ADR.md`](../templates/GLOSSARY-and-ADR.md)).

| Canonical Term | Definition | Not To Be Confused With | Code / Schema Location |
|---|---|---|---|
| **Candidate Item** | Normalized article or release emitted by deterministic Stage 0 after dedupe and filtering. | **Pending Candidate** (a Stage 2 survivor waiting in the weekly buffer) | [`scripts/radar/models.py`](../scripts/radar/models.py) |
| **Fast-Lane URL** | Owner-supplied `https://` URL submitted via `workflow_dispatch` for direct frontier evaluation. | **Scheduled Feed Item** (an entry pulled automatically from `radar/feeds.yaml`) | [`scripts/radar/fetcher.py`](../scripts/radar/fetcher.py) |
| **Plan B Resolution** | Safe, no-auth fallback extracting canonical blog links or public oEmbed text from stub pages. | **Anti-Bot Bypass** (solving CAPTCHAs or using private login cookies, which stays forbidden) | [`scripts/radar/fetcher.py`](../scripts/radar/fetcher.py) |
| **Content-Sufficiency Gate** | Deterministic check requiring `>= 600` chars and `>= 100` words without login/JS-wall text. | **Substance Gate** (LLM check for code, evals, or failure modes) | [`scripts/radar/fetcher.py`](../scripts/radar/fetcher.py) |
| **FETCH_INCOMPLETE** | Fail-closed error emitted before LLM calls when Plan B cannot recover full readable text. | **ALREADY_COVERED** (a Stage 1 drop verdict against `REPO_INVENTORY`) | [`scripts/radar/models.py`](../scripts/radar/models.py) |
| **Pending Buffer** | Weekly holding file (`pending-candidates.json`) on `radar-state` storing Mon–Sat survivors (`>= 7/10`). | **Weekly Digest** (`radar/YYYY-Www-digest.md` staged on a Draft PR) | [`scripts/radar/state.py`](../scripts/radar/state.py) |
| **Coherence Gate** | Stage 3 `gemini-4-neon` (`HIGH`) audit checking full-repo harmony, contradictions, and six poisons. | **Stage 2 Local Delta** (per-item rubric scoring against one target file) | [`scripts/radar/llm.py`](../scripts/radar/llm.py) |
| **De-Anchored Input** | Stage 3 payload with Stage 2 numeric scores and badges stripped to prevent anchoring bias. | **Raw RunResult** (full telemetry JSON archived in CI artifacts) | [`scripts/radar/models.py`](../scripts/radar/models.py) |
| **Systemic Poison** | Locally clever idea that degrades repo attention budget, cache hygiene, verification walls, or coherence. | **Release Fluff** (routine model benchmarks or patch notes dropped in Stage 1) | [`docs/specs/coherence-gate-and-fast-lane.md`](specs/coherence-gate-and-fast-lane.md) |
