"""Sanitização do Markdown editorial e validação de URLs no HTML gerado."""

from __future__ import annotations

import pytest

from ufabc_science.publisher.html import _environment, render_markdown, safe_url


@pytest.mark.parametrize(
    "payload",
    [
        "<script>alert(1)</script>",
        '<img src=x onerror="alert(1)">',
        "[clique](javascript:alert(1))",
        '<a href="javascript:alert(1)">x</a>',
        '<iframe src="https://evil.example"></iframe>',
        "<style>body{display:none}</style>",
        '<a href="data:text/html;base64,PHNjcmlwdD4=">x</a>',
    ],
)
def test_dangerous_markup_is_removed(payload: str) -> None:
    html = str(render_markdown(f"Texto {payload} fim"))
    lowered = html.lower()
    assert "<script" not in lowered
    assert "onerror" not in lowered
    assert "javascript:" not in lowered
    assert "<iframe" not in lowered
    assert "<style" not in lowered
    assert "data:text/html" not in lowered


def test_safe_markdown_is_preserved() -> None:
    html = str(render_markdown("Um **resultado** com [link](https://doi.org/10.1/x)."))
    assert "<strong>resultado</strong>" in html
    assert 'href="https://doi.org/10.1/x"' in html
    assert 'rel="noopener noreferrer nofollow"' in html


def test_templates_escape_dynamic_content() -> None:
    template = _environment().from_string("<h1>{{ title }}</h1>")
    assert template.render(title="<script>x</script>") == "<h1>&lt;script&gt;x&lt;/script&gt;</h1>"


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://doi.org/10.1/x", True),
        ("http://example.org", True),
        ("javascript:alert(1)", False),
        ("JaVaScRiPt:alert(1)", False),
        ("vbscript:x", False),
        ("/relative/path", False),
    ],
)
def test_only_http_urls_are_emitted(url: str, allowed: bool) -> None:
    assert (safe_url(url) is not None) is allowed
