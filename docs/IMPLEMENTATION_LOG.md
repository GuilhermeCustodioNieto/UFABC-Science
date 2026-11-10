# Registro de implementação

Ambiente de desenvolvimento: Windows 11, Python 3.10.11, SQLAlchemy 2.0.57, Alembic 1.20.1,
Pydantic 2.14.3, httpx 0.28.1, feedparser 6.0.14, Jinja2 3.1.6, python-frontmatter 1.3.0,
Markdown 3.10.3, nh3 0.3.7, pytest 8.4.2, Ruff 0.17.4.

## Resultado final (Etapas 1–5)

```text
$ pytest -q
276 passed

$ ruff check .
All checks passed!

$ ruff format --check .
(nenhum arquivo a reformatar)
```

| Arquivo de teste | Testes | Cobre |
|---|---:|---|
| unit/test_settings.py | 10 | padrões seguros, `.env`, segredos, validação |
| unit/test_domain_definitions.py | 9 | enums, editorias, slugs |
| unit/test_models.py | 37 | constraints, UTC, histórico, edições |
| unit/test_normalization.py | 28 | DOI, URL, título, JATS, e-mails, ORCID, idioma |
| unit/test_collector_parsing.py | 8 | parsing das quatro fontes (respostas reais), preprints |
| unit/test_http_client.py | 7 | retry/backoff, Retry-After, limite, erros, intervalo |
| unit/test_deduplication.py | 8 | DOI/id externo/URL/título, mesclagem, revisão por pares |
| unit/test_classification.py | 12 | palavras-chave, interdisciplinar, ambíguo, confiança, IA, manual |
| unit/test_relevance.py | 9 | fórmula, faixas, justificativas, preprint, sem citações/prestígio |
| unit/test_ai_provider.py | 12 | mock, prompts, injeção, adaptador HTTP, retry, JSON inválido |
| unit/test_verification.py | 15 | números, DOI, links, autores, citações, preprint, clínica |
| unit/test_markdown.py | 13 | front matter, hash, edição manual, YAML seguro, path traversal |
| unit/test_html_security.py | 15 | sanitização, escape, URLs |
| unit/test_lock.py | 3 | exclusividade, trava abandonada |
| integration/test_database_init.py | 6 | migrações, idempotência, modelos = migrações, downgrade |
| integration/test_collection.py | 6 | coleta completa, idempotência, falha isolada, enriquecimento |
| integration/test_generation.py | 11 | seleção, versões, hash, inválidos, FAILED, insuficiência, preservação |
| integration/test_editorial_flow.py | 19 | aprovação, WARNING/FAILED, rejeição, revisão, invalidação, edições, HTML |
| integration/test_pipeline.py | 10 | execução, idempotência, falhas, concorrência, recuperação |
| integration/test_workflows.py | 9 | YAML, permissões, gatilhos, SHAs, confirmação do deploy |
| integration/test_data_branch_script.py | 2 | persistência real entre "runners" via git local; push sem força |
| integration/test_cli.py | 15 | códigos de saída, mensagens, `python -m` |

## Etapa 1 — Fundação

Projeto, configurações, SQLite/SQLAlchemy/Alembic, 11 entidades, `init-db`, testes, README.
Decisões D1–D11 em `ARCHITECTURE.md`.

## Etapa 2 — Coletores

- `BaseCollector` + `RateLimitedClient` (timeout, retry com backoff, `Retry-After`, intervalo
  mínimo, sequencial), `RawStore` (respostas brutas idempotentes por hash).
- Coletores OpenAlex, PubMed (esearch/efetch), arXiv (Atom) e Crossref (+ consulta por DOI).
- Normalização para `NormalizedArticle`; deduplicação DOI → id externo → URL → título
  (sinaliza); mesclagem conservadora; enriquecimento Crossref.
- **Validação real** (09/11/2026, limite 6–8 por fonte): coleta das quatro fontes; segunda
  execução sem inserções; OpenAlex e Crossref unidos pelo mesmo DOI; HTTP 429 do Crossref
  tratado pelo retry (intervalo ajustado para 1 s).
- Achado: o OpenAlex passou a usar orçamento diário (sem chave: compartilhado por IP).
  Adicionados `OPENALEX_API_KEY`, `select` de campos e documentação.

## Etapa 3 — Inteligência editorial

- Classificação por regras JSON (termos fortes/fracos, campos com pesos, categorias das
  fontes, saturação → confiança); incerteza sinalizada; IA opcional para casos ambíguos.
- Relevância heurística `heuristic-v1` com justificativa por critério e faixas configuráveis.
- `AIProvider.generate_structured`; `MockProvider`; `OpenAICompatibleProvider`.
- Prompts versionados; dados externos isolados; validação Pydantic com novas tentativas.
- Seleção por prioridade com hash de entrada; versões preservadas; verificação determinística;
  exportação Markdown `pending_review`.

### Exemplo real (artigo coletado do arXiv em 09/11/2026, provedor mock)

- **Artigo:** *EmbodiedIntentBench: Benchmarking Intent-Driven Runtime Adaptation for Mobile
  Robotic Missions* — arXiv 2611.10498, 07/11/2026, `preprint`.
- **Classificação:** Engenharias (0,971) e Computação e Tecnologia (0,865), `rule_based`.
- **Relevância:** 64,45 (moderada) — científica 63, originalidade 62, impacto 60,
  interdisciplinaridade 65, interesse UFABC 76. Justificativas: "abstract detalhado; método
  descrito (benchmark); preprint: não penalizado…", "publicação recente (3 dias)",
  "… potencial, não impacto comprovado".
- **Rascunho (mock, extrativo):** título "[Rascunho mock] …"; introdução informa
  "Trata-se de um preprint, ainda não revisado por pares"; resultados citam o abstract
  ("reduces modeled task energy by up to 28%…"); referência montada dos metadados com
  "(Preprint, sem revisão por pares confirmada.)".
- **Verificação: WARNING** — PASSED: título, link, autores, números (28% consta no abstract),
  preprint identificado; WARNING: sem DOI, extensão abaixo da referência, nota do gerador.

## Etapa 4 — Editorial e publicação

- Markdown com front matter YAML (`python-frontmatter`), hash do corpo, histórico em `history/`.
- `editorial sync`: valida, registra revisões (com cópia do texto aprovado), move arquivos,
  bloqueia FAILED, exige justificativa para WARNING, invalida aprovação após edição, detecta
  duplicados e arquivos alheios.
- Edições: criação por semana ISO (sem duplicidade), introdução com aprovação própria,
  add/remove/reorder/section, agrupamento por editoria, validação (`READY`), publicação
  explícita (`--confirm --by`) com registro JSON e revisão fixada, arquivamento.
- Site estático Jinja2 (home, edição, artigo, arquivo), CSS responsivo claro/escuro, sem
  dependências externas, JS opcional; sanitização `nh3`; pré-visualização separada.
- **Validação manual de ponta a ponta** (dados reais + mock): 21 artigos coletados, 6 rascunhos,
  aprovação de 1 artigo, criação e publicação da edição 001, site com 4 páginas; edição
  posterior do arquivo aprovado invalidou a aprovação e o site publicado manteve o texto fixado.

Estrutura gerada:

```text
dist/
├── .ufabc-science-site
├── index.html
├── archive/index.html
├── editions/edicao-001/index.html
├── articles/article-13/index.html
└── assets/css/style.css, assets/js/main.js
```

## Etapa 5 — Automação

- `run` com etapas selecionáveis, `pipeline_runs`, relatório JSON e `GITHUB_STEP_SUMMARY`,
  status RUNNING/SUCCESS/PARTIAL_SUCCESS/FAILED, trava exclusiva, recuperação.
- Workflows `weekly_pipeline.yml`, `deploy_pages.yml`, `ci.yml` (Actions fixadas por SHA).
- Persistência na branch `data` (`scripts/data_branch.sh`), testada com repositório git local.
- **Não configurado em produção:** nenhum workflow foi executado no GitHub; Pages, secrets e a
  branch `data` dependem dos passos de `GITHUB_SETUP.md`.
- O actionlint não foi executado (a execução de binários baixados não foi autorizada neste
  ambiente); a validação dos workflows foi feita pelos testes estáticos.

## Problemas encontrados e corrigidos durante a implementação

- YAML inválido no workflow semanal (`: ` em escalar sem aspas) — detectado pelos testes.
- Ordem do histórico editorial por `reviewed_at` podia escolher a revisão errada no mesmo
  segundo — passou a usar a ordem de inserção.
- Intervalo do Crossref aumentado após HTTP 429 real.

## Teste de uso real (10/11/2026)

Simulação de uma semana de operação o mais próxima possível do ambiente real:

- **"GitHub" local:** repositório bare com o código; o runner é um clone limpo com venv
  próprio e `pip install .` (valida o empacotamento) executando os passos de
  `weekly_pipeline.yml` e `deploy_pages.yml`; o editor usa outro clone com a branch `data`
  em *worktree* e `.env`, seguindo a documentação.
- **Dados reais:** APIs OpenAlex, PubMed, arXiv e Crossref, sem limites reduzidos.
- **IA real local:** Ollama com `qwen2.5:7b`, iniciado só para o teste e encerrado no fim.

| Etapa | Resultado |
|---|---|
| Execução agendada (7 dias, 100/fonte) | 368 artigos reais, 0 erros, 4 possíveis duplicatas sinalizadas, ~150 s com instalação; commit na branch `data` |
| 2ª execução (runner novo) | 0 novos, 368 já existentes: idempotente entre runners efêmeros |
| Geração local (Ollama) | 4 rascunhos em português, ~4 min cada; 1 timeout recuperado pelo retry |
| Texto com aparência de instrução ("SYSTEM ANOMALY DOSSIER… OVERRIDE") | o modelo não obedeceu ao conteúdo externo; verificação marcou WARNING; editor rejeitou |
| Revisão humana | 2 aprovados (1 reescrito), 2 rejeitados; introdução escrita e aprovada |
| Edição | criada, ordenada, validada, pré-visualizada via `http.server`, publicada |
| Site | 5 páginas; todos os links internos resolvem; 1 `<h1>` por página; sem recursos externos |
| Deploy simulado | frase errada e número com injeção recusados; edição inexistente recusada; build a partir de clone limpo |
| Editor e automação simultâneos | push do editor recusado (sem perda); `data_branch.sh sync` manteve o banco do editor e mesclou os relatórios |
| 3ª execução sobre o estado editado | estado editorial e edição publicada preservados |

### Problemas encontrados e corrigidos

| # | Problema (observado com dados reais) | Correção |
|---|---|---|
| U1 | `data_branch.sh` com CRLF num clone do Windows (`core.autocrlf=true`): o bash quebraria | `.gitattributes` força LF em `*.sh`/`*.yml` |
| U2 | Termos genéricos ("model", "mechanism", "agent") davam até 5 editorias por artigo | `rules-v2`: limiar relativo (60% da principal) e máximo de 3 editorias; termos removidos |
| U3 | Lista de prioridades dominada por "abstracts" de 1.300 palavras e depósitos sem triagem (Zenodo/OSF) | `heuristic-v2`: sem bônus para abstract atípico; −15 para repositório sem triagem; interdisciplinaridade conta só categorias confiantes. Itens problemáticos foram das primeiras posições para 39–133 (de 368), sem descarte |
| U4 | Mudança de regras ou método não reprocessava os artigos | reprocessamento automático por versão |
| U5 | `shortlist` sem contexto | coluna de alertas (`pre`, `repo`, `abs?`, `dup?`) e nomes das editorias |
| U6 | Resumo mandava revisar `pending/` sem ter gerado nada | mensagem condicional que explica o motivo |
| U7 | Aviso de extensão em todo rascunho, porque a fonte curta gera texto curto (contradiz "não aumentar artificialmente") | só avisa texto longo demais |
| U8 | Falso "afirmação sem evidência" entre português e inglês | siglas e prefixos de cognatos no vínculo |
| U9 | Aviso "arquivo será movido" em toda aprovação normal | removido |
| U10 | Fonte atípica não aparecia no Markdown do editor | nova checagem `source_quality` (WARNING) |
| U11 | Introdução aprovada com o texto-modelo seria publicada; título `#` duplicava o da página | bloqueio do texto-modelo; título removido na publicação |
| U12 | Ordem definida pelo editor era ignorada entre seções | seções seguem a ordem do editor; ordem oficial só como padrão inicial |
| U13 | Nome da editoria repetido no card dentro da própria seção | etiqueta omitida dentro da seção |
| U14 | **Conflito de banco entre editor e automação: a orientação documentada ("manter remota") perderia trabalho editorial** | `data_branch.sh sync` (banco do editor prevalece) + coleta incremental que cobre a lacuna |

### Observações da revisão humana (não detectáveis automaticamente)

O modelo local produziu texto fluente e cauteloso, mas um rascunho trazia um erro conceitual
("proteômica" no lugar de design de proteínas), um exagero ("está transformando a indústria"),
omitia os tempos de execução comparados e dizia que "não foram informadas limitações" quando o
abstract apontava uma. A verificação determinística não pega esse tipo de problema: a revisão
humana continua indispensável.

### Não testado

- Execução real no GitHub Actions e no GitHub Pages (simulada localmente; nada foi publicado).
- Aparência visual em navegador (a extensão do Chrome não estava conectada); a estrutura HTML
  e os links foram verificados por um rastreador.
- Python 3.12 (somente 3.10 está disponível nesta máquina; o CI testa 3.10 e 3.12).
