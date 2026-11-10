# UFABC Science — Etapa 4: Fluxo Editorial e Publicação

**Objetivo:** implementar o fluxo de revisão humana por Markdown, gerenciamento de edições semanais, montagem editorial e geração de páginas HTML estáticas.

Leia integralmente `docs/SPECIFICATION.md` e inspecione as implementações das Etapas 1, 2 e 3.

Implemente exclusivamente a Etapa 4.

Não reescreva módulos existentes sem necessidade. Preserve os contratos de dados e as regras de negócio já implementadas.

Antes de modificar arquivos, apresente um plano técnico, identifique incompatibilidades e explique quais modelos ou migrações precisam ser ajustados.

---

# 1. Objetivo funcional

Ao final desta etapa, deverá ser possível:

1. Encontrar rascunhos gerados pela IA.
2. Editar os artigos diretamente em Markdown.
3. Aprovar ou rejeitar artigos por meio de seus arquivos.
4. Validar os arquivos editoriais.
5. Registrar revisões e histórico.
6. Criar uma edição semanal.
7. Selecionar artigos aprovados.
8. Organizar os artigos por editoria.
9. Gerar uma newsletter HTML.
10. Gerar um arquivo histórico das edições.
11. Visualizar a edição localmente antes da publicação.

Nenhum artigo poderá ser publicado sem aprovação humana.

# 2. Arquitetura editorial

Organize os componentes em:

```text
editorial/
├── __init__.py
├── workflow.py
├── markdown.py
├── approval.py
├── edition.py
├── validation.py
└── exceptions.py

publisher/
├── __init__.py
├── html.py
├── assets/
│   ├── css/
│   └── js/
└── templates/
    ├── base.html
    ├── home.html
    ├── newsletter.html
    ├── article.html
    ├── archive.html
    └── components/
        ├── header.html
        ├── footer.html
        └── article_card.html
```

Adapte à estrutura já existente.

# 3. Gerenciamento dos arquivos Markdown

Os arquivos Markdown serão a principal interface editorial.

Diretórios:

```text
data/editorial/
├── pending/
├── approved/
└── rejected/
```

Cada arquivo deverá possuir front matter YAML.

Exemplo:

```markdown
---
article_id: 123
status: pending_review
categories:
  - neurociencia
source_url: "https://example.org/article"
doi: "10.xxxx/example"
peer_review_status: verified
generated_at: "2026-11-09T12:00:00Z"
---

# Título editorial

## Introdução

Texto introdutório.

## O que foi investigado?

Descrição da pesquisa.

## Como foi realizada?

Descrição da metodologia.

## Principais resultados

Resultados.

## Limitações

Limitações do estudo.

## Por que isso importa?

Relevância para a comunidade UFABC.

## Referência

Referência bibliográfica.

[Consultar pesquisa original](https://example.org/article)
```

Utilize uma biblioteca apropriada para leitura e escrita de Markdown com front matter.

Não implemente parsing YAML por expressões regulares.

## 3.1 Regras de leitura

O sistema deverá:

- Identificar arquivos novos.
- Detectar alterações.
- Validar o front matter.
- Identificar o artigo correspondente.
- Verificar se o arquivo pertence ao projeto.
- Detectar arquivos duplicados.
- Preservar conteúdo editorial manual.
- Identificar alterações em artigos já aprovados.
- Registrar a versão do conteúdo.

Não sobrescreva um arquivo que já tenha sido editado manualmente.

Caso a geração de uma nova versão seja solicitada, preserve a anterior.

## 3.2 Estados editoriais

Utilize estados consistentes com a Etapa 3:

- `PENDING_REVIEW`
- `APPROVED`
- `REJECTED`
- `NEEDS_REVISION`

Se já houver enums equivalentes, reutilize-os.

O estado de aprovação deverá ser controlado pelo front matter, mas validado e sincronizado com o banco.

Exemplo:

```yaml
status: approved
```

Rejeição:

```yaml
status: rejected
```

Solicitação de revisão:

```yaml
status: needs_revision
```

## 3.3 Organização dos arquivos

Ao sincronizar os estados:

- Pendente: `data/editorial/pending/`
- Aprovado: `data/editorial/approved/`
- Rejeitado: `data/editorial/rejected/`

Evite movimentações que provoquem perda de histórico.

O sistema deverá manter a relação entre o arquivo, o artigo, suas versões e as revisões editoriais.

## 3.4 Metadados adicionais

Permita incluir:

```yaml
reviewed_at:
reviewer:
editorial_notes:
edition_slug:
```

Não exija informações que não estejam disponíveis.

O campo `reviewer` deverá ser opcional.

# 4. Aprovação editorial

Implemente um serviço de aprovação.

A aprovação deverá verificar:

1. Existência do artigo no banco.
2. Existência de conteúdo editorial.
3. Presença de título.
4. Presença de fonte original.
5. Presença de referência bibliográfica.
6. Categoria válida.
7. Resultado da verificação da Etapa 3.
8. Ausência de erros críticos.
9. Identificação correta de preprints.
10. Integridade do arquivo.

Regras:

- `FAILED` impede aprovação normal.
- `WARNING` permite aprovação com revisão explícita e justificativa.
- `PASSED` permite aprovação, desde que os demais requisitos estejam atendidos.
- Nenhuma aprovação poderá ser realizada automaticamente pela IA.
- Uma alteração posterior em artigo aprovado deverá invalidar a aprovação até nova revisão.

A aprovação deverá gerar um registro em `EditorialReview`.

O sistema deverá preservar a data e o histórico das aprovações.

# 5. Validação editorial

Implemente um validador independente.

Exemplo conceitual:

```python
class EditorialValidationResult:
    valid: bool
    errors: list[str]
    warnings: list[str]
```

Valide:

- Front matter.
- Campos obrigatórios.
- Tipos de dados.
- Categorias.
- URLs.
- DOI.
- Referência.
- Status.
- Integridade do conteúdo.
- Resultado da verificação científica.
- Aprovação humana.
- Duplicidade de inclusão na edição.

Separe erros impeditivos de avisos.

O validador deverá produzir mensagens claras e indicar o arquivo correspondente.

# 6. Gerenciamento das edições

Implemente um serviço para criar e administrar edições semanais.

Cada edição deverá possuir:

- Identificador.
- Número sequencial.
- Título.
- Slug.
- Data inicial.
- Data final.
- Data de publicação.
- Status.
- Introdução editorial.
- Artigos selecionados.
- Ordem de apresentação.

Estados:

- `DRAFT`
- `READY`
- `PUBLISHED`
- `ARCHIVED`

Não permita que uma edição seja publicada se algum artigo selecionado não estiver aprovado.

## 6.1 Criar edição

Comando:

```bash
python -m ufabc_science edition create --week 2026-W46
```

O sistema deverá:

- Identificar o intervalo da semana.
- Criar uma edição em estado `DRAFT`.
- Gerar um identificador.
- Evitar criar edições duplicadas para a mesma semana.
- Não adicionar automaticamente artigos sem aprovação.

## 6.2 Selecionar artigos

Comando:

```bash
python -m ufabc_science edition add --edition 1 --article-id 123
```

Remover:

```bash
python -m ufabc_science edition remove --edition 1 --article-id 123
```

Ordenar:

```bash
python -m ufabc_science edition reorder --edition 1
```

A ordenação poderá ser realizada por arquivo de configuração editorial ou por comandos CLI.

Não implemente painel web.

## 6.3 Introdução editorial

A edição deverá possuir uma introdução geral.

Ela poderá ser escrita manualmente ou gerada como rascunho pela IA, mas deverá passar por aprovação humana.

Sugestão de estrutura:

```markdown
# UFABC Science — Edição 001

Nesta edição, reunimos pesquisas recentes sobre neurociência,
inteligência artificial, engenharia e ciências biológicas.

Confira os principais destaques científicos da semana.
```

Armazene a introdução editorial separadamente dos artigos.

## 6.4 Organização por editoria

A edição deverá agrupar artigos por categorias.

Ordem inicial:

1. Neurociência.
2. Computação e Tecnologia.
3. Engenharias.
4. Ciências Biológicas.
5. Ciências e STEM.

Se um artigo pertencer a mais de uma categoria, evite reproduzir seu conteúdo integral várias vezes.

Escolha uma categoria principal para apresentação e mantenha as demais como categorias secundárias.

A seleção da categoria principal deverá ser editável pelo responsável editorial.

# 7. Publicação HTML

Utilize Jinja2.

Gere páginas estáticas, sem necessidade de servidor backend para visualização.

Diretório de saída:

```text
dist/
├── index.html
├── archive/
│   └── index.html
├── editions/
│   ├── edicao-001/
│   │   └── index.html
│   └── edicao-002/
│       └── index.html
├── articles/
│   └── article-123/
│       └── index.html
└── assets/
    ├── css/
    │   └── style.css
    └── js/
        └── main.js
```

## 7.1 Página inicial

A página inicial deverá apresentar:

- Identidade UFABC Science.
- Descrição breve da iniciativa.
- Edição mais recente.
- Destaques científicos.
- Editorias.
- Acesso ao arquivo de edições.

## 7.2 Página da edição

Cada edição deverá apresentar:

- Número da edição.
- Título.
- Período de referência.
- Introdução editorial.
- Artigos selecionados.
- Categorias.
- Autores.
- Periódicos.
- Datas.
- Links para as pesquisas originais.
- Identificação de preprints.

## 7.3 Página de artigo

Cada artigo deverá possuir página própria com:

- Título editorial.
- Título original.
- Categoria.
- Introdução.
- Contextualização.
- Pergunta de pesquisa.
- Metodologia.
- Resultados.
- Limitações.
- Relevância para UFABC.
- Referência bibliográfica.
- DOI.
- Link para a pesquisa original.

## 7.4 Arquivo de edições

O arquivo deverá listar todas as edições publicadas.

Ordenação:

- Mais recente primeiro.

Não inclua edições em estado `DRAFT` ou `READY` na página pública.

## 7.5 Design

Crie uma identidade visual científica, editorial e acadêmica.

Diretrizes:

- Design minimalista.
- Boa legibilidade.
- Tipografia consistente.
- Hierarquia visual clara.
- Layout responsivo.
- Navegação simples.
- Paleta sóbria.
- Espaçamento adequado.
- Destaque para títulos e categorias.
- Aparência de publicação científica independente, não de portal de notícias sensacionalista.

Não reproduza a identidade visual oficial da UFABC de maneira que sugira endosso institucional.

A marca UFABC Science deverá ser apresentada como iniciativa independente.

Inclua no rodapé:

"UFABC Science é uma iniciativa independente de curadoria e divulgação científica. Não representa oficialmente a Universidade Federal do ABC."

Não dependa de fontes, imagens ou scripts externos para o conteúdo principal.

# 8. Segurança e integridade da publicação

Implemente:

- Escape de conteúdo dinâmico nos templates.
- Sanitização de HTML proveniente de Markdown.
- Validação de URLs.
- Bloqueio de esquemas perigosos, como `javascript:`.
- Proteção contra path traversal.
- Validação de nomes de arquivos.
- Exclusão de conteúdo não aprovado.
- Geração segura de caminhos relativos.

Não permita que conteúdo científico externo seja interpretado como HTML executável.

# 9. CLI

Implemente ou adapte:

```bash
# Sincronizar arquivos Markdown
python -m ufabc_science editorial sync

# Validar arquivos editoriais
python -m ufabc_science editorial validate

# Mostrar artigos pendentes
python -m ufabc_science editorial list --status pending

# Mostrar artigos aprovados
python -m ufabc_science editorial list --status approved

# Criar edição
python -m ufabc_science edition create --week 2026-W46

# Adicionar artigo
python -m ufabc_science edition add --edition 1 --article-id 123

# Remover artigo
python -m ufabc_science edition remove --edition 1 --article-id 123

# Validar edição
python -m ufabc_science edition validate --edition 1

# Gerar HTML para pré-visualização
python -m ufabc_science publish --edition 1

# Mostrar informações da edição
python -m ufabc_science edition show --edition 1
```

Adapte a sintaxe à CLI existente.

## 9.1 Publicação

A geração HTML não deverá alterar automaticamente o estado da edição para `PUBLISHED`.

Implemente um processo explícito de publicação:

```bash
python -m ufabc_science edition publish --edition 1
```

Antes de publicar, verifique novamente:

- Artigos aprovados.
- Integridade dos arquivos.
- Links.
- Categorias.
- Referências.
- Introdução editorial aprovada.
- Ausência de conteúdo bloqueado.

A publicação deverá ser uma operação explícita e auditável.

# 10. Testes

Implemente testes para:

- Parsing do front matter.
- Leitura e escrita Markdown.
- Sincronização de estados.
- Aprovação.
- Rejeição.
- Solicitação de revisão.
- Preservação de versões.
- Detecção de alteração em artigo aprovado.
- Validação editorial.
- Criação de edição.
- Prevenção de edição duplicada.
- Inclusão de artigos.
- Remoção de artigos.
- Ordenação.
- Agrupamento por editoria.
- Bloqueio de artigos não aprovados.
- Geração HTML.
- Geração de arquivo histórico.
- Sanitização HTML.
- Validação de URLs.
- Ausência de drafts na publicação.
- Publicação explícita.

Os testes não poderão depender de internet.

# 11. Critérios de aceitação

A Etapa 4 será considerada concluída quando:

1. O sistema ler arquivos Markdown com front matter.
2. O sistema sincronizar os estados editoriais.
3. A aprovação humana for registrada.
4. A rejeição for registrada.
5. Alterações posteriores invalidarem aprovações anteriores.
6. Conteúdos com `FAILED` forem bloqueados.
7. Conteúdos com `WARNING` exigirem justificativa para aprovação.
8. Edições semanais puderem ser criadas.
9. Artigos puderem ser adicionados, removidos e ordenados.
10. Artigos forem agrupados por editoria.
11. Edições inválidas não puderem ser publicadas.
12. HTML responsivo for gerado.
13. O arquivo histórico funcionar.
14. Edições não publicadas não aparecerem no site público.
15. A publicação exigir ação explícita.
16. Todos os testes passarem.

Execute:

```bash
pytest
ruff check .
ruff format --check .
```

Corrija todos os problemas.

# 12. Documentação

Atualize:

- README.md
- docs/ARCHITECTURE.md
- docs/EDITORIAL_WORKFLOW.md

Crie ou atualize um guia operacional:

`docs/PUBLISHING_GUIDE.md`

Ele deverá explicar:

1. Como encontrar os rascunhos.
2. Como editar um Markdown.
3. Como aprovar um artigo.
4. Como rejeitar um artigo.
5. Como solicitar revisão.
6. Como sincronizar alterações.
7. Como criar uma edição.
8. Como adicionar e ordenar artigos.
9. Como validar uma edição.
10. Como gerar HTML.
11. Como visualizar localmente.
12. Como publicar uma edição.

# 13. Entrega

Ao concluir:

- Liste arquivos criados e modificados.
- Explique o fluxo editorial.
- Apresente um exemplo de Markdown aprovado.
- Apresente uma edição de demonstração.
- Mostre a estrutura HTML gerada.
- Informe os testes executados.
- Informe limitações conhecidas.
- Documente decisões técnicas.

Não avance para a Etapa 5 sem autorização.

**Comece auditando as Etapas 1, 2 e 3. Apresente o plano antes de modificar o código.**