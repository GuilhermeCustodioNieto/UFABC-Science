"""Normalização determinística de metadados científicos.

Funções puras, sem acesso a rede ou banco, usadas por todos os coletores para
produzir a mesma estrutura interna (``NormalizedArticle``) e pela deduplicação.
"""

from __future__ import annotations

import html
import re
import unicodedata
from html.parser import HTMLParser
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

# DOI: prefixo "10." + registrante numérico + "/" + sufixo sem espaços (Crossref/DataCite).
DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$")
_DOI_PREFIXES = (
    "https://doi.org/",
    "http://doi.org/",
    "https://dx.doi.org/",
    "http://dx.doi.org/",
    "doi.org/",
    "dx.doi.org/",
    "doi:",
    "doi ",
)
_TRAILING_PUNCTUATION = ".,;:)]}>\"'"

_TRACKING_PARAMS = re.compile(r"^(utm_\w+|fbclid|gclid|mc_cid|mc_eid|ref|source)$", re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_WHITESPACE = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_doi(value: str | None) -> str | None:
    """Normaliza um DOI para a forma canônica (``10.xxxx/sufixo`` em minúsculas).

    Aceita URLs ``doi.org``, prefixo ``doi:``, espaços e pontuação final. Retorna
    ``None`` quando o valor não é um DOI bem formado — nunca "inventa" um DOI.
    """
    if not value:
        return None
    doi = unquote(value).strip()
    lowered = doi.lower()
    for prefix in _DOI_PREFIXES:
        if lowered.startswith(prefix):
            doi = doi[len(prefix) :]
            lowered = doi.lower()
            break
    doi = doi.strip().rstrip(_TRAILING_PUNCTUATION).strip()
    doi = doi.lower()
    if not DOI_PATTERN.match(doi):
        return None
    return doi


def is_valid_doi(value: str | None) -> bool:
    return value is not None and DOI_PATTERN.match(value) is not None


def doi_url(doi: str) -> str:
    """URL de resolução do DOI (``https://doi.org/...``)."""
    return "https://doi.org/" + quote(doi, safe="/:;()._-")


def is_http_url(value: str | None) -> bool:
    """Indica se ``value`` é uma URL absoluta ``http``/``https`` com host."""
    if not value or any(ch.isspace() for ch in value.strip()):
        return False
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return False
    return parts.scheme in {"http", "https"} and bool(parts.netloc)


def normalize_url(value: str | None) -> str | None:
    """Normaliza URLs para comparação: esquema/host em minúsculas, sem fragmento,
    sem parâmetros de rastreamento, sem barra final e com ``http`` → ``https``.

    Retorna ``None`` para valores que não sejam URLs ``http(s)`` válidas.
    """
    if not is_http_url(value):
        return None
    assert value is not None
    parts = urlsplit(value.strip())
    host = parts.hostname or ""
    if parts.port and parts.port not in (80, 443):
        host = f"{host}:{parts.port}"
    if host.startswith("www."):
        host = host[4:]
    query = urlencode(
        sorted(
            (key, val)
            for key, val in parse_qsl(parts.query, keep_blank_values=True)
            if not _TRACKING_PARAMS.match(key)
        )
    )
    path = parts.path.rstrip("/") or ""
    return urlunsplit(("https", host.lower(), path, query, ""))


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_title(value: str | None) -> str:
    """Título para comparação: sem tags, acentos, pontuação e espaços extras."""
    if not value:
        return ""
    text = strip_accents(clean_text(value) or "").casefold()
    return _NON_ALNUM.sub(" ", text).strip()


class _TextExtractor(HTMLParser):
    _BLOCK_TAGS = frozenset({"p", "br", "div", "li", "sec", "title", "jats:p", "jats:sec"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._BLOCK_TAGS:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._BLOCK_TAGS:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def clean_text(value: str | None) -> str | None:
    """Remove marcação HTML/JATS e normaliza espaços. Nunca altera o conteúdo textual."""
    if value is None:
        return None
    extractor = _TextExtractor()
    extractor.feed(html.unescape(value) if "&" in value and "<" not in value else value)
    extractor.close()
    text = _WHITESPACE.sub(" ", "".join(extractor.parts)).strip()
    return unicodedata.normalize("NFC", text) or None


def strip_abstract_label(text: str | None) -> str | None:
    """Remove o rótulo "Abstract" que algumas fontes incluem no início do texto."""
    if not text:
        return text
    return re.sub(r"^(abstract|resumo|summary)\s*[:.\-–]?\s+", "", text, flags=re.IGNORECASE)  # noqa: RUF001


def redact_emails(text: str | None) -> str | None:
    """Remove endereços de e-mail (ex.: em afiliações do PubMed) por privacidade."""
    if not text:
        return text
    cleaned = _EMAIL.sub("", text)
    cleaned = re.sub(r"\s+([.,;])", r"\1", cleaned)
    cleaned = re.sub(r"[.,;\s]+$", "", cleaned)
    return _WHITESPACE.sub(" ", cleaned).strip() or None


def reconstruct_inverted_index(index: dict[str, list[int]] | None) -> str | None:
    """Reconstrói o abstract do OpenAlex (``abstract_inverted_index``)."""
    if not index:
        return None
    positions: dict[int, str] = {}
    for word, places in index.items():
        for place in places:
            positions[place] = word
    if not positions:
        return None
    return " ".join(positions[i] for i in sorted(positions))


def normalize_orcid(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"(\d{4}-\d{4}-\d{4}-\d{3}[\dX])", value.upper())
    return match.group(1) if match else None


def normalize_language(value: str | None) -> str | None:
    """Converte códigos de idioma (``eng``, ``en``, ``por``) para ISO 639-1."""
    if not value:
        return None
    code = value.strip().lower()
    three_to_two = {"eng": "en", "por": "pt", "spa": "es", "fre": "fr", "fra": "fr", "ger": "de"}
    code = three_to_two.get(code, code)
    return code[:16] if re.fullmatch(r"[a-z]{2,3}(-[a-z0-9]+)?", code) else None


def word_count(text: str | None) -> int:
    return len(text.split()) if text else 0
