from __future__ import annotations

from pathlib import Path

import pytest

from ufabc_science.editorial.markdown import (
    MarkdownFormatError,
    body_hash,
    dump_document,
    parse_document,
    render_body,
    safe_child,
)
from ufabc_science.intelligence.schemas import SECTION_FIELDS

SECTIONS = {name: f"Texto de {name}." for name in SECTION_FIELDS}


def make_text(**meta: object) -> str:
    body = render_body(
        "Título editorial", SECTIONS, "Autora. Título. Revista. 2026.", "https://doi.org/10.1/x"
    )
    metadata = {"schema": "ufabc-science/article@1", "article_id": 7, "status": "pending_review"}
    metadata.update(meta)
    metadata["generated_body_hash"] = body_hash(body)
    return dump_document(metadata, body)


def test_roundtrip_front_matter_and_sections() -> None:
    doc = parse_document(make_text(categories=["neurociencia"]))

    assert doc.metadata["article_id"] == 7
    assert doc.metadata["categories"] == ["neurociencia"]
    assert doc.headline == "Título editorial"
    assert doc.sections == SECTIONS
    assert doc.reference == "Autora. Título. Revista. 2026."
    assert doc.source_link == "https://doi.org/10.1/x"
    assert not doc.manually_edited


def test_front_matter_keys_keep_stable_order() -> None:
    text = make_text(doi="10.1/x", categories=["a"])
    header = text.split("---")[1]
    keys = [line.split(":")[0] for line in header.strip().splitlines() if not line.startswith("-")]
    assert keys[:4] == ["schema", "article_id", "status", "categories"]


def test_manual_edit_is_detected_but_front_matter_changes_are_not() -> None:
    text = make_text()
    status_only = text.replace("status: pending_review", "status: approved")
    assert not parse_document(status_only).manually_edited
    edited = text.replace("Texto de findings.", "Texto revisado pelo editor.")
    assert parse_document(edited).manually_edited


def test_hash_ignores_line_endings_and_trailing_spaces() -> None:
    assert body_hash("a  \r\nb\n") == body_hash("a\nb")


def test_unknown_sections_are_reported() -> None:
    text = make_text().replace("## Limitações", "## Seção inventada\n\nx\n\n## Limitações")
    assert parse_document(text).extra_sections == ["Seção inventada"]


@pytest.mark.parametrize("text", ["sem front matter", "---\n: [inválido\n---\ncorpo"])
def test_invalid_front_matter_is_rejected(text: str) -> None:
    with pytest.raises(MarkdownFormatError):
        parse_document(text)


def test_yaml_tags_are_not_executed() -> None:
    malicious = "---\narticle_id: !!python/object/apply:os.system ['echo x']\n---\ncorpo"
    with pytest.raises(MarkdownFormatError):
        parse_document(malicious)


@pytest.mark.parametrize("name", ["../fora.md", "../../etc/passwd", "a/../../b.md", ""])
def test_path_traversal_is_blocked(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError):
        safe_child(tmp_path / "data", name)


def test_safe_child_accepts_regular_names(tmp_path: Path) -> None:
    assert safe_child(tmp_path, "article-1.md") == tmp_path / "article-1.md"
