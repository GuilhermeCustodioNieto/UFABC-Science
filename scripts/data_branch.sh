#!/usr/bin/env bash
# Persistência dos dados na branch dedicada "data" (docs/PERSISTENCE_STRATEGY.md).
#
# Uso:
#   scripts/data_branch.sh fetch  [DIR]            # recupera (ou cria) a branch em DIR via git worktree
#   scripts/data_branch.sh commit [DIR] "mensagem" # valida o SQLite e faz commit/push SOMENTE se houver mudanças
#   scripts/data_branch.sh sync   [DIR] "mensagem" # uso do EDITOR: commit + integra a remota + push
#
# No "sync", se a automação enviou um banco novo enquanto o editor trabalhava, o banco do
# EDITOR prevalece (o trabalho editorial não é refazível; a coleta é idempotente e a próxima
# execução cobre a lacuna automaticamente). Arquivos de texto são mesclados normalmente.
#
# Regras de segurança:
#   * nunca usa push --force: se a branch remota avançou, o push falha e nada é sobrescrito;
#   * o banco é verificado com PRAGMA integrity_check antes do commit;
#   * dados brutos, travas e temporários são ignorados pelo .gitignore da branch.
set -euo pipefail

cmd="${1:?uso: data_branch.sh fetch|commit [DIR] [mensagem]}"
dir="${2:-persist}"
branch="${DATA_BRANCH:-data}"

write_branch_files() {
  cat > "$dir/.gitignore" <<'IGNORE'
# Branch de dados do UFABC Science: somente estado persistente e editorial.
data/raw/
data/exports/
data/database/*.lock
data/database/*-journal
data/database/*-wal
data/database/*-shm
*.tmp
build/
dist/
IGNORE
  cat > "$dir/README.md" <<'README'
# Dados do UFABC Science

Branch mantida pela automação semanal. Contém o banco SQLite, os arquivos
editoriais Markdown e os relatórios de execução. Não contém código.
Veja docs/PERSISTENCE_STRATEGY.md na branch principal.
README
}

case "$cmd" in
  fetch)
    if git ls-remote --exit-code --heads origin "$branch" >/dev/null 2>&1; then
      git fetch --no-tags origin "+refs/heads/$branch:refs/remotes/origin/$branch"
      git worktree add -B "$branch" "$dir" "origin/$branch"
      echo "Branch '$branch' recuperada em $dir."
    else
      git worktree add --detach "$dir"
      (
        cd "$dir"
        git checkout --orphan "$branch"
        git rm -rf --quiet . || true
        git clean -fdxq
      )
      write_branch_files
      echo "Branch '$branch' inexistente: criada (órfã) em $dir."
    fi
    mkdir -p "$dir/data/database" "$dir/data/editorial" "$dir/editions"
    ;;
  commit)
    message="${3:?informe a mensagem do commit}"
    db="$dir/data/database/ufabc_science.db"
    if [ -f "$db" ]; then
      python - "$db" <<'PY'
import sqlite3, sys
result = sqlite3.connect(sys.argv[1]).execute("PRAGMA integrity_check").fetchone()[0]
if result != "ok":
    sys.exit(f"Banco corrompido ({result}); commit cancelado.")
print("Integridade do SQLite: ok")
PY
    fi
    cd "$dir"
    [ -f .gitignore ] || { cd - >/dev/null; write_branch_files; cd "$dir"; }
    git add -A
    if git diff --cached --quiet; then
      echo "Nenhuma alteração nos dados; nenhum commit criado."
      exit 0
    fi
    git -c user.name="github-actions[bot]" \
        -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
        commit --quiet -m "$message"
    git push origin "HEAD:refs/heads/$branch"
    echo "Dados persistidos na branch '$branch'."
    ;;
  sync)
    message="${3:-editorial: revisão}"
    cd "$dir"
    git add -A
    if ! git diff --cached --quiet; then
      git commit --quiet -m "$message"
    fi
    git fetch --quiet origin "$branch"
    if ! git merge --no-edit --quiet "origin/$branch" >/dev/null 2>&1; then
      conflicts="$(git diff --name-only --diff-filter=U)"
      other="$(printf '%s\n' "$conflicts" | grep -v '\.db$' || true)"
      if [ -n "$other" ]; then
        echo "Conflito em arquivos editoriais (resolva manualmente e rode sync de novo):" >&2
        printf '  %s\n' $other >&2
        exit 1
      fi
      for db in $conflicts; do
        git checkout --ours -- "$db"
        git add "$db"
      done
      git commit --quiet --no-edit
      echo "Banco divergente: mantida a versão do editor. A próxima execução da automação"
      echo "recoleta o período da execução descartada (coleta incremental)."
    fi
    python - "data/database/ufabc_science.db" <<'PY'
import sqlite3, sys
from pathlib import Path
if Path(sys.argv[1]).exists():
    result = sqlite3.connect(sys.argv[1]).execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        sys.exit(f"Banco corrompido ({result}); nada foi enviado.")
PY
    git push --quiet origin "HEAD:refs/heads/$branch"
    echo "Branch '$branch' sincronizada."
    ;;
  *)
    echo "Comando desconhecido: $cmd" >&2
    exit 2
    ;;
esac
