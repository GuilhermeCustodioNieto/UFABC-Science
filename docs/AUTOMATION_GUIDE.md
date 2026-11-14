# Guia de automação

## Pipeline

```bash
python -m ufabc_science run --days 7
```

Ordem: `collect` → `enrich` (Crossref por DOI) → `classify` → `score` → `generate` (seleção,
geração, verificação e Markdown em `pending/`). O `run` em si **nunca** aprova, cria edição
ou publica; isso só acontece no comando separado `autopublish` (abaixo).

| Opção | Efeito |
|---|---|
| `--steps all` (padrão) / `process` / lista (`collect,enrich`) | Execução completa ou parcial. |
| `--days N` | Janela de coleta (padrão `COLLECTION_DAYS`). |
| `--sources openalex,arxiv` | Fontes (padrão `ENABLED_SOURCES`). |
| `--max-articles N` | Máximo por fonte (padrão `MAX_ARTICLES_PER_SOURCE`). |
| `--limit N` | Máximo de rascunhos (padrão `GENERATION_LIMIT`). |
| `--trigger` | Origem registrada (`local`, `schedule`, `workflow_dispatch`). |

Cada execução recebe um identificador, fica registrada em `pipeline_runs` (`runs` lista) e em
`data/runs/<data>-<id>.json`, e imprime um resumo: fontes consultadas, artigos encontrados,
novos, duplicados, possíveis duplicatas, classificados, selecionados, gerados, falhas de
verificação, erros de coleta e duração. No GitHub Actions o resumo também aparece na página da
execução (`GITHUB_STEP_SUMMARY`).

### Status

| Status | Quando |
|---|---|
| `RUNNING` | Em andamento. |
| `SUCCESS` | Sem erros. |
| `PARTIAL_SUCCESS` | Houve erros (ex.: uma fonte falhou), mas as demais etapas/fontes foram processadas. |
| `FAILED` | Todas as etapas executadas falharam, ou a execução foi interrompida. |

### Idempotência e recuperação

- Coleta: `(fonte, id externo)` único; respostas brutas idênticas não duplicam arquivos.
- Coleta incremental: se a última coleta registrada terminou antes do início da janela
  (`--days`), a janela é ampliada para cobrir a lacuna (até 60 dias) e isso aparece no resumo.
- Classificação e relevância são refeitas automaticamente quando a versão das regras
  (`rules-vN`) ou do método (`heuristic-vN`) muda; o histórico é preservado.
- Enriquecimento: cada DOI é consultado no Crossref uma única vez.
- Classificação e relevância: artigos já processados são ignorados.
- Geração: hash de entrada impede regenerar; conteúdo `FAILED` com a mesma entrada é bloqueado.
- Trava exclusiva (`data/database/pipeline.lock`) — uma segunda execução sai com código `3`.
  Travas e execuções `RUNNING` mais antigas que `PIPELINE_LOCK_STALE_HOURS` são recuperadas.
- Interrupções marcam a execução como `FAILED`; basta executar de novo.

## Workflows do GitHub Actions

| Workflow | Gatilho | Permissões | Faz |
|---|---|---|---|
| `weekly_pipeline.yml` | Agendado + manual | `contents: write` (só para a branch `data`) | Coleta e processamento; persiste dados; artifacts. |
| `deploy_pages.yml` | **Somente manual**, com confirmação | `contents: read`; deploy com `pages: write`, `id-token: write` | Revalida edição publicada, gera `dist/`, publica no Pages. |
| `ci.yml` | Push/PR | `contents: read` | Ruff e pytest (3.10 e 3.12). |

Todas as Actions são fixadas por SHA de commit; todo job tem `timeout-minutes`; entradas
manuais chegam ao shell apenas por variáveis de ambiente (evita injeção de comandos).

### Agendamento semanal

`cron: "0 11 * * 1"` — segunda-feira às **11:00 UTC = 08:00 em São Paulo** (UTC−3). O GitHub
agenda sempre em UTC. O Brasil não adota horário de verão desde 2019; se voltar a adotar, a
execução passará a ocorrer às 09:00 locais nesse período (ajuste para `0 10 * * 1` se quiser
manter 08:00). Execuções agendadas podem atrasar em horários de pico e são desativadas pelo
GitHub após 60 dias sem atividade no repositório.

Por padrão (`steps: auto`), rascunhos só são gerados se houver um provedor de IA real
configurado (`AI_PROVIDER` diferente de `mock`); caso contrário a rotina coleta, classifica e
pontua.

### Execução manual

GitHub → **Actions** → **Pipeline semanal** → **Run workflow**. Parâmetros: `days`,
`sources`, `max_articles`, `generation_limit`, `steps`. Campos vazios usam a configuração do
projeto. Com `AUTO_PUBLISH=true`, a execução manual também publica automaticamente.

### Recuperar uma execução com falha

1. Abra a execução e leia o resumo e os logs (nenhuma credencial é impressa).
2. Baixe o artifact `execucao-<id>` (relatório JSON, pendentes, respostas brutas).
3. Corrija a causa (ex.: fonte fora do ar, cota esgotada) e clique em **Re-run jobs** ou
   dispare manualmente. As etapas são idempotentes.
4. Se o push na branch `data` falhou porque ela avançou (edição humana), simplesmente execute
   de novo.

## Limites e riscos da infraestrutura gratuita

- GitHub Actions: repositórios públicos têm minutos gratuitos nos runners padrão; privados têm
  cota mensal limitada. Cada execução semanal leva poucos minutos com os limites padrão.
  Condições podem mudar — consulte a documentação de cobrança do GitHub.
- Artifacts: retenção configurada em 14 dias; contam na cota de armazenamento.
- GitHub Pages: gratuito para repositórios públicos; limites de tamanho e banda.
- APIs científicas: limites de taxa e orçamento (OpenAlex) podem mudar; falhas de uma fonte
  não interrompem as demais.
- Provedores de IA hospedados: cotas gratuitas são instáveis; o projeto não depende delas.

## Publicação automática (padrão no GitHub Actions)

Com `AUTO_PUBLISH=true` (padrão do workflow; desligue definindo a variável `AUTO_PUBLISH` como
`false`), a rotina semanal roda sozinha de ponta a ponta:

```text
run (coleta → … → rascunhos) → autopublish → commit na branch data → site build → deploy no Pages
```

`python -m ufabc_science autopublish [--max-articles N] [--date AAAA-MM-DD]`:

1. **Aprova automaticamente** apenas rascunhos em `pending/` que: foram gerados por um modelo
   real (nunca o `mock`); não foram editados à mão; são a versão mais recente; têm verificação
   `PASSED` no banco; e cuja revalidação do arquivo não gera nenhum erro **nem aviso**.
   `WARNING` e `FAILED` ficam em `pending/` para revisão humana opcional. A aprovação passa pelo
   mesmo `editorial sync` da aprovação humana (`reviewer: Publicação automática`, hash e cópia
   do texto aprovado).
2. Cria a edição da semana ISO corrente com até `AUTO_PUBLISH_MAX_ARTICLES` artigos aprovados
   ainda não publicados (maior prioridade primeiro), escreve uma introdução padronizada que
   declara a ausência de revisão humana e publica a edição.
3. Sem artigos elegíveis, nada é publicado naquela semana. A mesma semana nunca é publicada
   duas vezes e nenhum artigo é republicado.

O site exibe em todas as páginas um aviso de que os resumos foram escritos por IA, sem revisão
humana, sempre que houver alguma edição publicada automaticamente. O deploy só acontece se os
dados foram gravados com sucesso na branch `data`.

**IA padrão: GitHub Models** (`AI_BASE_URL=https://models.github.ai/inference`,
`AI_MODEL=openai/gpt-4.1-mini`), autenticado pelo `GITHUB_TOKEN` do próprio workflow
(permissão `models: read`): sem conta, chave ou custo, com limites diários de requisições que
o GitHub pode alterar. Para usar outro provedor, defina as variáveis `AI_*` e o secret
`AI_API_KEY`.

## Fluxo com revisão humana (`AUTO_PUBLISH=false`)

Revisar, aprovar, rejeitar e pedir revisão de artigos; aprovar a introdução; montar e validar
a edição; `edition publish --confirm`; disparar o deploy com a frase de confirmação.
