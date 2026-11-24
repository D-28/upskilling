"""Configuration, hard deterministic budgets, and dynamic model alias routing.

Follows playbooks/model-effort-economics.md and playbooks/harness-loop-graph.md:
- Defaults to Google's dynamic `-latest` aliases so pipelines don't rot on version
  deprecation cycles, while still allowing pinned overrides via env / repo vars.
- Automatically selects `v1beta` for `-latest` and `-preview` model aliases because
  `google-genai >= 3.0.0` defaults to `v1` where `-latest` aliases are not served.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Hard deterministic ceilings (Harness Walls outside the model)
MAX_ITEMS_PER_RUN = 40
MAX_STAGE1_BATCH_SIZE = 10
MAX_STAGE2_SURVIVORS = 5
MAX_ITEM_AGE_DAYS = 14
MAX_FEED_BYTES = 4_194_304  # 4 MiB cap for Stage 0 XML/JSON feeds and CHANGELOG.md
MAX_HTTP_BYTES = 512_000  # 500 KiB cap for Stage 2 untrusted web article enrichment
MAX_HTTP_REDIRECTS = 3
HTTP_TIMEOUT_SECONDS = 10.0
MAX_STAGE1_EXCERPT_CHARS = 1_500
MAX_STAGE2_BODY_CHARS = 16_000
SHORT_BODY_ENRICH_THRESHOLD = 600
MAX_RUN_COST_USD = 0.50
MAX_SEEN_ITEMS = 5_000
LLM_HTTP_TIMEOUT_MS = 120_000  # 120s per Gemini API request (HttpOptions.timeout is in ms)
STAGE1_MAX_OUTPUT_TOKENS = 8_192
STAGE2_MAX_OUTPUT_TOKENS = 16_384
STAGE3_MAX_OUTPUT_TOKENS = 32_768
MAX_STRUCTURED_OUTPUT_TOKENS = 32_768

# Rubric thresholds (deterministic Python sum of five 0..2 dimensions -> 0..10)
STAGE_SCORE_THRESHOLD = 6
HIGH_SIGNAL_SCORE_THRESHOLD = 9

# Dynamic latest model aliases & Stage 3 Coherence Gate frontier model (overridable via repo vars / env)
DEFAULT_STAGE1_MODEL = "gemini-flash-lite-latest"
DEFAULT_STAGE1_THINKING = "LOW"
DEFAULT_STAGE2_MODEL = "gemini-flash-latest"
DEFAULT_STAGE2_THINKING = "HIGH"
DEFAULT_STAGE3_MODEL = "gemini-4-neon"
DEFAULT_STAGE3_THINKING = "HIGH"

VALID_THINKING_LEVELS = frozenset({"MINIMAL", "LOW", "MEDIUM", "HIGH", "XHIGH"})

# Conservative fallback USD-per-1M-token rates for local cost-ceiling guardrails
# (input, cached_input, output_including_thinking). Intentionally slightly conservative
# so the circuit breaker trips early rather than late.
MODEL_PRICE_ESTIMATES_PER_MTOK: dict[str, tuple[float, float, float]] = {
    "flash-lite": (0.35, 0.04, 2.75),
    "flash": (0.75, 0.08, 4.50),
    "neon": (3.00, 0.15, 15.00),
    "pro": (2.50, 0.25, 15.00),
    "argon": (2.50, 0.25, 15.00),
    "carbon": (3.00, 0.30, 18.00),
    "default": (2.50, 0.25, 15.00),
}


def requires_v1beta(model_name: str) -> bool:
    """Return True when a Gemini model ID requires the `v1beta` Developer API."""
    lowered = model_name.strip().lower()
    return (
        lowered.endswith("-latest")
        or "-preview" in lowered
        or "-exp" in lowered
        or lowered.startswith("gemini-4-")
    )


def validate_thinking_level(model_name: str, level: str) -> str:
    """Normalize and validate thinking_level against known model constraints."""
    normalized = level.strip().upper()
    if normalized not in VALID_THINKING_LEVELS:
        raise ValueError(
            f"Unsupported thinking_level '{level}'. Valid: {sorted(VALID_THINKING_LEVELS)}"
        )
    lowered = model_name.strip().lower()
    if normalized == "MINIMAL" and "flash-lite" not in lowered:
        # Gemini 3.8 Flash / Gemini 4 reject MINIMAL with HTTP 400; fail closed to LOW.
        return "LOW"
    return normalized


def estimate_cost_usd(
    model_name: str,
    prompt_tokens: int,
    cached_tokens: int,
    output_and_thought_tokens: int,
) -> float:
    """Estimate request USD cost conservatively for circuit-breaker accounting."""
    lowered = model_name.lower()
    rates = MODEL_PRICE_ESTIMATES_PER_MTOK["default"]
    for key in ("flash-lite", "flash", "neon", "carbon", "argon", "pro"):
        if key in lowered:
            rates = MODEL_PRICE_ESTIMATES_PER_MTOK[key]
            break
    in_rate, cache_rate, out_rate = rates
    billable_cached = max(0, min(cached_tokens, prompt_tokens))
    uncached_input = max(0, prompt_tokens - billable_cached)
    cost = (
        (uncached_input / 1_000_000.0) * in_rate
        + (billable_cached / 1_000_000.0) * cache_rate
        + (max(0, output_and_thought_tokens) / 1_000_000.0) * out_rate
    )
    return round(cost, 6)


@dataclass(frozen=True)
class PipelineConfig:
    """Runtime settings for a single pipeline execution."""

    repo_root: Path
    feeds_path: Path
    stage1_model: str = DEFAULT_STAGE1_MODEL
    stage1_thinking: str = DEFAULT_STAGE1_THINKING
    stage2_model: str = DEFAULT_STAGE2_MODEL
    stage2_thinking: str = DEFAULT_STAGE2_THINKING
    stage3_model: str = DEFAULT_STAGE3_MODEL
    stage3_thinking: str = DEFAULT_STAGE3_THINKING
    max_items_per_run: int = MAX_ITEMS_PER_RUN
    max_stage1_batch_size: int = MAX_STAGE1_BATCH_SIZE
    max_stage2_survivors: int = MAX_STAGE2_SURVIVORS
    max_item_age_days: int = MAX_ITEM_AGE_DAYS
    max_run_cost_usd: float = MAX_RUN_COST_USD
    stage_score_threshold: int = STAGE_SCORE_THRESHOLD
    high_signal_threshold: int = HIGH_SIGNAL_SCORE_THRESHOLD
    user_agent: str = "upskilling-radar/0.1 (+https://github.com/D-28/upskilling)"

    @classmethod
    def from_env(cls, repo_root: Path | None = None) -> PipelineConfig:
        root = (repo_root or Path.cwd()).resolve()
        stage1_model = os.environ.get("STAGE1_MODEL", DEFAULT_STAGE1_MODEL).strip() or DEFAULT_STAGE1_MODEL
        stage2_model = os.environ.get("STAGE2_MODEL", DEFAULT_STAGE2_MODEL).strip() or DEFAULT_STAGE2_MODEL
        stage3_model = os.environ.get("STAGE3_MODEL", DEFAULT_STAGE3_MODEL).strip() or DEFAULT_STAGE3_MODEL
        stage1_thinking = validate_thinking_level(
            stage1_model, os.environ.get("STAGE1_THINKING", DEFAULT_STAGE1_THINKING)
        )
        stage2_thinking = validate_thinking_level(
            stage2_model, os.environ.get("STAGE2_THINKING", DEFAULT_STAGE2_THINKING)
        )
        stage3_thinking = validate_thinking_level(
            stage3_model, os.environ.get("STAGE3_THINKING", DEFAULT_STAGE3_THINKING)
        )
        return cls(
            repo_root=root,
            feeds_path=root / "radar" / "feeds.yaml",
            stage1_model=stage1_model,
            stage1_thinking=stage1_thinking,
            stage2_model=stage2_model,
            stage2_thinking=stage2_thinking,
            stage3_model=stage3_model,
            stage3_thinking=stage3_thinking,
            max_items_per_run=int(os.environ.get("RADAR_MAX_ITEMS", str(MAX_ITEMS_PER_RUN))),
            max_stage2_survivors=int(
                os.environ.get("RADAR_MAX_SURVIVORS", str(MAX_STAGE2_SURVIVORS))
            ),
            max_item_age_days=int(os.environ.get("RADAR_MAX_AGE_DAYS", str(MAX_ITEM_AGE_DAYS))),
            max_run_cost_usd=float(os.environ.get("RADAR_MAX_COST_USD", str(MAX_RUN_COST_USD))),
        )
