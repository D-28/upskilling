"""Deterministic security boundaries: SSRF walls, HTML stripping, and Markdown sanitization.

Enforces Harness Walls outside the model (playbooks/harness-loop-graph.md):
- Blocks non-HTTPS URLs and any hostname resolving to private, loopback, link-local
  (including cloud metadata 169.254.169.254), CGNAT, multicast, or reserved IPs.
- Strips HTML tags, scripts, styles, and unsafe markdown/link schemes from untrusted
  external feed text before it ever enters an LLM prompt or rendered radar digest.
"""

from __future__ import annotations

import html
import ipaddress
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
        # Collapse horizontal whitespace and excess blank lines
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
    # Strip ASCII control characters except newline/tab
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    if len(text) > max_chars:
        return text[: max_chars - 3].rstrip() + "..."
    return text


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_DANGEROUS_LINK_RE = re.compile(
    r"\[([^\]]+)\]\(\s*(?:javascript|data|vbscript|file):[^)]*\)", re.IGNORECASE
)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def sanitize_markdown_text(text: str, max_chars: int = 2_000) -> str:
    """Sanitize untrusted or LLM-emitted text before writing to radar/*.md.

    - Removes HTML comments (so untrusted text cannot forge `<!-- radar-id: ... -->` markers)
    - Removes raw HTML tags (`<script>`, `<img>`, `<iframe>`, etc.)
    - Neutralizes markdown images (prevents external tracking pixels in GitHub PRs)
    - Neutralizes dangerous link schemes (`javascript:`, `data:`, `vbscript:`, `file:`)
    """
    if not text:
        return ""
    cleaned = _HTML_COMMENT_RE.sub("", text)
    cleaned = _MD_IMAGE_RE.sub(lambda m: m.group(1) or "[image removed]", cleaned)
    cleaned = _DANGEROUS_LINK_RE.sub(lambda m: m.group(1), cleaned)
    cleaned = _HTML_TAG_RE.sub("", cleaned)
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
