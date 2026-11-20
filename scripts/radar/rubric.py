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
from scripts.radar.models import CandidateItem, ScoredSurvivor, Stage2Analysis
from scripts.radar.security import sanitize_markdown_text, sanitize_single_line

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
    badge = "HIGH SIGNAL" if scored.disposition == "HIGH_SIGNAL" else "STAGE"
    targets = ", ".join(f"`{sanitize_single_line(t, 80)}`" for t in a.target_repo_files) or "`radar/`"
    net_new = sanitize_markdown_text(a.what_is_net_new, max_chars=800)
    refinement = sanitize_markdown_text(a.proposed_refinement, max_chars=800)
    career = sanitize_markdown_text(a.career_takeaway, max_chars=400)
    counter = sanitize_markdown_text(a.counterargument_to_drop, max_chars=400)
    evidence = sanitize_markdown_text(a.evidence_quote, max_chars=300)

    marker = format_radar_marker(item.item_id, item.feed_id, item.domain)
    lines = [
        marker,
        f"### [{scored.score}/10 · {badge}] {title}",
        f"- **Source:** {feed_name} · [`{item.domain}`]({item.canonical_url})",
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
                "- **Policy:** Fail-closed staged draft (`CLEANUP UNDO`). Only net-new deltas scoring ≥ 6/10 appear here. Review and promote proven refinements manually into `playbooks/`, `templates/`, or `skills/`.",
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
