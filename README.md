# UFABC Science

Plataforma de **curadoria e divulgação científica assistida por IA** para a comunidade da
Universidade Federal do ABC (UFABC). O sistema descobre pesquisas recentes, organiza-as por
editoria, prioriza o que interessa à comunidade e produz rascunhos em português que **só são
publicados depois de aprovação humana**, em uma newsletter semanal em HTML estático.

> UFABC Science é uma iniciativa independente. Não representa oficialmente a UFABC.

**Estado:** Etapas 1 a 5 implementadas e testadas localmente (276 testes, sem rede) e validadas numa simulação de uma semana real de operação. A
publicação no GitHub Pages está **preparada, mas não configurada** neste repositório — veja
[`docs/GITHUB_SETUP.md`](docs/GITHUB_SETUP.md).

## Objetivo e escopo do MVP

- Coletar artigos do **OpenAlex, PubMed, arXiv e Crossref** (APIs oficiais e gratuitas).
- Normalizar para uma estrutura única, deduplicar sem descartar registros indevidamente.
- Classificar nas cinco editorias e calcular uma prioridade editorial (0 a 100).
- Gerar rascunhos em português **a partir apenas dos dados coletados**, com verificação
  determinística (`PASSED` / `WARNING` / `FAILED`).
- Revisão humana em **arquivos Markdown** (sem painel administrativo).
- Montar edições semanais e gerar um site estático com arquivo histórico.
- Custo obrigatório **R$ 0**. Funciona sem chave de IA (provedor `mock`).

## Arquitetura

Monólito modular orientado a pipeline; cada etapa pode ser executada isoladamente.

```text
collectors → normalization → deduplication → classification → relevance
→ generation (IA) → verification → Markdown (humano) → approval → edition → HTML → Pages
```

Detalhes: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · modelo de dados:
[`docs/DATABASE.md`](docs/DATABASE.md).

## Tecnologias

Python 3.10+ (CI em 3.10 e 3.12) · SQLite (portável para PostgreSQL) · SQLAlchemy 2 ·
Alembic · Pydantic / pydantic-settings · httpx · feedparser · Jinja2 · python-frontmatter ·
Markdown + nh3 (sanitização) · pytest · Ruff · GitHub Actions.

## Instalação

1. Instale o **Python 3.10 ou superior** (recomendado 3.12): <https://www.python.org/downloads/>.
2. Na raiz do repositório:

   ```powershell
   # Windows (PowerShell)
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   python -m pip install -e ".[dev]"
   ```

   ```bash
   # Linux / macOS
   python3 -m venv .venv && source .venv/bin/activate
   python -m pip install -e ".[dev]"
   ```

## Configuração (`.env`)

```bash
cp .env.example .env        # PowerShell: Copy-Item .env.example .env
python -m ufabc_science config check
```

Todas as variáveis são opcionais; o `.env.example` documenta cada uma, agrupadas em gerais,
diretórios, fontes, **credenciais**, IA, classificação/geração e automação. Recomendado:
`CONTACT_EMAIL` e uma `OPENALEX_API_KEY` gratuita (o OpenAlex mede o uso por orçamento diário).
`config check` mostra a configuração efetiva **sem revelar segredos**. Nunca versione o `.env`.

## Uso rápido

```bash
python -m ufabc_science init-db                 # cria/atualiza o banco (idempotente)
python -m ufabc_science run --days 7            # coleta → classificação → relevância → rascunhos
python -m ufabc_science editorial list          # rascunhos em data/editorial/pending/
# ... revise e aprove no próprio arquivo (status: approved) ...
python -m ufabc_science editorial sync          # registra aprovações/rejeições
python -m ufabc_science edition create --week 2026-W46
python -m ufabc_science edition add --edition 1 --article-id 13
python -m ufabc_science edition validate --edition 1
python -m ufabc_science publish --edition 1     # pré-visualização em build/preview/ (não publica)
python -m ufabc_science edition publish --edition 1 --by "Seu nome" --confirm
```

## Comandos

| Comando | Função |
|---|---|
| `init-db` | Aplica migrações e cadastra as editorias. |
| `config check` | Valida e mostra a configuração (sem segredos). |
| `collect [--days N \| --start D --end D] [--sources a,b] [--query Q] [--limit N] [--no-enrich] [--json]` | Coleta, normaliza, deduplica e persiste; confirma DOIs no Crossref. |
| `enrich [--limit N]` | Confirma publicação/metadados por DOI no Crossref. |
| `classify [--article-id 1,2] [--all] [--ai]` | Classificação por regras (IA opcional nos casos ambíguos). |
| `score [--article-id ..] [--all]` | Relevância editorial (histórico preservado). |
| `shortlist [--limit 20]` | Artigos prioritários com faixa de prioridade. |
| `generate [--limit N] [--article-id ..] [--force]` | Gera, verifica e exporta rascunhos Markdown. |
| `verify [--article-id ..]` | Reexecuta a verificação determinística. |
| `process [--limit N]` | `classify` + `score` + `generate`. |
| `editorial sync [--dry-run]` · `editorial validate` · `editorial list --status pending\|approved\|rejected\|needs_revision\|all` | Fluxo editorial em Markdown. |
| `edition create --week AAAA-Www` · `add` · `remove` · `reorder --order 3,1,2` · `section` · `validate` · `show` · `publish --by NOME --confirm` · `archive` | Edições semanais. |
| `publish --edition N` | **Pré-visualização** HTML local (não altera estado). |
| `site build [--require-edition N] [--strict]` | Site público em `dist/` só com edições publicadas. |
| `run [--days] [--sources] [--max-articles] [--limit] [--steps all\|process\|collect,enrich,...]` | Pipeline completo ou parcial; **nunca aprova nem publica**. |
| `runs [--limit 10]` | Histórico de execuções. |

Códigos de saída: `0` sucesso · `1` erro ou validação reprovada · `2` uso/configuração
inválidos · `3` outra execução do pipeline em andamento.

## Guias

| Tema | Documento |
|---|---|
| Revisar Markdown, aprovar, rejeitar, pedir revisão | [`docs/EDITORIAL_WORKFLOW.md`](docs/EDITORIAL_WORKFLOW.md) |
| Criar edição, gerar HTML, visualizar e publicar | [`docs/PUBLISHING_GUIDE.md`](docs/PUBLISHING_GUIDE.md) |
| Adicionar uma fonte científica | [`docs/ADDING_SOURCES.md`](docs/ADDING_SOURCES.md) |
| Configurar um provedor de IA (custos e limites) | [`docs/AI_PROVIDERS.md`](docs/AI_PROVIDERS.md) |
| Automação semanal e execução manual | [`docs/AUTOMATION_GUIDE.md`](docs/AUTOMATION_GUIDE.md) |
| Configurar GitHub (Actions, Pages, secrets) | [`docs/GITHUB_SETUP.md`](docs/GITHUB_SETUP.md) |
| Como os dados são preservados | [`docs/PERSISTENCE_STRATEGY.md`](docs/PERSISTENCE_STRATEGY.md) |
| Registro e resultados de cada etapa | [`docs/IMPLEMENTATION_LOG.md`](docs/IMPLEMENTATION_LOG.md) |

## Testes

```bash
pytest
ruff check .
ruff format --check .
```

Os testes usam respostas reais gravadas das APIs (`tests/fixtures/api`) servidas por um
transporte HTTP simulado: não acessam a internet nem exigem chaves.

## O que continua dependendo de ação humana

Aprovar, rejeitar ou pedir revisão de cada artigo; aprovar a introdução da edição; montar e
validar a edição; executar `edition publish --confirm`; disparar manualmente o workflow de
deploy com a frase de confirmação. Nenhuma rotina automática faz qualquer uma dessas ações.

## Limitações conhecidas

- O provedor `mock` gera rascunhos **extrativos** (trechos do abstract em inglês), úteis só
  para desenvolvimento. Para texto editorial é preciso um provedor real (ex.: Ollama local).
- A verificação automática não comprova a veracidade científica: aponta inconsistências
  (números, DOIs, links, autores, preprints, linguagem) para revisão humana. A vinculação de
  afirmações ao abstract é lexical e limitada quando o texto está em outro idioma.
- A classificação por regras é um ponto de partida; termos e pesos devem ser calibrados com o
  uso (`CLASSIFICATION_RULES_PATH`).
- A pontuação heurística é prioridade editorial, não avaliação de qualidade científica.
- PostgreSQL é suportado pela arquitetura, mas não foi testado em produção.
- GitHub Pages gratuito exige repositório público; os dados da branch `data` (inclusive
  rascunhos não aprovados) ficam visíveis — ver `docs/PERSISTENCE_STRATEGY.md`.

## Licença

[MIT](LICENSE).
