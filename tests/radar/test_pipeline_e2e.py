"""End-to-end offline tests: zero-tool Gemini config, v1beta alias routing, calibration fixture, and telemetry."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from scripts.radar.cli import apply_run_result_files, run_pipeline
from scripts.radar.config import PipelineConfig, requires_v1beta, validate_thinking_level
from scripts.radar.fetcher import load_feed_registry
from scripts.radar.inventory import build_repo_inventory
from scripts.radar.llm import GeminiRadarClient
from scripts.radar.models import (
    CandidateItem,
    FeedHealthState,
    FeedStats,
    LLMCallTrace,
    RubricDimensions,
    SeenState,
    Stage1BatchResponse,
    Stage1ItemVerdict,
    Stage2Analysis,
)
from scripts.radar.rubric import parse_radar_markers
from scripts.radar.state import (
    generate_feed_health_report,
    load_feed_health,
    load_seen_state,
    reconcile_pr_outcome,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "nov2026_replay.json"


def test_dynamic_latest_alias_routing_and_zero_tool_config() -> None:
    assert requires_v1beta("gemini-flash-lite-latest") is True
    assert requires_v1beta("gemini-flash-latest") is True
    assert requires_v1beta("gemini-pro-latest") is True
    assert requires_v1beta("gemini-3.8-flash") is False
    assert validate_thinking_level("gemini-3.8-flash", "MINIMAL") == "LOW"
    assert validate_thinking_level("gemini-flash-lite-latest", "MINIMAL") == "MINIMAL"

    captured: list[dict[str, object]] = []

    class _FakeModels:
        def generate_content(self, *, model, contents, config):
            captured.append({"model": model, "config": config})
            payload = Stage1BatchResponse(
                verdicts=[
                    Stage1ItemVerdict(
                        item_id="111111111111",
                        verdict="ALREADY_COVERED",
                        matched_repo_file="playbooks/verification-engineering.md",
                        reason="Covered in verification playbook.",
                    )
                ]
            ).model_dump_json()
            return SimpleNamespace(
                text=payload,
                model_version="gemini-3.5-flash-lite-2026-11",
                usage_metadata=SimpleNamespace(
                    prompt_token_count=2000,
                    cached_content_token_count=0,
                    candidates_token_count=100,
                    thoughts_token_count=50,
                ),
            )

    api_versions_seen: list[str] = []

    def fake_factory(*, api_version: str):
        api_versions_seen.append(api_version)
        return SimpleNamespace(models=_FakeModels())

    config = PipelineConfig(repo_root=REPO_ROOT, feeds_path=REPO_ROOT / "radar" / "feeds.yaml")
    client = GeminiRadarClient(config, api_key="dummy-key", client_factory=fake_factory)
    item = CandidateItem(
        item_id="111111111111",
        feed_id="test",
        feed_name="Test",
        title="Test",
        url="https://example.dev/1",
        canonical_url="https://example.dev/1",
        domain="example.dev",
    )
    resp, trace = client.triage_stage1_batch([item], "inventory")
    assert api_versions_seen == ["v1beta"]
    assert resp.verdicts[0].verdict == "ALREADY_COVERED"
    assert trace.resolved_model_version == "gemini-3.5-flash-lite-2026-11"
    # Verify Harness Wall: zero tools enabled on untrusted web input
    cfg = captured[0]["config"]
    assert getattr(cfg, "tools", None) is None
    assert getattr(cfg, "response_mime_type", None) == "application/json"


class _InventoryAwareStubLLM:
    """Deterministic stub simulating repo-aware delta filtering against the calibration fixture."""

    def triage_stage1_batch(
        self, items: list[CandidateItem], repo_inventory: str
    ) -> tuple[Stage1BatchResponse, LLMCallTrace]:
        verdicts: list[Stage1ItemVerdict] = []
        has_verif = "playbooks/verification-engineering.md" in repo_inventory
        has_harness = "playbooks/harness-loop-graph.md" in repo_inventory
        has_ste = "skills/ste-clarity/SKILL.md" in repo_inventory

        for item in items:
            if item.item_id == "b22222222222" and not has_verif:
                verdicts.append(
                    Stage1ItemVerdict(
                        item_id=item.item_id,
                        verdict="SURVIVOR",
                        matched_repo_file="playbooks/harness-loop-graph.md",
                        reason="Net-new verification engineering blueprint.",
                    )
                )
            elif item.item_id == "c33333333333" and not has_harness:
                verdicts.append(
                    Stage1ItemVerdict(
                        item_id=item.item_id,
                        verdict="SURVIVOR",
                        matched_repo_file="templates/undo-price-gating.md",
                        reason="Net-new 3-layer architecture framework.",
                    )
                )
            elif item.item_id == "h88888888880" and not has_ste:
                verdicts.append(
                    Stage1ItemVerdict(
                        item_id=item.item_id,
                        verdict="SURVIVOR",
                        matched_repo_file="templates/AGENTS.md.template",
                        reason="Net-new STE-80 clarity standard and 4-level output ladder.",
                    )
                )
            elif item.item_id.startswith("x"):
                verdicts.append(
                    Stage1ItemVerdict(
                        item_id=item.item_id,
                        verdict="MODEL_RELEASE_FLUFF",
                        reason="Noise or prompt injection decoy.",
                    )
                )
            else:
                verdicts.append(
                    Stage1ItemVerdict(
                        item_id=item.item_id,
                        verdict="ALREADY_COVERED",
                        matched_repo_file="playbooks/verification-engineering.md",
                        reason="Already covered in current playbooks.",
                    )
                )

        trace = LLMCallTrace(
            stage="stage1",
            requested_model="gemini-flash-lite-latest",
            resolved_model_version="stub-flash-lite",
            thinking_level="LOW",
            api_version="v1beta",
            estimated_cost_usd=0.0005,
            item_ids=[i.item_id for i in items],
        )
        return Stage1BatchResponse(verdicts=verdicts), trace

    def analyze_stage2_survivor(
        self, item: CandidateItem, target_repo_context: str
    ) -> tuple[Stage2Analysis, LLMCallTrace]:
        analysis = Stage2Analysis(
            item_id=item.item_id,
            passes_net_new_delta_gate=True,
            passes_substance_gate=True,
            counterargument_to_drop="General E2E testing is well known. However, base-branch REVIEW.md and 3-strike gates are net-new.",
            dimensions=RubricDimensions(
                delta_novelty=2,
                durability=2,
                actionability=2,
                evidence_quality=2,
                career_leverage=2,
            ),
            target_repo_files=["playbooks/verification-engineering.md"],
            what_is_net_new="Adds base-branch REVIEW.md loading, diff-triggered checklists, and observe-to-enforce commit gates.",
            proposed_refinement="Add a verification playbook covering E2E, property, and differential tests plus anti-gaming review rules.",
            career_takeaway="Enables Staff SWEs to review high-velocity AI diffs safely across teams.",
            evidence_quote="Roughly 90% of Claude Code's code is written and reviewed by Claude.",
        )
        trace = LLMCallTrace(
            stage="stage2",
            requested_model="gemini-flash-latest",
            resolved_model_version="stub-flash",
            thinking_level="HIGH",
            api_version="v1beta",
            estimated_cost_usd=0.002,
            item_ids=[item.item_id],
        )
        return analysis, trace


def test_replay_calibration_fixture_and_job2_staging_e2e(tmp_path: Path) -> None:
    from scripts.ste_lint import lint_file

    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    candidates = [CandidateItem.model_validate(item) for item in fixture["items"]]
    config = PipelineConfig(repo_root=REPO_ROOT, feeds_path=REPO_ROOT / "radar" / "feeds.yaml")
    stub = _InventoryAwareStubLLM()

    # 1. Verify inventory includes all current playbooks and STE-80 clarity skill
    inv = build_repo_inventory(REPO_ROOT)
    assert "playbooks/verification-engineering.md" in inv
    assert "playbooks/harness-loop-graph.md" in inv
    assert "skills/ste-clarity/SKILL.md" in inv

    # 2. Bootstrap mode seeds seen.json at $0 LLM cost
    boot_res = run_pipeline(
        config,
        seen=SeenState(),
        mode="bootstrap",
        offline_candidates=candidates,
        llm_client=stub,
        now=datetime(2026, 11, 20, 12, 0, tzinfo=UTC),
    )
    assert boot_res.total_estimated_cost_usd == 0.0
    assert len(boot_res.new_seen_records) == len(candidates)
    assert boot_res.staged_items == []

    # 3. Full repo present -> 0% false-positive bloat across A-H + decoys
    full_res = run_pipeline(
        config,
        seen=SeenState(),
        mode="observe",
        offline_candidates=candidates,
        llm_client=stub,
        now=datetime(2026, 11, 20, 12, 0, tzinfo=UTC),
    )
    assert full_res.stage1_reviewed == len(candidates)
    assert full_res.staged_items == []

    # 4. Withholding verification-engineering.md recovers B as 10/10 HIGH_SIGNAL while dropping decoys
    recall_res = run_pipeline(
        config,
        seen=SeenState(),
        mode="enforce",
        offline_candidates=candidates,
        exclude_repo_files=["playbooks/verification-engineering.md"],
        llm_client=stub,
        now=datetime(2026, 11, 20, 12, 0, tzinfo=UTC),
    )
    assert len(recall_res.staged_items) == 1
    assert recall_res.staged_items[0].item.item_id == "b22222222222"
    assert recall_res.staged_items[0].score == 10
    assert recall_res.has_high_signal is True

    # 5. Job 2 deterministic apply-state updates seen/health and renders radar/YYYY-Www-digest.md
    run_result_path = tmp_path / "run-result.json"
    seen_path = tmp_path / "state" / "seen.json"
    health_path = tmp_path / "state" / "feed-health.json"
    digest_dir = tmp_path / "radar"
    run_result_path.write_text(recall_res.model_dump_json(indent=2), encoding="utf-8")

    outcome = apply_run_result_files(
        run_result_path=run_result_path,
        seen_path=seen_path,
        health_path=health_path,
        digest_dir=digest_dir,
    )
    assert outcome["added_to_digest"] == 1
    assert outcome["has_high_signal"] is True
    digest_file = Path(str(outcome["digest_path"]))
    assert digest_file.is_file()
    markers = parse_radar_markers(digest_file.read_text(encoding="utf-8"))
    assert markers == [("b22222222222", "addy-osmani-elevate", "addyo.substack.com")]

    # Dogfood STE-80 linter on the rendered weekly radar digest file
    ste_stats, ste_violations = lint_file(digest_file, strict_20=True)
    assert ste_stats.errors == 0, f"STE-80 violations in rendered digest: {ste_violations}"
    assert ste_stats.ste_score == 100

    # Backward-compatible load of persisted state
    loaded_seen = load_seen_state(seen_path)
    loaded_health = load_feed_health(health_path)
    assert "b22222222222" in loaded_seen.items
    assert loaded_health.feeds["addy-osmani-elevate"].stage2_staged == 1


def test_pr_reconciliation_and_quarterly_health_report_promotion_and_pruning() -> None:
    registry = load_feed_registry(REPO_ROOT / "radar" / "feeds.yaml")
    health = FeedHealthState()
    now = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)

    # Reconcile 2 merged PRs containing items from an unsubscribed domain (newgem.dev)
    health = reconcile_pr_outcome(
        health,
        registry,
        pr_number=10,
        merged=True,
        staged_markers=[
            ("111111111111", "hn-agentic", "newgem.dev"),
            ("222222222222", "openai-news", "openai.com"),
        ],
        landed_item_ids={"111111111111"},  # human edited out item 2 before merging!
        reconciled_at="2026-11-10T12:00:00+00:00",
    )
    health = reconcile_pr_outcome(
        health,
        registry,
        pr_number=11,
        merged=True,
        staged_markers=[("333333333333", "simon-willison", "newgem.dev")],
        landed_item_ids={"333333333333"},
        reconciled_at="2026-11-18T12:00:00+00:00",
    )
    # Reconciling same PR #11 again must be idempotent
    health = reconcile_pr_outcome(
        health,
        registry,
        pr_number=11,
        merged=True,
        staged_markers=[("333333333333", "simon-willison", "newgem.dev")],
        landed_item_ids={"333333333333"},
        reconciled_at="2026-11-18T12:00:00+00:00",
    )
    # Simulate 3 consecutive fetch failures on google-deepmind-blog
    health.feeds["google-deepmind-blog"] = FeedStats(consecutive_fetch_errors=3)

    report = generate_feed_health_report(health, registry, now=now)
    assert "newgem.dev" in report
    assert "2 human-merged items" in report
    assert "google-deepmind-blog" in report
    assert "3 consecutive fetch errors" in report
    assert health.feeds["openai-news"].human_closed_rejected == 1
    assert health.feeds["hn-agentic"].human_merged == 1


def test_ste80_compliance_across_skills_templates_and_prompts(tmp_path: Path) -> None:
    from scripts.radar.llm import STAGE1_SYSTEM_PROMPT_TEMPLATE, STAGE2_SYSTEM_PROMPT_TEMPLATE
    from scripts.ste_lint import lint_file

    target_files = [
        *sorted((REPO_ROOT / "skills").glob("*/SKILL.md")),
        *sorted((REPO_ROOT / "templates").glob("*.md")),
        *sorted((REPO_ROOT / "templates").glob("*.template")),
    ]
    assert len(target_files) >= 8
    for path in target_files:
        stats, violations = lint_file(path, strict_20=True)
        assert stats.errors == 0, f"{path} failed STE-80 lint: {violations}"
        assert stats.ste_score == 100

    prompt_doc = tmp_path / "llm_prompts.md"
    prompt_doc.write_text(
        STAGE1_SYSTEM_PROMPT_TEMPLATE.format(repo_inventory="")
        + "\n\n"
        + STAGE2_SYSTEM_PROMPT_TEMPLATE.format(target_repo_context=""),
        encoding="utf-8",
    )
    p_stats, p_violations = lint_file(prompt_doc, strict_20=False)
    assert p_stats.errors == 0, f"LLM system prompts failed STE-80 lint: {p_violations}"
