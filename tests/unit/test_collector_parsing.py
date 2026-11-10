"""Parsing das respostas reais (fixtures) para a estrutura normalizada única."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import feedparser

from tests.conftest import load_fixture
from ufabc_science.collectors.arxiv import parse_arxiv_entry
from ufabc_science.collectors.crossref import classify_crossref, parse_crossref_item
from ufabc_science.collectors.openalex import classify_openalex, parse_openalex_work
from ufabc_science.collectors.pubmed import classify_pubmed, parse_pubmed_article
from ufabc_science.domain.enums import ArticleType, PeerReviewStatus
from ufabc_science.domain.schemas import NormalizedArticle


def _build(source: str, data: dict) -> NormalizedArticle:
    return NormalizedArticle(source=source, **data)


def test_openalex_work_is_normalized() -> None:
    works = json.loads(load_fixture("openalex_raw.json"))["results"]
    article = _build("openalex", parse_openalex_work(works[0], "data/raw/x.json"))

    assert article.external_id == "W7225396911"
    assert article.doi == "10.1016/j.tics.2026.10.005"
    assert article.journal == "Trends in Cognitive Sciences"
    assert article.article_type is ArticleType.REVIEW
    assert article.peer_review_status is PeerReviewStatus.VERIFIED
    assert article.abstract and len(article.abstract.split()) > 30
    assert article.authors[0].orcid == "0000-0001-9680-0763"
    assert any(inst.ror for inst in article.institutions)
    assert "neuromarketing" in article.keywords
    assert article.raw_data_path == "data/raw/x.json"
    assert article.source_metadata["openalex"]["source_type"] == "journal"


def test_openalex_repository_content_is_preprint() -> None:
    work = {
        "type": "article",
        "primary_location": {"source": {"type": "repository"}, "version": "submittedVersion"},
    }
    assert classify_openalex(work) == (ArticleType.PREPRINT, PeerReviewStatus.PREPRINT)
    assert classify_openalex({"type": "preprint"})[1] is PeerReviewStatus.PREPRINT
    # Sem fonte do tipo periódico, não há evidência de revisão por pares.
    assert classify_openalex({"type": "article", "primary_location": {}})[1] is (
        PeerReviewStatus.UNKNOWN
    )


def test_pubmed_article_is_normalized_without_emails() -> None:
    root = ET.fromstring(load_fixture("pubmed_efetch.xml"))
    nodes = root.findall("PubmedArticle")
    articles = [_build("pubmed", parse_pubmed_article(node)) for node in nodes]

    first = articles[0]
    assert first.external_id == "42986476"
    assert first.doi == "10.1007/s00429-026-03211-8"
    assert first.url == "https://pubmed.ncbi.nlm.nih.gov/42986476/"
    assert first.publication_date is not None and first.publication_date.isoformat() == "2026-11-05"
    assert first.peer_review_status is PeerReviewStatus.VERIFIED
    assert "Neurosciences" in first.keywords
    assert first.open_access is True  # possui PMC
    for article in articles:
        for author in article.authors:
            assert all("@" not in aff for aff in author.affiliations)


def test_pubmed_publication_types() -> None:
    assert classify_pubmed(["Preprint"]) == (ArticleType.PREPRINT, PeerReviewStatus.PREPRINT)
    assert classify_pubmed(["Journal Article", "Review"])[0] is ArticleType.REVIEW
    assert classify_pubmed(["Comment"])[1] is PeerReviewStatus.UNKNOWN


def test_arxiv_entries_are_always_preprints() -> None:
    feed = feedparser.parse(load_fixture("arxiv_feed.xml"))
    articles = [_build("arxiv", parse_arxiv_entry(entry)) for entry in feed.entries]

    assert len(articles) == 2
    first = articles[0]
    assert first.external_id == "2611.10501"  # sem sufixo de versão
    assert first.source_metadata["arxiv"]["version"] == "1"
    assert first.url == "https://arxiv.org/abs/2611.10501"
    assert all(a.peer_review_status is PeerReviewStatus.PREPRINT for a in articles)
    assert all(a.article_type is ArticleType.PREPRINT for a in articles)
    assert "cs.AI" in first.keywords


def test_crossref_item_is_normalized() -> None:
    item = json.loads(load_fixture("crossref_works.json"))["message"]["items"][0]
    article = _build("crossref", parse_crossref_item(item))

    assert article.doi == "10.3390/robotics15110229"
    assert article.external_id == article.doi
    assert article.journal == "Robotics"
    assert article.publisher == "MDPI AG"
    assert article.peer_review_status is PeerReviewStatus.VERIFIED
    assert article.abstract and "<jats" not in article.abstract
    assert article.open_access is True
    assert article.authors[0].orcid == "0000-0002-0408-1691"


def test_crossref_posted_content_is_preprint() -> None:
    assert classify_crossref({"type": "posted-content", "subtype": "preprint"}) == (
        ArticleType.PREPRINT,
        PeerReviewStatus.PREPRINT,
    )


def test_invalid_records_are_skipped() -> None:
    assert parse_openalex_work({"id": None}) is None
    assert parse_crossref_item({"DOI": "invalido", "title": ["x"]}) is None
    assert parse_arxiv_entry({"id": "x"}) is None
