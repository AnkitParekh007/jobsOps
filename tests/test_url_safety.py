"""SSRF / URL validation / redirect controls for job verification fetches."""
from __future__ import annotations

from urllib.parse import urlparse

from url_safety import validate_fetch_url, safe_http_fetch
from verify_jobs import http_fetch, verify_match


def test_blocks_localhost_and_loopback():
    for url in (
        "http://localhost/admin",
        "http://127.0.0.1/secret",
        "http://[::1]/v6",
        "http://169.254.169.254/latest/meta-data/",
        "http://metadata.google.internal/",
    ):
        result = validate_fetch_url(url, resolve_dns=False)
        assert result.ok is False, url


def test_blocks_credentials_and_bad_scheme():
    assert validate_fetch_url("https://user:pass@example.com/job", resolve_dns=False).ok is False
    assert validate_fetch_url("file:///etc/passwd", resolve_dns=False).ok is False
    assert validate_fetch_url("ftp://example.com/x", resolve_dns=False).ok is False


def test_allows_public_https_without_dns():
    result = validate_fetch_url("https://jobs.ashbyhq.com/acme/role-1", resolve_dns=False)
    assert result.ok is True
    assert urlparse(result.normalized).scheme == "https"
    assert urlparse(result.normalized).hostname == "jobs.ashbyhq.com"


def test_verify_match_skips_unsafe_url():
    result = verify_match(
        {
            "canonical_url": "http://127.0.0.1/internal-job",
            "employer_or_ats_url": "http://127.0.0.1/internal-job",
            "country": "Germany",
            "availability": "open",
            "posting_text": "Visa sponsorship available.",
        },
        offline=True,
    )
    assert result.decision["decision"] == "Skipped"
    assert any("unsafe_url" in b for b in result.blocking_reasons)


def test_http_fetch_ssrf_blocked_without_network():
    status, body = http_fetch("http://127.0.0.1/")
    assert status == 0
    assert "ssrf_blocked" in body
    status2, body2 = safe_http_fetch("http://169.254.169.254/latest/meta-data/")
    assert status2 == 0
    assert "ssrf_blocked" in body2
