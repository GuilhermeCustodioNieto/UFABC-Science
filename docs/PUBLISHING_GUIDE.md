# Guia de publicação

Passo a passo para transformar rascunhos aprovados em uma edição publicada.

## 1. Encontrar os rascunhos

```bash
python -m ufabc_science editorial list            # data/editorial/pending/
python -m ufabc_science shortlist --limit 20      # prioridade editorial
```

## 2. Editar um Markdown

Abra `data/editorial/pending/article-<id>.md` em qualquer editor de texto. Reescreva as seções
mantendo os títulos `##`. Detalhes em [`EDITORIAL_WORKFLOW.md`](EDITORIAL_WORKFLOW.md).

## 3. Aprovar um artigo

```yaml
status: approved
reviewer: Seu Nome
warning_justification: "Conferi extensão e ausência de DOI; link do arXiv validado."  # se WARNING
```

## 4. Rejeitar

```yaml
status: rejected
editorial_notes: "Fora do escopo da edição."
```

## 5. Solicitar revisão

```yaml
status: needs_revision
editorial_notes: "Explicar melhor a metodologia."
```

## 6. Sincronizar

```bash
python -m ufabc_science editorial validate
python -m ufabc_science editorial sync
```

## 7. Criar uma edição

```bash
python -m ufabc_science edition create --week 2026-W46
```

Cria a edição `DRAFT` (número sequencial, slug `edicao-001`, período segunda a domingo da
semana ISO) e o arquivo da introdução `editions/drafts/edicao-001.md`. Não é possível criar
duas edições para a mesma semana. Nenhum artigo é adicionado automaticamente.

Escreva a introdução e aprove-a no próprio arquivo (`status: approved`, `reviewer`).

## 8. Adicionar e ordenar artigos

```bash
python -m ufabc_science edition add --edition 1 --article-id 13
python -m ufabc_science edition add --edition 1 --article-id 8 --position 1 --section neurociencia
python -m ufabc_science edition remove --edition 1 --article-id 8
python -m ufabc_science edition reorder --edition 1 --order 13,8,21
python -m ufabc_science edition section --edition 1 --article-id 13 --section engenharias
python -m ufabc_science edition show --edition 1
```

Só artigos aprovados entram. A seção padrão é a `primary_category` do arquivo aprovado (ou a
categoria de maior confiança). Na página, os artigos são agrupados na ordem oficial das
editorias e cada artigo aparece uma única vez; as demais categorias aparecem como secundárias.

## 9. Validar a edição

```bash
python -m ufabc_science edition validate --edition 1
```

Verifica introdução aprovada, artigos aprovados, arquivo aprovado inalterado (hash), front
matter, categorias, links, DOI, referência e verificação científica do texto aprovado. Se
válida, a edição passa a `READY`. Qualquer alteração posterior a devolve para `DRAFT`.

## 10. Gerar HTML (pré-visualização)

```bash
python -m ufabc_science publish --edition 1
```

Gera `build/preview/edicao-001/` com faixa "Pré-visualização" e `noindex`. **Não altera o
estado da edição e não publica nada.** Itens não aprovados aparecem listados como bloqueados.

## 11. Visualizar localmente

Abra `build/preview/edicao-001/index.html` no navegador (funciona via `file://`, sem servidor
e sem JavaScript). Opcionalmente:

```bash
python -m http.server 8000 --directory build/preview/edicao-001
```

## 12. Publicar

```bash
python -m ufabc_science edition publish --edition 1 --by "Seu Nome" --confirm
```

Revalida tudo, fixa a revisão aprovada de cada artigo, muda o estado para `PUBLISHED`, registra
data e responsável, grava `editions/published/edicao-001.json` (registro auditável) e gera o
site público em `dist/` (somente edições `PUBLISHED`/`ARCHIVED`). Para colocar o site no ar,
siga [`GITHUB_SETUP.md`](GITHUB_SETUP.md) (workflow manual "Publicar no GitHub Pages").

```bash
python -m ufabc_science site build                    # regenera dist/ a qualquer momento
python -m ufabc_science edition archive --edition 1   # opcional; continua no arquivo público
```

## Estrutura gerada

```text
dist/
├── index.html                      # edição mais recente, destaques, editorias
├── archive/index.html              # edições publicadas, mais recente primeiro
├── editions/edicao-001/index.html
├── articles/article-13/index.html  # página completa do artigo
└── assets/{css/style.css, js/main.js}
```
