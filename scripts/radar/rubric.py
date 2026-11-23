"""Deterministic 0-10 signal rubric scorer and idempotent rolling digest renderer.

- Enforces the two hard pass/fail gates (Net-New Delta + Substance) in Python.
- Sums the five 0..2 rubric dimensions deterministically (never trusts free-form LLM totals).
- Renders sanitized Markdown into `radar/YYYY-Www-digest.md` with deterministic
  `<!-- radar-id: <id> source: <feed_id> domain: <domain> -->` markers so daily
  updates to a rolling weekly Draft PR are idempotent and merge outcomes reconcile cleanly.
"""

from __future__ import annotations

import re

from scripts.radar.config import HIGH_SIGNAL_SCORE_THRESHOLD, STAGE_SCORE_THRESHOLD
from scripts.radar.fetcher import canonicalize_url, extract_domain
from scripts.radar.models import (
    CandidateItem,
    CandidateSummary,
    ScoredSurvivor,
    Stage2Analysis,
    Stage3CoherenceVerdict,
    Stage3SynthesisProposal,
)
from scripts.radar.security import (
    filter_allowed_repo_paths,
    sanitize_markdown_text,
    sanitize_single_line,
)

_MARKER_RE = re.compile(
    r"<!--\s*radar-id:\s*([a-f0-9]{12})\s+source:\s*([A-Za-z0-9_.\-]+)\s+domain:\s*([A-Za-z0-9_.\-]+)\s*-->"
)


def score_stage2_analysis(
    item: CandidateItem,
    analysis: Stage2Analysis,
    *,
    stage_threshold: int = STAGE_SCORE_THRESHOLD,
    high_signal_threshold: int = HIGH_SIGNAL_SCORE_THRESHOLD,
) -> ScoredSurvivor:
    """Apply hard gates and deterministically sum the five 0..2 rubric dimensions."""
    if not analysis.passes_net_new_delta_gate:
        return ScoredSurvivor(
            item=item,
            analysis=analysis,
            score=0,
            disposition="DROP",
            gate_failure_reason="Failed Net-New Delta Gate (already covered in repo).",
        )
    if not analysis.passes_substance_gate:
        return ScoredSurvivor(
            item=item,
            analysis=analysis,
            score=0,
            disposition="DROP",
            gate_failure_reason="Failed Substance Gate (insufficient verifiable engineering evidence).",
        )

    dims = analysis.dimensions
    total = (
        dims.delta_novelty
        + dims.durability
        + dims.actionability
        + dims.evidence_quality
        + dims.career_leverage
    )

    if total >= high_signal_threshold:
        disposition = "HIGH_SIGNAL"
    elif total >= stage_threshold:
        disposition = "STAGE"
    else:
        disposition = "DROP"

    return ScoredSurvivor(
        item=item,
        analysis=analysis,
        score=total,
        disposition=disposition,
    )


def format_radar_marker(item_id: str, feed_id: str, domain: str) -> str:
    """Build deterministic HTML metadata marker for idempotency and PR telemetry."""
    safe_feed = re.sub(r"[^A-Za-z0-9_.\-]", "_", feed_id) or "unknown"
    safe_domain = re.sub(r"[^A-Za-z0-9_.\-]", "_", domain) or "unknown"
    return f"<!-- radar-id: {item_id} source: {safe_feed} domain: {safe_domain} -->"


def parse_radar_markers(markdown_text: str) -> list[tuple[str, str, str]]:
    """Parse all `(item_id, feed_id, domain)` metadata markers from a digest file."""
    return [(m.group(1), m.group(2), m.group(3)) for m in _MARKER_RE.finditer(markdown_text)]


def render_survivor_entry(scored: ScoredSurvivor) -> str:
    """Render a single sanitized Markdown section for a staged survivor."""
    item = scored.item
    a = scored.analysis
    d = a.dimensions

    title = sanitize_single_line(item.title, max_chars=180)
    feed_name = sanitize_single_line(item.feed_name, max_chars=80)
    safe_domain = re.sub(r"[^A-Za-z0-9_.\-]", "", item.domain) or "source"
    safe_url = canonicalize_url(item.canonical_url)
    badge = "HIGH SIGNAL" if scored.disposition == "HIGH_SIGNAL" else "STAGE"
    allowed_targets = filter_allowed_repo_paths(a.target_repo_files)
    targets = ", ".join(f"`{t}`" for t in allowed_targets) or "`radar/`"
    net_new = sanitize_markdown_text(a.what_is_net_new, max_chars=800)
    refinement = sanitize_markdown_text(a.proposed_refinement, max_chars=800)
    career = sanitize_markdown_text(a.career_takeaway, max_chars=400)
    counter = sanitize_markdown_text(a.counterargument_to_drop, max_chars=400)
    evidence = sanitize_markdown_text(a.evidence_quote, max_chars=300)

    marker = format_radar_marker(item.item_id, item.feed_id, safe_domain)
    lines = [
        marker,
        f"### [{scored.score}/10 · {badge}] {title}",
        f"- **Source:** {feed_name} · [`{safe_domain}`]({safe_url})",
        f"- **Target Repo Files:** {targets}",
        (
            f"- **Rubric Breakdown:** Novelty `{d.delta_novelty}/2` · Durability `{d.durability}/2` · "
            f"Actionability `{d.actionability}/2` · Evidence `{d.evidence_quality}/2` · "
            f"Career `{d.career_leverage}/2`"
        ),
        f"- **What Is Net-New:** {net_new}",
        f"- **Suggested Refinement (Review Before Applying):** {refinement}",
        f"- **Staff SWE / FDE Takeaway:** {career}",
        f"- **Counterargument to Drop (Anti-Bloat Check):** {counter}",
    ]
    if evidence:
        lines.append(f"- **Grounded Evidence:** {evidence}")
    lines.append("")
    return "\n".join(lines)


def merge_into_weekly_digest(
    existing_markdown: str | None,
    iso_week: str,
    new_survivors: list[ScoredSurvivor],
    *,
    updated_at: str,
) -> tuple[str, int]:
    """Idempotently create or append staged survivors into `radar/{iso_week}-digest.md`.

    Returns `(updated_markdown, added_count)`.
    """
    existing = (existing_markdown or "").strip()
    existing_ids = {item_id for item_id, _, _ in parse_radar_markers(existing)}

    to_add = [s for s in new_survivors if s.item.item_id not in existing_ids]
    if not existing:
        header = "\n".join(
            [
                f"# Automated Signal Radar — {iso_week}",
                "",
                f"- **Last Updated:** `{updated_at}`",
                "- **Policy:** Fail-closed staged draft (`CLEANUP UNDO`). Only net-new deltas scoring `>= 6/10` appear here. Review and promote proven refinements manually into `playbooks/`, `templates/`, or `skills/`.",
                "",
                "---",
                "",
            ]
        )
        body = "\n".join(render_survivor_entry(s) for s in to_add)
        return (header + body).rstrip() + "\n", len(to_add)

    if not to_add:
        return existing + "\n", 0

    updated_header = re.sub(
        r"^- \*\*Last Updated:\*\* `[^`]+`",
        f"- **Last Updated:** `{updated_at}`",
        existing,
        count=1,
        flags=re.MULTILINE,
    )
    appended = "\n".join(render_survivor_entry(s) for s in to_add)
    return (updated_header.rstrip() + "\n\n" + appended).rstrip() + "\n", len(to_add)


def enforce_stage3_coherence_guardrails(
    verdict: Stage3CoherenceVerdict,
    valid_item_ids: set[str],
) -> Stage3CoherenceVerdict:
    """Apply deterministic Python Harness Walls to a Stage 3 Coherence Gate verdict.

    - Drops unknown `item_id`s and filters `affected_repo_files` / `target_repo_files`.
    - Fails closed on any item with `>= 1` Systemic Poison boolean set (downgrades to `REJECT_ENTROPY`).
    - Filters `syntheses` to only poison-free approvable items; forces `REJECT_ALL` if none remain.
    """
    cleaned_audits = []
    approvable_ids: set[str] = set()
    seen_audit_ids: set[str] = set()

    for audit in verdict.item_audits:
        if audit.item_id not in valid_item_ids or audit.item_id in seen_audit_ids:
            continue
        seen_audit_ids.add(audit.item_id)
        item_copy = audit.model_copy(deep=True)
        item_copy.affected_repo_files = filter_allowed_repo_paths(item_copy.affected_repo_files)
        item_copy.related_item_ids = [
            rid for rid in item_copy.related_item_ids if rid in valid_item_ids
        ]
        if item_copy.poisons.has_any() and item_copy.verdict in (
            "APPROVE_SYNTHESIS",
            "COMPOUNDS_WITH",
        ):
            item_copy.verdict = "REJECT_ENTROPY"
        if (
            item_copy.verdict in ("APPROVE_SYNTHESIS", "COMPOUNDS_WITH")
            and not item_copy.poisons.has_any()
        ):
            approvable_ids.add(item_copy.item_id)
        cleaned_audits.append(item_copy)

    if verdict.decision != "APPROVE_SYNTHESIS":
        return Stage3CoherenceVerdict(
            decision="REJECT_ALL",
            executive_summary=verdict.executive_summary,
            item_audits=cleaned_audits,
            syntheses=[],
        )

    cleaned_syntheses: list[Stage3SynthesisProposal] = []
    for prop in verdict.syntheses:
        valid_sources = [iid for iid in dict.fromkeys(prop.source_item_ids) if iid in approvable_ids]
        if not valid_sources:
            continue
        prop_copy = prop.model_copy(deep=True)
        prop_copy.source_item_ids = valid_sources
        prop_copy.target_repo_files = filter_allowed_repo_paths(prop_copy.target_repo_files)
        cleaned_syntheses.append(prop_copy)

    if not cleaned_syntheses:
        return Stage3CoherenceVerdict(
            decision="REJECT_ALL",
            executive_summary=verdict.executive_summary,
            item_audits=cleaned_audits,
            syntheses=[],
        )

    return Stage3CoherenceVerdict(
        decision="APPROVE_SYNTHESIS",
        executive_summary=verdict.executive_summary,
        item_audits=cleaned_audits,
        syntheses=cleaned_syntheses,
    )


def approved_stage3_item_ids(verdict: Stage3CoherenceVerdict | None) -> list[str]:
    """Return ordered unique `item_id`s approved across Stage 3 unified syntheses."""
    if verdict is None or verdict.decision != "APPROVE_SYNTHESIS":
        return []
    ordered: list[str] = []
    seen: set[str] = set()
    for prop in verdict.syntheses:
        for iid in prop.source_item_ids:
            if iid not in seen:
                seen.add(iid)
                ordered.append(iid)
    return ordered


def render_stage3_synthesis_entry(
    proposal: Stage3SynthesisProposal,
    items_by_id: dict[str, CandidateSummary],
) -> str:
    """Render one sanitized Stage 3 unified synthesis section with deterministic radar-id markers."""
    title = sanitize_single_line(proposal.title, max_chars=180)
    allowed_targets = filter_allowed_repo_paths(proposal.target_repo_files)
    targets = ", ".join(f"`{t}`" for t in allowed_targets) or "`radar/`"
    thesis = sanitize_markdown_text(proposal.unified_thesis, max_chars=1000)
    changes = sanitize_markdown_text(proposal.proposed_repo_changes, max_chars=1200)
    pruning = sanitize_markdown_text(proposal.harmonization_and_pruning, max_chars=600)
    career = sanitize_markdown_text(proposal.career_takeaway, max_chars=400)

    markers: list[str] = []
    source_parts: list[str] = []
    for iid in proposal.source_item_ids:
        summary = items_by_id.get(iid)
        if summary is not None:
            raw_domain = summary.domain or extract_domain(summary.canonical_url)
            safe_domain = re.sub(r"[^A-Za-z0-9_.\-]", "", raw_domain) or "source"
            safe_url = canonicalize_url(summary.canonical_url)
            src_label = sanitize_single_line(summary.feed_name or summary.feed_id, max_chars=80)
            src_title = sanitize_single_line(summary.title, max_chars=140)
            markers.append(format_radar_marker(iid, summary.feed_id, safe_domain))
            source_parts.append(f"{src_label} ([`{safe_domain}`]({safe_url}): {src_title})")
        else:
            markers.append(format_radar_marker(iid, "unknown", "unknown"))
            source_parts.append(f"`{iid}`")

    lines = [
        *markers,
        f"### [COHERENCE GATE · SYNTHESIS] {title}",
        f"- **Sources ({len(proposal.source_item_ids)}):** {', '.join(source_parts)}",
        f"- **Target Repo Files:** {targets}",
        f"- **Unified Thesis:** {thesis}",
        f"- **Proposed Repo Changes:** {changes}",
    ]
    if pruning:
        lines.append(f"- **Harmonization and Pruning:** {pruning}")
    if career:
        lines.append(f"- **Staff SWE / FDE Takeaway:** {career}")
    lines.append("")
    return "\n".join(lines)


def merge_stage3_synthesis_into_weekly_digest(
    existing_markdown: str | None,
    iso_week: str,
    verdict: Stage3CoherenceVerdict,
    items_by_id: dict[str, CandidateSummary],
    *,
    updated_at: str,
) -> tuple[str, int]:
    """Idempotently create or append Stage 3 approved syntheses into `radar/{iso_week}-digest.md`.

    Returns `(updated_markdown, added_source_item_count)`. Emits `0` additions on `REJECT_ALL`.
    """
    existing = (existing_markdown or "").strip()
    if verdict.decision != "APPROVE_SYNTHESIS" or not verdict.syntheses:
        return (existing + "\n") if existing else "", 0

    existing_ids = {item_id for item_id, _, _ in parse_radar_markers(existing)}
    proposals_to_add: list[Stage3SynthesisProposal] = []
    added_ids: set[str] = set()

    for prop in verdict.syntheses:
        new_ids = [iid for iid in prop.source_item_ids if iid not in existing_ids]
        if not new_ids:
            continue
        proposals_to_add.append(prop)
        added_ids.update(new_ids)

    if not proposals_to_add:
        return (existing + "\n") if existing else "", 0

    if not existing:
        header = "\n".join(
            [
                f"# Automated Signal Radar — {iso_week}",
                "",
                f"- **Last Updated:** `{updated_at}`",
                "- **Policy:** Fail-closed Stage 3 Coherence Gate draft (`CLEANUP UNDO`). Only poison-free syntheses approved by `gemini-4-neon` appear here. Review and promote edits manually.",
                "",
                "---",
                "",
            ]
        )
        body = "\n".join(render_stage3_synthesis_entry(p, items_by_id) for p in proposals_to_add)
        return (header + body).rstrip() + "\n", len(added_ids)

    updated_header = re.sub(
        r"^- \*\*Last Updated:\*\* `[^`]+`",
        f"- **Last Updated:** `{updated_at}`",
        existing,
        count=1,
        flags=re.MULTILINE,
    )
    appended = "\n".join(render_stage3_synthesis_entry(p, items_by_id) for p in proposals_to_add)
    return (updated_header.rstrip() + "\n\n" + appended).rstrip() + "\n", len(added_ids)
