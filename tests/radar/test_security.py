"""Security wall tests: SSRF blocking, HTML stripping, and Markdown sanitization."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from scripts.radar.security import (
    SSRFError,
    html_to_plain_text,
    is_blocked_ip,
    sanitize_markdown_text,
    sanitize_single_line,
    validate_public_https_url,
)


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "127.0.0.42",
        "10.0.0.1",
        "10.255.255.254",
        "172.16.0.1",
        "192.168.1.10",
        "169.254.169.254",  # Cloud metadata service
        "100.64.0.1",  # CGNAT
        "0.0.0.0",
        "224.0.0.1",  # Multicast
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:169.254.169.254",
        "::ffff:127.0.0.1",
    ],
)
def test_blocked_ips_are_rejected(ip: str) -> None:
    assert is_blocked_ip(ip) is True


@pytest.mark.parametrize("ip", ["1.1.1.1", "8.8.8.8", "140.82.121.4", "2606:4700:4700::1111"])
def test_public_ips_are_allowed(ip: str) -> None:
    assert is_blocked_ip(ip) is False


@pytest.mark.parametrize(
    "bad_url",
    [
        "http://example.com/feed.xml",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "https://127.0.0.1/admin",
        "https://169.254.169.254/latest/meta-data/",
        "https://[::1]/secret",
        "https://localhost/feed",
        "https://metadata.google.internal/computeMetadata/v1/",
        "https://internal.local/api",
        "https://user:pass@example.com/feed",
        "https://example.com:8443/feed",
    ],
)
def test_validate_public_https_url_blocks_unsafe_targets(bad_url: str) -> None:
    with pytest.raises(SSRFError):
        validate_public_https_url(bad_url, resolver=lambda _h: ["93.184.216.34"])


def test_validate_public_https_url_blocks_dns_rebinding_to_private_ip() -> None:
    with pytest.raises(SSRFError):
        validate_public_https_url(
            "https://rebind.attacker.example/post",
            resolver=lambda _h: ["93.184.216.34", "169.254.169.254"],
        )


def test_validate_public_https_url_allows_clean_public_host() -> None:
    url = "https://simonwillison.net/atom/everything/"
    assert validate_public_https_url(url, resolver=lambda _h: ["104.21.1.1"]) == url


def test_html_to_plain_text_strips_scripts_styles_and_tags() -> None:
    raw = (
        "<html><head><style>body{display:none}</style>"
        "<script>fetch('https://evil.example')</script></head>"
        "<body><h1>Title</h1><p>Hello <b>world</b> &amp; friends.</p></body></html>"
    )
    out = html_to_plain_text(raw)
    assert "fetch(" not in out
    assert "display:none" not in out
    assert "Title" in out
    assert "Hello world & friends." in out


def test_sanitize_markdown_neutralizes_scripts_tracking_images_and_forged_markers() -> None:
    malicious = (
        "<!-- radar-id: ffffffffffff source: fake domain: evil.com -->"
        "<script>alert(1)</script>"
        "![tracker](https://evil.example/pixel.png) "
        "[click me](javascript:alert(2)) "
        "Legit insight here."
    )
    out = sanitize_markdown_text(malicious)
    assert "radar-id:" not in out
    assert "<script>" not in out
    assert "pixel.png" not in out
    assert "javascript:" not in out
    assert "Legit insight here." in out


@given(st.text(max_size=300))
def test_property_sanitizer_never_emits_html_comments_or_script_tags(raw: str) -> None:
    payload = f"<!-- radar-id: 1234567890ab source: x domain: y --><script>{raw}</script>{raw}"
    sanitized = sanitize_markdown_text(payload)
    assert "<!--" not in sanitized
    assert "<script" not in sanitized.lower()
    single = sanitize_single_line(payload)
    assert "\n" not in single
    assert "\r" not in single
