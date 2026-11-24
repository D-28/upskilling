"""Unit tests for GeminiRadarClient structured JSON resilience, retries, token budgets, and cost accounting."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.radar import llm as llm_mod
from scripts.radar.config import (
    LLM_HTTP_TIMEOUT_MS,
    MAX_STRUCTURED_OUTPUT_TOKENS,
    STAGE2_MAX_OUTPUT_TOKENS,
    PipelineConfig,
)
from scripts.radar.llm import (
    BudgetExceededError,
    GeminiRadarClient,
    StructuredOutputError,
    _extract_json_text,
    _normalize_structured_payload,
)
from scripts.radar.models import (
    CandidateItem,
    RubricDimensions,
    Stage1BatchResponse,
    Stage1ItemVerdict,
    Stage2Analysis,
    Stage3CoherenceVerdict,
    Stage3ItemAudit,
    SystemicPoisonFlags,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_item(item_id: str = "a11111111111") -> CandidateItem:
    return CandidateItem(
        item_id=item_id,
        feed_id="test-feed",
        feed_name="Test Feed",
        title="Deterministic Verification Harnesses",
        url="https://example.dev/harnesses",
        canonical_url="https://example.dev/harnesses",
        domain="example.dev",
        excerpt="Concrete harness pattern.",
        body="Concrete harness pattern with reproducible evals.",
    )


def _valid_stage2_dict(item_id: str = "a11111111111") -> dict[str, object]:
    return Stage2Analysis(
        item_id=item_id,
        passes_net_new_delta_gate=True,
        passes_substance_gate=True,
        counterargument_to_drop="Some overlap with existing docs.",
        dimensions=RubricDimensions(
            delta_novelty=2,
            durability=2,
            actionability=2,
            evidence_quality=1,
            career_leverage=1,
        ),
        target_repo_files=["playbooks/verification-engineering.md"],
        what_is_net_new="Adds structured retry telemetry.",
        proposed_refinement="Update verification playbook.",
        career_takeaway="Improves production reliability.",
        evidence_quote="Measured 99% recovery after bounded retries.",
    ).model_dump()


def _make_response(
    text: str | None,
    *,
    finish_reason: str = "STOP",
    prompt_tokens: int = 1000,
    output_tokens: int = 200,
    thought_tokens: int = 300,
    model_version: str = "gemini-3.8-flash-2026-11",
) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        model_version=model_version,
        candidates=[SimpleNamespace(finish_reason=finish_reason)],
        usage_metadata=SimpleNamespace(
            prompt_token_count=prompt_tokens,
            cached_content_token_count=0,
            candidates_token_count=output_tokens,
            thoughts_token_count=thought_tokens,
        ),
    )


def test_malformed_json_retries_and_accounts_for_all_attempt_costs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_mod.time, "sleep", lambda _s: None)
    responses = [
        _make_response('{"item_id": "a11111111111"\n  "bad": true', prompt_tokens=10_000, output_tokens=500, thought_tokens=1_500),
        _make_response(json.dumps(_valid_stage2_dict()), prompt_tokens=10_000, output_tokens=500, thought_tokens=1_500),
    ]
    calls = 0

    class _FakeModels:
        def generate_content(self, *, model, contents, config):
            nonlocal calls
            resp = responses[calls]
            calls += 1
            return resp

    config = PipelineConfig(repo_root=REPO_ROOT, feeds_path=REPO_ROOT / "radar" / "feeds.yaml")
    client = GeminiRadarClient(
        config,
        api_key="dummy-key",
        client_factory=lambda *, api_version: SimpleNamespace(models=_FakeModels()),
    )
    analysis, trace = client.analyze_stage2_survivor(_make_item(), "context")
    assert calls == 2
    assert analysis.item_id == "a11111111111"
    # Both attempt 1 (malformed) and attempt 2 (valid) must be counted in spend
    assert client.cumulative_cost_usd > 0.0
    assert trace.estimated_cost_usd == pytest.approx(client.cumulative_cost_usd)


def test_exhausted_malformed_json_raises_structured_output_error_with_redacted_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_mod.time, "sleep", lambda _s: None)
    secret = "test-gemini-env-secret-value-for-redaction"
    monkeypatch.setenv("GEMINI_API_KEY", secret)

    class _AlwaysBrokenModels:
        def generate_content(self, *, model, contents, config):
            return _make_response(
                f'{{"item_id": "a11111111111", "leak": "{secret}" broken',
                finish_reason="STOP",
            )

    config = PipelineConfig(repo_root=REPO_ROOT, feeds_path=REPO_ROOT / "radar" / "feeds.yaml")
    client = GeminiRadarClient(
        config,
        api_key=secret,
        client_factory=lambda *, api_version: SimpleNamespace(models=_AlwaysBrokenModels()),
    )
    with pytest.raises(StructuredOutputError) as exc_info:
        client.analyze_stage2_survivor(_make_item(), "context")

    err = exc_info.value
    assert err.stage == "stage2"
    assert err.item_ids == ["a11111111111"]
    assert err.finish_reason == "STOP"
    assert secret not in str(err)
    assert secret not in err.raw_preview
    assert "[REDACTED]" in err.raw_preview
    assert client.cumulative_cost_usd > 0.0


def test_markdown_fenced_json_bom_and_disallowed_nan_constants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_mod.time, "sleep", lambda _s: None)
    fenced = "\ufeff```json\n" + json.dumps(_valid_stage2_dict()) + "\n```\n"
    assert _extract_json_text(fenced).startswith("{")

    responses = [
        _make_response('{"item_id": "a11111111111", "passes_net_new_delta_gate": NaN}'),
        _make_response(fenced),
    ]
    idx = 0

    class _FakeModels:
        def generate_content(self, *, model, contents, config):
            nonlocal idx
            resp = responses[idx]
            idx += 1
            return resp

    config = PipelineConfig(repo_root=REPO_ROOT, feeds_path=REPO_ROOT / "radar" / "feeds.yaml")
    client = GeminiRadarClient(
        config,
        api_key="dummy-key",
        client_factory=lambda *, api_version: SimpleNamespace(models=_FakeModels()),
    )
    analysis, _ = client.analyze_stage2_survivor(_make_item(), "context")
    assert idx == 2
    assert analysis.item_id == "a11111111111"


def test_max_tokens_finish_reason_bumps_ceiling_and_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_mod.time, "sleep", lambda _s: None)
    seen_max_tokens: list[int] = []
    responses = [
        # Thinking consumed entire budget -> text=None and finish_reason=MAX_TOKENS
        _make_response(None, finish_reason="MAX_TOKENS", output_tokens=0, thought_tokens=STAGE2_MAX_OUTPUT_TOKENS),
        _make_response(json.dumps(_valid_stage2_dict()), finish_reason="STOP"),
    ]

    class _FakeModels:
        def generate_content(self, *, model, contents, config):
            seen_max_tokens.append(int(getattr(config, "max_output_tokens", 0)))
            return responses[len(seen_max_tokens) - 1]

    config = PipelineConfig(repo_root=REPO_ROOT, feeds_path=REPO_ROOT / "radar" / "feeds.yaml")
    client = GeminiRadarClient(
        config,
        api_key="dummy-key",
        client_factory=lambda *, api_version: SimpleNamespace(models=_FakeModels()),
    )
    analysis, _ = client.analyze_stage2_survivor(_make_item(), "context")
    assert analysis.item_id == "a11111111111"
    assert seen_max_tokens == [STAGE2_MAX_OUTPUT_TOKENS, MAX_STRUCTURED_OUTPUT_TOKENS]


def test_safety_finish_reason_fails_fast_without_retrying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_mod.time, "sleep", lambda _s: None)
    calls = 0

    class _SafetyBlockedModels:
        def generate_content(self, *, model, contents, config):
            nonlocal calls
            calls += 1
            return _make_response(None, finish_reason="SAFETY")

    config = PipelineConfig(repo_root=REPO_ROOT, feeds_path=REPO_ROOT / "radar" / "feeds.yaml")
    client = GeminiRadarClient(
        config,
        api_key="dummy-key",
        client_factory=lambda *, api_version: SimpleNamespace(models=_SafetyBlockedModels()),
    )
    with pytest.raises(StructuredOutputError) as exc_info:
        client.analyze_stage2_survivor(_make_item(), "context")

    assert calls == 1
    assert exc_info.value.finish_reason == "SAFETY"


def test_prose_max_length_is_bounded_while_structural_validation_stays_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_mod.time, "sleep", lambda _s: None)
    overlong_payload = _valid_stage2_dict()
    overlong_payload["evidence_quote"] = "x" * 420  # exceeds max_length=300
    overlong_payload["target_repo_files"] = [
        "playbooks/a.md",
        "playbooks/b.md",
        "playbooks/c.md",
        "playbooks/d.md",
        "playbooks/e.md",
    ]  # exceeds max_length=4

    normalized = _normalize_structured_payload(Stage2Analysis, overlong_payload)
    validated = Stage2Analysis.model_validate(normalized)
    assert len(validated.evidence_quote) == 300
    assert validated.evidence_quote.endswith("...")
    assert len(validated.target_repo_files) == 4

    # Nested Stage 3 list normalization also works without mutating item_id pattern
    s3_raw = Stage3CoherenceVerdict(
        decision="REJECT_ALL",
        executive_summary="Short summary.",
        item_audits=[
            Stage3ItemAudit(
                item_id="a11111111111",
                verdict="REJECT_ENTROPY",
                poisons=SystemicPoisonFlags(),
                rationale="Short rationale.",
            )
        ],
    ).model_dump()
    s3_raw["item_audits"][0]["rationale"] = "r" * 620
    s3_norm = _normalize_structured_payload(Stage3CoherenceVerdict, s3_raw)
    s3_val = Stage3CoherenceVerdict.model_validate(s3_norm)
    assert len(s3_val.item_audits[0].rationale) == 500

    # Structural violations (invalid item_id or out-of-range rubric score) MUST still fail
    bad_structural = _valid_stage2_dict()
    bad_structural["item_id"] = "NOT_A_VALID_HEX_ID_AT_ALL"
    bad_structural["dimensions"]["delta_novelty"] = 9  # type: ignore[index]

    calls = 0

    class _BadStructuralModels:
        def generate_content(self, *, model, contents, config):
            nonlocal calls
            calls += 1
            return _make_response(json.dumps(bad_structural))

    config = PipelineConfig(repo_root=REPO_ROOT, feeds_path=REPO_ROOT / "radar" / "feeds.yaml")
    client = GeminiRadarClient(
        config,
        api_key="dummy-key",
        client_factory=lambda *, api_version: SimpleNamespace(models=_BadStructuralModels()),
    )
    with pytest.raises(StructuredOutputError):
        client.analyze_stage2_survivor(_make_item(), "context")
    assert calls == 3


def test_budget_ceiling_stops_retries_after_expensive_failed_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_mod.time, "sleep", lambda _s: None)
    calls = 0

    class _ExpensiveBrokenModels:
        def generate_content(self, *, model, contents, config):
            nonlocal calls
            calls += 1
            # Very large token count exceeds max_run_cost_usd=0.01 on attempt 1
            return _make_response(
                "{broken",
                prompt_tokens=20_000,
                output_tokens=2_000,
                thought_tokens=2_000,
            )

    config = PipelineConfig(
        repo_root=REPO_ROOT,
        feeds_path=REPO_ROOT / "radar" / "feeds.yaml",
        max_run_cost_usd=0.01,
    )
    client = GeminiRadarClient(
        config,
        api_key="dummy-key",
        client_factory=lambda *, api_version: SimpleNamespace(models=_ExpensiveBrokenModels()),
    )
    with pytest.raises(BudgetExceededError):
        client.analyze_stage2_survivor(_make_item(), "context")
    assert calls == 1
    assert client.cumulative_cost_usd >= 0.01


def test_transient_network_errors_retry_and_non_transient_400_fails_fast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm_mod.time, "sleep", lambda _s: None)
    attempts = 0
    valid_s1 = Stage1BatchResponse(
        verdicts=[
            Stage1ItemVerdict(
                item_id="a11111111111",
                verdict="NO_WORKFLOW_DELTA",
                reason="No workflow delta.",
            )
        ]
    ).model_dump_json()

    class _FlakyNetworkModels:
        def generate_content(self, *, model, contents, config):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise TimeoutError("request timed out")
            if attempts == 2:
                raise RuntimeError("503 UNAVAILABLE backend busy")
            return _make_response(valid_s1)

    config = PipelineConfig(repo_root=REPO_ROOT, feeds_path=REPO_ROOT / "radar" / "feeds.yaml")
    client = GeminiRadarClient(
        config,
        api_key="dummy-key",
        client_factory=lambda *, api_version: SimpleNamespace(models=_FlakyNetworkModels()),
    )
    resp, _ = client.triage_stage1_batch([_make_item()], "inventory")
    assert attempts == 3
    assert len(resp.verdicts) == 1

    # Non-transient 400 error must fail fast in 1 attempt
    bad_calls = 0

    class _BadRequestModels:
        def generate_content(self, *, model, contents, config):
            nonlocal bad_calls
            bad_calls += 1
            raise RuntimeError("400 INVALID_ARGUMENT: unknown field")

    client2 = GeminiRadarClient(
        config,
        api_key="dummy-key",
        client_factory=lambda *, api_version: SimpleNamespace(models=_BadRequestModels()),
    )
    with pytest.raises(RuntimeError, match="400 INVALID_ARGUMENT"):
        client2.triage_stage1_batch([_make_item()], "inventory")
    assert bad_calls == 1


def test_real_genai_client_sets_explicit_http_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    from google import genai

    captured_kwargs: dict[str, object] = {}

    class _FakeGenAIClient:
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)

    monkeypatch.setattr(genai, "Client", _FakeGenAIClient)
    config = PipelineConfig(repo_root=REPO_ROOT, feeds_path=REPO_ROOT / "radar" / "feeds.yaml")
    client = GeminiRadarClient(config, api_key="dummy-key")
    client._get_client("v1beta")
    http_opts = captured_kwargs["http_options"]
    assert getattr(http_opts, "api_version", None) == "v1beta"
    assert getattr(http_opts, "timeout", None) == LLM_HTTP_TIMEOUT_MS
