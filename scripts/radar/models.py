"""Strict Pydantic schemas for feeds, items, LLM responses, state, and run artifacts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FeedEntry(BaseModel):
    """Single source definition in radar/feeds.yaml."""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    type: Literal["rss", "github_releases", "hn_algolia"]
    url: str
    category: str = "general"
    max_items: int = Field(default=10, ge=1, le=50)
    filter_patch_releases: bool = False
    changelog_fallback_url: str | None = None
    keywords: list[str] = Field(default_factory=list)
    use_default_keywords: bool = False
    min_points: int = 0
    notes: str = ""


class FeedRegistry(BaseModel):
    """Root schema for radar/feeds.yaml."""

    model_config = ConfigDict(extra="ignore")

    version: int = 1
    default_agentic_keywords: list[str] = Field(default_factory=list)
    feeds: list[FeedEntry] = Field(default_factory=list)


ITEM_ID_PATTERN = r"^[a-f0-9]{12}$"
ISO_WEEK_PATTERN = r"^20\d{2}-W(?:0[1-9]|[1-4]\d|5[0-3])$"
PENDING_BUFFER_MIN_SCORE = 7


class CandidateItem(BaseModel):
    """Normalized, sanitized item emitted by deterministic Stage 0."""

    model_config = ConfigDict(extra="ignore")

    item_id: str = Field(pattern=ITEM_ID_PATTERN)  # deterministic short sha256 of canonical_url
    feed_id: str
    feed_name: str
    title: str
    url: str
    canonical_url: str
    domain: str
    published_at: str | None = None
    excerpt: str = ""
    body: str = ""
    title_hash: str = ""
    content_hash: str = ""
    enrichment_status: Literal[
        "feed_sufficient",
        "enriched",
        "fetch_blocked",
        "fetch_incomplete",
        "not_needed",
    ] = "not_needed"


class CandidateSummary(BaseModel):
    """Compact per-candidate extraction metadata for self-contained Job Summaries."""

    model_config = ConfigDict(extra="ignore")

    item_id: str = Field(pattern=ITEM_ID_PATTERN)
    feed_id: str
    feed_name: str = ""
    title: str
    url: str = ""
    canonical_url: str
    domain: str = ""
    body_chars: int = 0
    word_count: int = 0
    enrichment_status: str = "not_needed"


Stage1VerdictCode = Literal[
    "SURVIVOR",
    "ALREADY_COVERED",
    "MODEL_RELEASE_FLUFF",
    "MARKETING_REBRAND",
    "NO_WORKFLOW_DELTA",
]


class Stage1ItemVerdict(BaseModel):
    """Structured triage decision for a single candidate item."""

    item_id: str = Field(pattern=ITEM_ID_PATTERN)
    verdict: Stage1VerdictCode
    matched_repo_file: str = Field(
        default="",
        description="Repo file that already covers this item (if ALREADY_COVERED) or the primary target file to compare against in Stage 2 (if SURVIVOR).",
    )
    reason: str = Field(max_length=400)


class Stage1BatchResponse(BaseModel):
    """Strict JSON Schema returned by zero-tool Stage 1 batched triage."""

    verdicts: list[Stage1ItemVerdict]


class RubricDimensions(BaseModel):
    """Five discrete 0..2 rubric dimensions summed deterministically in Python."""

    delta_novelty: int = Field(ge=0, le=2)
    durability: int = Field(ge=0, le=2)
    actionability: int = Field(ge=0, le=2)
    evidence_quality: int = Field(ge=0, le=2)
    career_leverage: int = Field(ge=0, le=2)


class Stage2Analysis(BaseModel):
    """Strict JSON Schema returned by zero-tool Stage 2 deep delta analysis."""

    item_id: str = Field(pattern=ITEM_ID_PATTERN)
    passes_net_new_delta_gate: bool = Field(
        description="True ONLY if the item introduces a concrete engineering methodology, workflow refinement, or failure mode NOT already covered in the repo."
    )
    passes_substance_gate: bool = Field(
        description="True ONLY if backed by concrete code, evals, release diff, failure mode, or reproducible walkthrough (not opinion/hype)."
    )
    counterargument_to_drop: str = Field(
        max_length=500,
        description="Strongest devil's-advocate case for why this item is redundant, hype, or not worth adding to the repo.",
    )
    dimensions: RubricDimensions
    target_repo_files: list[str] = Field(default_factory=list, max_length=4)
    what_is_net_new: str = Field(max_length=800)
    proposed_refinement: str = Field(
        max_length=800,
        description="Concrete <=5-line refinement for an existing playbook/template/skill, or concise radar note.",
    )
    career_takeaway: str = Field(
        max_length=400,
        description="Specific Staff SWE (org leverage) and/or FDE/FDSE (production customer system) implication.",
    )
    evidence_quote: str = Field(
        default="",
        max_length=300,
        description="Short grounded excerpt or concrete fact from the source proving substance.",
    )


class ScoredSurvivor(BaseModel):
    """Deterministically scored Stage 2 output ready for staging or dropping."""

    item: CandidateItem
    analysis: Stage2Analysis
    score: int = Field(ge=0, le=10)
    disposition: Literal["DROP", "STAGE", "HIGH_SIGNAL"]
    gate_failure_reason: str = ""


class PendingCandidate(ScoredSurvivor):
    """Stage 2 survivor (`score >= 7/10`) buffered in `radar-state/pending-candidates.json`."""

    model_config = ConfigDict(extra="ignore")

    buffered_at: str = ""
    iso_week: str = ""


class PendingCandidatesState(BaseModel):
    """Schema for radar-state/pending-candidates.json (backward-compatible empty defaults)."""

    model_config = ConfigDict(extra="ignore")

    schema_version: int = 1
    updated_at: str = ""
    items: dict[str, PendingCandidate] = Field(default_factory=dict)  # keyed by item_id


Stage3ItemVerdictCode = Literal[
    "SUBSUMED_BY",
    "CONFLICTS_WITH",
    "COMPOUNDS_WITH",
    "REJECT_ENTROPY",
    "APPROVE_SYNTHESIS",
]

Stage3RunDecision = Literal["REJECT_ALL", "APPROVE_SYNTHESIS"]


class SystemicPoisonFlags(BaseModel):
    """Six Systemic Poison failure modes audited by Stage 3 Coherence Gate."""

    attention_budget_poison: bool = Field(
        default=False,
        description="True if purely additive prose bloats context without replacing or sharpening an invariant.",
    )
    prompt_wish_poison: bool = Field(
        default=False,
        description="True if the proposal asks models to remember a rule instead of enforcing it via lint, script, or hook.",
    )
    verification_weakening_poison: bool = Field(
        default=False,
        description="True if it promotes same-context self-grading, LLM confidence thresholds, or weaker base-branch REVIEW.md walls.",
    )
    orchestration_tax_poison: bool = Field(
        default=False,
        description="True if it adds multi-agent graph complexity where one loop or deterministic script suffices.",
    )
    cache_smart_zone_poison: bool = Field(
        default=False,
        description="True if mid-session effort toggles or raw tool dumps break prompt-cache reuse or Smart Zone discipline.",
    )
    cross_file_disharmony: bool = Field(
        default=False,
        description="True if it contradicts existing playbooks, duplicates another item, or leaves skill/template updates unpropagated.",
    )

    def active_poisons(self) -> list[str]:
        names = (
            "attention_budget_poison",
            "prompt_wish_poison",
            "verification_weakening_poison",
            "orchestration_tax_poison",
            "cache_smart_zone_poison",
            "cross_file_disharmony",
        )
        return [name for name in names if getattr(self, name)]

    def has_any(self) -> bool:
        return bool(self.active_poisons())


class Stage3ItemAudit(BaseModel):
    """Per-candidate verdict and Systemic Poison audit emitted by Stage 3."""

    item_id: str = Field(pattern=ITEM_ID_PATTERN)
    verdict: Stage3ItemVerdictCode
    related_item_ids: list[str] = Field(
        default_factory=list,
        description="Other candidate item_ids this candidate is subsumed by, conflicts with, or compounds with.",
    )
    affected_repo_files: list[str] = Field(default_factory=list, max_length=6)
    poisons: SystemicPoisonFlags = Field(default_factory=SystemicPoisonFlags)
    rationale: str = Field(max_length=500)


class Stage3SynthesisProposal(BaseModel):
    """Unified synthesis proposal when Stage 3 approves standalone or compounding candidates."""

    title: str = Field(max_length=180)
    source_item_ids: list[str] = Field(default_factory=list)
    target_repo_files: list[str] = Field(default_factory=list, max_length=6)
    unified_thesis: str = Field(max_length=1000)
    proposed_repo_changes: str = Field(max_length=1200)
    harmonization_and_pruning: str = Field(
        default="",
        max_length=600,
        description="Existing prose to tighten, replace, or update across playbooks, skills, or templates to keep attention budget flat.",
    )
    career_takeaway: str = Field(default="", max_length=400)


class Stage3CoherenceVerdict(BaseModel):
    """Strict JSON Schema returned by zero-tool Stage 3 Coherence Gate (gemini-4-neon, HIGH)."""

    decision: Stage3RunDecision = "REJECT_ALL"
    executive_summary: str = Field(max_length=800)
    item_audits: list[Stage3ItemAudit] = Field(default_factory=list)
    syntheses: list[Stage3SynthesisProposal] = Field(default_factory=list)


class DeAnchoredCandidate(BaseModel):
    """Score-blind Stage 3 input payload with Stage 2 numeric scores and badges stripped."""

    item_id: str = Field(pattern=ITEM_ID_PATTERN)
    feed_id: str
    feed_name: str
    title: str
    canonical_url: str
    domain: str
    published_at: str | None = None
    body: str = ""
    source_path: Literal["pending_buffer", "stage2_survivor", "fast_lane_direct"] = "stage2_survivor"
    target_repo_files: list[str] = Field(default_factory=list)
    what_is_net_new: str = ""
    proposed_refinement: str = ""
    career_takeaway: str = ""
    counterargument_to_drop: str = ""
    evidence_quote: str = ""


class LLMCallTrace(BaseModel):
    """Trace telemetry for a single zero-tool Gemini API call."""

    stage: Literal["stage1", "stage2", "stage3"]
    requested_model: str
    resolved_model_version: str = ""
    thinking_level: str
    api_version: str
    prompt_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    thought_tokens: int = 0
    estimated_cost_usd: float = 0.0
    item_ids: list[str] = Field(default_factory=list)


class SeenRecord(BaseModel):
    """Deduplication entry stored on orphan branch `radar-state`."""

    model_config = ConfigDict(extra="ignore")

    canonical_url: str
    title_hash: str = ""
    content_hash: str = ""
    feed_id: str = ""
    first_seen_at: str = ""
    verdict: str = ""


class SeenState(BaseModel):
    """Schema for radar-state/seen.json (backward-compatible defaults)."""

    model_config = ConfigDict(extra="ignore")

    schema_version: int = 1
    updated_at: str = ""
    items: dict[str, SeenRecord] = Field(default_factory=dict)  # keyed by item_id


class FeedStats(BaseModel):
    """Per-feed empirical health metrics."""

    model_config = ConfigDict(extra="ignore")

    items_fetched: int = 0
    stage1_survivors: int = 0
    stage2_staged: int = 0
    human_merged: int = 0
    human_closed_rejected: int = 0
    consecutive_fetch_errors: int = 0
    last_error: str = ""
    last_success_at: str = ""
    last_merged_at: str = ""


class DomainHitRecord(BaseModel):
    """Tracks human-merged items from unsubscribed domains for >=2 promotion."""

    model_config = ConfigDict(extra="ignore")

    merged_item_ids: list[str] = Field(default_factory=list)
    merged_dates: list[str] = Field(default_factory=list)


class FeedHealthState(BaseModel):
    """Schema for radar-state/feed-health.json (backward-compatible defaults)."""

    model_config = ConfigDict(extra="ignore")

    schema_version: int = 1
    updated_at: str = ""
    feeds: dict[str, FeedStats] = Field(default_factory=dict)
    unsubscribed_domain_hits: dict[str, DomainHitRecord] = Field(default_factory=dict)
    reconciled_prs: list[int] = Field(default_factory=list)


class FeedFetchSummary(BaseModel):
    """Per-feed outcome for a single Stage 0 run."""

    feed_id: str
    ok: bool = True
    error: str = ""
    raw_count: int = 0
    new_count: int = 0
    filtered_count: int = 0


class RunResult(BaseModel):
    """Validated JSON artifact handed from Job 1 (read-only) to Job 2 (privileged stager)."""

    schema_version: int = 1
    run_at: str
    iso_week: str = Field(pattern=ISO_WEEK_PATTERN)
    mode: Literal["observe", "enforce", "bootstrap"]
    fast_lane_url: str | None = None
    force: bool = False
    run_coherence_gate: bool = False
    status: Literal["OK", "FETCH_INCOMPLETE"] = "OK"
    error_code: str = ""
    error_message: str = ""
    feed_summaries: list[FeedFetchSummary] = Field(default_factory=list)
    candidate_summaries: list[CandidateSummary] = Field(default_factory=list)
    candidates_fetched: int = 0
    stage1_reviewed: int = 0
    stage1_verdicts: list[Stage1ItemVerdict] = Field(default_factory=list)
    stage2_results: list[ScoredSurvivor] = Field(default_factory=list)
    buffered_items: list[ScoredSurvivor] = Field(default_factory=list)
    drained_item_ids: list[str] = Field(default_factory=list)
    stage3_verdict: Stage3CoherenceVerdict | None = None
    staged_items: list[ScoredSurvivor] = Field(default_factory=list)
    has_high_signal: bool = False
    new_seen_records: dict[str, SeenRecord] = Field(default_factory=dict)
    traces: list[LLMCallTrace] = Field(default_factory=list)
    total_estimated_cost_usd: float = 0.0
    cost_cap_triggered: bool = False
    summary_markdown: str = ""
