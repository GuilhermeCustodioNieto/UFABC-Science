"""Comportamento da CLI: códigos de saída, mensagens e idempotência."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from ufabc_science import __version__
from ufabc_science.main import main


def test_init_db_succeeds_and_is_idempotent(
    db_url: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["init-db", "--database-url", db_url]) == 0
    first = capsys.readouterr()
    assert "editorias criadas: 5" in first.out
    assert (tmp_path / "db" / "test.db").is_file()

    assert main(["init-db", "--database-url", db_url]) == 0
    second = capsys.readouterr()
    assert "editorias criadas: 0" in second.out
    assert "Schema já atualizado" in second.err


def test_init_db_uses_database_url_from_environment(
    db_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", db_url)

    assert main(["init-db"]) == 0
    assert (tmp_path / "db" / "test.db").is_file()


def test_default_database_path_is_relative_to_working_directory(isolated_env: Path) -> None:
    assert main(["init-db"]) == 0
    assert (isolated_env / "data" / "database" / "ufabc_science.db").is_file()


def test_missing_command_returns_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    assert "init-db" in capsys.readouterr().out


def test_unknown_command_returns_usage_error() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["publicar-tudo"])
    assert exc.value.code == 2


def test_invalid_configuration_returns_usage_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("COLLECTION_DAYS", "0")

    assert main(["init-db"]) == 2
    assert "Configuração inválida" in capsys.readouterr().err


def test_runtime_failure_returns_error_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    blocker = tmp_path / "arquivo"
    blocker.write_text("não é diretório", encoding="utf-8")
    url = f"sqlite:///{(blocker / 'db.sqlite').as_posix()}"

    assert main(["init-db", "--database-url", url]) == 1
    assert "ERROR" in capsys.readouterr().err


def test_password_is_hidden_in_logs(capsys: pytest.CaptureFixture[str]) -> None:
    # Banco inexistente: falha, mas a senha não pode aparecer na saída.
    url = "postgresql://user:segredo123@127.0.0.1:1/ufabc"
    main(["init-db", "--database-url", url])

    captured = capsys.readouterr()
    assert "segredo123" not in captured.err
    assert "segredo123" not in captured.out


def _run_module(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in {"DATABASE_URL", "LOG_LEVEL"}}
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "ufabc_science", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )


def test_python_dash_m_entrypoint(isolated_env: Path) -> None:
    version = _run_module("--version", cwd=isolated_env)
    assert version.returncode == 0
    assert __version__ in version.stdout

    init = _run_module("init-db", cwd=isolated_env)
    assert init.returncode == 0, init.stderr
    assert (isolated_env / "data" / "database" / "ufabc_science.db").is_file()


# --- Comandos das etapas 2 a 5 ------------------------------------------------------


@pytest.fixture
def initialized(isolated_env: Path) -> Path:
    assert main(["init-db"]) == 0
    return isolated_env


def test_commands_require_initialized_database(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["classify"]) == 1
    assert "init-db" in capsys.readouterr().err


def test_config_check_never_prints_secrets(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NCBI_API_KEY", "segredo-ncbi-123")
    monkeypatch.setenv("OPENALEX_API_KEY", "segredo-openalex-456")
    assert main(["config", "check"]) == 0
    out = capsys.readouterr()
    assert "segredo" not in out.out + out.err
    assert '"ncbi_api_key": "configurada"' in out.out


def test_offline_steps_run_without_credentials(initialized: Path) -> None:
    assert main(["run", "--steps", "classify,score", "--trigger", "teste"]) == 0
    assert main(["process", "--limit", "1"]) == 0
    assert main(["shortlist"]) == 0
    assert main(["runs"]) == 0
    assert list((initialized / "data" / "runs").glob("*.json"))


def test_invalid_arguments_return_usage_error() -> None:
    for argv in (["run", "--steps", "aprovar"], ["collect", "--sources", "google"]):
        with pytest.raises(SystemExit) as exc:
            main(argv)
        assert exc.value.code == 2


def test_editorial_and_edition_errors_are_clear(
    initialized: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["editorial", "validate"]) == 0
    assert main(["editorial", "sync"]) == 0
    assert main(["edition", "create", "--week", "semana-1"]) == 1
    assert "Semana inválida" in capsys.readouterr().err
    assert main(["edition", "create", "--week", "2026-W46"]) == 0
    assert main(["edition", "validate", "--edition", "1"]) == 1  # sem artigos
    assert main(["edition", "publish", "--edition", "1", "--by", "Eu"]) == 1
    assert "confirmação explícita" in capsys.readouterr().err
    assert main(["publish", "--edition", "1"]) == 0  # pré-visualização não publica
    assert (initialized / "build" / "preview" / "edicao-001" / "index.html").is_file()
    assert main(["site", "build", "--require-edition", "1"]) == 1
    assert main(["edition", "show", "--edition", "1"]) == 0


def test_locked_pipeline_returns_exit_code_3(initialized: Path) -> None:
    lock = initialized / "data" / "database" / "pipeline.lock"
    lock.write_text(
        '{"run_id": "outro", "started_at": "2999-01-01T00:00:00+00:00"}', encoding="utf-8"
    )
    assert main(["run", "--steps", "score"]) == 3
