"""Stage 0 fetcher tests: URL canonicalization properties, RSS/Atom/HN parsing, dedupe, and filters."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from scripts.radar.config import PipelineConfig
from scripts.radar.fetcher import (
    canonicalize_url,
    enrich_survivor_body,
    extract_changelog_section,
    fetch_candidates,
    is_patch_only_semver,
    make_item_id,
)
from scripts.radar.models import CandidateItem, FeedEntry, FeedRegistry, SeenRecord, SeenState


@given(
    host=st.from_regex(r"[a-z]{3,10}\.(com|dev|org)", fullmatch=True),
    path=st.from_regex(r"/[a-z0-9\-/]{0,30}", fullmatch=True),
    keep_val=st.from_regex(r"[a-z0-9]{1,8}", fullmatch=True),
    utm_val=st.from_regex(r"[a-z0-9]{1,8}", fullmatch=True),
)
def test_property_canonicalize_url_is_idempotent_and_strips_utm(
    host: str, path: str, keep_val: str, utm_val: str
) -> None:
    raw = f"HTTPS://{host.upper()}:443{path}/?utm_source={utm_val}&id={keep_val}&ref=twitter#frag"
    once = canonicalize_url(raw)
    twice = canonicalize_url(once)
    assert once == twice
    assert "utm_source" not in once
    assert "ref=" not in once
    assert "#" not in once
    assert f"id={keep_val}" in once


def test_patch_semver_detection() -> None:
    assert is_patch_only_semver("v2.1.326") is True
    assert is_patch_only_semver("v2.2.0") is False
    assert is_patch_only_semver("v3.0.0") is False
    assert is_patch_only_semver("Introducing Code Mode") is False


def test_extract_changelog_section() -> None:
    changelog = (
        "# Changelog\n\n"
        "## 2.1.326\n- Added Code Mode support for hooks and sandboxed scripts.\n\n"
        "## 2.1.325\n- Minor typo fix.\n"
    )
    sec = extract_changelog_section(changelog, "v2.1.326")
    assert "Code Mode support" in sec
    assert "Minor typo fix" not in sec


def test_fetch_candidates_dedupes_cross_source_filters_old_and_uses_changelog_fallback(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
    atom_xml = b"""<?xml version="1.0" encoding="utf-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>v2.1.326</title>
        <link href="https://github.com/anthropics/claude-code/releases/tag/v2.1.326" />
        <updated>2026-11-19T10:00:00Z</updated>
        <content></content>
      </entry>
      <entry>
        <title>v2.1.325</title>
        <link href="https://github.com/anthropics/claude-code/releases/tag/v2.1.325" />
        <updated>2026-11-18T10:00:00Z</updated>
        <content>Fixed minor Windows color typo.</content>
      </entry>
      <entry>
        <title>v2.0.0</title>
        <link href="https://github.com/anthropics/claude-code/releases/tag/v2.0.0" />
        <updated>2026-09-01T10:00:00Z</updated>
        <content>Old major release outside 14 day cutoff.</content>
      </entry>
    </feed>
    """
    changelog_md = (
        b"## 2.1.326\n- Added sandboxed MCP hook execution improvements and Code Mode flags.\n"
    )
    hn_json = json.dumps(
        {
            "hits": [
                {
                    "title": "v2.1.326",
                    "url": "https://github.com/anthropics/claude-code/releases/tag/v2.1.326?utm_source=hn",
                    "points": 250,
                    "created_at": "2026-11-19T12:00:00Z",
                },
                {
                    "title": "New verification harness for coding agents",
                    "url": "https://blog.example.dev/verification-harness?ref=hn",
                    "points": 180,
                    "created_at": "2026-11-19T15:00:00Z",
                },
                {
                    "title": "Best sourdough recipe for winter",
                    "url": "https://bakery.example/sourdough",
                    "points": 400,
                    "created_at": "2026-11-19T16:00:00Z",
                },
            ]
        }
    ).encode("utf-8")

    registry = FeedRegistry(
        default_agentic_keywords=["agent", "verification", "harness", "mcp", "hook", "code mode"],
        feeds=[
            FeedEntry(
                id="claude-code-releases",
                name="Claude Code Releases",
                type="github_releases",
                url="https://github.com/anthropics/claude-code/releases.atom",
                changelog_fallback_url="https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md",
                filter_patch_releases=True,
                keywords=["code mode", "hook", "mcp"],
            ),
            FeedEntry(
                id="hn-agentic",
                name="HN",
                type="hn_algolia",
                url="https://hn.algolia.com/api/v1/search_by_date",
                min_points=100,
                use_default_keywords=True,
            ),
        ],
    )

    responses = {
        "https://github.com/anthropics/claude-code/releases.atom": atom_xml,
        "https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md": changelog_md,
        "https://hn.algolia.com/api/v1/search_by_date": hn_json,
    }
    config = PipelineConfig(repo_root=tmp_path, feeds_path=tmp_path / "feeds.yaml")

    candidates, summaries = fetch_candidates(
        registry,
        SeenState(),
        config,
        now=now,
        http_get=lambda u: (u, responses[u]),
    )
    assert all(s.ok for s in summaries)
    # Kept: v2.1.326 (via CHANGELOG keyword match) + HN verification harness
    # Dropped: v2.1.325 (patch noise), v2.0.0 (>14d old), HN duplicate of v2.1.326, sourdough
    assert len(candidates) == 2
    assert candidates[0].title == "v2.1.326"
    assert "Code Mode" in candidates[0].body
    assert candidates[1].canonical_url == "https://blog.example.dev/verification-harness"

    # Re-running with seen state populated yields 0 new candidates
    seen = SeenState(
        items={
            c.item_id: SeenRecord(canonical_url=c.canonical_url, title_hash=c.title_hash)
            for c in candidates
        }
    )
    again, _ = fetch_candidates(
        registry, seen, config, now=now, http_get=lambda u: (u, responses[u])
    )
    assert again == []


def test_survivor_enricher_fails_closed_on_captcha_and_enriches_clean_article(
    tmp_path: Path,
) -> None:
    config = PipelineConfig(repo_root=tmp_path, feeds_path=tmp_path / "feeds.yaml")
    short_item = CandidateItem(
        item_id=make_item_id("https://blog.example.dev/post"),
        feed_id="hn-agentic",
        feed_name="HN",
        title="Post",
        url="https://blog.example.dev/post",
        canonical_url="https://blog.example.dev/post",
        domain="blog.example.dev",
        excerpt="Short HN blurb",
        body="Short HN blurb",
    )

    blocked = enrich_survivor_body(
        short_item,
        config=config,
        http_get=lambda u: (u, b"<html><body>Please verify you are human (Cloudflare)</body></html>"),
    )
    assert blocked.enrichment_status == "fetch_blocked"

    clean_html = (
        b"<html><body><article><h1>Deep Verification</h1>"
        + (b"<p>Detailed engineering walkthrough with code and eval results.</p>" * 10)
        + b"</article></body></html>"
    )
    enriched = enrich_survivor_body(
        short_item,
        config=config,
        http_get=lambda u: (u, clean_html),
    )
    assert enriched.enrichment_status == "enriched"
    assert "Detailed engineering walkthrough" in enriched.body
