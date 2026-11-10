"""Fluxo editorial por Markdown, edições e publicação HTML (Etapa 4)."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from tests.conftest import FakeApis, Workspace
from ufabc_science.collectors.service import collect_articles
from ufabc_science.domain.enums import EditionStatus, EditorialStatus
from ufabc_science.domain.models import Article, EditorialReview, NewsletterEdition
from ufabc_science.editorial import edition as editions
from ufabc_science.editorial.approval import latest_approval, sync_editorial, validate_files
from ufabc_science.editorial.exceptions import EditionError, PublicationBlockedError
from ufabc_science.editorial.markdown import (
    dump_document,
    find_article_files,
    parse_document,
    read_document,
)
from ufabc_science.infrastructure.database import session_scope
from ufabc_science.intelligence.generation import generate_contents
from ufabc_science.intelligence.provider import MockProvider
from ufabc_science.processing.classification import classify_articles, load_rules
from ufabc_science.processing.relevance import score_articles
from ufabc_science.publisher.html import SITE_MARKER, build_preview, build_site

JUSTIFICATION = "Avisos revisados: extensão e DOI conferidos manualmente."


@pytest.fixture
def drafts(workspace: Workspace, fake_apis: FakeApis) -> Workspace:
    collect_articles(
        workspace.settings,
        workspace.factory,
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 8),
        query="teste",
        max_articles=10,
        transport=fake_apis.transport(),
    )
    with session_scope(workspace.factory) as session:
        classify_articles(session, rules=load_rules(), min_confidence=0.35, uncertain_below=0.5)
        score_articles(session, today=date(2026, 11, 9))
    generate_contents(
        workspace.factory,
        MockProvider(),
        editorial_dir=workspace.editorial,
        limit=4,
        min_abstract_words=40,
    )
    return workspace


def files(ws: Workspace) -> list[Path]:
    return find_article_files(ws.editorial)


def edit_front_matter(path: Path, **changes: object) -> None:
    doc = read_document(path)
    doc.metadata.update(changes)
    path.write_text(dump_document(doc.metadata, doc.body), encoding="utf-8")


def edit_body(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def sync(ws: Workspace):
    with session_scope(ws.factory) as session:
        return sync_editorial(session, ws.editorial, min_abstract_words=40)


def approve(ws: Workspace, path: Path, **extra: object) -> Path:
    edit_front_matter(
        path,
        status="approved",
        reviewer="Editora",
        warning_justification=JUSTIFICATION,
        **extra,
    )
    report = sync(ws)
    outcome = next(o for o in report.outcomes if Path(o.path).name == path.name)
    assert outcome.action == "approved", outcome.messages
    return ws.editorial / "approved" / path.name


def reviews(ws: Workspace, article_id: int) -> list[EditorialReview]:
    with ws.factory() as session:
        return list(
            session.scalars(
                select(EditorialReview)
                .where(EditorialReview.article_id == article_id)
                .order_by(EditorialReview.id)
            )
        )


# --- Aprovação ----------------------------------------------------------------------------


def test_approval_is_recorded_with_snapshot_and_file_is_moved(drafts: Workspace) -> None:
    path = files(drafts)[0]
    article_id = read_document(path).article_id

    approved_path = approve(drafts, path)

    assert approved_path.exists() and not path.exists()
    doc = read_document(approved_path)
    assert doc.metadata["reviewed_at"]  # data da aprovação registrada no arquivo
    review = reviews(drafts, article_id)[-1]
    assert review.status is EditorialStatus.APPROVED
    assert review.reviewer == "Editora"
    assert review.content_hash == doc.current_hash
    assert review.content_snapshot == doc.body
    assert review.warning_justification == JUSTIFICATION


def test_warning_requires_justification(drafts: Workspace) -> None:
    path = files(drafts)[0]
    # Linguagem sensacionalista gera WARNING na verificação do texto editado.
    edit_body(path, "## Introdução\n\n", "## Introdução\n\nResultado definitivamente inédito. ")
    edit_front_matter(path, status="approved", reviewer="Editora")

    report = sync(drafts)

    outcome = next(o for o in report.outcomes if Path(o.path).name == path.name)
    assert outcome.action == "error"
    assert any("warning_justification" in m for m in outcome.messages)
    assert path.exists()  # continua em pending/
    assert all(
        r.status is not EditorialStatus.APPROVED
        for r in reviews(drafts, read_document(path).article_id)
    )


def test_failed_content_cannot_be_approved(drafts: Workspace) -> None:
    path = files(drafts)[0]
    edit_body(
        path, "## Principais resultados\n\n", "## Principais resultados\n\nCurou 99,9% dos casos. "
    )
    edit_front_matter(path, status="approved", warning_justification=JUSTIFICATION)

    report = sync(drafts)

    outcome = next(o for o in report.outcomes if Path(o.path).name == path.name)
    assert outcome.action == "error"
    assert any("FAILED" in m for m in outcome.messages)


def test_rejection_and_revision_request(drafts: Workspace) -> None:
    first, second = files(drafts)[:2]
    first_id, second_id = read_document(first).article_id, read_document(second).article_id
    edit_front_matter(first, status="rejected", editorial_notes="Fora do escopo.")
    edit_front_matter(second, status="needs_revision", editorial_notes="Explicar o método.")

    sync(drafts)

    assert (drafts.editorial / "rejected" / first.name).exists()
    assert (drafts.editorial / "pending" / second.name).exists()
    assert reviews(drafts, first_id)[-1].status is EditorialStatus.REJECTED
    assert reviews(drafts, first_id)[-1].comments == "Fora do escopo."
    assert reviews(drafts, second_id)[-1].status is EditorialStatus.NEEDS_REVISION
    with drafts.factory() as session:
        assert session.get(Article, first_id) is not None  # rejeição não apaga o artigo


def test_change_after_approval_invalidates_it(drafts: Workspace) -> None:
    approved = approve(drafts, files(drafts)[0])
    article_id = read_document(approved).article_id
    edit_body(approved, "## Limitações\n\n", "## Limitações\n\nTexto alterado. ")

    report = sync(drafts)

    assert any(o.action == "invalidated" for o in report.outcomes)
    pending = drafts.editorial / "pending" / approved.name
    assert pending.exists() and read_document(pending).status == "pending_review"
    history = [r.status for r in reviews(drafts, article_id)]
    assert history[-2:] == [EditorialStatus.APPROVED, EditorialStatus.PENDING_REVIEW]
    with drafts.factory() as session:
        assert latest_approval(session.get(Article, article_id)) is None

    # Nova aprovação explícita registra uma nova revisão (histórico preservado).
    approve(drafts, pending)
    assert [r.status for r in reviews(drafts, article_id)].count(EditorialStatus.APPROVED) == 2


def test_sync_is_idempotent(drafts: Workspace) -> None:
    approve(drafts, files(drafts)[0])
    before = len(reviews(drafts, read_document(files(drafts)[0]).article_id))
    report = sync(drafts)
    assert {o.action for o in report.outcomes} == {"unchanged"}
    assert len(reviews(drafts, read_document(files(drafts)[0]).article_id)) == before


def test_duplicate_and_foreign_files_are_errors(drafts: Workspace) -> None:
    original = files(drafts)[0]
    duplicate = drafts.editorial / "rejected" / original.name
    duplicate.parent.mkdir(parents=True, exist_ok=True)
    duplicate.write_text(original.read_text(encoding="utf-8"), encoding="utf-8")
    foreign = drafts.editorial / "pending" / "article-999.md"
    foreign.write_text("---\ntitle: outro projeto\n---\ntexto\n", encoding="utf-8")

    report = sync(drafts)

    errors = {Path(o.path).name: o for o in report.errors}
    assert original.name in errors
    assert "duplicado" in errors[original.name].messages[0]
    assert "article-999.md" in errors


def test_validate_reports_without_changing_anything(drafts: Workspace) -> None:
    path = files(drafts)[0]
    edit_front_matter(path, categories=["astrologia"], source_url="javascript:alert(1)")
    before = path.read_text(encoding="utf-8")
    with drafts.factory() as session:
        results = validate_files(session, drafts.editorial, min_abstract_words=40)
    result = next(r for r in results if r.path and r.path.endswith(path.name))
    assert any("Categorias desconhecidas" in e for e in result.errors)
    assert any("source_url" in e for e in result.errors)
    assert path.read_text(encoding="utf-8") == before


# --- Edições ------------------------------------------------------------------------------


def _approved_ids(ws: Workspace, count: int) -> list[int]:
    ids = []
    for path in files(ws)[:count]:
        ids.append(read_document(path).article_id)
        approve(ws, path)
    return ids


def _approve_intro(ws: Workspace, number: int = 1) -> None:
    path = ws.settings.editions_dir / "drafts" / f"edicao-{number:03d}.md"
    doc = read_document(path)
    doc.metadata.update(status="approved", reviewer="Editora")
    body = f"# Título interno\n\nIntrodução escrita pela editora para a edição {number}.\n"
    path.write_text(dump_document(doc.metadata, body), encoding="utf-8")


def test_template_introduction_cannot_be_approved(drafts: Workspace) -> None:
    ws = drafts
    with session_scope(ws.factory) as session:
        editions.create_edition(session, "2026-W46", ws.settings.editions_dir)
    path = ws.settings.editions_dir / "drafts" / "edicao-001.md"
    edit_front_matter(path, status="approved", reviewer="Editora")  # esqueceu o texto-modelo
    with session_scope(ws.factory) as session:
        result = editions.validate_edition(session, 1, **_kwargs(ws))
        assert any("texto-modelo" in e for e in result.errors)
        assert (
            editions.get_edition(session, 1).introduction_status is EditorialStatus.PENDING_REVIEW
        )

    _approve_intro(ws)
    with session_scope(ws.factory) as session:
        editions.validate_edition(session, 1, **_kwargs(ws))
        intro = editions.get_edition(session, 1).introduction
    assert intro == "Introdução escrita pela editora para a edição 1."  # título removido


def _kwargs(ws: Workspace) -> dict[str, object]:
    return {"editorial_dir": ws.editorial, "editions_dir": ws.settings.editions_dir}


def test_edition_lifecycle(drafts: Workspace) -> None:
    ids = _approved_ids(drafts, 2)
    unapproved = read_document(
        next(p for p in files(drafts) if p.parent.name == "pending")
    ).article_id
    ws = drafts
    with session_scope(ws.factory) as session:
        edition = editions.create_edition(session, "2026-W46", ws.settings.editions_dir)
        assert (edition.start_date, edition.end_date) == (date(2026, 11, 9), date(2026, 11, 15))
        assert edition.status is EditionStatus.DRAFT and edition.items == []
        with pytest.raises(EditionError, match="Já existe"):
            editions.create_edition(session, "2026-W46", ws.settings.editions_dir)
    assert (ws.settings.editions_dir / "drafts" / "edicao-001.md").exists()

    with session_scope(ws.factory) as session:
        with pytest.raises(EditionError, match="não está aprovado"):
            editions.add_article(session, 1, unapproved, ws.editorial)
        for article_id in ids:
            editions.add_article(session, 1, article_id, ws.editorial)
        with pytest.raises(EditionError, match="já está"):
            editions.add_article(session, 1, ids[0], ws.editorial)
        editions.reorder(session, 1, list(reversed(ids)))
        edition = editions.get_edition(session, 1)
        assert [i.article_id for i in edition.items] == list(reversed(ids))
        with pytest.raises(EditionError):
            editions.reorder(session, 1, [ids[0]])

    with session_scope(ws.factory) as session:
        result = editions.validate_edition(session, 1, **_kwargs(ws))
        assert not result.valid
        assert any("introdução" in e.lower() for e in result.errors)

    _approve_intro(ws)
    with session_scope(ws.factory) as session:
        result = editions.validate_edition(session, 1, **_kwargs(ws))
        assert result.valid, result.errors
        assert editions.get_edition(session, 1).status is EditionStatus.READY
        editions.remove_article(session, 1, ids[0])
        assert editions.get_edition(session, 1).status is EditionStatus.DRAFT  # mudou -> DRAFT
        editions.add_article(session, 1, ids[0], ws.editorial, position=1)
        assert [i.position for i in editions.get_edition(session, 1).items] == [1, 2]

    with session_scope(ws.factory) as session:
        with pytest.raises(PublicationBlockedError, match="confirmação"):
            editions.publish_edition(
                session, 1, published_by="Editora", confirm=False, **_kwargs(ws)
            )
        with pytest.raises(PublicationBlockedError, match="responsável"):
            editions.publish_edition(session, 1, published_by=" ", confirm=True, **_kwargs(ws))

    with session_scope(ws.factory) as session:
        edition = editions.publish_edition(
            session, 1, published_by="Editora", confirm=True, **_kwargs(ws)
        )
        assert edition.status is EditionStatus.PUBLISHED
        assert edition.published_at is not None and edition.published_by == "Editora"
        assert all(item.review_id for item in edition.items)

    snapshot = json.loads(
        (ws.settings.editions_dir / "published" / "edicao-001.json").read_text(encoding="utf-8")
    )
    assert [i["article_id"] for i in snapshot["items"]] == [ids[0], ids[1]]
    assert all(i["content_hash"] for i in snapshot["items"])

    with session_scope(ws.factory) as session, pytest.raises(EditionError, match="imutável"):
        editions.add_article(session, 1, unapproved, ws.editorial)


def test_publication_is_blocked_when_an_article_loses_approval(drafts: Workspace) -> None:
    ws = drafts
    article_id = _approved_ids(ws, 1)[0]
    with session_scope(ws.factory) as session:
        editions.create_edition(session, "2026-W46", ws.settings.editions_dir)
        editions.add_article(session, 1, article_id, ws.editorial)
    _approve_intro(ws)
    approved = ws.editorial / "approved" / f"article-{article_id}.md"
    edit_body(approved, "## Limitações\n\n", "## Limitações\n\nAlteração tardia. ")

    with session_scope(ws.factory) as session, pytest.raises(PublicationBlockedError) as exc:
        editions.publish_edition(session, 1, published_by="Editora", confirm=True, **_kwargs(ws))
    assert any("alterado após a aprovação" in e for e in exc.value.errors)


def test_grouping_follows_editoria_order_without_repetition(drafts: Workspace) -> None:
    ws = drafts
    ids = _approved_ids(ws, 3)
    with session_scope(ws.factory) as session:
        editions.create_edition(session, "2026-W46", ws.settings.editions_dir)
        sections = ["ciencias-e-stem", "neurociencia", "neurociencia"]
        for article_id, section in zip(ids, sections, strict=True):
            editions.add_article(session, 1, article_id, ws.editorial, section=section)
        groups = editions.group_by_section(list(editions.get_edition(session, 1).items))
    assert [slug for slug, _ in groups] == ["neurociencia", "ciencias-e-stem"]
    flat = [item.article_id for _, items in groups for item in items]
    assert sorted(flat) == sorted(ids) and len(flat) == len(set(flat))


def test_invalid_week_is_rejected(workspace: Workspace) -> None:
    with session_scope(workspace.factory) as session:
        for week in ("2026-46", "2026-W54", "semana"):
            with pytest.raises(EditionError):
                editions.create_edition(session, week, workspace.settings.editions_dir)


# --- HTML ---------------------------------------------------------------------------------


def _published_site(ws: Workspace) -> tuple[list[int], Path]:
    ids = _approved_ids(ws, 2)
    with session_scope(ws.factory) as session:
        editions.create_edition(session, "2026-W46", ws.settings.editions_dir)
        for article_id in ids:
            editions.add_article(session, 1, article_id, ws.editorial)
    _approve_intro(ws)
    with session_scope(ws.factory) as session:
        editions.publish_edition(session, 1, published_by="Editora", confirm=True, **_kwargs(ws))
    # Uma segunda edição em DRAFT nunca deve aparecer no site público.
    remaining = read_document(files(ws)[-1])
    edit_front_matter(
        files(ws)[-1], status="approved", warning_justification=JUSTIFICATION, reviewer="E"
    )
    sync(ws)
    with session_scope(ws.factory) as session:
        editions.create_edition(session, "2026-W47", ws.settings.editions_dir)
        editions.add_article(session, 2, remaining.article_id, ws.editorial)
    with ws.factory() as session:
        build_site(session, ws.settings.output_dir, timezone_name="America/Sao_Paulo")
    return ids, ws.settings.output_dir


def _digest(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_site_contains_only_published_content(drafts: Workspace) -> None:
    ids, dist = _published_site(drafts)

    expected = {
        "index.html",
        "archive/index.html",
        "editions/edicao-001/index.html",
        "assets/css/style.css",
        "assets/js/main.js",
        SITE_MARKER,
        *{f"articles/article-{i}/index.html" for i in ids},
    }
    assert set(_digest(dist)) == expected  # edição 002 (DRAFT) não aparece
    home = (dist / "index.html").read_text(encoding="utf-8")
    assert "Não representa oficialmente a Universidade Federal do ABC" in home
    assert "edicao-002" not in (dist / "archive" / "index.html").read_text(encoding="utf-8")
    page = (dist / f"articles/article-{ids[0]}/index.html").read_text(encoding="utf-8")
    assert "Consultar pesquisa original" in page
    assert '<html lang="pt-BR">' in page
    assert 'name="viewport"' in page
    assert (
        "<main" in page
        and "<article" in page
        and "<nav" in (dist / "index.html").read_text(encoding="utf-8")
    )


def test_site_generation_is_deterministic(drafts: Workspace) -> None:
    _, dist = _published_site(drafts)
    first = _digest(dist)
    with drafts.factory() as session:
        build_site(session, dist, timezone_name="America/Sao_Paulo")
    assert _digest(dist) == first


def test_preprints_are_labeled_in_html(drafts: Workspace) -> None:
    ws = drafts
    with ws.factory() as session:
        preprint_ids = {
            a.id
            for a in session.scalars(select(Article))
            if a.peer_review_status.value == "preprint"
        }
    target = next((p for p in files(ws) if read_document(p).article_id in preprint_ids), None)
    if target is None:
        pytest.skip("nenhum preprint entre os rascunhos gerados")
    article_id = read_document(target).article_id
    approve(ws, target)
    with session_scope(ws.factory) as session:
        editions.create_edition(session, "2026-W46", ws.settings.editions_dir)
        editions.add_article(session, 1, article_id, ws.editorial)
    with ws.factory() as session:
        result = build_preview(
            session, 1, ws.settings.preview_dir, timezone_name="America/Sao_Paulo"
        )
    page = (result.output_dir / f"articles/article-{article_id}/index.html").read_text(
        encoding="utf-8"
    )
    assert "Preprint — sem revisão por pares" in page


def test_preview_is_separate_and_marked(drafts: Workspace) -> None:
    ws = drafts
    article_id = _approved_ids(ws, 1)[0]
    with session_scope(ws.factory) as session:
        editions.create_edition(session, "2026-W46", ws.settings.editions_dir)
        editions.add_article(session, 1, article_id, ws.editorial)
    with ws.factory() as session:
        result = build_preview(
            session, 1, ws.settings.preview_dir, timezone_name="America/Sao_Paulo"
        )
        edition = session.scalars(select(NewsletterEdition)).one()
        assert edition.status is EditionStatus.DRAFT  # gerar HTML não publica
    html = (result.output_dir / "editions/edicao-001/index.html").read_text(encoding="utf-8")
    assert "Pré-visualização local" in html
    assert 'content="noindex, nofollow"' in html
    assert "Introdução editorial ainda não aprovada." in html
    assert not ws.settings.output_dir.exists()


def test_build_refuses_to_delete_foreign_directory(drafts: Workspace, tmp_path: Path) -> None:
    target = tmp_path / "pasta-importante"
    target.mkdir()
    (target / "nao-apagar.txt").write_text("x", encoding="utf-8")
    with drafts.factory() as session, pytest.raises(RuntimeError, match="recusando"):
        build_site(session, target, timezone_name="America/Sao_Paulo")
    assert (target / "nao-apagar.txt").exists()


def test_malicious_metadata_is_escaped(drafts: Workspace) -> None:
    ws = drafts
    path = files(ws)[0]
    article_id = read_document(path).article_id
    with session_scope(ws.factory) as session:
        article = session.get(Article, article_id)
        article.journal = "<script>alert('x')</script>"
    edit_body(path, "## Introdução\n\n", "## Introdução\n\n<script>alert('x')</script> ")
    approve(ws, path)
    with session_scope(ws.factory) as session:
        editions.create_edition(session, "2026-W46", ws.settings.editions_dir)
        editions.add_article(session, 1, article_id, ws.editorial)
    with ws.factory() as session:
        result = build_preview(
            session, 1, ws.settings.preview_dir, timezone_name="America/Sao_Paulo"
        )
    page = (result.output_dir / f"articles/article-{article_id}/index.html").read_text(
        encoding="utf-8"
    )
    assert "<script>alert" not in page
    assert "&lt;script&gt;" in page


def test_parse_document_of_published_snapshot(drafts: Workspace) -> None:
    approved = approve(drafts, files(drafts)[0])
    review = reviews(drafts, read_document(approved).article_id)[-1]
    doc = parse_document("---\nschema: x\n---\n" + (review.content_snapshot or ""))
    assert doc.headline


def test_editor_order_controls_sections(drafts: Workspace) -> None:
    ws = drafts
    ids = _approved_ids(ws, 2)
    with session_scope(ws.factory) as session:
        editions.create_edition(session, "2026-W46", ws.settings.editions_dir)
        editions.add_article(session, 1, ids[0], ws.editorial, section="ciencias-e-stem")
        editions.add_article(session, 1, ids[1], ws.editorial, section="neurociencia")
        default = [
            s for s, _ in editions.group_by_section(list(editions.get_edition(session, 1).items))
        ]
        editions.reorder(session, 1, [ids[0], ids[1]])
        custom = [
            s for s, _ in editions.group_by_section(list(editions.get_edition(session, 1).items))
        ]
    assert default == ["neurociencia", "ciencias-e-stem"]  # ordem inicial oficial
    assert custom == ["ciencias-e-stem", "neurociencia"]  # ordem definida pelo editor
