"""Pipeline orchestrator and CLI entrypoints for the Automated Signal Ingestion Pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from scripts.radar.config import PipelineConfig
from scripts.radar.fetcher import (
    FetchIncompleteError,
    build_fast_lane_candidate,
    canonicalize_url,
    enrich_survivor_body,
    extract_domain,
    fetch_candidates,
    load_feed_registry,
    make_item_id,
)
from scripts.radar.inventory import (
    build_repo_inventory,
    load_full_repo_baseline,
    load_target_repo_context,
)
from scripts.radar.llm import (
    BudgetExceededError,
    GeminiRadarClient,
    RadarLLMClient,
    StructuredOutputError,
    de_anchor_candidate,
)
from scripts.radar.models import (
    PENDING_BUFFER_MIN_SCORE,
    CandidateItem,
    CandidateSummary,
    DeAnchoredCandidate,
    FeedFetchSummary,
    PendingCandidatesState,
    RunResult,
    ScoredSurvivor,
    SeenRecord,
    SeenState,
    Stage1ItemVerdict,
    Stage3CoherenceVerdict,
    StageErrorRecord,
)
from scripts.radar.rubric import (
    approved_stage3_item_ids,
    enforce_stage3_coherence_guardrails,
    merge_stage3_synthesis_into_weekly_digest,
    score_stage2_analysis,
)
from scripts.radar.security import (
    filter_allowed_repo_paths,
    redact_secrets,
    sanitize_single_line,
)
from scripts.radar.state import (
    append_weekly_audit,
    apply_run_result_to_pending,
    apply_run_result_to_state,
    generate_feed_health_report,
    load_feed_health,
    load_pending_candidates,
    load_seen_state,
    save_feed_health,
    save_pending_candidates,
    save_seen_state,
)


def current_iso_week(now: datetime | None = None) -> str:
    """Return ISO week label like `2026-W47`."""
    dt = now or datetime.now(UTC)
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _record_stage_error(
    result: RunResult,
    *,
    stage: str,
    item_ids: list[str],
    exc: Exception,
) -> None:
    """Append a sanitized stage error record and emit a GitHub Actions warning annotation."""
    finish_reason = str(getattr(exc, "finish_reason", "") or "")
    safe_msg = sanitize_single_line(redact_secrets(str(exc)), 300)
    err = StageErrorRecord(
        stage=stage,  # type: ignore[arg-type]
        item_ids=list(item_ids),
        error_type=type(exc).__name__,
        message=safe_msg,
        finish_reason=finish_reason,
    )
    result.stage_errors.append(err)
    ids_label = ",".join(item_ids[:5]) if item_ids else "none"
    print(
        f"::warning title=Radar {stage} error ({err.error_type})::"
        f"items={ids_label} finish_reason={finish_reason or 'n/a'} {safe_msg}",
        file=sys.stderr,
    )


def _write_github_output(path: Path, values: dict[str, object]) -> None:
    """Append sanitized single-line key=value pairs to a $GITHUB_OUTPUT file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for key, val in values.items():
        if isinstance(val, bool):
            rendered = "true" if val else "false"
        else:
            rendered = str(val).replace("\r", " ").replace("\n", " ").strip()
        lines.append(f"{key}={rendered}")
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def _to_candidate_summary(item: CandidateItem) -> CandidateSummary:
    return CandidateSummary(
        item_id=item.item_id,
        feed_id=item.feed_id,
        feed_name=item.feed_name,
        title=item.title,
        url=item.url,
        canonical_url=item.canonical_url,
        domain=item.domain,
        body_chars=len(item.body),
        word_count=len(item.body.split()),
        enrichment_status=item.enrichment_status,
    )


def build_job_summary_markdown(result: RunResult) -> str:
    """Format a self-contained, sanitized Markdown summary for GitHub Actions & PR bodies."""
    fast_lane_display = (
        sanitize_single_line(result.fast_lane_url, 200) if result.fast_lane_url else "none"
    )
    lines = [
        f"## Radar Ingestion Summary — `{result.iso_week}` (`{result.mode}`)",
        "",
        f"- **Run timestamp:** `{sanitize_single_line(result.run_at, 64)}`",
        (
            f"- **Run inputs:** `mode={result.mode}` · `fast_lane_url={fast_lane_display}` · "
            f"`force={str(result.force).lower()}` · `run_coherence_gate={str(result.run_coherence_gate).lower()}`"
        ),
        f"- **Pipeline status:** `{result.status}`"
        + (
            f" (`{sanitize_single_line(result.error_code, 40)}`)"
            if result.error_code and result.error_code != result.status
            else ""
        ),
        f"- **New candidates after Stage 0:** `{result.candidates_fetched}`",
        f"- **Stage 1 reviewed:** `{result.stage1_reviewed}`",
        f"- **Stage 2 evaluated:** `{len(result.stage2_results)}`",
        f"- **Buffered for weekly gate (score ≥ 7/10):** `{len(result.buffered_items)}`"
        + (
            f" (Drained from pending buffer: `{len(result.drained_item_ids)}`)"
            if result.drained_item_ids
            else ""
        ),
        f"- **Staged (Stage 3 approved):** `{len(approved_stage3_item_ids(result.stage3_verdict)) if result.stage3_verdict else len(result.staged_items)}` (High Signal ≥ 9/10: `{'yes' if result.has_high_signal else 'no'}`)",
        *(
            [
                f"- **Stage 3 Coherence Gate:** `{result.stage3_verdict.decision}` "
                f"(audited: `{len(result.stage3_verdict.item_audits)}`, "
                f"syntheses: `{len(result.stage3_verdict.syntheses)}`)"
            ]
            if result.stage3_verdict is not None
            else []
        ),
        f"- **Estimated API cost:** `${result.total_estimated_cost_usd:.4f}`"
        + (" *(cost cap triggered)*" if result.cost_cap_triggered else ""),
    ]
    if result.traces:
        models_used = sorted(
            {
                f"{t.stage}:{t.requested_model}->{t.resolved_model_version or 'unreported'} ({t.api_version}/{t.thinking_level})"
                for t in result.traces
            }
        )
        lines.append(
            f"- **Models resolved:** {', '.join(f'`{sanitize_single_line(m, 90)}`' for m in models_used)}"
        )

    candidates_by_id: dict[str, CandidateSummary] = {
        cs.item_id: cs for cs in result.candidate_summaries
    }
    for s in result.stage2_results:
        if s.item.item_id not in candidates_by_id:
            candidates_by_id[s.item.item_id] = _to_candidate_summary(s.item)
    for s in result.staged_items:
        if s.item.item_id not in candidates_by_id:
            candidates_by_id[s.item.item_id] = _to_candidate_summary(s.item)

    if result.fast_lane_url and result.candidate_summaries:
        fl = result.candidate_summaries[0]
        fl_title = sanitize_single_line(fl.title, 180)
        fl_canon = sanitize_single_line(fl.canonical_url, 200)
        lines.append(
            f"- **Fast-lane extraction:** title=`{fl_title}` · canonical_url=`{fl_canon}` · "
            f"`body_chars={fl.body_chars}` · `words={fl.word_count}` · status=`{fl.enrichment_status}`"
        )

    if result.status == "FETCH_INCOMPLETE" or result.error_code == "FETCH_INCOMPLETE":
        safe_err = sanitize_single_line(redact_secrets(result.error_message), 280)
        lines.extend(
            [
                "",
                "### Fail-Closed Content Gate (`FETCH_INCOMPLETE`)",
                "",
                f"- **Reason:** {safe_err}",
            ]
        )

    if result.stage1_verdicts:
        lines.extend(
            [
                "",
                "### Stage 1 Triage Verdicts",
                "",
                "| Item ID | Feed | Title | `body_chars` | Verdict | Matched File | Drop / Triage Reason |",
                "|---|---|---|---:|---|---|---|",
            ]
        )
        for v in result.stage1_verdicts:
            cs = candidates_by_id.get(v.item_id)
            feed_cell = sanitize_single_line(cs.feed_id if cs else "", 60) or "-"
            title_cell = sanitize_single_line(cs.title if cs else v.item_id, 140)
            chars_cell = str(cs.body_chars) if cs is not None else "0"
            matched_cell = sanitize_single_line(v.matched_repo_file, 80) or "-"
            reason_cell = sanitize_single_line(v.reason, 220)
            lines.append(
                f"| `{v.item_id}` | `{feed_cell}` | {title_cell} | `{chars_cell}` | "
                f"`{v.verdict}` | `{matched_cell}` | {reason_cell} |"
            )

    if result.stage2_results:
        lines.extend(
            [
                "",
                "### Stage 2 Deep Delta Verdicts",
                "",
                "| Item ID | Title | `body_chars` | Score | Disposition | Target Files | Gate / Evaluation Summary |",
                "|---|---|---:|---:|---|---|---|",
            ]
        )
        for s in result.stage2_results:
            cs = candidates_by_id.get(s.item.item_id)
            chars_cell = str(cs.body_chars if cs is not None else len(s.item.body))
            safe_title = sanitize_single_line(s.item.title, 140)
            targets = ", ".join(filter_allowed_repo_paths(s.analysis.target_repo_files)) or "radar/"
            summary_cell = sanitize_single_line(
                s.gate_failure_reason or s.analysis.what_is_net_new, 220
            )
            lines.append(
                f"| `{s.item.item_id}` | {safe_title} | `{chars_cell}` | `{s.score}/10` | "
                f"`{s.disposition}` | `{targets}` | {summary_cell} |"
            )

    if result.stage3_verdict is not None:
        v3 = result.stage3_verdict
        lines.extend(
            [
                "",
                "### Stage 3 Systemic Coherence Gate",
                "",
                f"- **Decision:** `{v3.decision}`",
                f"- **Executive Summary:** {sanitize_single_line(v3.executive_summary, 800)}",
            ]
        )
        if v3.item_audits:
            lines.extend(
                [
                    "",
                    "| Item ID | Title | Verdict | Systemic Poisons | Related IDs | Affected Files | Rationale |",
                    "|---|---|---|---|---|---|---|",
                ]
            )
            for audit in v3.item_audits:
                cs = candidates_by_id.get(audit.item_id)
                title_cell = sanitize_single_line(cs.title if cs else audit.item_id, 120)
                poisons_cell = ", ".join(audit.poisons.active_poisons()) or "none"
                related_cell = ", ".join(audit.related_item_ids) or "-"
                files_cell = ", ".join(filter_allowed_repo_paths(audit.affected_repo_files)) or "-"
                rationale_cell = sanitize_single_line(audit.rationale, 500)
                lines.append(
                    f"| `{audit.item_id}` | {title_cell} | `{audit.verdict}` | `{poisons_cell}` | "
                    f"`{related_cell}` | `{files_cell}` | {rationale_cell} |"
                )

        if v3.decision == "APPROVE_SYNTHESIS" and v3.syntheses:
            lines.extend(["", "### Approved Unified Syntheses", ""])
            for prop in v3.syntheses:
                p_title = sanitize_single_line(prop.title, 180)
                src_ids = ", ".join(prop.source_item_ids)
                targets = ", ".join(filter_allowed_repo_paths(prop.target_repo_files)) or "radar/"
                lines.append(f"- **[APPROVE_SYNTHESIS]** {p_title} (`{src_ids}`) -> `{targets}`")
        else:
            lines.extend(
                [
                    "",
                    "_Stage 3 Coherence Gate emitted `REJECT_ALL` (0 PRs opened; audit logged to `weekly-audits.md`)._",
                ]
            )
    elif result.staged_items:
        lines.extend(["", "### Survivors Crossing the Bar", ""])
        for s in result.staged_items:
            safe_title = sanitize_single_line(s.item.title, 180)
            safe_feed = sanitize_single_line(s.item.feed_id, 60)
            targets = ", ".join(filter_allowed_repo_paths(s.analysis.target_repo_files)) or "radar/"
            lines.append(
                f"- **[{s.score}/10 · {s.disposition}]** {safe_title} (`{safe_feed}`) -> {targets}"
            )
    elif result.buffered_items:
        lines.extend(
            [
                "",
                "### Survivors Buffered in `pending-candidates.json` (Awaiting Weekly Gate)",
                "",
            ]
        )
        for s in result.buffered_items:
            safe_title = sanitize_single_line(s.item.title, 180)
            safe_feed = sanitize_single_line(s.item.feed_id, 60)
            targets = ", ".join(filter_allowed_repo_paths(s.analysis.target_repo_files)) or "radar/"
            lines.append(
                f"- **[{s.score}/10 · BUFFERED]** {safe_title} (`{safe_feed}`) -> {targets}"
            )
    else:
        lines.extend(["", "_Nothing crossed the bar this run._"])

    failed_feeds = [f for f in result.feed_summaries if not f.ok]
    if failed_feeds:
        lines.extend(["", "### Feed Fetch Errors", ""])
        for f in failed_feeds:
            safe_err = sanitize_single_line(redact_secrets(f.error), 200)
            lines.append(f"- `{sanitize_single_line(f.feed_id, 60)}`: {safe_err}")

    if result.stage_errors:
        lines.extend(
            [
                "",
                "### Pipeline / LLM Errors",
                "",
                "| Stage | Item IDs | Error Type | Finish Reason | Details |",
                "|---|---|---|---|---|",
            ]
        )
        for err in result.stage_errors:
            ids_cell = sanitize_single_line(", ".join(err.item_ids) or "-", 120)
            type_cell = sanitize_single_line(err.error_type or "Error", 60)
            reason_cell = sanitize_single_line(err.finish_reason or "-", 40)
            msg_cell = sanitize_single_line(redact_secrets(err.message), 260)
            lines.append(
                f"| `{err.stage}` | `{ids_cell}` | `{type_cell}` | `{reason_cell}` | {msg_cell} |"
            )

    lines.append("")
    return "\n".join(lines)


def run_pipeline(
    config: PipelineConfig,
    *,
    seen: SeenState,
    pending: PendingCandidatesState | None = None,
    mode: str = "observe",
    fast_lane_url: str | None = None,
    force: bool = False,
    run_coherence_gate: bool | None = None,
    llm_client: RadarLLMClient | None = None,
    http_get: Callable[[str], tuple[str, bytes]] | None = None,
    offline_candidates: list[CandidateItem] | None = None,
    exclude_repo_files: list[str] | None = None,
    now: datetime | None = None,
) -> RunResult:
    """Execute Stage 0 -> Stage 1 -> Survivor Enricher -> Stage 2 -> Buffer / Weekly Gate."""
    run_dt = now or datetime.now(UTC)
    run_at = run_dt.isoformat()
    iso_week = current_iso_week(run_dt)
    excluded = tuple(exclude_repo_files or ())
    effective_seen = SeenState() if force else seen
    if run_coherence_gate is None:
        effective_coherence_gate = (
            run_dt.isoweekday() == 7 and not fast_lane_url and mode != "bootstrap"
        )
    else:
        effective_coherence_gate = bool(run_coherence_gate) and mode != "bootstrap"

    feed_summaries: list[FeedFetchSummary] = []
    if offline_candidates is not None:
        candidates = list(offline_candidates)[: config.max_items_per_run]
    elif fast_lane_url:
        try:
            fast_candidate = build_fast_lane_candidate(
                fast_lane_url, config=config, http_get=http_get
            )
        except FetchIncompleteError as exc:
            failed_canon = exc.canonical_url or canonicalize_url(fast_lane_url)
            incomplete_result = RunResult(
                run_at=run_at,
                iso_week=iso_week,
                mode=mode,  # type: ignore[arg-type]
                fast_lane_url=fast_lane_url,
                force=force,
                run_coherence_gate=effective_coherence_gate,
                status="FETCH_INCOMPLETE",
                error_code="FETCH_INCOMPLETE",
                error_message=str(exc),
                candidate_summaries=[
                    CandidateSummary(
                        item_id=make_item_id(failed_canon),
                        feed_id="fast-lane",
                        feed_name="Fast-Lane Manual URL",
                        title=exc.title or extract_domain(failed_canon),
                        url=fast_lane_url,
                        canonical_url=failed_canon,
                        domain=extract_domain(failed_canon),
                        body_chars=exc.body_chars,
                        word_count=exc.word_count,
                        enrichment_status="fetch_incomplete",
                    )
                ],
                candidates_fetched=0,
            )
            incomplete_result.summary_markdown = build_job_summary_markdown(incomplete_result)
            return incomplete_result

        seen_urls = {rec.canonical_url for rec in effective_seen.items.values()}
        initial_id = make_item_id(canonicalize_url(fast_lane_url))
        if not force and (
            fast_candidate.item_id in effective_seen.items
            or initial_id in effective_seen.items
            or fast_candidate.canonical_url in seen_urls
        ):
            candidates = []
        else:
            candidates = [fast_candidate]
    else:
        registry = load_feed_registry(config.feeds_path)
        candidates, feed_summaries = fetch_candidates(
            registry, effective_seen, config, now=run_dt, http_get=http_get
        )

    result = RunResult(
        run_at=run_at,
        iso_week=iso_week,
        mode=mode,  # type: ignore[arg-type]
        fast_lane_url=fast_lane_url,
        force=force,
        run_coherence_gate=effective_coherence_gate,
        feed_summaries=feed_summaries,
        candidate_summaries=[_to_candidate_summary(c) for c in candidates],
        candidates_fetched=len(candidates),
    )

    # Bootstrap mode: mark all current feed items seen with $0 LLM spend
    if mode == "bootstrap":
        for item in candidates:
            result.new_seen_records[item.item_id] = SeenRecord(
                canonical_url=item.canonical_url,
                title_hash=item.title_hash,
                content_hash=item.content_hash,
                feed_id=item.feed_id,
                first_seen_at=run_at,
                verdict="BOOTSTRAP_SEEDED",
            )
        result.summary_markdown = build_job_summary_markdown(result)
        return result

    has_pending_to_drain = bool(effective_coherence_gate and pending and pending.items)
    if not candidates and not has_pending_to_drain:
        result.summary_markdown = build_job_summary_markdown(result)
        return result

    client: RadarLLMClient | None = None

    def _get_llm_client() -> RadarLLMClient:
        nonlocal client
        if client is None:
            client = llm_client or GeminiRadarClient(config)
        return client

    is_fast_lane_direct = bool(fast_lane_url) and offline_candidates is None
    qualifying_survivors: list[ScoredSurvivor] = []
    summaries_by_id = {cs.item_id: cs for cs in result.candidate_summaries}

    # Regular feeds (or offline_candidates) run Stage 1 -> Survivor Enricher -> Stage 2.
    # Verified fast_lane_url candidates bypass Stage 1 & Stage 2 directly into Stage 3.
    if candidates and not is_fast_lane_direct:
        active_client = _get_llm_client()
        repo_inventory = build_repo_inventory(config.repo_root, exclude_files=excluded)

        # Stage 1: batched zero-tool triage (up to 10 items per call)
        by_id = {c.item_id: c for c in candidates}
        verdicts_by_id: dict[str, Stage1ItemVerdict] = {}
        batch_size = max(1, config.max_stage1_batch_size)

        for start in range(0, len(candidates), batch_size):
            batch = candidates[start : start + batch_size]
            try:
                batch_resp, trace = active_client.triage_stage1_batch(batch, repo_inventory)
                result.traces.append(trace)
                result.total_estimated_cost_usd = round(
                    result.total_estimated_cost_usd + trace.estimated_cost_usd, 6
                )
                for v in batch_resp.verdicts:
                    if v.item_id in by_id and v.item_id not in verdicts_by_id:
                        verdicts_by_id[v.item_id] = v
                        result.stage1_verdicts.append(v)
            except BudgetExceededError:
                result.cost_cap_triggered = True
                break
            except (StructuredOutputError, RuntimeError) as exc:
                _record_stage_error(
                    result,
                    stage="stage1",
                    item_ids=[i.item_id for i in batch],
                    exc=exc,
                )
                continue

        result.stage1_reviewed = len(verdicts_by_id)

        # Mark reviewed candidates seen except manual observe fast-lane test runs
        skip_seen_burn = bool(fast_lane_url) and mode == "observe"
        if not skip_seen_burn:
            for item_id, verdict in verdicts_by_id.items():
                item = by_id[item_id]
                if item.feed_id == "fast-lane" and mode == "observe":
                    continue
                result.new_seen_records[item_id] = SeenRecord(
                    canonical_url=item.canonical_url,
                    title_hash=item.title_hash,
                    content_hash=item.content_hash,
                    feed_id=item.feed_id,
                    first_seen_at=run_at,
                    verdict=verdict.verdict,
                )

        survivor_verdicts = [v for v in result.stage1_verdicts if v.verdict == "SURVIVOR"][
            : config.max_stage2_survivors
        ]

        # Stage 2: enrich short-body survivors deterministically, then deep rubric delta
        for idx, sv in enumerate(survivor_verdicts):
            item = by_id[sv.item_id]
            if offline_candidates is None:
                item = enrich_survivor_body(item, config=config, http_get=http_get)
                by_id[sv.item_id] = item
                if sv.item_id in summaries_by_id:
                    summaries_by_id[sv.item_id].body_chars = len(item.body)
                    summaries_by_id[sv.item_id].word_count = len(item.body.split())
                    summaries_by_id[sv.item_id].enrichment_status = item.enrichment_status
                if item.enrichment_status == "fetch_blocked":
                    if item.item_id in result.new_seen_records:
                        result.new_seen_records[item.item_id].verdict = "FETCH_BLOCKED"
                    continue

            target_files = [sv.matched_repo_file] if sv.matched_repo_file else []
            target_context = load_target_repo_context(
                config.repo_root, target_files, exclude_files=excluded
            )
            try:
                analysis, trace = active_client.analyze_stage2_survivor(item, target_context)
                result.traces.append(trace)
                result.total_estimated_cost_usd = round(
                    result.total_estimated_cost_usd + trace.estimated_cost_usd, 6
                )
            except BudgetExceededError:
                result.cost_cap_triggered = True
                # Un-burn this and all remaining un-scored Stage 2 survivors so they retry next run
                for rem_sv in survivor_verdicts[idx:]:
                    result.new_seen_records.pop(rem_sv.item_id, None)
                break
            except (StructuredOutputError, RuntimeError) as exc:
                _record_stage_error(
                    result,
                    stage="stage2",
                    item_ids=[item.item_id],
                    exc=exc,
                )
                # Un-burn failed survivor so it is NOT lost in seen.json and retries next run
                result.new_seen_records.pop(item.item_id, None)
                continue

            scored = score_stage2_analysis(
                item,
                analysis,
                stage_threshold=config.stage_score_threshold,
                high_signal_threshold=config.high_signal_threshold,
            )
            result.stage2_results.append(scored)
            if item.item_id in result.new_seen_records:
                result.new_seen_records[item.item_id].verdict = f"{scored.disposition}:{scored.score}"
            if (
                scored.disposition in ("STAGE", "HIGH_SIGNAL")
                and scored.score >= PENDING_BUFFER_MIN_SCORE
            ):
                qualifying_survivors.append(scored)

    if effective_coherence_gate or (is_fast_lane_direct and bool(candidates)):
        combined_by_id: dict[str, ScoredSurvivor] = {}
        drained_ids: list[str] = []
        de_anchored_inputs: list[DeAnchoredCandidate] = []
        valid_stage3_ids: set[str] = set()

        if is_fast_lane_direct:
            for item in candidates:
                de_anchored_inputs.append(
                    de_anchor_candidate(item, source_path="fast_lane_direct")
                )
                valid_stage3_ids.add(item.item_id)

        if effective_coherence_gate and pending is not None:
            for item_id, pc in pending.items.items():
                if (
                    pc.disposition in ("STAGE", "HIGH_SIGNAL")
                    and pc.score >= PENDING_BUFFER_MIN_SCORE
                ):
                    scored_pc = ScoredSurvivor(
                        item=pc.item,
                        analysis=pc.analysis,
                        score=pc.score,
                        disposition=pc.disposition,
                        gate_failure_reason=pc.gate_failure_reason,
                    )
                    combined_by_id[item_id] = scored_pc
                    drained_ids.append(item_id)
                    if item_id not in summaries_by_id:
                        cs = _to_candidate_summary(pc.item)
                        result.candidate_summaries.append(cs)
                        summaries_by_id[item_id] = cs

        for s in qualifying_survivors:
            combined_by_id[s.item.item_id] = s

        drained_id_set = set(drained_ids)
        for item_id, scored in combined_by_id.items():
            if item_id in valid_stage3_ids:
                continue
            src_route = "pending_buffer" if item_id in drained_id_set else "stage2_survivor"
            de_anchored_inputs.append(de_anchor_candidate(scored, source_path=src_route))
            valid_stage3_ids.add(item_id)

        result.drained_item_ids = drained_ids
        result.buffered_items = []

        if de_anchored_inputs:
            full_baseline = load_full_repo_baseline(config.repo_root, exclude_files=excluded)
            active_client = _get_llm_client()
            verdict: Stage3CoherenceVerdict | None = None
            try:
                raw_verdict, trace = active_client.evaluate_stage3_coherence(
                    de_anchored_inputs, full_baseline
                )
                result.traces.append(trace)
                result.total_estimated_cost_usd = round(
                    result.total_estimated_cost_usd + trace.estimated_cost_usd, 6
                )
                verdict = enforce_stage3_coherence_guardrails(raw_verdict, valid_stage3_ids)
                result.coherence_gate_completed = bool(effective_coherence_gate)
            except BudgetExceededError:
                result.cost_cap_triggered = True
                result.coherence_gate_completed = False
                qualifying_survivors.sort(key=lambda s: s.score, reverse=True)
                result.buffered_items = qualifying_survivors
                verdict = Stage3CoherenceVerdict(
                    decision="REJECT_ALL",
                    executive_summary="Stage 3 skipped because run cost ceiling was reached.",
                )
            except (StructuredOutputError, RuntimeError) as exc:
                _record_stage_error(
                    result,
                    stage="stage3",
                    item_ids=[c.item_id for c in de_anchored_inputs],
                    exc=exc,
                )
                result.coherence_gate_completed = False
                qualifying_survivors.sort(key=lambda s: s.score, reverse=True)
                result.buffered_items = qualifying_survivors

            if verdict is not None:
                result.stage3_verdict = verdict
                audits_by_id = {a.item_id: a for a in verdict.item_audits}

                if (
                    is_fast_lane_direct
                    and mode != "observe"
                    and not result.cost_cap_triggered
                ):
                    for item in candidates:
                        audit = audits_by_id.get(item.item_id)
                        v_code = audit.verdict if audit is not None else verdict.decision
                        result.new_seen_records[item.item_id] = SeenRecord(
                            canonical_url=item.canonical_url,
                            title_hash=item.title_hash,
                            content_hash=item.content_hash,
                            feed_id=item.feed_id,
                            first_seen_at=run_at,
                            verdict=f"STAGE3:{v_code}",
                        )

                approved_ids = approved_stage3_item_ids(verdict)
                staged = [combined_by_id[iid] for iid in approved_ids if iid in combined_by_id]
                staged.sort(key=lambda s: s.score, reverse=True)
                result.staged_items = staged
                result.has_high_signal = any(s.disposition == "HIGH_SIGNAL" for s in staged)
            else:
                result.staged_items = []
                result.has_high_signal = False
        else:
            result.coherence_gate_completed = bool(effective_coherence_gate)
            result.staged_items = []
            result.has_high_signal = False
    else:
        qualifying_survivors.sort(key=lambda s: s.score, reverse=True)
        result.buffered_items = qualifying_survivors
        result.staged_items = []
        result.has_high_signal = False

    if client is not None:
        client_spend = float(getattr(client, "cumulative_cost_usd", 0.0) or 0.0)
        if client_spend > result.total_estimated_cost_usd:
            result.total_estimated_cost_usd = round(client_spend, 6)

    if result.stage_errors:
        fast_lane_failed = is_fast_lane_direct and any(
            err.stage == "stage3" for err in result.stage_errors
        )
        all_stage1_failed = (
            bool(candidates)
            and not is_fast_lane_direct
            and result.stage1_reviewed == 0
            and not result.coherence_gate_completed
        )
        pure_stage3_failed = (
            not candidates and has_pending_to_drain and not result.coherence_gate_completed
        )
        if fast_lane_failed or all_stage1_failed or pure_stage3_failed:
            result.status = "FAILED"
            result.error_code = result.stage_errors[0].error_type or "LLM_STAGE_ERROR"
            result.error_message = result.stage_errors[0].message
        else:
            result.status = "PARTIAL_ERROR"
            result.error_code = "PARTIAL_ERROR"
            result.error_message = (
                f"{len(result.stage_errors)} LLM stage error(s) isolated; partial work preserved."
            )

    result.summary_markdown = build_job_summary_markdown(result)
    return result


def apply_run_result_files(
    *,
    run_result_path: Path,
    seen_path: Path,
    health_path: Path,
    pending_path: Path | None = None,
    audits_path: Path | None = None,
    digest_dir: Path | None = None,
    summary_out_path: Path | None = None,
    update_state: bool = True,
) -> dict[str, object]:
    """Job 2 deterministic helper: validate run-result.json, update state/buffer/audits, and render radar/ digest."""
    result = RunResult.model_validate_json(run_result_path.read_text(encoding="utf-8"))
    effective_pending_path = pending_path or (seen_path.parent / "pending-candidates.json")
    effective_audits_path = audits_path or (seen_path.parent / "weekly-audits.md")
    pending = load_pending_candidates(effective_pending_path)
    audit_logged = False

    if update_state:
        seen = load_seen_state(seen_path)
        health = load_feed_health(health_path)
        updated_seen, updated_health = apply_run_result_to_state(seen, health, result)
        updated_pending = apply_run_result_to_pending(pending, result)
        save_seen_state(seen_path, updated_seen)
        save_feed_health(health_path, updated_health)
        save_pending_candidates(effective_pending_path, updated_pending)
        if result.stage3_verdict is not None:
            audit_logged = append_weekly_audit(effective_audits_path, result)
    else:
        updated_pending = pending

    if summary_out_path is not None:
        summary_out_path.parent.mkdir(parents=True, exist_ok=True)
        summary_out_path.write_text(build_job_summary_markdown(result), encoding="utf-8")

    stage3_decision = result.stage3_verdict.decision if result.stage3_verdict is not None else ""
    approved_ids = approved_stage3_item_ids(result.stage3_verdict)
    digest_path: Path | None = None
    added_count = 0
    if (
        digest_dir is not None
        and result.mode == "enforce"
        and result.stage3_verdict is not None
        and result.stage3_verdict.decision == "APPROVE_SYNTHESIS"
        and result.stage3_verdict.syntheses
    ):
        items_by_id: dict[str, CandidateSummary] = {
            cs.item_id: cs for cs in result.candidate_summaries
        }
        for s in result.stage2_results:
            items_by_id.setdefault(s.item.item_id, _to_candidate_summary(s.item))
        for s in result.staged_items:
            items_by_id.setdefault(s.item.item_id, _to_candidate_summary(s.item))

        digest_dir.mkdir(parents=True, exist_ok=True)
        digest_path = digest_dir / f"{result.iso_week}-digest.md"
        existing = digest_path.read_text(encoding="utf-8") if digest_path.is_file() else None
        merged_md, added_count = merge_stage3_synthesis_into_weekly_digest(
            existing,
            result.iso_week,
            result.stage3_verdict,
            items_by_id,
            updated_at=result.run_at[:10],
        )
        if added_count > 0:
            digest_path.write_text(merged_md, encoding="utf-8")
        elif not digest_path.is_file():
            digest_path = None

    return {
        "mode": result.mode,
        "iso_week": result.iso_week,
        "run_coherence_gate": result.run_coherence_gate,
        "stage3_decision": stage3_decision,
        "audit_logged": audit_logged,
        "buffered_count": len(result.buffered_items),
        "pending_count": len(updated_pending.items),
        "staged_count": len(approved_ids),
        "added_to_digest": added_count,
        "has_high_signal": result.has_high_signal,
        "digest_path": str(digest_path) if digest_path else "",
    }


def _cmd_inventory(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    inv = build_repo_inventory(repo_root, exclude_files=args.exclude or [])
    print(inv)
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    try:
        config = PipelineConfig.from_env(Path(args.repo_root))
        seen = load_seen_state(Path(args.seen_path)) if args.seen_path else SeenState()
        pending_arg = getattr(args, "pending_path", "")
        pending = (
            load_pending_candidates(Path(pending_arg))
            if pending_arg
            else PendingCandidatesState()
        )
        offline_candidates = None
        if args.offline_items:
            raw = json.loads(Path(args.offline_items).read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                raise ValueError(
                    f"Expected JSON array in --offline-items ({args.offline_items}), "
                    f"got {type(raw).__name__}"
                )
            offline_candidates = [CandidateItem.model_validate(item) for item in raw]

        gate_flag = getattr(args, "run_coherence_gate", None)
        result = run_pipeline(
            config,
            seen=seen,
            pending=pending,
            mode=args.mode,
            fast_lane_url=args.url or None,
            force=bool(getattr(args, "force", False)),
            run_coherence_gate=gate_flag,
            offline_candidates=offline_candidates,
            exclude_repo_files=args.withhold or [],
        )
    except Exception as exc:  # noqa: BLE001
        safe_err = sanitize_single_line(redact_secrets(str(exc)), 300)
        if args.summary_out:
            summary_path = Path(args.summary_out)
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(
                "\n".join(
                    [
                        f"## Radar Ingestion Summary — Fatal Error (`{args.mode}`)",
                        "",
                        f"- **Error Type:** `{type(exc).__name__}`",
                        f"- **Details:** {safe_err}",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
        raise

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    if args.summary_out:
        summary_path = Path(args.summary_out)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(result.summary_markdown, encoding="utf-8")
    print(result.summary_markdown)
    if result.status in ("FETCH_INCOMPLETE", "FAILED") or result.error_code == "FETCH_INCOMPLETE":
        return 1
    return 0


def _cmd_apply_state(args: argparse.Namespace) -> int:
    pending_arg = getattr(args, "pending_path", "")
    audits_arg = getattr(args, "audits_path", "")
    outcome = apply_run_result_files(
        run_result_path=Path(args.run_result),
        seen_path=Path(args.seen_path),
        health_path=Path(args.health_path),
        pending_path=Path(pending_arg) if pending_arg else None,
        audits_path=Path(audits_arg) if audits_arg else None,
        digest_dir=Path(args.digest_dir) if args.digest_dir else None,
        summary_out_path=Path(args.summary_out) if args.summary_out else None,
        update_state=not args.no_update_state,
    )
    github_output = getattr(args, "github_output", "")
    if github_output:
        _write_github_output(
            Path(github_output),
            {
                "mode": outcome["mode"],
                "iso_week": outcome["iso_week"],
                "run_coherence_gate": outcome["run_coherence_gate"],
                "stage3_decision": outcome["stage3_decision"],
                "buffered_count": outcome["buffered_count"],
                "staged_count": outcome["staged_count"],
                "has_high_signal": outcome["has_high_signal"],
            },
        )
    print(json.dumps(outcome, indent=2))
    return 0


def _cmd_health_report(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    registry = load_feed_registry(repo_root / "radar" / "feeds.yaml")
    health = load_feed_health(Path(args.health_path))
    report = generate_feed_health_report(health, registry)
    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
    print(report)
    return 0


def _cmd_eval_fixture(args: argparse.Namespace) -> int:
    """Run the offline or live Phase 0 replay calibration fixture."""
    fixture_path = Path(args.fixture)
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    candidates = [CandidateItem.model_validate(c) for c in fixture["items"]]
    config = PipelineConfig.from_env(Path(args.repo_root))

    if not args.live:
        print(
            f"Loaded calibration fixture '{fixture.get('name', fixture_path.name)}' "
            f"with {len(candidates)} items. Pass --live with GEMINI_API_KEY to benchmark live models."
        )
        return 0

    result = run_pipeline(
        config,
        seen=SeenState(),
        mode="observe",
        offline_candidates=candidates,
        exclude_repo_files=args.withhold or [],
    )
    print(result.summary_markdown)
    if args.output:
        Path(args.output).write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="radar",
        description="Automated, repo-aware signal ingestion pipeline for D-28/upskilling.",
    )
    parser.add_argument("--repo-root", default=".", help="Path to repository root.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_inv = sub.add_parser("inventory", help="Print deterministic REPO_INVENTORY.")
    p_inv.add_argument("--exclude", action="append", default=[], help="Relative repo paths to withhold.")
    p_inv.set_defaults(func=_cmd_inventory)

    p_run = sub.add_parser(
        "run", help="Run Stage 0 -> Stage 1 -> Stage 2 -> Stage 3 pipeline (read-only Job 1)."
    )
    p_run.add_argument("--mode", choices=["observe", "enforce", "bootstrap"], default="observe")
    p_run.add_argument("--seen-path", default="", help="Path to seen.json from radar-state.")
    p_run.add_argument(
        "--pending-path",
        default="",
        help="Path to pending-candidates.json from radar-state.",
    )
    p_run.add_argument("--output", required=True, help="Path to write validated run-result.json.")
    p_run.add_argument("--summary-out", default="", help="Optional path to write Job Summary markdown.")
    p_run.add_argument("--url", default="", help="Optional single URL for manual fast-lane triage.")
    p_run.add_argument(
        "--force",
        action="store_true",
        help="Bypass seen.json deduplication to force re-evaluation.",
    )
    p_run.add_argument(
        "--run-coherence-gate",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Drain pending-candidates.json through the weekly Coherence Gate (pass --no-run-coherence-gate to disable on Sundays).",
    )
    p_run.add_argument("--offline-items", default="", help="Optional JSON list of CandidateItems for offline runs.")
    p_run.add_argument("--withhold", action="append", default=[], help="Withhold repo files (calibration testing).")
    p_run.set_defaults(func=_cmd_run)

    p_apply = sub.add_parser("apply-state", help="Apply validated run-result.json to state & digest (Job 2).")
    p_apply.add_argument("--run-result", required=True)
    p_apply.add_argument("--seen-path", required=True)
    p_apply.add_argument("--health-path", required=True)
    p_apply.add_argument(
        "--pending-path",
        default="",
        help="Path to pending-candidates.json on radar-state.",
    )
    p_apply.add_argument(
        "--audits-path",
        default="",
        help="Path to weekly-audits.md on radar-state.",
    )
    p_apply.add_argument("--digest-dir", default="", help="Directory for radar/YYYY-Www-digest.md (enforce mode).")
    p_apply.add_argument("--summary-out", default="", help="Regenerate sanitized summary markdown in Job 2.")
    p_apply.add_argument("--github-output", default="", help="Optional $GITHUB_OUTPUT path for Job 2 step outputs.")
    p_apply.add_argument("--no-update-state", action="store_true", help="Render digest without re-applying state counters.")
    p_apply.set_defaults(func=_cmd_apply_state)

    p_health = sub.add_parser("health-report", help="Emit quarterly feed-health & promotion report.")
    p_health.add_argument("--health-path", required=True)
    p_health.add_argument("--output", default="")
    p_health.set_defaults(func=_cmd_health_report)

    p_eval = sub.add_parser("eval-fixture", help="Run Phase 0 replay calibration fixture.")
    p_eval.add_argument(
        "--fixture",
        default="tests/radar/fixtures/nov2026_replay.json",
        help="Path to replay fixture JSON.",
    )
    p_eval.add_argument("--live", action="store_true", help="Invoke live Gemini API (requires GEMINI_API_KEY).")
    p_eval.add_argument("--withhold", action="append", default=[], help="Withhold a playbook to test recall.")
    p_eval.add_argument("--output", default="")
    p_eval.set_defaults(func=_cmd_eval_fixture)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
