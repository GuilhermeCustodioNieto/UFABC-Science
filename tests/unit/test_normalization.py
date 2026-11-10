from __future__ import annotations

import pytest

from ufabc_science.processing.normalization import (
    clean_text,
    doi_url,
    is_http_url,
    normalize_doi,
    normalize_language,
    normalize_orcid,
    normalize_title,
    normalize_url,
    reconstruct_inverted_index,
    redact_emails,
    strip_abstract_label,
)


@pytest.mark.parametrize(
    "raw",
    [
        "10.1000/ABC.123",
        "https://doi.org/10.1000/abc.123",
        "http://dx.doi.org/10.1000/ABC.123",
        "doi:10.1000/abc.123",
        "DOI: 10.1000/abc.123.",
        "  10.1000/abc.123  ",
        "https://doi.org/10.1000%2Fabc.123",
    ],
)
def test_doi_variants_normalize_to_same_value(raw: str) -> None:
    assert normalize_doi(raw) == "10.1000/abc.123"


@pytest.mark.parametrize("raw", [None, "", "abc", "10.12/x", "11.1000/x", "10.1000/", "http://x"])
def test_invalid_dois_are_rejected_not_guessed(raw: str | None) -> None:
    assert normalize_doi(raw) is None


def test_doi_url() -> None:
    assert doi_url("10.1000/abc(1)") == "https://doi.org/10.1000/abc(1)"


def test_url_normalization_for_comparison() -> None:
    assert (
        normalize_url("HTTP://WWW.Example.org/Path/?utm_source=x&b=2&a=1#frag")
        == "https://example.org/Path?a=1&b=2"
    )
    assert normalize_url("https://example.org/") == "https://example.org"
    assert normalize_url("javascript:alert(1)") is None
    assert normalize_url("ftp://example.org/x") is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://example.org", True),
        ("http://example.org/a?b=c", True),
        ("javascript:alert(1)", False),
        ("data:text/html,x", False),
        ("//example.org", False),
        ("https://exa mple.org", False),
        (None, False),
    ],
)
def test_is_http_url(value: str | None, expected: bool) -> None:
    assert is_http_url(value) is expected


def test_title_normalization_ignores_case_accents_and_punctuation() -> None:
    assert normalize_title("<i>Neurociência</i>: Um Estudo!") == normalize_title(
        "neurociencia um estudo"
    )


def test_clean_text_removes_jats_markup() -> None:
    raw = (
        "<jats:title>Abstract</jats:title><jats:p>Robots &amp; humans</jats:p>"
        "<jats:p>work.</jats:p>"
    )
    assert clean_text(raw) == "Abstract Robots & humans work."
    assert strip_abstract_label("Abstract Robots & humans work.") == "Robots & humans work."


def test_reconstruct_openalex_inverted_index() -> None:
    assert reconstruct_inverted_index({"world": [1], "Hello": [0], "again": [3], "hello": [2]}) == (
        "Hello world hello again"
    )
    assert reconstruct_inverted_index(None) is None


def test_emails_are_redacted_from_affiliations() -> None:
    assert (
        redact_emails("Enrico Fermi Research Center, Rome, Italy. someone@cref.it.")
        == "Enrico Fermi Research Center, Rome, Italy"
    )


def test_orcid_and_language() -> None:
    assert normalize_orcid("https://orcid.org/0000-0002-1825-009x") == "0000-0002-1825-009X"
    assert normalize_orcid("sem orcid") is None
    assert normalize_language("eng") == "en"
    assert normalize_language("por") == "pt"
    assert normalize_language("???") is None
