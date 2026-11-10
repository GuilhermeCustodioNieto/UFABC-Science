# Configuração do GitHub

> Nada disto foi configurado automaticamente. Os workflows estão prontos no repositório, mas
> só funcionam depois destes passos, feitos por você.

## 1. Repositório

- Publique o repositório no GitHub. Para usar o GitHub Pages sem custo, ele precisa ser
  **público** — leia a seção "Exposição de dados" de [`PERSISTENCE_STRATEGY.md`](PERSISTENCE_STRATEGY.md).
- A branch principal deve se chamar `main` (o deploy só é aceito a partir dela).

## 2. Habilitar GitHub Actions

**Settings → Actions → General**:

- *Actions permissions*: permitir actions (as usadas são oficiais `actions/*`, fixadas por SHA).
- *Workflow permissions*: **Read repository contents** (padrão restrito). Os workflows pedem
  explicitamente só o que precisam (`contents: write` apenas no pipeline semanal, para a
  branch `data`).
- Não marque "Allow GitHub Actions to create and approve pull requests".

## 3. Variáveis e secrets

**Settings → Secrets and variables → Actions**.

*Variables* (não sensíveis):

| Nome | Exemplo | Obrigatória |
|---|---|---|
| `CONTACT_EMAIL` | `contato@exemplo.org` | Recomendada |
| `ENABLED_SOURCES` | `openalex,pubmed,arxiv,crossref` | Não |
| `AI_PROVIDER` | `mock` ou `openai_compatible` | Não (padrão `mock`) |
| `AI_MODEL` | nome do modelo | Se `openai_compatible` |
| `AI_BASE_URL` | URL da API compatível | Se `openai_compatible` |

*Secrets* (sensíveis):

| Nome | Uso |
|---|---|
| `OPENALEX_API_KEY` | Orçamento próprio no OpenAlex (gratuito). Recomendado. |
| `NCBI_API_KEY` | Limite maior no PubMed (gratuito). Opcional. |
| `AI_API_KEY` | Chave do provedor de IA, se houver. Opcional. |

Use o `GITHUB_TOKEN` automático; não crie tokens pessoais. Um provedor de IA local (Ollama)
não é acessível pelo runner do GitHub.

## 4. Branch de dados

Nada a fazer: a primeira execução do **Pipeline semanal** cria a branch órfã `data`. Opcional:
proteja a `main` (Settings → Branches) exigindo o workflow **CI**; não aplique regras que
impeçam o `github-actions[bot]` de enviar para `data`.

## 5. GitHub Pages

1. **Settings → Pages → Build and deployment → Source: GitHub Actions**.
2. **Settings → Environments → github-pages**: em *Deployment branches*, permita só `main`.
   Recomendado: adicione você em *Required reviewers* — o deploy pedirá aprovação manual
   adicional (segunda trava humana).

## 6. Primeira execução

1. Actions → **Pipeline semanal** → *Run workflow* (`steps: collect,enrich` para começar).
2. Confira o resumo e a nova branch `data`.
3. Faça a revisão editorial localmente (ver `PERSISTENCE_STRATEGY.md`, "Uso local") e envie a
   branch `data`.

## 7. Autorizar uma publicação

1. Localmente, com a branch `data` atualizada:

   ```bash
   python -m ufabc_science edition validate --edition 1
   python -m ufabc_science publish --edition 1          # revise a pré-visualização
   python -m ufabc_science edition publish --edition 1 --by "Seu Nome" --confirm
   ```

2. Faça commit e push da branch `data`.
3. Actions → **Publicar no GitHub Pages** → *Run workflow*: `edition = 1`,
   `confirm = PUBLICAR edicao-001`.
4. O workflow recusa se a frase estiver errada, se não for a `main`, se a edição não estiver
   `PUBLISHED` ou se algum item publicado estiver inconsistente.

A rotina semanal não tem permissão de Pages e não aciona este workflow; a existência de novos
arquivos Markdown nunca é tratada como autorização.

## Validação local opcional dos workflows

Os testes (`tests/integration/test_workflows.py`) verificam a sintaxe YAML, permissões,
gatilhos, SHAs fixados, `timeout-minutes` e a confirmação do deploy. Para uma análise mais
completa, você pode rodar o [actionlint](https://github.com/rhysd/actionlint) (gratuito):
`actionlint .github/workflows/*.yml`.
