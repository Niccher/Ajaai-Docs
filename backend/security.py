"""
Ajaia Collaborative Document Editor - Security Module
Provides robust HTML sanitization via Mozilla/Rust-backed nh3 and HTTP security headers middleware.
"""

from typing import Set, Dict
import nh3
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

# Quill.js Rich-Text Editor Tag & Attribute Allowlist
ALLOWED_TAGS: Set[str] = {
    "p",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "strong",
    "b",
    "em",
    "i",
    "u",
    "s",
    "strike",
    "ol",
    "ul",
    "li",
    "blockquote",
    "pre",
    "code",
    "hr",
    "br",
    "span",
    "a",
}

# Note: "rel" on <a> is automatically managed by link_rel parameter in nh3.clean
ALLOWED_ATTRIBUTES: Dict[str, Set[str]] = {
    "a": {"href", "target", "title"},
    "span": {"class"},
    "li": {"data-list", "class"},
    "pre": {"spellcheck"},
}

ALLOWED_URL_SCHEMES: Set[str] = {"http", "https", "mailto"}


def sanitize_html(html_str: str) -> str:
    """
    Sanitize HTML string to eliminate Cross-Site Scripting (XSS) vectors.
    Uses nh3 (Rust-based ammonia library) with a strict allowlist matching Quill.js.
    Strips script tags, event handlers (onclick, onerror), iframes, objects, and javascript: protocols.
    """
    if not html_str or not html_str.strip():
        return ""

    cleaned = nh3.clean(
        html_str,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes=ALLOWED_URL_SCHEMES,
        link_rel="noopener noreferrer",
        strip_comments=True,
    )
    return cleaned


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware injecting defense-in-depth HTTP security headers on all responses.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)

        # Content-Type sniff protection
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Clickjacking defense
        response.headers["X-Frame-Options"] = "DENY"

        # Referrer privacy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Restrict hardware API access
        response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"

        # Content Security Policy accommodating CDN dependencies (Bootstrap, Quill)
        csp_policy = (
            "default-src 'self'; "
            "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
            "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
            "font-src 'self' https://cdn.jsdelivr.net; "
            "img-src 'self' data: https:; "
            "connect-src 'self';"
        )
        response.headers["Content-Security-Policy"] = csp_policy

        return response
