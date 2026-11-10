# Estratégia de persistência

Os runners do GitHub Actions são efêmeros: nada criado em uma execução existe na próxima. A
estratégia escolhida é a **Alternativa A — persistência versionada no Git, em uma branch
dedicada `data`**.

## Por que esta alternativa

| Alternativa | Avaliação |
|---|---|
| **A. Branch `data` no próprio repositório** | ✅ Escolhida. Custo zero, histórico completo de cada mudança, recuperação por `git revert`, editor trabalha com Git (que já usa), sem segredos extras (`GITHUB_TOKEN`). |
| B. Artifacts do Actions | ❌ Como banco: retenção limitada (padrão 90 dias, aqui 14) e cota de armazenamento. Usados apenas para inspeção da execução. |
| C. SQLite local como fonte principal | ❌ A coleta semanal automática dependeria da máquina do editor ligada. Continua possível para uso só local. |

## Layout da branch `data`

```text
data/database/ufabc_science.db   # banco SQLite (fonte da verdade)
data/editorial/{pending,approved,rejected,history}/article-*.md
data/runs/*.json                 # relatórios de execução
editions/drafts/*.md             # introduções
editions/published/*.json        # registros de publicação
.gitignore                       # exclui data/raw/, travas, journals do SQLite, build/, dist/
```

A branch `main` contém apenas código e a estrutura de diretórios (o `.gitignore` da `main`
exclui esses dados). A automação **nunca** faz commit na `main`.

## Ciclo da automação semanal

1. `scripts/data_branch.sh fetch persist` — recupera `data` como *git worktree* em `persist/`
   (ou cria a branch órfã na primeira execução).
2. O pipeline roda com `DATA_DIR=persist/data`, `EDITIONS_DIR=persist/editions` e
   `DATABASE_URL=sqlite:///persist/data/database/ufabc_science.db`.
3. `scripts/data_branch.sh commit persist "..."` — executa `PRAGMA integrity_check`; se não há
   mudanças, **não cria commit**; senão faz commit e `push` **sem `--force`**.
4. Respostas brutas, relatórios e pendentes também vão como artifact por 14 dias.

## Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Duas execuções modificando o banco | `concurrency: ufabc-science-data` (fila, sem cancelamento) no workflow; trava `pipeline.lock` + verificação de execuções `RUNNING` na aplicação. |
| Conflito entre automação e editor | `push` sem força: se a branch remota avançou, o push falha e nada é sobrescrito. O editor usa `scripts/data_branch.sh sync` (abaixo), que integra a versão remota antes de enviar. Recomendado: comece o dia com `git pull` e evite editar durante a janela agendada (segunda 08:00). |
| Conflito de merge no banco SQLite (binário) | **O banco do editor prevalece.** O trabalho editorial (rascunhos gerados localmente, aprovações, edições, publicação) não é refazível; o que a automação fez é: a coleta é idempotente e **incremental** — a próxima execução começa no fim da última coleta registrada e cobre o período da execução descartada (até 60 dias). Arquivos de texto (Markdown, relatórios) são mesclados normalmente. Testado em simulação real (ver `IMPLEMENTATION_LOG.md`). |
| Corrupção do banco | Transações por fonte/artigo; `integrity_check` antes do commit; histórico Git permite voltar a qualquer versão (`git checkout <commit> -- data/database/ufabc_science.db`). |
| Execução interrompida | Trava liberada em `finally`; execução marcada `FAILED`; etapas idempotentes — reexecutar continua de onde parou. Execuções canceladas não fazem commit. |
| Crescimento do repositório | O banco muda a cada semana e cada versão fica no histórico. Volume estimado pequeno (MB por ano com os limites padrão); se crescer, compacte a branch (novo commit órfão) após backup. |
| **Exposição de dados** | GitHub Pages gratuito exige repositório **público**: a branch `data` (incluindo rascunhos não aprovados e nomes de revisores) fica visível. Os dados são metadados científicos públicos, mas rascunhos podem conter erros. Se isso não for aceitável: repositório privado (Pages exige plano pago) ou guardar `data` em um repositório privado separado (exige token com escopo mínimo — fora do escopo atual). |
| Segredos | Nenhum segredo é gravado no banco, nos Markdown ou nos relatórios; chaves vêm de *secrets* via variáveis de ambiente. |

## Uso local com a branch `data`

```bash
git fetch origin data
git worktree add ../ufabc-science-data data      # cópia de trabalho dos dados
```

`.env` local:

```env
DATA_DIR=../ufabc-science-data/data
EDITIONS_DIR=../ufabc-science-data/editions
DATABASE_URL=sqlite:///../ufabc-science-data/data/database/ufabc_science.db
```

Rotina do editor:

```bash
git -C ../ufabc-science-data pull          # 1. antes de começar
# 2. revisar, editorial sync, edição, publicação...
bash scripts/data_branch.sh sync ../ufabc-science-data "editorial: revisão da semana"   # 3. enviar
```

`sync` faz commit do seu trabalho, integra o que a automação enviou nesse meio-tempo (se o
banco divergir, mantém o seu e avisa), verifica a integridade do SQLite e envia — sem
`--force`. Se houver conflito em um arquivo **de texto** (raro: a automação só cria arquivos
novos em `pending/`), ele para e lista os arquivos para resolução manual.

No Windows com `core.autocrlf=true`, os Markdown podem ser gravados com CRLF; isso não
invalida aprovações (o hash do corpo ignora quebras de linha). O `.gitattributes` garante LF
nos scripts e workflows.

## Recuperação

- Desfazer uma execução: `git revert <commit>` na branch `data`.
- Restaurar o banco de uma data: `git log -- data/database/ufabc_science.db` e
  `git checkout <commit> -- data/database/ufabc_science.db`.
- Trava abandonada: é removida automaticamente após `PIPELINE_LOCK_STALE_HOURS` (6 h); ou
  apague `data/database/pipeline.lock` se tiver certeza de que nenhuma execução está ativa.
