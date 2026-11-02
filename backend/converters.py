"""
Ajaia Collaborative Document Editor - Converters Module
Handles HTML-to-Markdown, HTML-to-Plain-Text, and File-to-HTML bidirectional document transformations.
"""

import html
import re
from typing import Tuple
import markdown


def html_to_markdown(html_str: str) -> str:
    """
    Convert HTML markup back into Markdown representation for clean export.
    Supports Quill list representations (including data-list="bullet" and data-list="ordered"),
    standard headings, strong/em styling, blockquotes, and code blocks.
    """
    if not html_str:
        return ""

    text = html_str

    # Convert headers
    text = re.sub(r"<h1>(.*?)</h1>", r"# \1\n\n", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<h2>(.*?)</h2>", r"## \1\n\n", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<h3>(.*?)</h3>", r"### \1\n\n", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<h4>(.*?)</h4>", r"#### \1\n\n", text, flags=re.IGNORECASE | re.DOTALL)

    # Convert code blocks and inline code
    text = re.sub(r"<pre.*?>(.*?)</pre>", r"```\n\1\n```\n\n", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<code>(.*?)</code>", r"`\1`", text, flags=re.IGNORECASE | re.DOTALL)

    # Convert strong/b and em/i
    text = re.sub(r"<(?:strong|b)>(.*?)</(?:strong|b)>", r"**\1**", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<(?:em|i)>(.*?)</(?:em|i)>", r"*\1*", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<(?:s|strike)>(.*?)</(?:s|strike)>", r"~~\1~~", text, flags=re.IGNORECASE | re.DOTALL)

    # Convert blockquotes
    text = re.sub(r"<blockquote>(.*?)</blockquote>", r"> \1\n\n", text, flags=re.IGNORECASE | re.DOTALL)

    # Convert Quill data-list items
    text = re.sub(r'<li[^>]*data-list=["\']bullet["\'][^>]*>(.*?)</li>', r"- \1\n", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<li[^>]*data-list=["\']ordered["\'][^>]*>(.*?)</li>', r"1. \1\n", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<li>(.*?)</li>", r"- \1\n", text, flags=re.IGNORECASE | re.DOTALL)

    # Convert paragraphs and breaks
    text = re.sub(r"<p>(.*?)</p>", r"\1\n\n", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<br\s*/?>", r"\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<hr\s*/?>", r"\n---\n\n", text, flags=re.IGNORECASE)

    # Strip remaining HTML tags
    text = re.sub(r"<[^>]+>", "", text)

    # Unescape HTML entities (e.g. &amp;, &lt;, &gt;, &quot;)
    text = html.unescape(text)

    # Normalize excessive newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def html_to_text(html_str: str) -> str:
    """
    Extract plain text from an HTML document with normalized whitespace and unescaped entities.
    """
    if not html_str:
        return ""

    # Replace block-level tags and breaks with newlines
    text = re.sub(r"</(?:p|h[1-6]|li|tr|div|blockquote)>", "\n", html_str, flags=re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)

    # Strip all remaining tags
    text = re.sub(r"<[^>]+>", " ", text)

    # Unescape HTML entities
    text = html.unescape(text)

    # Clean up whitespace
    lines = [line.strip() for line in text.splitlines()]
    clean_text = "\n".join(line for line in lines if line)
    return clean_text.strip()


def file_to_html(content_bytes: bytes, filename: str) -> Tuple[str, str]:
    """
    Convert uploaded raw file bytes (.md or .txt) into editable HTML for Quill and plain text.
    Returns a tuple of (content_html, content_text).
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    # Decode bytes with fallback encoding support
    try:
        decoded_text = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        decoded_text = content_bytes.decode("latin-1", errors="replace")

    if ext == "md":
        content_html = markdown.markdown(
            decoded_text,
            extensions=["extra", "nl2br", "sane_lists"]
        )
        content_text = html_to_text(content_html)
    else:  # txt or plain text
        # Escape raw text for HTML embedding
        escaped_lines = [f"<p>{html.escape(line)}</p>" if line.strip() else "<p><br></p>" for line in decoded_text.splitlines()]
        content_html = "".join(escaped_lines)
        content_text = decoded_text.strip()

    return content_html, content_text
