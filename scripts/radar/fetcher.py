"""Stage 0 deterministic fetcher, URL canonicalizer, deduper, and Survivor Enricher.

Zero LLM tokens are spent here (playbooks/harness-loop-graph.md, 4 Cuts #3):
- Parses RSS 2.0, Atom, GitHub Releases Atom (+ CHANGELOG.md fallback), and HN Algolia JSON.
- Uses incremental `ET.XMLPullParser` with `MAX_FEED_BYTES` (4 MiB) + entity-expansion
  guards so large full-content RSS feeds parse cleanly and stop as soon as `max_items`
  are collected (gracefully surviving trailing truncation if >=1 complete item parsed).
- Canonicalizes URLs (stripping tracking params and percent-encoding Markdown-breaking
  characters), deduplicates across sources by (canonical_url, title_hash, content_hash),
  drops items older than MAX_ITEM_AGE_DAYS, and filters noisy patch-only releases.
- Enriches only Stage 1 survivors that have short feed excerpts, with strict SSRF walls
  (including post-connect peer-IP verification against DNS rebinding) and fail-closed
  handling for paywalls/403s/CAPTCHAs.
"""

from __future__ import annotations

import email.utils
import hashlib
import http.client
import json
import os
import re
import ssl
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlparse, urlunparse

import yaml

from scripts.radar.config import (
    HTTP_TIMEOUT_SECONDS,
    MAX_FEED_BYTES,
    MAX_HTTP_BYTES,
    MAX_HTTP_REDIRECTS,
    MAX_STAGE1_EXCERPT_CHARS,
    MAX_STAGE2_BODY_CHARS,
    SHORT_BODY_ENRICH_THRESHOLD,
    PipelineConfig,
)
from scripts.radar.models import (
    CandidateItem,
    FeedEntry,
    FeedFetchSummary,
    FeedRegistry,
    SeenState,
)
from scripts.radar.security import (
    SSRFError,
    html_to_plain_text,
    is_blocked_ip,
    redact_secrets,
    sanitize_single_line,
    validate_public_https_url,
    validate_xml_no_entities,
)

# Tracking / marketing query parameters removed during URL canonicalization
_TRACKING_PARAMS = frozenset(
    {
        "ref",
        "source",
        "src",
        "fbclid",
        "gclid",
        "dclid",
        "msclkid",
        "mc_cid",
        "mc_eid",
        "igshid",
        "si",
        "s",
        "t",
        "_hsenc",
        "_hsmi",
        "mkt_tok",
    }
)

_SEMVER_RE = re.compile(r"\bv?(\d+)\.(\d+)\.(\d+)(?:[-+][A-Za-z0-9.\-]+)?\b")
_BOT_WALL_PATTERNS = (
    "verify you are human",
    "attention required! | cloudflare",
    "cf-browser-verification",
    "enable javascript and cookies to continue",
    "g-recaptcha",
    "hcaptcha",
    "just a moment...",
)
_LOGIN_OR_PAYWALL_PATTERNS = (
    "javascript is not available",
    "we've detected that javascript is disabled",
    "we’ve detected that javascript is disabled",
    "please enable javascript",
    "log in to x",
    "sign in to x",
    "sign in to continue reading",
    "log in to continue reading",
    "subscribe to continue reading",
    "this post is for paid subscribers",
    "create an account to read the full story",
    "members-only story",
)
MIN_FAST_LANE_CHARS = 600
MIN_FAST_LANE_WORDS = 100
MAX_PLAN_B_FETCHES = 3
_X_STATUS_DOMAINS = frozenset({"x.com", "twitter.com", "mobile.twitter.com"})
_X_INTERNAL_DOMAINS = frozenset(
    {
        "x.com",
        "twitter.com",
        "mobile.twitter.com",
        "publish.twitter.com",
        "help.twitter.com",
        "support.twitter.com",
        "developer.twitter.com",
        "business.twitter.com",
        "pbs.twimg.com",
        "abs.twimg.com",
        "video.twimg.com",
        "pic.twitter.com",
    }
)
_GENERIC_STUB_TITLES = frozenset(
    {
        "",
        "x",
        "twitter",
        "x / ?",
        "javascript is not available",
        "javascript is not available.",
        "log in to x",
        "sign in",
        "login",
        "just a moment...",
    }
)
_PLAIN_HTTPS_URL_RE = re.compile(r"https://[^\s\"'<>)\]]+")
_UNSAFE_URL_CHARS_RE = re.compile(r"[\s()\[\]<>\"'`\\]")
_GZIP_MAGIC = b"\x1f\x8b"


class FetchIncompleteError(ValueError):
    """Raised when fast-lane Plan B resolution fails the content-sufficiency gate (`FETCH_INCOMPLETE`)."""

    def __init__(
        self,
        message: str,
        *,
        url: str = "",
        canonical_url: str = "",
        title: str = "",
        body_chars: int = 0,
        word_count: int = 0,
        reason: str = "",
    ) -> None:
        super().__init__(message)
        self.url = url
        self.canonical_url = canonical_url
        self.title = title
        self.body_chars = body_chars
        self.word_count = word_count
        self.reason = reason or message


def decompress_if_gzipped(data: bytes, max_bytes: int = MAX_FEED_BYTES) -> bytes:
    """Safely decompress gzip payloads (e.g. Google Frontend CDN) with a hard byte cap."""
    if not data.startswith(_GZIP_MAGIC):
        return data
    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
    out = decompressor.decompress(data, max_bytes)
    return out


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Disable automatic redirects so every redirect hop passes SSRF validation."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _SSRFSafeHTTPSConnection(http.client.HTTPSConnection):
    """HTTPSConnection that verifies the connected socket peer IP before TLS/HTTP traffic.

    Eliminates DNS-rebinding TOCTOU between `validate_public_https_url` and socket connect.
    """

    def connect(self) -> None:
        super().connect()
        if self.sock is not None:
            try:
                peer_ip = self.sock.getpeername()[0]
            except OSError:
                peer_ip = ""
            if peer_ip and is_blocked_ip(peer_ip):
                self.close()
                raise SSRFError(f"Connected socket peer IP {peer_ip} is blocked (DNS rebinding guard)")


class _SSRFSafeHTTPSHandler(urllib.request.HTTPSHandler):
    """HTTPSHandler using _SSRFSafeHTTPSConnection when no HTTP(S)_PROXY is active."""

    def https_open(self, req: urllib.request.Request):
        if os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"):
            return super().https_open(req)
        return self.do_open(
            _SSRFSafeHTTPSConnection,
            req,
            context=ssl.create_default_context(),
        )


def _encode_markdown_unsafe_chars(text: str) -> str:
    return _UNSAFE_URL_CHARS_RE.sub(lambda m: quote(m.group(0), safe=""), text)


def canonicalize_url(url: str) -> str:
    """Normalize a URL deterministically so cross-posted links dedupe and never break Markdown."""
    raw = url.strip()
    parsed = urlparse(raw)
    scheme = parsed.scheme.lower() or "https"
    hostname = (parsed.hostname or "").lower().rstrip(".")
    port = parsed.port
    if (scheme == "https" and port == 443) or (scheme == "http" and port == 80):
        netloc = hostname
    elif port is not None:
        netloc = f"{hostname}:{port}"
    else:
        netloc = hostname

    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    path = _encode_markdown_unsafe_chars(path)

    filtered_qs = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=False)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_PARAMS
    ]
    filtered_qs.sort(key=lambda pair: (pair[0], pair[1]))
    query = _encode_markdown_unsafe_chars(urlencode(filtered_qs, doseq=True))
    return urlunparse((scheme, netloc, path, "", query, ""))


def make_item_id(canonical_url: str) -> str:
    """Return deterministic 12-char hex ID derived from canonical URL."""
    return hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:12]


def normalize_title_hash(title: str) -> str:
    """Normalize title into a short hash to collapse cross-posted identical stories."""
    norm = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:12]


def make_content_hash(text: str) -> str:
    """Hash normalized text body for content-level dedupe."""
    norm = re.sub(r"\s+", " ", text.lower()).strip()[:4000]
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:12]


def extract_domain(url: str) -> str:
    """Extract normalized lowercase domain (without leading www.)."""
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def parse_timestamp(raw: str | None) -> datetime | None:
    """Parse ISO-8601 or RFC-2822 timestamps into UTC datetimes."""
    if not raw or not raw.strip():
        return None
    text = raw.strip()
    try:
        iso = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso)
        return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
    except ValueError:
        pass
    try:
        dt = email.utils.parsedate_to_datetime(text)
        return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def is_patch_only_semver(text: str) -> bool:
    """Return True if a release title/tag represents a patch release (z > 0)."""
    m = _SEMVER_RE.search(text)
    if not m:
        return False
    return int(m.group(3)) > 0


def matches_keywords(text: str, keywords: list[str]) -> bool:
    """Case-insensitive substring match against a keyword list."""
    if not keywords:
        return True
    haystack = text.lower()
    return any(kw.lower() in haystack for kw in keywords)


def load_feed_registry(feeds_path: Path) -> FeedRegistry:
    """Load and validate radar/feeds.yaml."""
    raw = yaml.safe_load(feeds_path.read_text(encoding="utf-8"))
    return FeedRegistry.model_validate(raw or {})


def safe_http_get(
    url: str,
    *,
    user_agent: str = "upskilling-radar/0.1",
    timeout: float = HTTP_TIMEOUT_SECONDS,
    max_bytes: int = MAX_HTTP_BYTES,
    max_redirects: int = MAX_HTTP_REDIRECTS,
    resolver: Callable[[str], list[str]] | None = None,
) -> tuple[str, bytes]:
    """Fetch a public HTTPS URL with per-hop SSRF validation, peer-IP check, and byte caps."""
    current_url = validate_public_https_url(url, resolver=resolver)
    opener = urllib.request.build_opener(_NoRedirectHandler(), _SSRFSafeHTTPSHandler())

    for _ in range(max_redirects + 1):
        req = urllib.request.Request(
            current_url,
            headers={
                "User-Agent": user_agent,
                "Accept": "application/atom+xml, application/rss+xml, application/json, text/html, text/plain;q=0.9",
                "Accept-Encoding": "gzip, identity",
            },
            method="GET",
        )
        try:
            with opener.open(req, timeout=timeout) as resp:
                data = resp.read(max_bytes + 1)
                if len(data) > max_bytes:
                    data = data[:max_bytes]
                data = decompress_if_gzipped(data, max_bytes=max_bytes)
                return current_url, data
        except urllib.error.HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308):
                location = exc.headers.get("Location")
                if not location:
                    raise
                next_url = urljoin(current_url, location)
                current_url = validate_public_https_url(next_url, resolver=resolver)
                continue
            raise
    raise SSRFError(f"Exceeded max redirects ({max_redirects}) fetching {url}")


def _local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower() if "}" in tag else tag.lower()


def _child_text(elem: ET.Element, *names: str) -> str:
    wanted = {n.lower() for n in names}
    for child in elem:
        if _local_tag(child.tag) in wanted and child.text:
            return child.text.strip()
    return ""


def _extract_atom_entry(entry: ET.Element) -> dict[str, str] | None:
    title = _child_text(entry, "title")
    link = ""
    for child in entry:
        if _local_tag(child.tag) == "link":
            href = child.attrib.get("href", "").strip()
            rel = child.attrib.get("rel", "alternate").lower()
            if href and (rel == "alternate" or not link):
                link = href
    published = _child_text(entry, "published", "updated")
    content = _child_text(entry, "content", "summary")
    if title or link:
        return {"title": title, "url": link, "published_at": published, "raw_body": content}
    return None


def _extract_rss_item(item: ET.Element) -> dict[str, str] | None:
    title = _child_text(item, "title")
    link = _child_text(item, "link", "guid")
    published = _child_text(item, "pubdate", "date", "published", "updated")
    content = _child_text(item, "encoded", "description", "summary")
    if title or link:
        return {"title": title, "url": link, "published_at": published, "raw_body": content}
    return None


def parse_rss_or_atom(xml_bytes: bytes, feed: FeedEntry) -> list[dict[str, str]]:
    """Incrementally parse RSS 2.0 or Atom XML with DTD/ENTITY guard and early-stop resilience.

    Stops reading as soon as `feed.max_items` complete `<item>` or `<entry>` blocks are
    collected. If a multi-megabyte feed is truncated at `MAX_FEED_BYTES` after at least one
    complete item has been parsed, returns the complete items instead of failing the feed.
    """
    xml_bytes = decompress_if_gzipped(xml_bytes, max_bytes=MAX_FEED_BYTES)
    validate_xml_no_entities(xml_bytes)

    pull = ET.XMLPullParser(events=("start", "end"))
    entries: list[dict[str, str]] = []
    root_name = ""
    chunk_size = 65_536

    try:
        for offset in range(0, len(xml_bytes), chunk_size):
            pull.feed(xml_bytes[offset : offset + chunk_size])
            for event, elem in pull.read_events():
                tag = _local_tag(elem.tag)
                if event == "start":
                    if not root_name:
                        root_name = tag
                    continue

                # event == "end"
                if root_name == "feed" and tag == "entry":
                    extracted = _extract_atom_entry(elem)
                    if extracted is not None:
                        entries.append(extracted)
                    elem.clear()
                elif root_name != "feed" and tag == "item":
                    extracted = _extract_rss_item(elem)
                    if extracted is not None:
                        entries.append(extracted)
                    elem.clear()

                if len(entries) >= feed.max_items:
                    return entries[: feed.max_items]
        pull.close()
    except ET.ParseError:
        if entries:
            return entries[: feed.max_items]
        raise

    return entries[: feed.max_items]


def parse_hn_algolia(json_bytes: bytes, feed: FeedEntry) -> list[dict[str, str]]:
    """Parse HN Algolia search_by_date JSON payload into raw item dicts."""
    payload = json.loads(json_bytes.decode("utf-8", errors="replace"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object from HN Algolia feed, got {type(payload).__name__}")
    hits = payload.get("hits", [])
    if not isinstance(hits, list):
        raise ValueError(f"Expected JSON list for 'hits' in HN Algolia feed, got {type(hits).__name__}")
    entries: list[dict[str, str]] = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        raw_points = hit.get("points")
        try:
            points = int(float(raw_points)) if raw_points not in (None, "") else 0
        except (TypeError, ValueError):
            points = 0
        if points < feed.min_points:
            continue
        title = str(hit.get("title") or "").strip()
        url = str(hit.get("url") or "").strip()
        if not url and hit.get("objectID"):
            url = f"https://news.ycombinator.com/item?id={hit['objectID']}"
        published = str(hit.get("created_at") or "").strip()
        story_text = str(hit.get("story_text") or "").strip()
        body = story_text or f"HN discussion ({points} points): {title}"
        if title and url:
            entries.append(
                {"title": title, "url": url, "published_at": published, "raw_body": body}
            )
        if len(entries) >= feed.max_items:
            break
    return entries


def extract_changelog_section(changelog_md: str, version_title: str) -> str:
    """Extract the matching version block from a Markdown CHANGELOG.md."""
    m = _SEMVER_RE.search(version_title)
    if not m:
        return ""
    ver = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
    pattern = re.compile(rf"^##\s+\[?v?{re.escape(ver)}\]?(?:\s|$)", re.MULTILINE)
    match = pattern.search(changelog_md)
    if not match:
        return ""
    start = match.end()
    next_heading = re.search(r"^##\s+", changelog_md[start:], re.MULTILINE)
    end = start + next_heading.start() if next_heading else min(len(changelog_md), start + 4000)
    return changelog_md[start:end].strip()


def fetch_candidates(
    registry: FeedRegistry,
    seen: SeenState,
    config: PipelineConfig,
    *,
    now: datetime | None = None,
    http_get: Callable[[str], tuple[str, bytes]] | None = None,
) -> tuple[list[CandidateItem], list[FeedFetchSummary]]:
    """Run deterministic Stage 0 across all feeds in `registry`."""
    current_time = now or datetime.now(UTC)
    cutoff = current_time - timedelta(days=config.max_item_age_days)
    getter = http_get or (
        lambda u: safe_http_get(u, user_agent=config.user_agent, max_bytes=MAX_FEED_BYTES)
    )

    seen_urls = {rec.canonical_url for rec in seen.items.values()}
    seen_title_hashes = {rec.title_hash for rec in seen.items.values() if rec.title_hash}
    seen_content_hashes = {rec.content_hash for rec in seen.items.values() if rec.content_hash}

    candidates: list[CandidateItem] = []
    summaries: list[FeedFetchSummary] = []

    for feed in registry.feeds:
        summary = FeedFetchSummary(feed_id=feed.id)
        try:
            _, raw_bytes = getter(feed.url)
            if feed.type == "hn_algolia":
                raw_entries = parse_hn_algolia(raw_bytes, feed)
            else:
                raw_entries = parse_rss_or_atom(raw_bytes, feed)
        except Exception as exc:  # noqa: BLE001
            summary.ok = False
            summary.error = redact_secrets(str(exc))[:240]
            summaries.append(summary)
            continue

        changelog_cache: str | None = None
        summary.raw_count = len(raw_entries)
        effective_keywords = list(feed.keywords)
        if feed.use_default_keywords:
            effective_keywords.extend(registry.default_agentic_keywords)

        for entry in raw_entries:
            raw_url = entry.get("url", "").strip()
            if not raw_url.startswith("https://"):
                summary.filtered_count += 1
                continue
            canonical = canonicalize_url(raw_url)
            item_id = make_item_id(canonical)
            title = sanitize_single_line(entry.get("title", ""), max_chars=240)
            if not title:
                summary.filtered_count += 1
                continue

            pub_dt = parse_timestamp(entry.get("published_at"))
            if pub_dt is not None and pub_dt < cutoff:
                summary.filtered_count += 1
                continue

            body_text = html_to_plain_text(
                entry.get("raw_body", ""), max_chars=MAX_STAGE2_BODY_CHARS
            )

            if (
                feed.type == "github_releases"
                and feed.changelog_fallback_url
                and len(body_text) < 120
            ):
                if changelog_cache is None:
                    try:
                        _, cl_bytes = getter(feed.changelog_fallback_url)
                        changelog_cache = cl_bytes.decode("utf-8", errors="replace")
                    except Exception:  # noqa: BLE001
                        changelog_cache = ""
                section = extract_changelog_section(changelog_cache, title)
                if section:
                    body_text = html_to_plain_text(section, max_chars=MAX_STAGE2_BODY_CHARS)

            combined_text = f"{title}\n{body_text}"

            if feed.filter_patch_releases and is_patch_only_semver(title) and not matches_keywords(
                combined_text, effective_keywords
            ):
                summary.filtered_count += 1
                continue

            if (
                not feed.filter_patch_releases
                and effective_keywords
                and not matches_keywords(combined_text, effective_keywords)
            ):
                summary.filtered_count += 1
                continue

            title_hash = normalize_title_hash(title)
            content_hash = make_content_hash(body_text) if len(body_text) >= 120 else ""

            if (
                item_id in seen.items
                or canonical in seen_urls
                or title_hash in seen_title_hashes
                or (content_hash and content_hash in seen_content_hashes)
            ):
                summary.filtered_count += 1
                continue

            seen_urls.add(canonical)
            seen_title_hashes.add(title_hash)
            if content_hash:
                seen_content_hashes.add(content_hash)

            excerpt = body_text[:MAX_STAGE1_EXCERPT_CHARS]
            candidate = CandidateItem(
                item_id=item_id,
                feed_id=feed.id,
                feed_name=feed.name,
                title=title,
                url=raw_url,
                canonical_url=canonical,
                domain=extract_domain(canonical),
                published_at=pub_dt.isoformat() if pub_dt else None,
                excerpt=excerpt,
                body=body_text,
                title_hash=title_hash,
                content_hash=content_hash,
                enrichment_status=(
                    "feed_sufficient"
                    if len(body_text) >= SHORT_BODY_ENRICH_THRESHOLD
                    else "not_needed"
                ),
            )
            candidates.append(candidate)
            summary.new_count += 1

            if len(candidates) >= config.max_items_per_run:
                break

        summaries.append(summary)
        if len(candidates) >= config.max_items_per_run:
            break

    return candidates, summaries


class _PlanBHTMLParser(HTMLParser):
    """Extract og:url, canonical link, external anchor links, and metadata titles from stub HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_title = False
        self._title_parts: list[str] = []
        self.og_title: str = ""
        self.og_urls: list[str] = []
        self.canonical_urls: list[str] = []
        self.anchor_urls: list[str] = []
        self.description_urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        attr_map = {k.lower(): (v or "").strip() for k, v in attrs if k}
        if t == "title":
            self._in_title = True
        elif t == "meta":
            key = (attr_map.get("property") or attr_map.get("name") or "").lower()
            content = attr_map.get("content", "")
            if not content:
                return
            if key in ("og:url", "twitter:url"):
                self.og_urls.append(content)
            elif key in ("og:title", "twitter:title") and not self.og_title:
                self.og_title = content
            elif key in ("og:description", "twitter:description", "description"):
                for match in _PLAIN_HTTPS_URL_RE.findall(content):
                    self.description_urls.append(match.rstrip(".,;:!?"))
        elif t == "link":
            rel_tokens = {tok.lower() for tok in attr_map.get("rel", "").split()}
            href = attr_map.get("href", "")
            if "canonical" in rel_tokens and href:
                self.canonical_urls.append(href)
        elif t == "a":
            href = attr_map.get("href", "")
            if href:
                self.anchor_urls.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)

    @property
    def title_text(self) -> str:
        return "".join(self._title_parts).strip()


def _validate_fast_lane_ssrf(url: str, *, use_live_dns: bool) -> str:
    """Validate URL against SSRF rules (live DNS in production; deterministic IP/host checks in offline tests)."""
    if use_live_dns:
        return validate_public_https_url(url)
    return validate_public_https_url(url, resolver=lambda _host: ["93.184.216.34"])


def check_content_sufficiency(body_text: str, raw_html: str = "") -> tuple[bool, str]:
    """Enforce the fail-closed content-sufficiency gate (`>= 600` chars AND `>= 100` words, no walls)."""
    lowered_html = raw_html.lower()
    lowered_body = body_text.lower()
    if any(pat in lowered_html or pat in lowered_body for pat in _BOT_WALL_PATTERNS):
        return False, "Target URL is gated by a bot-wall or CAPTCHA"
    if any(pat in lowered_html or pat in lowered_body for pat in _LOGIN_OR_PAYWALL_PATTERNS):
        return False, "Target URL is gated by a login, paywall, or JS wall"

    char_count = len(body_text)
    word_count = len(body_text.split())
    if char_count < MIN_FAST_LANE_CHARS or word_count < MIN_FAST_LANE_WORDS:
        return (
            False,
            f"Extracted text below content-sufficiency gate "
            f"({char_count}/{MIN_FAST_LANE_CHARS} chars, {word_count}/{MIN_FAST_LANE_WORDS} words)",
        )
    return True, ""


def _parse_html_metadata_and_plan_b_urls(
    raw_html: str,
    current_url: str,
    visited: set[str],
    *,
    use_live_dns: bool,
) -> tuple[str, list[str]]:
    """Extract clean page title and ordered, SSRF-validated Plan B follow URLs."""
    parser = _PlanBHTMLParser()
    try:
        parser.feed(raw_html)
        parser.close()
    except Exception:  # noqa: BLE001
        pass

    raw_title = sanitize_single_line(
        html_to_plain_text(parser.title_text, max_chars=240), max_chars=240
    )
    og_title = sanitize_single_line(
        html_to_plain_text(parser.og_title, max_chars=240), max_chars=240
    )
    if raw_title and raw_title.lower() not in _GENERIC_STUB_TITLES:
        title = raw_title
    elif og_title and og_title.lower() not in _GENERIC_STUB_TITLES:
        title = og_title
    elif raw_title:
        title = raw_title
    else:
        title = extract_domain(current_url)

    ordered_raw = [
        *parser.og_urls,
        *parser.canonical_urls,
        *parser.anchor_urls,
        *parser.description_urls,
    ]
    candidates: list[str] = []
    for href in ordered_raw:
        resolved = urljoin(current_url, href.strip())
        if not resolved.lower().startswith("https://"):
            continue
        try:
            _validate_fast_lane_ssrf(resolved, use_live_dns=use_live_dns)
        except SSRFError:
            continue
        canon = canonicalize_url(resolved)
        if canon in visited or canon in candidates:
            continue
        if extract_domain(canon) in _X_INTERNAL_DOMAINS:
            continue
        candidates.append(canon)

    return title, candidates


def _make_fast_lane_item(
    *,
    original_url: str,
    canonical_url: str,
    title: str,
    body_text: str,
) -> CandidateItem:
    return CandidateItem(
        item_id=make_item_id(canonical_url),
        feed_id="fast-lane",
        feed_name="Manual Fast-Lane",
        title=title or extract_domain(canonical_url),
        url=original_url,
        canonical_url=canonical_url,
        domain=extract_domain(canonical_url),
        published_at=datetime.now(UTC).isoformat(),
        excerpt=body_text[:MAX_STAGE1_EXCERPT_CHARS],
        body=body_text,
        title_hash=normalize_title_hash(title or extract_domain(canonical_url)),
        content_hash=make_content_hash(body_text),
        enrichment_status="enriched",
    )


def build_fast_lane_candidate(
    url: str,
    *,
    config: PipelineConfig,
    http_get: Callable[[str], tuple[str, bytes]] | None = None,
) -> CandidateItem:
    """Create a validated CandidateItem from an owner-supplied URL with SSRF-safe Plan B resolution.

    Plan B resolution sequence for thin/stub pages:
    1. Follow SSRF-validated `og:url`, `<link rel="canonical">`, or external article links.
    2. For `x.com` / `twitter.com` status URLs, query `publish.twitter.com/oembed` and follow
       any embedded external blog links or extract full oEmbed text.
    3. Enforce the fail-closed content-sufficiency gate (`>= 600` chars AND `>= 100` words,
       no login/paywall/CAPTCHA/JS wall) before any LLM call, raising `FetchIncompleteError`.
    """
    use_live_dns = http_get is None
    initial_canonical = canonicalize_url(url)
    _validate_fast_lane_ssrf(initial_canonical, use_live_dns=use_live_dns)

    getter = http_get or (
        lambda u: safe_http_get(u, user_agent=config.user_agent, max_bytes=MAX_HTTP_BYTES)
    )

    def _safe_fetch(target_url: str) -> tuple[str, str]:
        _validate_fast_lane_ssrf(target_url, use_live_dns=use_live_dns)
        final_u, raw_b = getter(target_url)
        _validate_fast_lane_ssrf(final_u, use_live_dns=use_live_dns)
        return canonicalize_url(final_u), raw_b.decode("utf-8", errors="replace")

    visited: set[str] = {initial_canonical}
    best_canonical = initial_canonical
    best_title = extract_domain(initial_canonical)
    best_body = ""
    last_reason = "Empty response"
    initial_item: CandidateItem | None = None
    plan_b_urls: list[str] = []

    try:
        final_canonical, decoded = _safe_fetch(initial_canonical)
        visited.add(final_canonical)
        title, plan_b_urls = _parse_html_metadata_and_plan_b_urls(
            decoded, final_canonical, visited, use_live_dns=use_live_dns
        )
        body_text = html_to_plain_text(decoded, max_chars=MAX_STAGE2_BODY_CHARS)
        best_canonical = final_canonical
        best_title = title
        best_body = body_text
        is_ok, last_reason = check_content_sufficiency(body_text, decoded)
        if is_ok:
            initial_item = _make_fast_lane_item(
                original_url=url,
                canonical_url=final_canonical,
                title=title,
                body_text=body_text,
            )
            # Return immediately unless this is an X/Twitter status page with an embedded external article link
            if not (extract_domain(final_canonical) in _X_STATUS_DOMAINS and plan_b_urls):
                return initial_item
    except SSRFError:
        raise
    except Exception as exc:  # noqa: BLE001
        last_reason = f"Initial HTTP fetch failed: {redact_secrets(str(exc))[:160]}"

    # Plan B Step 1: follow og:url, <link rel="canonical">, or external article links
    extra_fetches = 0
    for cand_url in plan_b_urls:
        if extra_fetches >= MAX_PLAN_B_FETCHES:
            break
        extra_fetches += 1
        visited.add(cand_url)
        try:
            cand_final, cand_html = _safe_fetch(cand_url)
        except Exception:  # noqa: BLE001
            continue
        visited.add(cand_final)
        cand_title, _ = _parse_html_metadata_and_plan_b_urls(
            cand_html, cand_final, visited, use_live_dns=use_live_dns
        )
        cand_body = html_to_plain_text(cand_html, max_chars=MAX_STAGE2_BODY_CHARS)
        cand_ok, cand_reason = check_content_sufficiency(cand_body, cand_html)
        if cand_ok:
            return _make_fast_lane_item(
                original_url=url,
                canonical_url=cand_final,
                title=cand_title,
                body_text=cand_body,
            )
        if len(cand_body) > len(best_body):
            best_canonical = cand_final
            best_title = cand_title
            best_body = cand_body
        last_reason = cand_reason

    # Plan B Step 2: publish.twitter.com/oembed fallback for x.com / twitter.com status URLs
    is_x_url = (
        extract_domain(initial_canonical) in _X_STATUS_DOMAINS
        or extract_domain(best_canonical) in _X_STATUS_DOMAINS
    )
    if is_x_url and extra_fetches < MAX_PLAN_B_FETCHES:
        extra_fetches += 1
        oembed_candidates = [
            f"https://publish.twitter.com/oembed?{urlencode({'url': initial_canonical, 'omit_script': 'true'})}",
            f"https://publish.twitter.com/oembed?{urlencode({'url': initial_canonical})}",
            f"https://publish.twitter.com/oembed?url={initial_canonical}",
        ]
        oembed_raw: str | None = None
        for oembed_url in oembed_candidates:
            try:
                _, oembed_raw = _safe_fetch(oembed_url)
                break
            except KeyError:
                continue
            except Exception:  # noqa: BLE001
                break

        if oembed_raw:
            try:
                oembed_payload = json.loads(oembed_raw)
            except ValueError:
                oembed_payload = {}
            if isinstance(oembed_payload, dict):
                oembed_html = str(oembed_payload.get("html") or "")
                author_name = sanitize_single_line(
                    str(oembed_payload.get("author_name") or ""), max_chars=80
                )
                _, oembed_links = _parse_html_metadata_and_plan_b_urls(
                    oembed_html, initial_canonical, visited, use_live_dns=use_live_dns
                )
                for olink in oembed_links:
                    if extra_fetches >= MAX_PLAN_B_FETCHES:
                        break
                    extra_fetches += 1
                    visited.add(olink)
                    try:
                        ofinal, ohtml = _safe_fetch(olink)
                    except Exception:  # noqa: BLE001
                        continue
                    visited.add(ofinal)
                    otitle, _ = _parse_html_metadata_and_plan_b_urls(
                        ohtml, ofinal, visited, use_live_dns=use_live_dns
                    )
                    obody = html_to_plain_text(ohtml, max_chars=MAX_STAGE2_BODY_CHARS)
                    ook, oreason = check_content_sufficiency(obody, ohtml)
                    if ook:
                        return _make_fast_lane_item(
                            original_url=url,
                            canonical_url=ofinal,
                            title=otitle,
                            body_text=obody,
                        )
                    if len(obody) > len(best_body):
                        best_canonical = ofinal
                        best_title = otitle
                        best_body = obody
                    last_reason = oreason

                oembed_body = html_to_plain_text(oembed_html, max_chars=MAX_STAGE2_BODY_CHARS)
                oembed_ok, oembed_reason = check_content_sufficiency(oembed_body, oembed_html)
                if oembed_ok:
                    oembed_title = (
                        sanitize_single_line(
                            f"{author_name} on X: {oembed_body[:100]}", max_chars=240
                        )
                        if author_name
                        else best_title
                    )
                    return _make_fast_lane_item(
                        original_url=url,
                        canonical_url=initial_canonical,
                        title=oembed_title,
                        body_text=oembed_body,
                    )
                if len(oembed_body) > len(best_body):
                    best_body = oembed_body
                    if author_name and best_title.lower() in _GENERIC_STUB_TITLES:
                        best_title = sanitize_single_line(f"{author_name} on X", max_chars=240)
                last_reason = oembed_reason

    if initial_item is not None:
        return initial_item

    word_count = len(best_body.split())
    raise FetchIncompleteError(
        f"FETCH_INCOMPLETE: {last_reason} "
        f"(url={best_canonical}, body_chars={len(best_body)}, words={word_count})",
        url=url,
        canonical_url=best_canonical,
        title=best_title,
        body_chars=len(best_body),
        word_count=word_count,
        reason=last_reason,
    )


def enrich_survivor_body(
    item: CandidateItem,
    *,
    config: PipelineConfig,
    http_get: Callable[[str], tuple[str, bytes]] | None = None,
) -> CandidateItem:
    """Deterministically fetch readable target-page text ONLY for short-body Stage 1 survivors.

    Fails closed (`enrichment_status='fetch_blocked'`) on SSRF error, HTTP block, or CAPTCHA.
    """
    if len(item.body) >= SHORT_BODY_ENRICH_THRESHOLD:
        return item.model_copy(update={"enrichment_status": "feed_sufficient"})

    getter = http_get or (
        lambda u: safe_http_get(u, user_agent=config.user_agent, max_bytes=MAX_HTTP_BYTES)
    )
    try:
        _, raw_bytes = getter(item.canonical_url)
        decoded = raw_bytes.decode("utf-8", errors="replace")
        lowered = decoded.lower()
        if any(pat in lowered for pat in _BOT_WALL_PATTERNS):
            return item.model_copy(update={"enrichment_status": "fetch_blocked"})
        extracted = html_to_plain_text(decoded, max_chars=MAX_STAGE2_BODY_CHARS)
        if len(extracted) < 120:
            return item.model_copy(update={"enrichment_status": "fetch_blocked"})
        return item.model_copy(
            update={
                "body": extracted,
                "content_hash": make_content_hash(extracted),
                "enrichment_status": "enriched",
            }
        )
    except Exception:  # noqa: BLE001
        return item.model_copy(update={"enrichment_status": "fetch_blocked"})
