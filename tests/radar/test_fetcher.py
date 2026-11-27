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


def test_parse_hn_algolia_handles_malformed_json_shapes_and_non_numeric_points() -> None:
    import pytest

    from scripts.radar.fetcher import parse_hn_algolia

    feed = FeedEntry(
        id="hn-agentic",
        name="HN",
        type="hn_algolia",
        url="https://hn.algolia.com/api/v1/search_by_date?tags=story",
        min_points=10,
        max_items=5,
    )

    with pytest.raises(ValueError, match="Expected JSON object"):
        parse_hn_algolia(b"[]", feed)

    with pytest.raises(ValueError, match="Expected JSON object"):
        parse_hn_algolia(b"null", feed)

    with pytest.raises(ValueError, match="Expected JSON list"):
        parse_hn_algolia(b'{"hits": null}', feed)

    mixed_payload = json.dumps(
        {
            "hits": [
                "not-a-dict",
                {"title": "Bad points string", "url": "https://example.dev/a", "points": "N/A"},
                {"title": "Inf points string", "url": "https://example.dev/inf", "points": "inf"},
                {"title": "Good float points", "url": "https://example.dev/b", "points": "42.0"},
            ]
        }
    ).encode("utf-8")
    parsed = parse_hn_algolia(mixed_payload, feed)
    assert len(parsed) == 1
    assert parsed[0]["url"] == "https://example.dev/b"

    # Truncated JSON from HN is caught per-feed in fetch_candidates without aborting other feeds
    registry = FeedRegistry(feeds=[feed])
    config = PipelineConfig(repo_root=Path("."), feeds_path=Path("radar/feeds.yaml"))
    candidates, summaries = fetch_candidates(
        registry,
        SeenState(),
        config,
        http_get=lambda u: (u, b'{"hits": [{"title": "cut off'),
    )
    assert candidates == []
    assert len(summaries) == 1
    assert summaries[0].ok is False
    assert summaries[0].error


def test_source_identity_classification_feed_hints_and_aliases() -> None:
    from scripts.radar.fetcher import (
        classify_source,
        extract_source_key,
        is_source_subscribed,
        load_feed_registry,
        resolve_feed_hint,
        subscribed_source_keys,
    )

    # Scoped source keys across shared hosts
    assert extract_source_key("https://github.com/Anthropics/Claude-Code/blob/main/README.md") == "github.com/anthropics/claude-code"
    assert extract_source_key("https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed.xml") == "github.com/olshansk/rss-feeds"
    assert extract_source_key("https://gist.github.com/Karpathy/12345") == "gist.github.com/karpathy"
    assert extract_source_key("https://x.com/Karpathy/status/123456") == "x.com/@karpathy"
    assert extract_source_key("https://twitter.com/hwchase17/status/999") == "x.com/@hwchase17"
    assert extract_source_key("https://x.com/i/web/status/123") == "x.com"
    assert extract_source_key("https://x.com/search?q=agents") == "x.com"
    assert extract_source_key("https://x.com/intent/tweet") == "x.com"
    assert extract_source_key("https://medium.com/@alice-eng/agent-evals-123") == "medium.com/@alice-eng"
    assert extract_source_key("https://substack.com/@bob/note/c-123") == "substack.com/@bob"
    assert extract_source_key("https://addyo.substack.com/p/agentic-coding") == "addyo.substack.com"
    assert extract_source_key("https://dev.to/jdoe/deterministic-harnesses") == "dev.to/jdoe"
    assert extract_source_key("https://www.anthropic.com/engineering/building-agents") == "anthropic.com"

    # Source classes: one_off_artifact vs serial_publisher
    assert classify_source("https://github.com/org/repo/blob/main/README.md") == "one_off_artifact"
    assert classify_source("https://github.com/org/repo/tree/main/skills") == "one_off_artifact"
    assert classify_source("https://github.com/org/repo/issues/42") == "one_off_artifact"
    assert classify_source("https://github.com/org/repo/pull/7") == "one_off_artifact"
    assert classify_source("https://github.com/org/repo/discussions/9") == "one_off_artifact"
    assert classify_source("https://github.com/org/repo/commit/abc123") == "one_off_artifact"
    assert classify_source("https://github.com/org/repo") == "one_off_artifact"
    assert classify_source("https://raw.githubusercontent.com/org/repo/main/README.md") == "one_off_artifact"
    assert classify_source("https://gist.github.com/karpathy/12345") == "one_off_artifact"
    assert classify_source("https://news.ycombinator.com/item?id=12345") == "one_off_artifact"
    assert classify_source("https://arxiv.org/abs/2611.01234") == "one_off_artifact"
    assert classify_source("https://www.youtube.com/watch?v=abc") == "one_off_artifact"
    assert classify_source("https://youtu.be/abc") == "one_off_artifact"
    assert classify_source("https://x.com/karpathy/status/123") == "one_off_artifact"

    assert classify_source("https://github.com/org/repo/releases/tag/v2.0.0") == "serial_publisher"
    assert classify_source("https://github.com/org/repo/releases.atom") == "serial_publisher"
    assert classify_source("https://blog.example.dev/post") == "serial_publisher"
    assert classify_source("https://addyo.substack.com/p/post") == "serial_publisher"
    assert classify_source("https://medium.com/@alice/post") == "serial_publisher"
    assert classify_source("https://dev.to/alice/post") == "serial_publisher"

    # Feed hints
    assert resolve_feed_hint("medium.com/@alice") == "https://medium.com/feed/@alice"
    assert resolve_feed_hint("github.com/org/repo") == "https://github.com/org/repo/releases.atom"
    assert (
        resolve_feed_hint("blog.example.dev", "https://blog.example.dev/rss.xml")
        == "https://blog.example.dev/rss.xml"
    )
    assert resolve_feed_hint("blog.example.dev") == ""

    # Mirror & alias support in live radar/feeds.yaml
    repo_root = Path(__file__).resolve().parents[2]
    live_registry = load_feed_registry(repo_root / "radar" / "feeds.yaml")
    subscribed = subscribed_source_keys(live_registry)
    assert is_source_subscribed("anthropic.com", subscribed) is True
    assert is_source_subscribed("addyo.substack.com", subscribed) is True
    assert is_source_subscribed("addyosmani.com", subscribed) is True
    assert is_source_subscribed("github.com/anthropics/claude-code", subscribed) is True
    assert is_source_subscribed("github.com/openai/codex", subscribed) is True
    # Unrelated GitHub repos MUST NOT be treated as subscribed
    assert is_source_subscribed("github.com/langchain-ai/deepagents", subscribed) is False
    # Pre-release filtering enabled on both GitHub release feeds
    by_id = {f.id: f for f in live_registry.feeds}
    assert by_id["claude-code-releases"].filter_prereleases is True
    assert by_id["openai-codex-releases"].filter_prereleases is True


@given(
    owner=st.from_regex(r"[a-z][a-z0-9\-]{1,12}", fullmatch=True),
    repo=st.from_regex(r"[a-z][a-z0-9_\-]{1,12}", fullmatch=True),
    subpath=st.sampled_from(["", "/blob/main/README.md", "/releases/tag/v1.0.0", "/issues/12"]),
)
def test_property_extract_source_key_github_invariants(owner: str, repo: str, subpath: str) -> None:
    from scripts.radar.fetcher import extract_source_key, normalize_source_key

    key = extract_source_key(f"https://github.com/{owner.upper()}/{repo.upper()}{subpath}")
    assert key == f"github.com/{owner}/{repo}"
    assert not key.endswith("/")
    assert normalize_source_key(key) == key


def test_prerelease_filtering_and_deeper_atom_scan(tmp_path: Path) -> None:
    from scripts.radar.fetcher import is_prerelease_version

    assert is_prerelease_version("rust-v0.174.0-alpha.4") is True
    assert is_prerelease_version("v2.1.0-rc.1") is True
    assert is_prerelease_version("v1.0.0-beta2") is True
    assert is_prerelease_version("v0.5.0-canary.1") is True
    assert is_prerelease_version("codex-nightly") is True
    assert is_prerelease_version("v0.4.0-preview") is True
    assert is_prerelease_version("rust-v0.173.0") is False
    assert is_prerelease_version("v2.1.326") is False
    assert is_prerelease_version("v2.2.0+build.123") is False
    assert is_prerelease_version("v2.2.0 - preview docs") is False

    now = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
    # 12 alpha releases ahead of 1 stable release (exceeding max_items=10)
    alpha_entries = "\n".join(
        f"""
        <entry>
          <title>rust-v0.174.0-alpha.{i}</title>
          <link href="https://github.com/openai/codex/releases/tag/rust-v0.174.0-alpha.{i}" />
          <updated>2026-11-19T1{i % 10}:00:00Z</updated>
          <content>Shared release body with sandbox and mcp improvements for codex agents.</content>
        </entry>
        """
        for i in range(12, 0, -1)
    )
    stable_entry = """
        <entry>
          <title>rust-v0.173.0</title>
          <link href="https://github.com/openai/codex/releases/tag/rust-v0.173.0" />
          <updated>2026-11-18T10:00:00Z</updated>
          <content>Shared release body with sandbox and mcp improvements for codex agents.</content>
        </entry>
    """
    atom_xml = (
        f'<?xml version="1.0" encoding="utf-8"?>'
        f'<feed xmlns="http://www.w3.org/2005/Atom">{alpha_entries}{stable_entry}</feed>'
    ).encode()

    registry = FeedRegistry(
        feeds=[
            FeedEntry(
                id="openai-codex-releases",
                name="OpenAI Codex CLI Releases",
                type="github_releases",
                url="https://github.com/openai/codex/releases.atom",
                max_items=10,
                filter_patch_releases=True,
                filter_prereleases=True,
                keywords=["mcp", "sandbox"],
            )
        ]
    )
    config = PipelineConfig(repo_root=tmp_path, feeds_path=tmp_path / "feeds.yaml")
    candidates, summaries = fetch_candidates(
        registry,
        SeenState(),
        config,
        now=now,
        http_get=lambda u: (u, atom_xml),
    )
    assert summaries[0].ok is True
    # Deeper scan reaches stable rust-v0.173.0 and alphas do NOT poison seen_content_hashes
    assert [c.title for c in candidates] == ["rust-v0.173.0"]
    assert candidates[0].domain == "github.com/openai/codex"


def test_accurate_wall_detection_across_fast_lane_and_enricher(tmp_path: Path) -> None:
    from scripts.radar.fetcher import check_content_sufficiency
    from scripts.radar.security import html_to_plain_text

    config = PipelineConfig(repo_root=tmp_path, feeds_path=tmp_path / "feeds.yaml")
    article_prose = " ".join(
        ["Deterministic verification harnesses enforce bounded agent loop guarantees."] * 25
    )

    # 1. Readable blog with Disqus <noscript> and <script> g-recaptcha MUST PASS
    disqus_html = (
        "<html><head><title>Verification Harnesses</title>"
        '<link rel="alternate" type="application/rss+xml" href="/feed.xml" />'
        '<script src="https://cdn.example/g-recaptcha.js"></script>'
        "</head><body>"
        f"<article><p>{article_prose}</p></article>"
        "<noscript>Please enable JavaScript to view the comments powered by Disqus.</noscript>"
        "</body></html>"
    )
    disqus_body = html_to_plain_text(disqus_html)
    ok_disqus, reason_disqus = check_content_sufficiency(disqus_body, disqus_html)
    assert ok_disqus is True, reason_disqus

    # 2. Long security post mentioning "hcaptcha" in visible prose MUST PASS
    long_security_prose = " ".join(
        [
            "In this security audit we explain how browser sandboxes handle hcaptcha widgets "
            "and why agents must never bypass bot walls in production harnesses."
        ]
        * 25
    )
    assert len(long_security_prose) > 1500
    assert len(long_security_prose.split()) > 250
    sec_html = f"<html><head><title>Browser Audit</title></head><body><p>{long_security_prose}</p></body></html>"
    ok_sec, reason_sec = check_content_sufficiency(html_to_plain_text(sec_html), sec_html)
    assert ok_sec is True, reason_sec

    # 3. Explicit paywall truncation banner MUST FAIL CLOSED even after 2,000+ chars free preview
    long_preview = " ".join(
        ["Detailed free introduction covering agentic engineering workflows and eval gates."] * 35
    )
    assert len(long_preview) > 2000
    paywall_html = (
        "<html><head><title>Paid Post</title></head><body>"
        f"<p>{long_preview}</p><p>This post is for paid subscribers only.</p></body></html>"
    )
    ok_pay, reason_pay = check_content_sufficiency(html_to_plain_text(paywall_html), paywall_html)
    assert ok_pay is False
    assert "paywall" in reason_pay.lower()

    # 4. Survivor enricher catches >120-char JS-wall stubs AND passively discovers RSS feed on clean HTML
    short_item = CandidateItem(
        item_id=make_item_id("https://blog.example.dev/post"),
        feed_id="hn-agentic",
        feed_name="HN",
        title="Post",
        url="https://blog.example.dev/post",
        canonical_url="https://blog.example.dev/post",
        domain="blog.example.dev",
        excerpt="Short blurb",
        body="Short blurb",
    )
    js_stub = (
        b"<html><head><title>JavaScript is not available.</title></head>"
        b"<body>JavaScript is not available in this browser. "
        + (b"Please enable JavaScript to continue viewing this page. " * 4)
        + b"</body></html>"
    )
    blocked_js = enrich_survivor_body(short_item, config=config, http_get=lambda u: (u, js_stub))
    assert blocked_js.enrichment_status == "fetch_blocked"

    blocked_paywall = enrich_survivor_body(
        short_item, config=config, http_get=lambda u: (u, paywall_html.encode("utf-8"))
    )
    assert blocked_paywall.enrichment_status == "fetch_blocked"

    fetch_count = 0

    def _counting_getter(u: str) -> tuple[str, bytes]:
        nonlocal fetch_count
        fetch_count += 1
        return u, disqus_html.encode("utf-8")

    enriched_disqus = enrich_survivor_body(short_item, config=config, http_get=_counting_getter)
    assert enriched_disqus.enrichment_status == "enriched"
    assert enriched_disqus.discovered_feed_url == "https://blog.example.dev/feed.xml"
    assert fetch_count == 1  # zero extra HTTP requests for feed autodiscovery


def test_matches_keywords_exact_word_boundaries() -> None:
    from scripts.radar.fetcher import matches_keywords

    assert matches_keywords("Click the client button now", ["cli"]) is False
    assert matches_keywords("New Copilot CLI workflow", ["cli"]) is True
    assert matches_keywords("my-cli runner", ["cli"]) is True
    assert matches_keywords("Retrieval augmented evaluation pipeline", ["eval"]) is False
    assert matches_keywords("Deterministic eval harness", ["eval"]) is True
    assert matches_keywords("Deterministic evals harness", ["eval"]) is False
    assert matches_keywords("Deterministic evals harness", ["eval", "evals"]) is True
    assert matches_keywords("Update AGENTS.md and review.md for Code Mode", ["agents.md"]) is True
    assert matches_keywords("Added Code Mode execution", ["code mode"]) is True
    assert matches_keywords("Diff-triggered checks", ["diff-triggered"]) is True


def test_github_blob_raw_extraction_and_fallbacks(tmp_path: Path) -> None:
    from scripts.radar.fetcher import build_fast_lane_candidate

    config = PipelineConfig(repo_root=tmp_path, feeds_path=tmp_path / "feeds.yaml")
    blob_url = "https://github.com/acme/agent-kit/blob/main/docs/HARNESS.md"
    raw_url = "https://raw.githubusercontent.com/acme/agent-kit/main/docs/HARNESS.md"
    md_body = (
        "# Harness Verification Playbook\n\n"
        + " ".join(["Isolated verification loops prevent regressions across agentic commits."] * 25)
    ).encode("utf-8")

    # 1. Clean raw extraction keeps canonical_url on github.com and derives H1 title
    fetched: list[str] = []

    def _raw_getter(u: str) -> tuple[str, bytes]:
        fetched.append(u)
        if u == raw_url:
            return u, md_body
        raise AssertionError(f"Should not fetch HTML when raw succeeds: {u}")

    item = build_fast_lane_candidate(blob_url, config=config, http_get=_raw_getter)
    assert fetched == [raw_url]
    assert item.canonical_url == blob_url
    assert item.domain == "github.com/acme/agent-kit"
    assert item.title == "Harness Verification Playbook"

    # 2. NUL-byte binary payload falls back to normal HTML fetch
    fallback_html = (
        "<html><head><title>Fallback Page</title></head><body><article><p>"
        + " ".join(["Readable fallback documentation explaining verification invariants cleanly."] * 25)
        + "</p></article></body></html>"
    ).encode("utf-8")

    def _nul_fallback_getter(u: str) -> tuple[str, bytes]:
        if u == raw_url:
            return u, b"\x89PNG\r\n\x1a\n\x00\x00\x00binary"
        if u == blob_url:
            return u, fallback_html
        raise KeyError(u)

    item_fb = build_fast_lane_candidate(blob_url, config=config, http_get=_nul_fallback_getter)
    assert item_fb.title == "Fallback Page"
    assert item_fb.canonical_url == blob_url

    # 3. Raw fetch without H1 derives <owner>/<repo>/<path> title
    no_h1_body = " ".join(["Plain text engineering specification without markdown heading."] * 25).encode("utf-8")
    item_no_h1 = build_fast_lane_candidate(
        blob_url,
        config=config,
        http_get=lambda u: (u, no_h1_body),
    )
    assert item_no_h1.title == "acme/agent-kit/docs/HARNESS.md"


def test_fast_lane_plan_b_x_oembed_uses_redirected_x_url_and_discovers_feed(
    tmp_path: Path,
) -> None:
    from scripts.radar.fetcher import build_fast_lane_candidate

    config = PipelineConfig(repo_root=tmp_path, feeds_path=tmp_path / "feeds.yaml")
    short_url = "https://short.example/go-x"
    resolved_x = "https://x.com/karpathy/status/999999"
    blog_url = "https://blog.example.dev/harness-notes"
    blog_body = " ".join(["Strict deterministic boundaries keep agent loops reliable in production."] * 25)
    blog_html = (
        f'<html><head><title>Harness Notes</title>'
        f'<link rel="alternate" type="application/atom+xml" href="https://blog.example.dev/atom.xml" />'
        f'<link rel="alternate" type="application/rss+xml" href="http://127.0.0.1/evil.xml" />'
        f"</head><body><article><p>{blog_body}</p></article></body></html>"
    ).encode()
    x_js_wall = (
        b"<html><head><title>JavaScript is not available.</title></head>"
        b"<body>We've detected that JavaScript is disabled in this browser.</body></html>"
    )
    oembed_json = json.dumps(
        {
            "author_name": "Andrej Karpathy",
            "html": f'<blockquote>Read: <a href="{blog_url}">notes</a></blockquote>',
        }
    ).encode("utf-8")

    oembed_queries: list[str] = []

    def _redirect_getter(u: str) -> tuple[str, bytes]:
        if u == short_url:
            return resolved_x, x_js_wall
        if u.startswith("https://publish.twitter.com/oembed"):
            oembed_queries.append(u)
            return u, oembed_json
        if u == blog_url:
            return u, blog_html
        raise KeyError(u)

    item = build_fast_lane_candidate(short_url, config=config, http_get=_redirect_getter)
    assert len(oembed_queries) == 1
    assert "x.com%2Fkarpathy%2Fstatus%2F999999" in oembed_queries[0]
    assert item.canonical_url == blog_url
    assert item.discovered_feed_url == "https://blog.example.dev/atom.xml"


def test_diff_review_regressions_source_keys_prereleases_titles_and_blob_budget(
    tmp_path: Path,
) -> None:
    import pytest

    from scripts.radar.fetcher import (
        FetchIncompleteError,
        build_fast_lane_candidate,
        classify_source,
        extract_source_key,
        is_prerelease_version,
        is_source_subscribed,
        subscribed_source_keys,
    )

    config = PipelineConfig(repo_root=tmp_path, feeds_path=tmp_path / "feeds.yaml")

    # 1. dev.to/feed/<author> scopes identically to dev.to/<author>/<slug>, and bare shared hosts are one_off_artifact
    assert extract_source_key("https://dev.to/feed/Alice") == "dev.to/alice"
    reg = FeedRegistry(
        feeds=[
            FeedEntry(
                id="devto-alice",
                name="Alice on DEV",
                type="rss",
                url="https://dev.to/feed/alice",
            )
        ]
    )
    assert is_source_subscribed("dev.to/alice", subscribed_source_keys(reg)) is True
    assert classify_source("https://medium.com/some-pub/post") == "one_off_artifact"
    assert classify_source("https://substack.com/home/post/p-123") == "one_off_artifact"
    assert classify_source("https://dev.to/t/ai") == "one_off_artifact"

    # 2. Stable release titles containing hyphenated prose (-dev, -preview, -beta) must NOT be dropped
    assert is_prerelease_version("v2.2.0: Add local-dev sandbox and live-preview hooks") is False
    assert is_prerelease_version("v1.3.0: public-beta MCP support") is False
    assert is_prerelease_version("codex-nightly") is True
    assert is_prerelease_version("v0.4.0-preview") is True
    assert is_prerelease_version("Release 2.0", "https://github.com/org/repo/releases/tag/v2.0.0-rc.1") is True

    # 3. Escaped <template> in <title> must not truncate title via double HTML parsing
    long_body = " ".join(["Verification engineering invariants prevent regressions in agentic workflows."] * 22)
    escaped_title_html = (
        f"<html><head><title>Why &lt;template&gt; breaks naive scrapers</title></head>"
        f"<body><article><p>{long_body}</p></article></body></html>"
    ).encode()
    titled_item = build_fast_lane_candidate(
        "https://blog.example.dev/template-post",
        config=config,
        http_get=lambda u: (u, escaped_title_html),
    )
    assert "breaks naive scrapers" in titled_item.title

    # 4. Non-Markdown GitHub code blobs must NOT treat `# comment` as an H1 title
    py_blob = "https://github.com/acme/tool/blob/main/scripts/run.py"
    py_raw = "https://raw.githubusercontent.com/acme/tool/main/scripts/run.py"
    py_code = ("# Copyright 2026 Acme Corp\n" + ("def verify_step():\n    return 'deterministic harness check'\n" * 20)).encode()
    py_item = build_fast_lane_candidate(py_blob, config=config, http_get=lambda u: (u, py_code if u == py_raw else b""))
    assert py_item.title == "acme/tool/scripts/run.py"

    # 5. Thin raw GitHub blob fails closed WITHOUT falling back to GitHub HTML chrome
    thin_blob = "https://github.com/acme/tool/blob/main/README.md"
    thin_raw = "https://raw.githubusercontent.com/acme/tool/main/README.md"
    chrome_html = (
        "<html><head><title>GitHub</title></head><body>"
        + ("<div>GitHub navigation sidebar footer chrome text for repository view.</div>" * 30)
        + "</body></html>"
    ).encode()
    thin_calls: list[str] = []

    def _thin_blob_getter(u: str) -> tuple[str, bytes]:
        thin_calls.append(u)
        if u == thin_raw:
            return u, b"# Tiny\nToo short."
        return u, chrome_html

    with pytest.raises(FetchIncompleteError, match="FETCH_INCOMPLETE"):
        build_fast_lane_candidate(thin_blob, config=config, http_get=_thin_blob_getter)
    assert thin_calls == [thin_raw]

    thin_survivor = CandidateItem(
        item_id=make_item_id(thin_blob),
        feed_id="hn-agentic",
        feed_name="HN",
        title="Tiny",
        url=thin_blob,
        canonical_url=thin_blob,
        domain="github.com/acme/tool",
        body="short",
    )
    thin_calls.clear()
    blocked_thin = enrich_survivor_body(thin_survivor, config=config, http_get=_thin_blob_getter)
    assert blocked_thin.enrichment_status == "fetch_blocked"
    assert thin_calls == [thin_raw]

    # 6. Plan B MAX_PLAN_B_FETCHES = 3 cap holds strictly per actual HTTP request on GitHub blob links
    stub_with_3_blobs = (
        b"<html><head><title>Stub</title></head><body>Short stub "
        b'<a href="https://github.com/a/b/blob/main/1.md">1</a>'
        b'<a href="https://github.com/a/b/blob/main/2.md">2</a>'
        b'<a href="https://github.com/a/b/blob/main/3.md">3</a>'
        b"</body></html>"
    )
    plan_b_calls: list[str] = []

    def _failing_blobs_getter(u: str) -> tuple[str, bytes]:
        plan_b_calls.append(u)
        if u == "https://stub.example.dev/list":
            return u, stub_with_3_blobs
        raise OSError("HTTP 404")

    with pytest.raises(FetchIncompleteError):
        build_fast_lane_candidate(
            "https://stub.example.dev/list",
            config=config,
            http_get=_failing_blobs_getter,
        )
    # 1 initial fetch + at most MAX_PLAN_B_FETCHES (3) extra fetches = 4 total HTTP calls
    assert len(plan_b_calls) == 4




