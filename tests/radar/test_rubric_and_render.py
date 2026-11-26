"""Rubric math property tests, radar-id marker round-trip, and idempotent weekly digest rendering."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from scripts.radar.models import CandidateItem, RubricDimensions, Stage2Analysis
from scripts.radar.rubric import (
    format_radar_marker,
    merge_into_weekly_digest,
    parse_radar_markers,
    score_stage2_analysis,
)


def _sample_item(item_id: str = "abcdef012345", title: str = "Sample Signal") -> CandidateItem:
    return CandidateItem(
        item_id=item_id,
        feed_id="addy-osmani-elevate",
        feed_name="Addy Osmani",
        title=title,
        url=f"https://example.dev/{item_id}",
        canonical_url=f"https://example.dev/{item_id}",
        domain="example.dev",
    )


@given(
    net_new=st.booleans(),
    substance=st.booleans(),
    d1=st.integers(0, 2),
    d2=st.integers(0, 2),
    d3=st.integers(0, 2),
    d4=st.integers(0, 2),
    d5=st.integers(0, 2),
)
def test_property_rubric_scoring_gates_and_thresholds(
    net_new: bool, substance: bool, d1: int, d2: int, d3: int, d4: int, d5: int
) -> None:
    item = _sample_item()
    analysis = Stage2Analysis(
        item_id=item.item_id,
        passes_net_new_delta_gate=net_new,
        passes_substance_gate=substance,
        counterargument_to_drop="Could be marginal.",
        dimensions=RubricDimensions(
            delta_novelty=d1,
            durability=d2,
            actionability=d3,
            evidence_quality=d4,
            career_leverage=d5,
        ),
        target_repo_files=["playbooks/verification-engineering.md"],
        what_is_net_new="Concrete gap.",
        proposed_refinement="Add 3 lines.",
        career_takeaway="Org leverage.",
    )
    scored = score_stage2_analysis(item, analysis)

    if not net_new or not substance:
        assert scored.score == 0
        assert scored.disposition == "DROP"
        assert scored.gate_failure_reason != ""
    else:
        expected = d1 + d2 + d3 + d4 + d5
        assert scored.score == expected
        if expected >= 9:
            assert scored.disposition == "HIGH_SIGNAL"
        elif expected >= 6:
            assert scored.disposition == "STAGE"
        else:
            assert scored.disposition == "DROP"


@given(
    item_id=st.from_regex(r"[a-f0-9]{12}", fullmatch=True),
    feed_id=st.from_regex(r"[a-z0-9_\-]{3,20}", fullmatch=True),
    domain=st.one_of(
        st.from_regex(r"[a-z]{3,10}\.[a-z]{2,5}", fullmatch=True),
        st.from_regex(r"github\.com/[a-z0-9\-]{2,12}/[a-z0-9_\-]{2,12}", fullmatch=True),
        st.from_regex(r"x\.com/@[a-z0-9_]{2,12}", fullmatch=True),
        st.from_regex(r"medium\.com/@[a-z0-9_\-]{2,12}", fullmatch=True),
        st.from_regex(r"dev\.to/[a-z0-9_]{2,12}", fullmatch=True),
    ),
)
def test_property_radar_marker_round_trip(item_id: str, feed_id: str, domain: str) -> None:
    marker = format_radar_marker(item_id, feed_id, domain)
    parsed = parse_radar_markers(marker)
    assert parsed == [(item_id, feed_id, domain)]


def test_radar_marker_strips_trailing_slash_and_rejects_trailing_slash_in_parse() -> None:
    marker = format_radar_marker("abcdef012345", "hn-agentic", "github.com/org/repo/")
    assert "domain: github.com/org/repo -->" in marker
    assert parse_radar_markers(marker) == [("abcdef012345", "hn-agentic", "github.com/org/repo")]
    # Raw marker with trailing slash must not parse
    assert parse_radar_markers("<!-- radar-id: abcdef012345 source: hn domain: github.com/org/ -->") == []


def test_merge_into_weekly_digest_is_idempotent_and_appends_new_items() -> None:
    item1 = _sample_item("111111111111", "First Breakthrough")
    item2 = _sample_item("222222222222", "Second Refinement")

    def make_scored(item: CandidateItem, high: bool):
        dims = (
            RubricDimensions(
                delta_novelty=2, durability=2, actionability=2, evidence_quality=2, career_leverage=2
            )
            if high
            else RubricDimensions(
                delta_novelty=1, durability=2, actionability=1, evidence_quality=1, career_leverage=1
            )
        )
        return score_stage2_analysis(
            item,
            Stage2Analysis(
                item_id=item.item_id,
                passes_net_new_delta_gate=True,
                passes_substance_gate=True,
                counterargument_to_drop="Devil's advocate check.",
                dimensions=dims,
                target_repo_files=["playbooks/harness-loop-graph.md"],
                what_is_net_new="Net-new method.",
                proposed_refinement="Add bullet to section 3.",
                career_takeaway="Staff SWE leverage.",
            ),
        )

    s1 = make_scored(item1, high=True)
    s2 = make_scored(item2, high=False)

    md1, added1 = merge_into_weekly_digest(None, "2026-W47", [s1], updated_at="2026-11-19")
    assert added1 == 1
    assert "[10/10 · HIGH SIGNAL] First Breakthrough" in md1

    # Re-merging identical item adds 0 duplicates
    md_dup, added_dup = merge_into_weekly_digest(md1, "2026-W47", [s1], updated_at="2026-11-19")
    assert added_dup == 0
    assert md_dup == md1

    # Appending a new item updates Last Updated and appends only item2
    md2, added2 = merge_into_weekly_digest(md1, "2026-W47", [s1, s2], updated_at="2026-11-20")
    assert added2 == 1
    assert "`2026-11-20`" in md2
    markers = parse_radar_markers(md2)
    assert [m[0] for m in markers] == ["111111111111", "222222222222"]
