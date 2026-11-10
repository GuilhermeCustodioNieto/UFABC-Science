"""Coletor PubMed via NCBI E-utilities (https://www.ncbi.nlm.nih.gov/books/NBK25501/).

Fluxo: ``esearch`` (JSON) para obter PMIDs no período e ``efetch`` (XML) em lotes.
Limite oficial: 3 requisições/s sem chave e 10/s com ``NCBI_API_KEY``.

O XML é processado com ``xml.etree`` da biblioteca padrão, que não resolve DTDs
externas; a versão do expat embutida no Python suportado mitiga expansão de
entidades ("billion laughs").
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date
from typing import Any

from ufabc_science.collectors.base import (
    BaseCollector,
    CollectionResult,
    CollectorError,
    RateLimitedClient,
)
from ufabc_science.domain.enums import ArticleType, PeerReviewStatus
from ufabc_science.domain.schemas import NormalizedArticle
from ufabc_science.processing.normalization import (
    clean_text,
    normalize_language,
    normalize_orcid,
    redact_emails,
)

_MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"],
        start=1,
    )
}
_FETCH_BATCH = 100


def _text(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    return clean_text("".join(element.itertext()))


def _parse_date(element: ET.Element | None) -> date | None:
    if element is None:
        return None
    year = element.findtext("Year")
    if not year or not year.isdigit():
        medline = element.findtext("MedlineDate") or ""
        return date(int(medline[:4]), 1, 1) if medline[:4].isdigit() else None
    month_text = (element.findtext("Month") or "1").strip().lower()
    month = int(month_text) if month_text.isdigit() else _MONTHS.get(month_text[:3], 1)
    day_text = element.findtext("Day") or "1"
    day = int(day_text) if day_text.isdigit() else 1
    try:
        return date(int(year), month, day)
    except ValueError:
        return date(int(year), month, 1)


def classify_pubmed(publication_types: list[str]) -> tuple[ArticleType, PeerReviewStatus]:
    """Tipo e revisão por pares a partir de ``PublicationType`` do PubMed."""
    lowered = {item.lower() for item in publication_types}
    if "preprint" in lowered:
        return ArticleType.PREPRINT, PeerReviewStatus.PREPRINT
    if lowered & {"review", "systematic review", "meta-analysis", "scoping review"}:
        return ArticleType.REVIEW, PeerReviewStatus.VERIFIED
    if "journal article" in lowered:
        return ArticleType.JOURNAL_ARTICLE, PeerReviewStatus.VERIFIED
    return ArticleType.OTHER, PeerReviewStatus.UNKNOWN


def parse_pubmed_article(node: ET.Element, raw_path: str = "") -> dict[str, Any] | None:
    """Converte um ``PubmedArticle`` na estrutura de ``NormalizedArticle``."""
    citation = node.find("MedlineCitation")
    if citation is None:
        return None
    pmid = citation.findtext("PMID")
    article = citation.find("Article")
    if not pmid or article is None:
        return None
    title = _text(article.find("ArticleTitle"))
    if not title:
        return None

    parts = []
    for abstract_text in article.findall("Abstract/AbstractText"):
        text = _text(abstract_text)
        if not text:
            continue
        label = abstract_text.get("Label")
        parts.append(f"{label.capitalize()}: {text}" if label else text)
    abstract = " ".join(parts) or None

    ids = {
        (item.get("IdType") or "").lower(): (item.text or "").strip()
        for item in node.findall("PubmedData/ArticleIdList/ArticleId")
    }
    doi = ids.get("doi")
    if not doi:
        for eloc in article.findall("ELocationID"):
            if eloc.get("EIdType") == "doi":
                doi = (eloc.text or "").strip()

    pub_date = _parse_date(article.find("ArticleDate")) or _parse_date(
        article.find("Journal/JournalIssue/PubDate")
    )

    authors: list[dict[str, Any]] = []
    institutions: dict[str, dict[str, Any]] = {}
    for author in article.findall("AuthorList/Author"):
        if author.get("ValidYN", "Y") != "Y":
            continue
        name = author.findtext("CollectiveName")
        if not name:
            fore, last = author.findtext("ForeName"), author.findtext("LastName")
            name = " ".join(p for p in (fore, last) if p)
        if not name:
            continue
        affiliations = []
        for aff in author.findall("AffiliationInfo/Affiliation"):
            cleaned = redact_emails(_text(aff))
            if cleaned:
                affiliations.append(cleaned[:500])
                institutions.setdefault(cleaned[:500], {"name": cleaned[:500]})
        orcid = None
        for ident in author.findall("Identifier"):
            if ident.get("Source") == "ORCID":
                orcid = normalize_orcid(ident.text)
        authors.append({"name": name, "orcid": orcid, "affiliations": tuple(affiliations)})

    publication_types = [
        (pt.text or "").strip() for pt in article.findall("PublicationTypeList/PublicationType")
    ]
    article_type, peer_status = classify_pubmed(publication_types)
    mesh = [
        (d.text or "").strip()
        for d in citation.findall("MeshHeadingList/MeshHeading/DescriptorName")
    ]
    keywords = mesh + [(k.text or "").strip() for k in citation.findall("KeywordList/Keyword")]

    return {
        "external_id": pmid,
        "title": title,
        "abstract": abstract,
        "doi": doi,
        "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        "publication_date": pub_date,
        "journal": _text(article.find("Journal/Title")),
        "publisher": None,
        "authors": authors,
        "institutions": list(institutions.values()),
        "article_type": article_type,
        "peer_review_status": peer_status,
        # PMC indica texto completo gratuito; ausência não significa acesso fechado.
        "open_access": True if ids.get("pmc") else None,
        "language": normalize_language(article.findtext("Language")),
        "keywords": keywords,
        "source_metadata": {
            "pubmed": {
                "pmid": pmid,
                "pmcid": ids.get("pmc"),
                "publication_types": publication_types,
                "mesh": mesh,
            }
        },
        "raw_data_path": raw_path or None,
    }


class PubMedCollector(BaseCollector):
    name = "pubmed"
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    default_queries = (
        "(neurosciences[MeSH] OR brain[tiab] OR cognition[MeSH] OR neurons[MeSH])",
        "(genetics[MeSH] OR genomics[MeSH] OR molecular biology[MeSH] OR microbiology[MeSH] "
        "OR biotechnology[MeSH] OR ecology[MeSH])",
        "(biomedical engineering[MeSH] OR bioengineering[MeSH])",
    )

    @property
    def min_interval(self) -> float:  # type: ignore[override]
        return 0.11 if self.config.api_key else 0.34

    def _common_params(self) -> dict[str, Any]:
        params: dict[str, Any] = {"db": "pubmed", "tool": "ufabc_science"}
        if self.config.contact_email:
            params["email"] = self.config.contact_email
        if self.config.api_key:
            params["api_key"] = self.config.api_key
        return params

    def _collect_query(
        self,
        client: RateLimitedClient,
        result: CollectionResult,
        query: str,
        start_date: date,
        end_date: date,
        limit: int,
    ) -> list[NormalizedArticle]:
        search = client.get(
            f"{self.base_url}/esearch.fcgi",
            params={
                **self._common_params(),
                "term": f"{query} AND hasabstract",
                "datetype": "pdat",
                "mindate": start_date.strftime("%Y/%m/%d"),
                "maxdate": end_date.strftime("%Y/%m/%d"),
                "retmax": limit,
                "retmode": "json",
                "sort": "pub_date",
            },
        )
        self._save_raw(result, "esearch", search.content, "json")
        try:
            pmids = search.json()["esearchresult"]["idlist"]
        except (KeyError, ValueError) as exc:
            raise CollectorError(f"pubmed: resposta inesperada do esearch: {exc}") from exc

        articles: list[NormalizedArticle] = []
        for offset in range(0, len(pmids), _FETCH_BATCH):
            batch = pmids[offset : offset + _FETCH_BATCH]
            fetch = client.get(
                f"{self.base_url}/efetch.fcgi",
                params={**self._common_params(), "id": ",".join(batch), "retmode": "xml"},
            )
            raw_path = self._save_raw(result, "efetch", fetch.content, "xml")
            try:
                root = ET.fromstring(fetch.content)
            except ET.ParseError as exc:
                raise CollectorError(f"pubmed: XML inválido no efetch: {exc}") from exc
            for node in root.findall("PubmedArticle"):
                data = parse_pubmed_article(node, raw_path)
                if data is None:
                    result.invalid_records += 1
                    continue
                article = self._build(result, data)
                if article is not None:
                    articles.append(article)
        return articles[:limit]
