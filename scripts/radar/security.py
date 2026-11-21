"""Deterministic security boundaries: SSRF walls, XML entity guard, secret redaction, and Markdown sanitization.

Enforces Harness Walls outside the model (playbooks/harness-loop-graph.md):
- Blocks non-HTTPS URLs and any hostname resolving to private, loopback, link-local
  (including cloud metadata 169.254.169.254), CGNAT, multicast, or reserved IPs.
- Blocks XML DTD / ENTITY expansion ("Billion Laughs" / XXE) before XML parsing.
- Redacts API keys and tokens from all error strings before logging or persisting to
  public artifacts / `radar-state`.
- Strips HTML tags, scripts, styles, unsafe markdown link schemes, and bare GitHub
  `@mentions` from untrusted external feed text before it enters prompts or PRs.
"""

from __future__ import annotations

import html
import ipaddress
import os
import re
import socket
from collections.abc import Callable
from html.parser import HTMLParser
from urllib.parse import urlparse

# Carrier-grade NAT (RFC 6598) is not always flagged by is_private on older Python versions
_CGNAT_NET = ipaddress.ip_network("100.64.0.0/10")
_METADATA_HOSTNAMES = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "metadata.google.internal",
        "metadata",
        "instance-data",
    }
)


class SSRFError(ValueError):
    """Raised when a URL violates SSRF egress boundaries."""


class UnsafeXMLError(ValueError):
    """Raised when an XML payload contains forbidden DTD or ENTITY declarations."""


def is_blocked_ip(ip_str: str) -> bool:
    """Return True if an IPv4/IPv6 address is non-global / unsafe for outbound fetch."""
    addr = ipaddress.ip_address(ip_str)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    if isinstance(addr, ipaddress.IPv4Address) and addr in _CGNAT_NET:
        return True
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
        or not addr.is_global
    )


def validate_public_https_url(
    url: str,
    resolver: Callable[[str], list[str]] | None = None,
) -> str:
    """Validate that `url` is a safe public HTTPS URL with no private/metadata DNS targets.

    Args:
        url: Candidate URL string.
        resolver: Optional custom hostname->IP list resolver (used for deterministic tests).

    Returns:
        Normalized URL string if safe.

    Raises:
        SSRFError: If scheme, host, port, or resolved IP is disallowed.
    """
    if not url or not isinstance(url, str):
        raise SSRFError("URL must be a non-empty string")
    cleaned = url.strip()
    parsed = urlparse(cleaned)
    if parsed.scheme.lower() != "https":
        raise SSRFError(f"Only https:// URLs are permitted (got '{parsed.scheme}')")
    if not parsed.hostname:
        raise SSRFError("URL missing hostname")
    if parsed.username or parsed.password:
        raise SSRFError("URL credentials in userinfo are forbidden")
    if parsed.port is not None and parsed.port not in (443,):
        raise SSRFError(f"Non-standard port {parsed.port} is disallowed")

    host = parsed.hostname.lower().rstrip(".")
    if host in _METADATA_HOSTNAMES or host.endswith(".local") or host.endswith(".internal"):
        raise SSRFError(f"Blocked internal hostname: {host}")

    # Direct IP literal check (parse separately so ValueError never swallows SSRFError)
    ip_literal = None
    try:
        ip_literal = ipaddress.ip_address(host)
    except ValueError:
        ip_literal = None

    if ip_literal is not None:
        if is_blocked_ip(host):
            raise SSRFError(f"Blocked non-public IP literal: {host}")
        return cleaned

    if resolver is not None:
        resolved_ips = resolver(host)
    else:
        try:
            infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise SSRFError(f"DNS resolution failed for {host}: {exc}") from exc
        resolved_ips = sorted({str(info[4][0]) for info in infos})

    if not resolved_ips:
        raise SSRFError(f"No DNS records resolved for {host}")

    for ip_str in resolved_ips:
        if is_blocked_ip(ip_str):
            raise SSRFError(f"Hostname {host} resolved to blocked IP {ip_str}")

    return cleaned


_XML_ENTITY_DECL_RE = re.compile(rb"<!\s*ENTITY\b", re.IGNORECASE)
_XML_DOCTYPE_DECL_RE = re.compile(rb"<!\s*DOCTYPE\b", re.IGNORECASE)
_XML_ROOT_START_RE = re.compile(rb"<\s*(?:rss|feed|rdf:rdf)\b", re.IGNORECASE)


def validate_xml_no_entities(xml_bytes: bytes) -> None:
    """Reject XML entity declarations and prolog DOCTYPEs (Billion Laughs / XXE defense).

    Allows `<!DOCTYPE html>` when it appears inside `<![CDATA[...]]>` item bodies after
    the root `<rss>` / `<feed>` tag, while blocking any `<!ENTITY` or prolog `<!DOCTYPE`.
    """
    if _XML_ENTITY_DECL_RE.search(xml_bytes):
        raise UnsafeXMLError("XML ENTITY declarations are forbidden (entity expansion guard)")
    root_match = _XML_ROOT_START_RE.search(xml_bytes)
    prolog = xml_bytes[: root_match.start()] if root_match else xml_bytes[:4096]
    if _XML_DOCTYPE_DECL_RE.search(prolog):
        raise UnsafeXMLError("XML prolog DOCTYPE declarations are forbidden")


_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{12,}"),
    re.compile(r"(?i)((?:api[_-]?key|token|secret|password)\s*[=:]\s*)[^\s&\"']{6,}"),
)


def redact_secrets(text: str) -> str:
    """Scrub API keys and bearer tokens from error messages before logging or persisting."""
    if not text:
        return ""
    scrubbed = text
    env_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if len(env_key) >= 8 and env_key in scrubbed:
        scrubbed = scrubbed.replace(env_key, "[REDACTED]")
    gh_token = os.environ.get("GH_TOKEN", "").strip()
    if len(gh_token) >= 8 and gh_token in scrubbed:
        scrubbed = scrubbed.replace(gh_token, "[REDACTED]")

    for idx, pat in enumerate(_SECRET_PATTERNS):
        if idx >= 3:
            scrubbed = pat.sub(r"\1[REDACTED]", scrubbed)
        else:
            scrubbed = pat.sub("[REDACTED]", scrubbed)
    return scrubbed


class _SafeTextHTMLParser(HTMLParser):
    """Minimal stdlib HTML-to-text extractor that drops script/style/noscript blocks."""

    _SKIP_TAGS = frozenset({"script", "style", "noscript", "svg", "iframe", "object", "embed"})
    _BLOCK_TAGS = frozenset(
        {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "pre", "blockquote"}
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if t in self._SKIP_TAGS:
            self._skip_depth += 1
        elif self._skip_depth == 0 and t in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif self._skip_depth == 0 and t in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        raw = "".join(self._parts)
        raw = html.unescape(raw)
        lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in raw.splitlines()]
        compact = "\n".join(line for line in lines if line)
        return compact.strip()


def html_to_plain_text(raw_html: str, max_chars: int = 16_000) -> str:
    """Deterministically strip HTML/script/style into bounded plain text."""
    if not raw_html:
        return ""
    parser = _SafeTextHTMLParser()
    parser.feed(raw_html)
    parser.close()
    text = parser.get_text()
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    if len(text) > max_chars:
        return text[: max_chars - 3].rstrip() + "..."
    return text


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]*)\)")
_MD_REF_LINK_DEF_RE = re.compile(r"^\s*\[[^\]]+\]:\s*\S+.*$", re.MULTILINE)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_BARE_MENTION_RE = re.compile(
    r"(?<!`)(?<![A-Za-z0-9._%+\-/])@([A-Za-z0-9](?:[A-Za-z0-9_\-]{0,37}[A-Za-z0-9])?)(?!`)"
)


def _sanitize_md_link(match: re.Match[str]) -> str:
    label = match.group(1)
    target = match.group(2).strip()
    if target.lower().startswith("https://") and not any(c in target for c in " \t\n\r()<>\"'`"):
        return f"[{label}]({target})"
    return label


def sanitize_markdown_text(text: str, max_chars: int = 2_000) -> str:
    """Sanitize untrusted or LLM-emitted text before writing to radar/*.md or PR bodies.

    - Removes HTML comments (so untrusted text cannot forge `<!-- radar-id: ... -->` markers)
    - Removes raw HTML tags (`<script>`, `<img>`, `<iframe>`, etc.)
    - Neutralizes markdown images (prevents external tracking pixels in GitHub PRs)
    - Strips any markdown links that are not clean `https://` targets (blocks `javascript:`,
      `data:`, `vbscript:`, `file:`, and reference-style link definitions)
    - Wraps bare `@username` mentions in backticks (`` `@username` ``) so public-repo
      Draft PRs never send unsolicited notification pings to random GitHub users.
    """
    if not text:
        return ""
    cleaned = _HTML_COMMENT_RE.sub("", text)
    cleaned = _MD_IMAGE_RE.sub(lambda m: m.group(1) or "[image removed]", cleaned)
    cleaned = _MD_REF_LINK_DEF_RE.sub("", cleaned)
    cleaned = _MD_LINK_RE.sub(_sanitize_md_link, cleaned)
    cleaned = _HTML_TAG_RE.sub("", cleaned)
    cleaned = _BARE_MENTION_RE.sub(r"`@\1`", cleaned)
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", cleaned)
    cleaned = cleaned.strip()
    if len(cleaned) > max_chars:
        cleaned = cleaned[: max_chars - 3].rstrip() + "..."
    return cleaned


def sanitize_single_line(text: str, max_chars: int = 200) -> str:
    """Sanitize and collapse text to a safe single line (for titles/tables)."""
    cleaned = sanitize_markdown_text(text, max_chars=max_chars)
    cleaned = re.sub(r"\s+", " ", cleaned).replace("|", "\\|").strip()
    if len(cleaned) > max_chars:
        cleaned = cleaned[: max_chars - 3].rstrip() + "..."
    return cleaned


_ALLOWED_REPO_PATH_RE = re.compile(
    r"^(?:(?:playbooks|templates|skills|hooks|radar|docs)/[A-Za-z0-9_.\-/]+|todo\.md|README\.md)$"
)


def filter_allowed_repo_paths(paths: list[str]) -> list[str]:
    """Filter LLM-proposed `target_repo_files` to valid, non-traversing repository paths."""
    valid: list[str] = []
    for raw in paths:
        clean = raw.strip().lstrip("/")
        if ".." in clean or not _ALLOWED_REPO_PATH_RE.match(clean):
            continue
        if clean not in valid:
            valid.append(clean)
    return valid
