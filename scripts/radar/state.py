"""Backward-compatible state persistence, PR outcome reconciliation, and feed health reporting.

State files (`seen.json`, `feed-health.json`, `pending-candidates.json`, `weekly-audits.md`)
live on the dedicated orphan branch `radar-state` so `main` remains clean and branch-protected.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from scripts.radar.config import MAX_SEEN_ITEMS
from scripts.radar.fetcher import (
    classify_source,
    classify_source_key,
    extract_source_key,
    is_source_subscribed,
    normalize_source_key,
    resolve_feed_hint,
    subscribed_source_keys,
)
from scripts.radar.models import (
    PENDING_BUFFER_MIN_SCORE,
    CandidateSummary,
    DomainHitRecord,
    FeedHealthState,
    FeedRegistry,
    FeedStats,
    PendingCandidate,
    PendingCandidatesState,
    RunResult,
    SeenState,
)
from scripts.radar.rubric import approved_stage3_item_ids
from scripts.radar.security import (
    filter_allowed_repo_paths,
    redact_secrets,
    sanitize_markdown_text,
    sanitize_single_line,
)


def _load_json_dict(path: Path) -> dict[str, Any]:
    """Load a JSON object from `path`, returning `{}` when absent or 0-byte/whitespace-only."""
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in state file {path}: {exc}") from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"Expected JSON object in state file {path}, got {type(raw).__name__}")
    return raw


def load_seen_state(path: Path) -> SeenState:
    """Load seen.json safely with backward-compatible defaults when absent or empty."""
    return SeenState.model_validate(_load_json_dict(path))


def save_seen_state(path: Path, state: SeenState) -> None:
    """Persist seen.json with stable sorted keys for clean git diffs on radar-state."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_feed_health(path: Path) -> FeedHealthState:
    """Load feed-health.json safely with backward-compatible defaults when absent or empty."""
    return FeedHealthState.model_validate(_load_json_dict(path))


def save_feed_health(path: Path, state: FeedHealthState) -> None:
    """Persist feed-health.json with stable sorted keys."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_pending_candidates(path: Path) -> PendingCandidatesState:
    """Load pending-candidates.json safely with backward-compatible empty defaults when absent or empty."""
    return PendingCandidatesState.model_validate(_load_json_dict(path))


def save_pending_candidates(path: Path, state: PendingCandidatesState) -> None:
    """Persist pending-candidates.json with stable sorted keys for clean git diffs on radar-state."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def apply_run_result_to_pending(
    pending: PendingCandidatesState,
    result: RunResult,
) -> PendingCandidatesState:
    """Buffer Mon-Sat survivors (`>= 7/10`) or clear the buffer after a completed weekly Coherence Gate run."""
    updated = pending.model_copy(deep=True)
    if result.status in ("FETCH_INCOMPLETE", "FAILED") or result.mode == "bootstrap":
        return updated
    if bool(result.fast_lane_url) and result.mode == "observe":
        return updated

    stage3_errored = any(err.stage == "stage3" for err in result.stage_errors)
    gate_completed = result.run_coherence_gate and (
        result.coherence_gate_completed
        or (
            result.stage3_verdict is not None
            and not result.cost_cap_triggered
            and not stage3_errored
        )
    )
    if gate_completed:
        updated.items.clear()
        updated.updated_at = result.run_at
        return updated

    for scored in result.buffered_items:
        if (
            scored.disposition in ("STAGE", "HIGH_SIGNAL")
            and scored.score >= PENDING_BUFFER_MIN_SCORE
        ):
            updated.items[scored.item.item_id] = PendingCandidate(
                item=scored.item,
                analysis=scored.analysis,
                score=scored.score,
                disposition=scored.disposition,
                gate_failure_reason=scored.gate_failure_reason,
                buffered_at=result.run_at,
                iso_week=result.iso_week,
            )
    if result.buffered_items:
        updated.updated_at = result.run_at
    return updated


def _candidate_summaries_by_id(result: RunResult) -> dict[str, CandidateSummary]:
    """Build an item_id -> CandidateSummary map from RunResult fields."""
    by_id: dict[str, CandidateSummary] = {cs.item_id: cs for cs in result.candidate_summaries}
    for s in (*result.stage2_results, *result.staged_items):
        if s.item.item_id not in by_id:
            by_id[s.item.item_id] = CandidateSummary(
                item_id=s.item.item_id,
                feed_id=s.item.feed_id,
                feed_name=s.item.feed_name,
                title=s.item.title,
                url=s.item.url,
                canonical_url=s.item.canonical_url,
                domain=s.item.domain,
                body_chars=len(s.item.body),
                word_count=len(s.item.body.split()),
                enrichment_status=s.item.enrichment_status,
                discovered_feed_url=s.item.discovered_feed_url,
            )
    return by_id


def apply_run_result_to_state(
    seen: SeenState,
    health: FeedHealthState,
    result: RunResult,
    *,
    max_seen_items: int = MAX_SEEN_ITEMS,
    registry: FeedRegistry | None = None,
) -> tuple[SeenState, FeedHealthState]:
    """Deterministically apply a validated Job 1 RunResult into seen & feed-health state."""
    updated_seen = seen.model_copy(deep=True)
    updated_health = health.model_copy(deep=True)

    skip_seen_burn = result.status in ("FETCH_INCOMPLETE", "FAILED") or (
        bool(result.fast_lane_url) and result.mode == "observe"
    )
    if not skip_seen_burn:
        updated_seen.updated_at = result.run_at
        for item_id, rec in result.new_seen_records.items():
            if rec.verdict == "FETCH_INCOMPLETE":
                continue
            if rec.feed_id == "fast-lane" and result.mode == "observe":
                continue
            updated_seen.items[item_id] = rec

        if len(updated_seen.items) > max_seen_items:
            sorted_pairs = sorted(
                updated_seen.items.items(),
                key=lambda kv: (kv[1].first_seen_at or "", kv[0]),
                reverse=True,
            )[:max_seen_items]
            updated_seen.items = dict(sorted_pairs)

    updated_health.updated_at = result.run_at
    for fs in result.feed_summaries:
        stats = updated_health.feeds.setdefault(fs.feed_id, FeedStats())
        if fs.ok:
            if result.mode != "bootstrap":
                stats.items_fetched += fs.new_count
            if result.mode == "enforce":
                stats.enforce_items_fetched += fs.new_count
            stats.consecutive_fetch_errors = 0
            stats.last_error = ""
            stats.last_success_at = result.run_at
        else:
            stats.consecutive_fetch_errors += 1
            stats.last_error = redact_secrets(fs.error)[:240]

    # Track Stage 1 survivors & Stage 2 staged counts per feed
    survivor_ids = {v.item_id for v in result.stage1_verdicts if v.verdict == "SURVIVOR"}
    for item_id in survivor_ids:
        rec = result.new_seen_records.get(item_id)
        if rec and rec.feed_id:
            stats = updated_health.feeds.setdefault(rec.feed_id, FeedStats())
            stats.stage1_survivors += 1

    is_observe_fast_lane = result.mode == "observe" and bool(result.fast_lane_url)
    staged_ids: set[str] = set()
    for staged in result.staged_items:
        staged_ids.add(staged.item.item_id)
        if is_observe_fast_lane or (
            result.mode == "observe" and staged.item.feed_id == "fast-lane"
        ):
            continue
        stats = updated_health.feeds.setdefault(staged.item.feed_id, FeedStats())
        stats.stage2_staged += 1

    # Also count direct fast-lane Stage 3 approvals that bypassed Stage 2 (except observe fast-lane)
    summaries_by_id = _candidate_summaries_by_id(result)
    approved_ids = approved_stage3_item_ids(result.stage3_verdict)
    for iid in approved_ids:
        if iid in staged_ids:
            continue
        cs = summaries_by_id.get(iid)
        if cs and cs.feed_id:
            if is_observe_fast_lane or (result.mode == "observe" and cs.feed_id == "fast-lane"):
                continue
            stats = updated_health.feeds.setdefault(cs.feed_id, FeedStats())
            stats.stage2_staged += 1

    # Track Stage 3 approved items from unsubscribed sources (deduplicated strictly by item_id)
    if (
        result.mode != "bootstrap"
        and result.stage3_verdict is not None
        and result.stage3_verdict.decision == "APPROVE_SYNTHESIS"
    ):
        subscribed = subscribed_source_keys(registry) if registry is not None else set()
        for iid in approved_ids:
            cs = summaries_by_id.get(iid)
            if cs is None:
                continue
            source_key = (
                extract_source_key(cs.canonical_url)
                if cs.canonical_url
                else normalize_source_key(cs.domain)
            )
            if not source_key:
                continue
            if subscribed and is_source_subscribed(source_key, subscribed):
                continue
            hit = updated_health.unsubscribed_domain_hits.setdefault(
                source_key, DomainHitRecord()
            )
            src_class = (
                classify_source(cs.canonical_url)
                if cs.canonical_url
                else classify_source_key(source_key)
            )
            if src_class == "serial_publisher" or not hit.source_class:
                hit.source_class = src_class
            if cs.discovered_feed_url:
                hit.discovered_feed_url = cs.discovered_feed_url
            if iid not in hit.approved_item_ids:
                hit.approved_item_ids.append(iid)
                hit.approved_dates.append(result.run_at)

    return updated_seen, updated_health


def load_weekly_audits(path: Path) -> str:
    """Load weekly-audits.md safely with backward-compatible empty default when absent."""
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def format_weekly_audit_entry(result: RunResult) -> str:
    """Render a sanitized Markdown audit section for `radar-state/weekly-audits.md`."""
    verdict = result.stage3_verdict
    if verdict is None:
        return ""

    summaries_by_id = _candidate_summaries_by_id(result)
    route = "fast-lane" if result.fast_lane_url else "weekly-coherence-gate"
    run_date = sanitize_single_line(result.run_at[:10], 20)
    marker = f"<!-- radar-audit: {result.iso_week} run_at: {sanitize_single_line(result.run_at, 64)} -->"
    exec_summary = sanitize_single_line(verdict.executive_summary, 800)

    lines = [
        marker,
        f"## {result.iso_week} — `{verdict.decision}` ({run_date})",
        "",
        f"- **Run Timestamp:** `{sanitize_single_line(result.run_at, 64)}` · **Mode:** `{result.mode}` · **Route:** `{route}`",
        f"- **Executive Summary:** {exec_summary}",
        "",
    ]

    if verdict.item_audits:
        lines.extend(
            [
                "| Item ID | Title | Verdict | Systemic Poisons | Related IDs | Affected Files | Rationale |",
                "|---|---|---|---|---|---|---|",
            ]
        )
        for audit in verdict.item_audits:
            cs = summaries_by_id.get(audit.item_id)
            title_cell = sanitize_single_line(cs.title if cs else audit.item_id, 120)
            poisons_cell = ", ".join(audit.poisons.active_poisons()) or "none"
            related_cell = ", ".join(audit.related_item_ids) or "-"
            files_cell = ", ".join(filter_allowed_repo_paths(audit.affected_repo_files)) or "-"
            rationale_cell = sanitize_single_line(audit.rationale, 500)
            lines.append(
                f"| `{audit.item_id}` | {title_cell} | `{audit.verdict}` | `{poisons_cell}` | "
                f"`{related_cell}` | `{files_cell}` | {rationale_cell} |"
            )
        lines.append("")

    if verdict.decision == "APPROVE_SYNTHESIS" and verdict.syntheses:
        lines.append("### Approved Syntheses")
        lines.append("")
        for prop in verdict.syntheses:
            p_title = sanitize_single_line(prop.title, 180)
            src_ids = ", ".join(prop.source_item_ids)
            allowed_targets = filter_allowed_repo_paths(prop.target_repo_files)
            targets = ", ".join(f"`{t}`" for t in allowed_targets) or "`radar/`"
            thesis = sanitize_markdown_text(prop.unified_thesis, max_chars=1000)
            changes = sanitize_markdown_text(prop.proposed_repo_changes, max_chars=1200)
            pruning = sanitize_markdown_text(prop.harmonization_and_pruning, max_chars=600)
            career = sanitize_markdown_text(prop.career_takeaway, max_chars=400)
            lines.extend(
                [
                    f"#### {p_title}",
                    f"- **Source Item IDs:** `{src_ids}`",
                    f"- **Target Repo Files:** {targets}",
                    f"- **Unified Thesis:** {thesis}",
                    f"- **Proposed Repo Changes:** {changes}",
                ]
            )
            if pruning:
                lines.append(f"- **Harmonization and Pruning:** {pruning}")
            if career:
                lines.append(f"- **Staff SWE / FDE Takeaway:** {career}")
            lines.append("")

    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def append_weekly_audit(path: Path, result: RunResult) -> bool:
    """Idempotently create or append a Stage 3 audit entry to `radar-state/weekly-audits.md`.

    Returns True when a new audit entry was written, False when skipped or already logged.
    """
    if result.stage3_verdict is None:
        return False

    marker = f"<!-- radar-audit: {result.iso_week} run_at: {sanitize_single_line(result.run_at, 64)} -->"
    existing = load_weekly_audits(path).strip()
    if marker in existing:
        return False

    entry = format_weekly_audit_entry(result)
    if not entry:
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    if not existing:
        header = "\n".join(
            [
                "# Weekly Coherence Gate Audit Log",
                "",
                "Append-only log of Stage 3 (`gemini-4-neon`, `HIGH`) systemic coherence decisions, "
                "poison rejections, and approved syntheses on orphan branch `radar-state`.",
                "",
                "---",
                "",
            ]
        )
        content = header + entry
    else:
        content = existing + "\n\n" + entry

    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return True


def reconcile_pr_outcome(
    health: FeedHealthState,
    registry: FeedRegistry,
    *,
    pr_number: int,
    merged: bool,
    staged_markers: list[tuple[str, str, str]],
    landed_item_ids: set[str],
    reconciled_at: str | None = None,
) -> FeedHealthState:
    """Update per-feed human merge/reject counts and unsubscribed domain promotion hits.

    Args:
        health: Current FeedHealthState.
        registry: Current FeedRegistry (used to identify already-subscribed domains/source keys).
        pr_number: GitHub PR number being reconciled (idempotent via reconciled_prs).
        merged: Whether the PR was merged (True) or closed without merging (False).
        staged_markers: All `(item_id, feed_id, domain)` entries that were in the PR.
        landed_item_ids: Set of `item_id`s that actually landed on `main` after merge.
        reconciled_at: ISO timestamp for merge date tracking.
    """
    updated = health.model_copy(deep=True)
    if pr_number in updated.reconciled_prs:
        return updated

    now_iso = reconciled_at or datetime.now(UTC).isoformat()
    subscribed_keys = subscribed_source_keys(registry)

    seen_marker_ids: set[str] = set()
    for item_id, feed_id, domain in staged_markers:
        if item_id in seen_marker_ids:
            continue
        seen_marker_ids.add(item_id)
        stats = updated.feeds.setdefault(feed_id, FeedStats())
        if merged and item_id in landed_item_ids:
            stats.human_merged += 1
            stats.last_merged_at = now_iso
            source_key = normalize_source_key(domain)
            if source_key and not is_source_subscribed(source_key, subscribed_keys):
                hit = updated.unsubscribed_domain_hits.setdefault(source_key, DomainHitRecord())
                if not hit.source_class:
                    hit.source_class = classify_source_key(source_key)
                if item_id not in hit.merged_item_ids:
                    hit.merged_item_ids.append(item_id)
                    hit.merged_dates.append(now_iso)
        else:
            stats.human_closed_rejected += 1

    updated.reconciled_prs.append(pr_number)
    updated.updated_at = now_iso
    return updated


def _is_within_window(raw_dt: str, cutoff: datetime) -> bool:
    if not raw_dt:
        return True
    try:
        dt = datetime.fromisoformat(raw_dt.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt >= cutoff
    except ValueError:
        return True


def recent_distinct_source_item_ids(
    rec: DomainHitRecord,
    cutoff: datetime,
) -> tuple[set[str], set[str]]:
    """Return `(recent_merged_ids, recent_approved_ids)` within the cutoff window."""
    recent_merged: set[str] = set()
    if rec.merged_item_ids:
        for idx, iid in enumerate(rec.merged_item_ids):
            raw_dt = rec.merged_dates[idx] if idx < len(rec.merged_dates) else ""
            if _is_within_window(raw_dt, cutoff):
                recent_merged.add(iid)
    elif rec.merged_dates:
        for idx, raw_dt in enumerate(rec.merged_dates):
            if _is_within_window(raw_dt, cutoff):
                recent_merged.add(f"__merged_date_{idx}")

    recent_approved: set[str] = set()
    if rec.approved_item_ids:
        for idx, iid in enumerate(rec.approved_item_ids):
            raw_dt = rec.approved_dates[idx] if idx < len(rec.approved_dates) else ""
            if _is_within_window(raw_dt, cutoff):
                recent_approved.add(iid)
    elif rec.approved_dates:
        for idx, raw_dt in enumerate(rec.approved_dates):
            if _is_within_window(raw_dt, cutoff):
                recent_approved.add(f"__approved_date_{idx}")

    return recent_merged, recent_approved


def count_recent_distinct_source_hits(
    rec: DomainHitRecord,
    cutoff: datetime,
) -> tuple[int, int, int]:
    """Return `(total_distinct, merged_recent, approved_only_recent)` across merged ∪ approved."""
    recent_merged, recent_approved = recent_distinct_source_item_ids(rec, cutoff)
    union_ids = recent_merged | recent_approved
    return len(union_ids), len(recent_merged), len(recent_approved - recent_merged)


def _collect_health_candidates(
    health: FeedHealthState,
    registry: FeedRegistry,
    *,
    now: datetime | None = None,
    window_days: int = 90,
) -> tuple[datetime, list[str], list[str], list[str]]:
    """Compute per-feed rows, prune candidates, and manual promotion candidates."""
    current = now or datetime.now(UTC)
    cutoff = current - timedelta(days=window_days)

    prune_candidates: list[str] = []
    healthy_rows: list[str] = []

    for feed in registry.feeds:
        s = health.feeds.get(feed.id, FeedStats())
        reviewed = s.human_merged + s.human_closed_rejected
        reject_rate = (s.human_closed_rejected / reviewed) if reviewed > 0 else 0.0

        reasons: list[str] = []
        if s.consecutive_fetch_errors >= 3:
            reasons.append(f"{s.consecutive_fetch_errors} consecutive fetch errors")
        if reviewed >= 3 and reject_rate > 0.90:
            reasons.append(
                f"{reject_rate:.0%} human rejection rate ({s.human_closed_rejected}/{reviewed})"
            )
        if (
            s.human_merged == 0
            and s.last_success_at
            and (len(health.reconciled_prs) >= 4 or s.enforce_items_fetched >= 30)
        ):
            reasons.append("0 human-merged items in window")

        if reasons:
            prune_candidates.append(f"- **`{feed.id}`** ({feed.name}): {'; '.join(reasons)}")

        healthy_rows.append(
            f"| `{feed.id}` | {s.items_fetched} | {s.stage1_survivors} | {s.stage2_staged} | "
            f"{s.human_merged} | {s.human_closed_rejected} | {s.consecutive_fetch_errors} |"
        )

    subscribed_keys = subscribed_source_keys(registry)
    promote_candidates: list[str] = []
    for source_key, rec in sorted(health.unsubscribed_domain_hits.items()):
        norm_key = normalize_source_key(source_key)
        if not norm_key or is_source_subscribed(norm_key, subscribed_keys):
            continue
        total_distinct, merged_recent, approved_only_recent = count_recent_distinct_source_hits(
            rec, cutoff
        )
        if total_distinct < 2:
            continue
        if approved_only_recent == 0:
            count_label = f"{merged_recent} human-merged items"
        elif merged_recent == 0:
            count_label = f"{total_distinct} Stage 3-approved items"
        else:
            count_label = (
                f"{total_distinct} distinct items "
                f"({merged_recent} human-merged, {approved_only_recent} Stage 3-approved)"
            )
        feed_hint = resolve_feed_hint(norm_key, rec.discovered_feed_url)
        hint_clause = f" · feed hint: `{sanitize_single_line(feed_hint, 200)}`" if feed_hint else ""
        promote_candidates.append(
            f"- **`{norm_key}`**: {count_label} in last {window_days}d{hint_clause} — "
            f"consider adding RSS/Atom feed to `radar/feeds.yaml`."
        )

    return current, healthy_rows, prune_candidates, promote_candidates


def generate_feed_health_report(
    health: FeedHealthState,
    registry: FeedRegistry,
    *,
    now: datetime | None = None,
    window_days: int = 90,
) -> str:
    """Emit a quarterly Markdown report flagging prune & manual promotion candidates."""
    current, healthy_rows, prune_candidates, promote_candidates = _collect_health_candidates(
        health, registry, now=now, window_days=window_days
    )
    lines = [
        "# Radar Feed Health & Pruning Report",
        "",
        f"- **Generated:** `{current.isoformat()}`",
        f"- **Evaluation Window:** Last `{window_days}` days",
        "",
        "## Per-Feed Telemetry",
        "",
        "| Feed ID | Fetched | Stage 1 Survivors | Stage 2 Staged | Human Merged | Rejected | Consecutive Errors |",
        "|---|---:|---:|---:|---:|---:|---:|",
        *healthy_rows,
        "",
        "## Prune Candidates (Review Manually)",
        *(prune_candidates or ["- None flagged."]),
        "",
        "## Promotion Candidates (>= 2 Distinct Items in 90d from Unsubscribed Sources)",
        *(promote_candidates or ["- None yet."]),
        "",
    ]
    return "\n".join(lines)


def format_active_health_summary(
    health: FeedHealthState,
    registry: FeedRegistry,
    *,
    now: datetime | None = None,
    window_days: int = 90,
) -> str:
    """Return compact Markdown alerts for Job 2 `$GITHUB_STEP_SUMMARY` only when >= 1 candidate is flagged."""
    _, _, prune_candidates, promote_candidates = _collect_health_candidates(
        health, registry, now=now, window_days=window_days
    )
    if not prune_candidates and not promote_candidates:
        return ""

    lines = ["## Active Radar Feed Health Alerts", ""]
    if prune_candidates:
        lines.extend(["### Prune Candidates (Review Manually)", *prune_candidates, ""])
    if promote_candidates:
        lines.extend(
            [
                "### Promotion Candidates (>= 2 Distinct Items in 90d from Unsubscribed Sources)",
                *promote_candidates,
                "",
            ]
        )
    return "\n".join(lines)
