"""Validação estática dos workflows do GitHub Actions (sem executá-los)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
PINNED = re.compile(r"^[\w.-]+/[\w.-]+@[0-9a-f]{40}$")


def load(name: str) -> dict[str, Any]:
    data = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    # PyYAML (YAML 1.1) interpreta a chave "on" como True.
    data["on"] = data.pop(True, data.get("on"))
    return data


def all_steps(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for job in workflow["jobs"].values() for step in job.get("steps", [])]


@pytest.mark.parametrize("name", ["weekly_pipeline.yml", "deploy_pages.yml", "ci.yml"])
def test_workflow_is_valid_and_hardened(name: str) -> None:
    workflow = load(name)
    assert workflow["name"]
    assert "permissions" in workflow, "permissões devem ser explícitas"
    assert "pull_request_target" not in workflow["on"]
    for job in workflow["jobs"].values():
        assert job.get("timeout-minutes"), "todo job precisa de timeout"
    for step in all_steps(workflow):
        if "uses" in step:
            assert PINNED.match(step["uses"]), f"Action sem SHA fixo: {step['uses']}"
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    # Entradas do usuário só podem chegar ao shell por variáveis de ambiente.
    for block in re.findall(r"run: \|(.*?)(?=\n\s+- name:|\Z)", text, re.DOTALL):
        assert "${{ inputs." not in block and "${{ github.event.inputs" not in block


def test_weekly_pipeline_schedule_and_manual_parameters() -> None:
    workflow = load("weekly_pipeline.yml")
    triggers = workflow["on"]
    assert triggers["schedule"] == [{"cron": "0 11 * * 1"}]  # segunda, 08:00 em São Paulo
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert {"days", "sources", "max_articles", "generation_limit", "steps"} <= set(inputs)
    assert workflow["permissions"] == {"contents": "write"}
    assert workflow["concurrency"]["cancel-in-progress"] is False


def test_weekly_pipeline_never_approves_or_publishes() -> None:
    text = (WORKFLOWS / "weekly_pipeline.yml").read_text(encoding="utf-8")
    workflow = load("weekly_pipeline.yml")
    assert "pages" not in str(workflow["permissions"])
    for forbidden in ("edition publish", "site build", "deploy-pages", "status: approved"):
        assert forbidden not in text
    assert "--force" not in text
    commands = " ".join(step.get("run", "") for step in all_steps(workflow))
    assert "python -m ufabc_science run" in commands
    assert "data_branch.sh commit" in commands


def test_weekly_pipeline_uses_secrets_only_through_env() -> None:
    workflow = load("weekly_pipeline.yml")
    env = workflow["jobs"]["pipeline"]["env"]
    for key in ("AI_API_KEY", "OPENALEX_API_KEY", "NCBI_API_KEY"):
        assert env[key] == f"${{{{ secrets.{key} }}}}"
    text = (WORKFLOWS / "weekly_pipeline.yml").read_text(encoding="utf-8")
    assert "echo $AI_API_KEY" not in text
    assert all("secrets." not in str(step) for step in all_steps(workflow))


def test_deploy_requires_explicit_manual_confirmation() -> None:
    workflow = load("deploy_pages.yml")
    assert set(workflow["on"]) == {
        "workflow_dispatch"
    }  # nunca disparado por agenda ou outro workflow
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert inputs["confirm"]["required"] is True and inputs["edition"]["required"] is True
    build = workflow["jobs"]["build"]
    first = build["steps"][0]
    assert "PUBLICAR edicao-" in first["run"]
    commands = " ".join(step.get("run", "") for step in build["steps"])
    assert "site build --require-edition" in commands and "--strict" in commands
    assert build["permissions"] == {"contents": "read"}
    assert workflow["jobs"]["deploy"]["permissions"] == {"pages": "write", "id-token": "write"}
    assert workflow["permissions"] == {"contents": "read"}


def test_ci_runs_tests_and_lint_without_secrets() -> None:
    workflow = load("ci.yml")
    commands = " ".join(step.get("run", "") for step in all_steps(workflow))
    assert "pytest" in commands and "ruff check" in commands and "ruff format --check" in commands
    assert "secrets." not in (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    assert workflow["permissions"] == {"contents": "read"}


def test_data_branch_script_never_force_pushes() -> None:
    script = (ROOT / "scripts" / "data_branch.sh").read_text(encoding="utf-8")
    commands = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))
    assert "--force" not in commands and "push -f" not in commands
    assert "integrity_check" in script
    assert "git diff --cached --quiet" in script  # sem commit quando não há mudanças
