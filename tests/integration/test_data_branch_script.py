"""Persistência entre execuções via branch "data" (git local, sem rede)."""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "data_branch.sh"
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(
    BASH is None or shutil.which("git") is None, reason="requer bash e git"
)


def sh(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    # O script usa "python" para verificar o SQLite: garante o interpretador dos testes.
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    result = subprocess.run(
        list(args), cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def git(*args: str, cwd: Path) -> str:
    return sh(
        "git", "-c", "user.name=t", "-c", "user.email=t@example.org", *args, cwd=cwd
    ).stdout.strip()


def clone(remote: Path, target: Path) -> Path:
    sh("git", "clone", "-q", str(remote), str(target), cwd=target.parent)
    return target


def run_script(repo: Path, *args: str) -> str:
    return sh(BASH, str(SCRIPT), *args, cwd=repo).stdout  # type: ignore[arg-type]


def write_db(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS t (v TEXT)")
        conn.execute("INSERT INTO t VALUES (?)", (value,))


def test_data_persists_between_runs(tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    sh("git", "init", "-q", "--bare", "-b", "main", str(remote), cwd=tmp_path)
    seed = clone(remote, tmp_path / "seed")
    (seed / "README.md").write_text("código\n", encoding="utf-8")
    git("add", ".", cwd=seed)
    git("commit", "-q", "-m", "init", cwd=seed)
    git("push", "-q", "origin", "HEAD:main", cwd=seed)

    # Execução 1: a branch "data" não existe; é criada órfã e recebe o banco.
    run1 = clone(remote, tmp_path / "run1")
    assert "criada" in run_script(run1, "fetch", "persist")
    write_db(run1 / "persist/data/database/ufabc_science.db", "primeira")
    (run1 / "persist/data/raw").mkdir(parents=True)
    (run1 / "persist/data/raw/resposta.json").write_text("{}", encoding="utf-8")
    assert "persistidos" in run_script(run1, "commit", "persist", "data: execução 1")
    assert "Nenhuma alteração" in run_script(run1, "commit", "persist", "data: sem mudanças")

    # Execução 2 em um runner novo (efêmero): recupera o estado anterior.
    run2 = clone(remote, tmp_path / "run2")
    assert "recuperada" in run_script(run2, "fetch", "persist")
    db = run2 / "persist/data/database/ufabc_science.db"
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT v FROM t").fetchall() == [("primeira",)]
    assert not (run2 / "persist/data/raw").exists()  # dados brutos não são versionados
    assert not (run2 / "persist/README.md").read_text(encoding="utf-8").startswith("código")
    write_db(db, "segunda")
    run_script(run2, "commit", "persist", "data: execução 2")

    log = git("log", "--format=%s", "origin/data", cwd=run2)
    assert log.splitlines() == ["data: execução 2", "data: execução 1"]
    main_files = git("ls-tree", "--name-only", "origin/main", cwd=run2).splitlines()
    assert main_files == ["README.md"]  # a branch principal não recebe commits automáticos


def test_push_never_overwrites_newer_remote_data(tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    sh("git", "init", "-q", "--bare", "-b", "main", str(remote), cwd=tmp_path)
    seed = clone(remote, tmp_path / "seed")
    (seed / "x").write_text("x", encoding="utf-8")
    git("add", ".", cwd=seed)
    git("commit", "-q", "-m", "init", cwd=seed)
    git("push", "-q", "origin", "HEAD:main", cwd=seed)
    first = clone(remote, tmp_path / "a")
    run_script(first, "fetch", "persist")
    write_db(first / "persist/data/database/ufabc_science.db", "base")
    run_script(first, "commit", "persist", "base")

    slow = clone(remote, tmp_path / "slow")
    run_script(slow, "fetch", "persist")
    fast = clone(remote, tmp_path / "fast")
    run_script(fast, "fetch", "persist")
    write_db(fast / "persist/data/database/ufabc_science.db", "editor")
    run_script(fast, "commit", "persist", "edição humana")

    write_db(slow / "persist/data/database/ufabc_science.db", "automação")
    with pytest.raises(AssertionError):  # push rejeitado (sem --force)
        run_script(slow, "commit", "persist", "automação atrasada")
    assert git("log", "-1", "--format=%s", "origin/data", cwd=fast) == "edição humana"


def test_editor_sync_keeps_editor_database_and_merges_text(tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    sh("git", "init", "-q", "--bare", "-b", "main", str(remote), cwd=tmp_path)
    seed = clone(remote, tmp_path / "seed")
    (seed / "x").write_text("x", encoding="utf-8")
    git("add", ".", cwd=seed)
    git("commit", "-q", "-m", "init", cwd=seed)
    git("push", "-q", "origin", "HEAD:main", cwd=seed)
    bot = clone(remote, tmp_path / "bot")
    run_script(bot, "fetch", "persist")
    write_db(bot / "persist/data/database/ufabc_science.db", "base")
    run_script(bot, "commit", "persist", "base")

    editor = clone(remote, tmp_path / "editor")
    git("config", "user.name", "Editora", cwd=editor)
    git("config", "user.email", "e@example.org", cwd=editor)
    run_script(editor, "fetch", "persist")
    git("config", "user.name", "Editora", cwd=editor / "persist")
    git("config", "user.email", "e@example.org", cwd=editor / "persist")

    # Automação envia banco e relatório novos enquanto o editor trabalha.
    run2 = clone(remote, tmp_path / "bot2")
    run_script(run2, "fetch", "persist")
    write_db(run2 / "persist/data/database/ufabc_science.db", "automação")
    (run2 / "persist/data/runs").mkdir(parents=True)
    (run2 / "persist/data/runs/r2.json").write_text("{}", encoding="utf-8")
    run_script(run2, "commit", "persist", "automação")

    write_db(editor / "persist/data/database/ufabc_science.db", "aprovação do editor")
    (editor / "persist/data/editorial").mkdir(parents=True, exist_ok=True)
    (editor / "persist/data/editorial/a.md").write_text("aprovado", encoding="utf-8")
    out = run_script(editor, "sync", "persist", "editorial")
    assert "mantida a versão do editor" in out

    final = clone(remote, tmp_path / "final")
    run_script(final, "fetch", "persist")
    with sqlite3.connect(final / "persist/data/database/ufabc_science.db") as conn:
        values = [v for (v,) in conn.execute("SELECT v FROM t")]
    assert "aprovação do editor" in values and "automação" not in values
    assert (final / "persist/data/runs/r2.json").exists()  # texto da automação preservado
    assert (final / "persist/data/editorial/a.md").exists()
