"""Runnable Python starter: Property-Based (Hypothesis) & Differential Tests.

Copy and adapt these four patterns when hardening parsers, state normalizers,
or legacy-to-refactored migrations (see playbooks/verification-engineering.md):
  1. Round-trip property:     decode(encode(x)) == x
  2. Idempotency property:    normalize(normalize(x)) == normalize(x)
  3. Invariant preservation:  structural guarantees hold for all generated inputs
  4. Differential harness:    legacy(x) == refactored(x) after deterministic normalization

Run directly via pytest:
  uv run pytest -v examples/testing/test_property_and_differential_starter.py
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Example Units Under Test (replace with your own production functions)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Record:
    id: str
    tags: tuple[str, ...]
    score: int


def encode_record(rec: Record) -> str:
    return json.dumps({"id": rec.id, "tags": list(rec.tags), "score": rec.score})


def decode_record(raw: str) -> Record:
    data = json.loads(raw)
    return Record(id=str(data["id"]), tags=tuple(data["tags"]), score=int(data["score"]))


def normalize_tag(raw: str) -> str:
    """Lowercase, trim, and collapse internal whitespace/hyphens into single dashes."""
    collapsed = re.sub(r"[\s-]+", "-", raw.strip().lower())
    return collapsed.strip("-")


def rank_top_k(scores: list[int], k: int) -> list[int]:
    """Return the k highest scores in descending order."""
    if k <= 0:
        return []
    return sorted(scores, reverse=True)[:k]


def legacy_summarize_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Reference legacy implementation (e.g., before migration or refactor)."""
    counts: dict[str, int] = {}
    for ev in events:
        kind = normalize_tag(ev["kind"])
        if not kind:
            continue
        counts[kind] = counts.get(kind, 0) + int(ev["weight"])
    return {
        "engine": "legacy-v1",  # Volatile metadata field ignored during diffing
        "totals": [{"kind": k, "weight": v} for k, v in counts.items()],
    }


def refactored_summarize_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    """New implementation that must match legacy behavior on all valid inputs."""
    totals: dict[str, int] = {}
    for ev in events:
        if key := normalize_tag(ev["kind"]):
            totals[key] = totals.get(key, 0) + int(ev["weight"])
    return {
        "engine": "refactored-v2",
        "totals": [{"kind": k, "weight": totals[k]} for k in sorted(totals)],
    }


def normalize_for_diff(output: dict[str, Any]) -> dict[str, Any]:
    """Strip expected volatile metadata and canonicalize ordering before comparing."""
    return {
        "totals": sorted(output["totals"], key=lambda row: row["kind"]),
    }


# ---------------------------------------------------------------------------
# 1. Round-Trip Property: decode(encode(x)) == x
# ---------------------------------------------------------------------------

_record_strategy = st.builds(
    Record,
    id=st.text(min_size=1, max_size=32),
    tags=st.lists(st.text(max_size=16), max_size=8).map(tuple),
    score=st.integers(min_value=-10_000, max_value=10_000),
)


@given(record=_record_strategy)
def test_round_trip_record_codec(record: Record) -> None:
    assert decode_record(encode_record(record)) == record


# ---------------------------------------------------------------------------
# 2. Idempotency Property: f(f(x)) == f(x)
# ---------------------------------------------------------------------------


@given(raw=st.text(max_size=64))
def test_normalize_tag_is_idempotent(raw: str) -> None:
    once = normalize_tag(raw)
    twice = normalize_tag(once)
    assert twice == once


# ---------------------------------------------------------------------------
# 3. Invariant Preservation
# ---------------------------------------------------------------------------


@given(
    scores=st.lists(st.integers(min_value=-1000, max_value=1000), max_size=40),
    k=st.integers(min_value=0, max_value=50),
)
def test_rank_top_k_preserves_invariants(scores: list[int], k: int) -> None:
    top = rank_top_k(scores, k)
    # Length bound
    assert len(top) == min(len(scores), k)
    # Monotonic non-increasing order
    assert all(top[i] >= top[i + 1] for i in range(len(top) - 1))
    # Every selected item comes from the input and beats or ties any excluded item
    if top and len(scores) > k:
        assert min(top) >= sorted(scores, reverse=True)[k]


# ---------------------------------------------------------------------------
# 4. Differential Test Harness: legacy vs. refactored across generated inputs
# ---------------------------------------------------------------------------

_event_strategy = st.fixed_dictionaries(
    {
        "kind": st.text(
            alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters=" -"),
            max_size=16,
        ),
        "weight": st.integers(min_value=-100, max_value=100),
    }
)


@given(events=st.lists(_event_strategy, max_size=30))
def test_differential_legacy_vs_refactored(events: list[dict[str, Any]]) -> None:
    legacy_out = normalize_for_diff(legacy_summarize_events(events))
    refactored_out = normalize_for_diff(refactored_summarize_events(events))
    assert refactored_out == legacy_out
