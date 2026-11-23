#!/usr/bin/env python3
"""Strict URL validation, redirect controls, and SSRF protections for outbound fetches."""
from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Sequence

# Public job boards should never target these hostnames.
BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "metadata.google.internal",
        "metadata",
        "kubernetes",
        "kubernetes.default",
        "kubernetes.default.svc",
    }
)

MAX_REDIRECTS = 3
DEFAULT_TIMEOUT = 12.0
MAX_BODY_BYTES = 400_000

FetchFn = Callable[[str], tuple[int, str]]


@dataclass(frozen=True)
class UrlSafetyResult:
    ok: bool
    reason: str = ""
    normalized: str = ""
    resolved_ips: tuple[str, ...] = ()
    hostname: str = ""
    port: int = 0
    scheme: str = ""


def _is_blocked_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if addr.is_private or addr.is_loopback or addr.is_link_local:
        return True
    if addr.is_reserved or addr.is_multicast or addr.is_unspecified:
        return True
    # Cloud metadata / CGNAT / documentation ranges often abused for SSRF.
    blocked_networks = (
        ipaddress.ip_network("169.254.0.0/16"),
        ipaddress.ip_network("100.64.0.0/10"),
        ipaddress.ip_network("0.0.0.0/8"),
        ipaddress.ip_network("192.0.0.0/24"),
        ipaddress.ip_network("192.0.2.0/24"),
        ipaddress.ip_network("198.51.100.0/24"),
        ipaddress.ip_network("203.0.113.0/24"),
        ipaddress.ip_network("224.0.0.0/4"),
        ipaddress.ip_network("240.0.0.0/4"),
        ipaddress.ip_network("::1/128"),
        ipaddress.ip_network("fc00::/7"),
        ipaddress.ip_network("fe80::/10"),
        ipaddress.ip_network("ff00::/8"),
    )
    for net in blocked_networks:
        try:
            if addr in net:
                return True
        except TypeError:
            continue
    return False


def validate_ip_literal(ip_str: str) -> UrlSafetyResult:
    """Connection-time IP check — used to defeat DNS rebinding."""
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return UrlSafetyResult(False, f"invalid_connect_ip:{ip_str}")
    if _is_blocked_ip(addr):
        return UrlSafetyResult(False, f"blocked_connect_ip:{ip_str}")
    return UrlSafetyResult(True, "ok", resolved_ips=(ip_str,))


def validate_fetch_url(
    url: str,
    *,
    allow_http: bool = True,
    resolve_dns: bool = True,
) -> UrlSafetyResult:
    """
    Validate a candidate fetch URL before any network I/O.
    Blocks credentials-in-URL, non-http(s), blocked hosts, and private/metadata IPs.
    """
    if not isinstance(url, str) or not url.strip():
        return UrlSafetyResult(False, "empty_url")
    raw = url.strip()
    try:
        parsed = urllib.parse.urlparse(raw)
    except ValueError as exc:
        return UrlSafetyResult(False, f"parse_error:{exc}")

    scheme = (parsed.scheme or "").lower()
    allowed_schemes = {"https", "http"} if allow_http else {"https"}
    if scheme not in allowed_schemes:
        return UrlSafetyResult(False, f"disallowed_scheme:{scheme or 'missing'}")

    if parsed.username is not None or parsed.password is not None:
        return UrlSafetyResult(False, "credentials_in_url")

    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        return UrlSafetyResult(False, "missing_host")
    if host in BLOCKED_HOSTNAMES or host.endswith(".localhost") or host.endswith(".local"):
        return UrlSafetyResult(False, f"blocked_hostname:{host}")

    # Literal IP in hostname.
    try:
        literal = ipaddress.ip_address(host)
        if _is_blocked_ip(literal):
            return UrlSafetyResult(False, f"blocked_literal_ip:{host}")
    except ValueError:
        literal = None

    default_port = 443 if scheme == "https" else 80
    port = int(parsed.port or default_port)

    resolved: list[str] = []
    if resolve_dns and literal is None:
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            return UrlSafetyResult(False, f"dns_failure:{exc}")
        except OSError as exc:
            return UrlSafetyResult(False, f"dns_os_error:{exc}")
        for info in infos:
            ip_str = info[4][0]
            resolved.append(ip_str)
            try:
                addr = ipaddress.ip_address(ip_str)
            except ValueError:
                return UrlSafetyResult(False, f"invalid_resolved_ip:{ip_str}")
            if _is_blocked_ip(addr):
                return UrlSafetyResult(
                    False,
                    f"blocked_resolved_ip:{ip_str}",
                    normalized=raw,
                    resolved_ips=tuple(dict.fromkeys(resolved)),
                    hostname=host,
                    port=port,
                    scheme=scheme,
                )
    elif literal is not None:
        resolved = [host]

    if parsed.port:
        netloc = f"{host}:{parsed.port}"
    else:
        netloc = host
    normalized = urllib.parse.urlunparse(
        (scheme, netloc, parsed.path or "", "", parsed.query, "")
    )

    return UrlSafetyResult(
        True,
        "ok",
        normalized=normalized,
        resolved_ips=tuple(dict.fromkeys(resolved)),
        hostname=host,
        port=port,
        scheme=scheme,
    )


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-validate every redirect target; cap hop count."""

    def __init__(self, *, max_redirects: int = MAX_REDIRECTS, allow_http: bool = True):
        super().__init__()
        self.max_redirects = max_redirects
        self.allow_http = allow_http
        self._hops = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        self._hops += 1
        if self._hops > self.max_redirects:
            raise urllib.error.HTTPError(
                newurl, code, f"too_many_redirects:{self._hops}", headers, fp
            )
        check = validate_fetch_url(newurl, allow_http=self.allow_http, resolve_dns=True)
        if not check.ok:
            raise urllib.error.HTTPError(
                newurl, code, f"redirect_blocked:{check.reason}", headers, fp
            )
        return super().redirect_request(req, fp, code, msg, headers, check.normalized or newurl)


def _pin_connect(
    *,
    scheme: str,
    hostname: str,
    ip: str,
    port: int,
    path_query: str,
    timeout: float,
    user_agent: str,
) -> tuple[int, str, str]:
    """
    Connect to a pre-validated IP while sending the original Host header.
    Re-validates the IP immediately before and after connect (DNS-rebinding defense).
    Returns (status, body, location_or_final_url).
    """
    ip_check = validate_ip_literal(ip)
    if not ip_check.ok:
        raise PermissionError(f"ssrf_blocked_connect:{ip_check.reason}")

    sock = socket.create_connection((ip, port), timeout=timeout)
    try:
        peer = sock.getpeername()[0]
        peer_check = validate_ip_literal(peer)
        if not peer_check.ok:
            raise PermissionError(f"ssrf_blocked_peer:{peer_check.reason}")

        if scheme == "https":
            context = ssl.create_default_context()
            ssock = context.wrap_socket(sock, server_hostname=hostname)
            sock = ssock  # noqa: PLW2901 — ownership transferred to HTTPSConnection
            conn: http.client.HTTPConnection = http.client.HTTPSConnection(
                hostname, port=port, timeout=timeout
            )
            conn.sock = sock
        else:
            conn = http.client.HTTPConnection(hostname, port=port, timeout=timeout)
            conn.sock = sock

        host_header = hostname if port in (80, 443) else f"{hostname}:{port}"
        headers = {
            "Host": host_header,
            "User-Agent": user_agent,
            "Connection": "close",
        }
        conn.request("GET", path_query or "/", headers=headers)
        resp = conn.getresponse()
        raw = resp.read(MAX_BODY_BYTES)
        charset = "utf-8"
        ctype = resp.getheader("Content-Type") or ""
        if "charset=" in ctype:
            charset = ctype.split("charset=", 1)[1].split(";")[0].strip() or "utf-8"
        try:
            text = raw.decode(charset, errors="replace")
        except LookupError:
            text = raw.decode("utf-8", errors="replace")
        final = f"{scheme}://{host_header}{path_query or '/'}"
        if resp.status in {301, 302, 303, 307, 308}:
            location = resp.getheader("Location") or ""
            return int(resp.status), text, location
        return int(resp.status), text, final
    finally:
        try:
            sock.close()
        except OSError:
            pass


def safe_http_fetch(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_redirects: int = MAX_REDIRECTS,
    allow_http: bool = True,
    user_agent: str = "JobOps-verify/1.0 (+local research)",
    pin_ip: bool = True,
) -> tuple[int, str]:
    """
    Fetch a URL with SSRF controls. Returns (status, body_or_error_token).
    Never follows redirects to private/metadata targets.
    When pin_ip=True (default), connects to the validated IP with Host header
    to mitigate DNS rebinding between resolve and connect.
    """
    current = url
    for _hop in range(max_redirects + 1):
        check = validate_fetch_url(current, allow_http=allow_http, resolve_dns=True)
        if not check.ok:
            return 0, f"fetch_error:ssrf_blocked:{check.reason}"

        parsed = urllib.parse.urlparse(check.normalized)
        path_query = parsed.path or "/"
        if parsed.query:
            path_query = f"{path_query}?{parsed.query}"

        if not pin_ip or not check.resolved_ips:
            # Fallback path (literal already validated) still uses opener with redirect checks.
            return _safe_http_fetch_opener(
                check.normalized,
                timeout=timeout,
                max_redirects=max_redirects,
                allow_http=allow_http,
                user_agent=user_agent,
            )

        last_err = ""
        for ip in check.resolved_ips:
            # Connection-time revalidation (DNS rebinding defense).
            ip_check = validate_ip_literal(ip)
            if not ip_check.ok:
                last_err = ip_check.reason
                continue
            try:
                status, body, location = _pin_connect(
                    scheme=check.scheme,
                    hostname=check.hostname,
                    ip=ip,
                    port=check.port,
                    path_query=path_query,
                    timeout=timeout,
                    user_agent=user_agent,
                )
            except PermissionError as exc:
                return 0, f"fetch_error:{exc}"
            except Exception as exc:  # noqa: BLE001
                last_err = f"{type(exc).__name__}:{exc}"
                continue

            if status in {301, 302, 303, 307, 308} and location:
                # Resolve relative redirects against current URL.
                current = urllib.parse.urljoin(check.normalized, location)
                break
            return status, body
        else:
            return 0, f"fetch_error:ssrf_blocked:no_safe_ip:{last_err}"
        continue
    return 0, "fetch_error:ssrf_blocked:too_many_redirects"


def _safe_http_fetch_opener(
    url: str,
    *,
    timeout: float,
    max_redirects: int,
    allow_http: bool,
    user_agent: str,
) -> tuple[int, str]:
    check = validate_fetch_url(url, allow_http=allow_http, resolve_dns=True)
    if not check.ok:
        return 0, f"fetch_error:ssrf_blocked:{check.reason}"

    opener = urllib.request.build_opener(
        _SafeRedirectHandler(max_redirects=max_redirects, allow_http=allow_http)
    )
    req = urllib.request.Request(
        check.normalized,
        headers={"User-Agent": user_agent},
        method="GET",
    )
    try:
        with opener.open(req, timeout=timeout) as resp:  # nosec B310 — URL pre-validated
            final = getattr(resp, "geturl", lambda: check.normalized)()
            final_check = validate_fetch_url(final, allow_http=allow_http, resolve_dns=True)
            if not final_check.ok:
                return 0, f"fetch_error:ssrf_blocked_final:{final_check.reason}"
            raw = resp.read(MAX_BODY_BYTES)
            charset = resp.headers.get_content_charset() or "utf-8"
            try:
                text = raw.decode(charset, errors="replace")
            except LookupError:
                text = raw.decode("utf-8", errors="replace")
            return int(resp.status), text
    except urllib.error.HTTPError as exc:
        reason = str(exc.reason or "")
        if reason.startswith("redirect_blocked:") or reason.startswith("too_many_redirects:"):
            return 0, f"fetch_error:ssrf_blocked:{reason}"
        body = ""
        try:
            body = exc.read(50_000).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            body = ""
        return int(exc.code), body
    except Exception as exc:  # noqa: BLE001
        return 0, f"fetch_error:{type(exc).__name__}:{exc}"


def assert_safe_urls(urls: Sequence[str], *, allow_http: bool = True) -> list[UrlSafetyResult]:
    """Batch-validate URLs; useful for tests and preflight."""
    return [validate_fetch_url(u, allow_http=allow_http) for u in urls]
