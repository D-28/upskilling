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


def test_parse_rss_or_atom_recovers_complete_items_from_truncated_large_feed() -> None:
    from scripts.radar.fetcher import parse_rss_or_atom

    truncated_rss = (
        b'<?xml version="1.0" encoding="utf-8"?>'
        b"<rss version=\"2.0\"><channel><title>Large Substack</title>"
        b"<item><title>First Complete Post</title><link>https://example.com/1</link>"
        b"<description><![CDATA[<p>Full content 1</p>]]></description></item>"
        b"<item><title>Second Complete Post</title><link>https://example.com/2</link>"
        b"<description><![CDATA[<p>Full content 2</p>]]></description></item>"
        b"<item><title>Third Truncated Post</title><link>https://example.com/3</link>"
        b"<description><![CDATA[<p>Unclosed CDATA section cut mid-stream..."
    )
    feed = FeedEntry(
        id="addy-osmani-elevate",
        name="Elevate",
        type="rss",
        url="https://addyo.substack.com/feed",
        max_items=10,
    )
    parsed = parse_rss_or_atom(truncated_rss, feed)
    assert len(parsed) == 2
    assert parsed[0]["title"] == "First Complete Post"
    assert parsed[1]["title"] == "Second Complete Post"


def test_canonicalize_url_percent_encodes_markdown_link_breakout_chars() -> None:
    malicious = 'https://evil.example/path) [Click](https://phish.example)?q=a(b)`c"'
    canon = canonicalize_url(malicious)
    assert ")" not in canon
    assert "(" not in canon
    assert " " not in canon
    assert "`" not in canon
    assert '"' not in canon


def test_parse_rss_or_atom_handles_gzipped_feed_payload() -> None:
    import gzip

    from scripts.radar.fetcher import parse_rss_or_atom

    raw_xml = (
        b'<?xml version="1.0" encoding="utf-8"?>'
        b"<rss version=\"2.0\"><channel><title>DeepMind Blog</title>"
        b"<item><title>Gzipped Agent Post</title><link>https://deepmind.google/blog/post-1</link>"
        b"<description>Agent verification details</description></item></channel></rss>"
    )
    gzipped = gzip.compress(raw_xml)
    assert gzipped.startswith(b"\x1f\x8b")

    feed = FeedEntry(
        id="google-deepmind-blog",
        name="Google DeepMind Blog",
        type="rss",
        url="https://deepmind.google/blog/rss.xml",
        max_items=5,
    )
    items = parse_rss_or_atom(gzipped, feed)
    assert len(items) == 1
    assert items[0]["title"] == "Gzipped Agent Post"


def test_fast_lane_plan_b_resolves_x_stub_with_embedded_blog_link_and_oembed(
    tmp_path: Path,
) -> None:
    import pytest

    from scripts.radar.fetcher import FetchIncompleteError, build_fast_lane_candidate

    config = PipelineConfig(repo_root=tmp_path, feeds_path=tmp_path / "feeds.yaml")
    full_blog_body = " ".join(
        ["Deterministic verification harnesses and isolated agent sandboxes prevent regressions."]
        * 20
    )
    full_blog_html = (
        f"<html><head><title>Deep Agent Harnesses in Production</title></head>"
        f"<body><article><p>{full_blog_body}</p></article></body></html>"
    ).encode()

    # 1. X stub with embedded external blog link resolves directly to the blog post via Plan B
    x_stub_with_link = (
        b"<html><head><title>X</title>"
        b'<meta property="og:url" content="https://x.com/hwchase17/status/2124181216719151585" />'
        b"</head><body>JavaScript is not available. "
        b'<a href="https://blog.langchain.dev/deep-agent-harnesses?utm_source=x">Read post</a>'
        b"</body></html>"
    )
    responses_direct = {
        "https://x.com/hwchase17/status/2124181216719151585": x_stub_with_link,
        "https://blog.langchain.dev/deep-agent-harnesses": full_blog_html,
    }
    item = build_fast_lane_candidate(
        "https://x.com/hwchase17/status/2124181216719151585?s=20",
        config=config,
        http_get=lambda u: (u, responses_direct[u]),
    )
    assert item.canonical_url == "https://blog.langchain.dev/deep-agent-harnesses"
    assert item.domain == "blog.langchain.dev"
    assert item.title == "Deep Agent Harnesses in Production"
    assert len(item.body) >= 600
    assert len(item.body.split()) >= 100

    # 2. X JS-wall stub without inline links resolves via publish.twitter.com/oembed -> external blog link
    x_pure_js_shell = (
        b"<html><head><title>JavaScript is not available.</title></head>"
        b"<body>We've detected that JavaScript is disabled in this browser.</body></html>"
    )
    oembed_json = json.dumps(
        {
            "author_name": "Harrison Chase",
            "html": (
                '<blockquote>New post on agent harness boundaries: '
                '<a href="https://blog.langchain.dev/deep-agent-harnesses">blog.langchain.dev</a>'
                "</blockquote>"
            ),
        }
    ).encode("utf-8")

    def fake_oembed_getter(u: str) -> tuple[str, bytes]:
        if u.startswith("https://publish.twitter.com/oembed"):
            return u, oembed_json
        if u == "https://x.com/hwchase17/status/2124181216719151585":
            return u, x_pure_js_shell
        if u == "https://blog.langchain.dev/deep-agent-harnesses":
            return u, full_blog_html
        raise KeyError(u)

    item_via_oembed = build_fast_lane_candidate(
        "https://x.com/hwchase17/status/2124181216719151585",
        config=config,
        http_get=fake_oembed_getter,
    )
    assert item_via_oembed.canonical_url == "https://blog.langchain.dev/deep-agent-harnesses"
    assert len(item_via_oembed.body) >= 600
    assert len(item_via_oembed.body.split()) >= 100

    # 3. Malicious SSRF canonical/external links inside a stub are blocked and never fetched
    ssrf_stub = (
        b"<html><head><title>Stub</title>"
        b'<link rel="canonical" href="https://169.254.169.254/latest/meta-data/" />'
        b'</head><body><a href="http://127.0.0.1/admin">Internal</a>Short stub.</body></html>'
    )
    fetched_urls: list[str] = []

    def ssrf_tracking_getter(u: str) -> tuple[str, bytes]:
        fetched_urls.append(u)
        return u, ssrf_stub

    with pytest.raises(FetchIncompleteError, match="FETCH_INCOMPLETE"):
        build_fast_lane_candidate(
            "https://stub.example.dev/thin",
            config=config,
            http_get=ssrf_tracking_getter,
        )
    assert fetched_urls == ["https://stub.example.dev/thin"]

