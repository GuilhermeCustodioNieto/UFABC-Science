"""Arquivos Markdown editoriais: escrita, leitura e integridade (SPECIFICATION.md, seção 13).

Formato: front matter YAML (lido com ``python-frontmatter``/``yaml.SafeLoader``,
nunca por expressões regulares) seguido do corpo com seções de título fixo.

O hash do corpo (``generated_body_hash``) registra o texto escrito pelo
sistema; se o corpo atual difere, o arquivo foi editado manualmente e não é
sobrescrito automaticamente.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import frontmatter
import yaml

from ufabc_science.domain.enums import EditorialStatus
from ufabc_science.intelligence.schemas import SECTION_FIELDS, SECTION_TITLES

SCHEMA_ID = "ufabc-science/article@1"
EDITION_SCHEMA_ID = "ufabc-science/edition@1"
ARTICLE_FILE = re.compile(r"^article-(?P<id>[1-9]\d{0,9})\.md$")
REFERENCE_TITLE = "Referência"
STATUS_DIRS = {
    EditorialStatus.PENDING_REVIEW: "pending",
    EditorialStatus.NEEDS_REVISION: "pending",
    EditorialStatus.APPROVED: "approved",
    EditorialStatus.REJECTED: "rejected",
}
EDITORIAL_SUBDIRS = ("pending", "approved", "rejected")
_TITLE_TO_FIELD = {title.casefold(): name for name, title in SECTION_TITLES.items()}
_LINK = re.compile(r"\[(?P<label>[^\]]+)\]\((?P<url>[^)\s]+)\)")

# Ordem estável das chaves do front matter (diffs legíveis no Git).
FRONT_MATTER_ORDER = (
    "schema",
    "article_id",
    "content_id",
    "content_version",
    "status",
    "categories",
    "primary_category",
    "source_url",
    "doi",
    "peer_review_status",
    "article_type",
    "original_title",
    "generated_at",
    "model_provider",
    "model_name",
    "prompt_version",
    "verification_status",
    "verification_messages",
    "generated_body_hash",
    "reviewer",
    "reviewed_at",
    "editorial_notes",
    "warning_justification",
    "edition_slug",
)


def body_hash(body: str) -> str:
    """SHA-256 do corpo normalizado (quebras de linha e espaços finais)."""
    normalized = "\n".join(line.rstrip() for line in body.replace("\r\n", "\n").split("\n"))
    return hashlib.sha256(normalized.strip().encode("utf-8")).hexdigest()


def article_filename(article_id: int) -> str:
    return f"article-{int(article_id)}.md"


def safe_child(root: Path, name: str) -> Path:
    """Caminho ``root/name`` garantindo que não escapa de ``root`` (path traversal)."""
    if not name or "\x00" in name:
        raise ValueError("Nome de arquivo inválido.")
    candidate = (root / name).resolve()
    base = root.resolve()
    if candidate != base and base not in candidate.parents:
        raise ValueError(f"Caminho fora do diretório permitido: {name}")
    return root / name


@dataclass
class ArticleDocument:
    """Representação de um arquivo editorial de artigo."""

    metadata: dict[str, Any]
    headline: str
    sections: dict[str, str]
    reference: str
    source_link: str | None
    body: str
    path: Path | None = None
    extra_sections: list[str] = field(default_factory=list)

    @property
    def article_id(self) -> Any:
        return self.metadata.get("article_id")

    @property
    def status(self) -> str:
        return str(self.metadata.get("status") or "")

    @property
    def current_hash(self) -> str:
        return body_hash(self.body)

    @property
    def manually_edited(self) -> bool:
        return self.metadata.get("generated_body_hash") != self.current_hash


def render_body(headline: str, sections: dict[str, str], reference: str, source_url: str) -> str:
    lines = [f"# {headline.strip()}", ""]
    for name in SECTION_FIELDS:
        lines += [f"## {SECTION_TITLES[name]}", "", (sections.get(name) or "").strip(), ""]
    lines += [f"## {REFERENCE_TITLE}", "", reference.strip(), ""]
    lines += [f"[Consultar pesquisa original]({source_url})", ""]
    return "\n".join(lines)


def _yaml_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "value") and not isinstance(value, (str, int, float, bool)):
        return value.value
    return value


def dump_document(metadata: dict[str, Any], body: str) -> str:
    ordered = {key: _yaml_value(metadata.get(key)) for key in FRONT_MATTER_ORDER if key in metadata}
    for key, value in metadata.items():
        if key not in ordered:
            ordered[key] = _yaml_value(value)
    header = yaml.safe_dump(ordered, allow_unicode=True, sort_keys=False, width=100)
    return f"---\n{header}---\n\n{body.strip()}\n"


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)


class MarkdownFormatError(ValueError):
    """Arquivo editorial com estrutura inválida."""


def parse_body(body: str) -> tuple[str, dict[str, str], str, str | None, list[str]]:
    """Separa título, seções conhecidas, referência e link do corpo Markdown."""
    headline = ""
    sections: dict[str, list[str]] = {}
    extra: list[str] = []
    current: str | None = None
    for line in body.replace("\r\n", "\n").split("\n"):
        if line.startswith("# ") and not headline:
            headline = line[2:].strip()
            current = None
            continue
        if line.startswith("## "):
            title = line[3:].strip()
            if title.casefold() == REFERENCE_TITLE.casefold():
                current = "__reference__"
            else:
                current = _TITLE_TO_FIELD.get(title.casefold())
                if current is None:
                    extra.append(title)
                    current = f"__extra__{title}"
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line)
    joined = {key: "\n".join(lines).strip() for key, lines in sections.items()}
    reference_block = joined.pop("__reference__", "")
    link = None
    reference_lines = []
    for line in reference_block.split("\n"):
        match = _LINK.search(line)
        if match and "pesquisa original" in match.group("label").casefold():
            link = match.group("url")
        elif line.strip():
            reference_lines.append(line.strip())
    known = {k: v for k, v in joined.items() if not k.startswith("__extra__")}
    return headline, known, " ".join(reference_lines), link, extra


def parse_document(text: str, path: Path | None = None) -> ArticleDocument:
    """Lê um arquivo editorial. Lança ``MarkdownFormatError`` se a estrutura for inválida."""
    try:
        post = frontmatter.loads(text)
    except yaml.YAMLError as exc:
        raise MarkdownFormatError(f"Front matter YAML inválido: {exc}") from exc
    if not post.metadata:
        raise MarkdownFormatError("Front matter ausente.")
    headline, sections, reference, link, extra = parse_body(post.content)
    return ArticleDocument(
        metadata=dict(post.metadata),
        headline=headline,
        sections=sections,
        reference=reference,
        source_link=link,
        body=post.content,
        path=path,
        extra_sections=extra,
    )


def read_document(path: Path) -> ArticleDocument:
    return parse_document(path.read_text(encoding="utf-8"), path)


def find_article_files(editorial_dir: Path) -> list[Path]:
    """Arquivos ``article-<id>.md`` nas pastas pending/approved/rejected (ordem estável)."""
    files = []
    for sub in EDITORIAL_SUBDIRS:
        directory = editorial_dir / sub
        if directory.is_dir():
            files += sorted(p for p in directory.iterdir() if p.is_file() and p.suffix == ".md")
    return files
