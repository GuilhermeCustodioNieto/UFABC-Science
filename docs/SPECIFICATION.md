# UFABC Science — Especificação Técnica para Claude Code

**Versão:** 1.0  
**Tipo:** Especificação de implementação do MVP  
**Idioma da aplicação e dos conteúdos:** Português brasileiro  
**Frequência editorial:** Semanal  
**Modelo de aprovação:** Arquivos Markdown  
**Modelo de publicação:** HTML estático  
**Restrição financeira:** R$ 0,00 em custos obrigatórios

---

# 1. Instruções gerais para implementação

Você atuará como engenheiro de software responsável pela implementação do **UFABC Science**, uma plataforma automatizada de curadoria e divulgação científica destinada exclusivamente à comunidade da Universidade Federal do ABC (UFABC).

Antes de escrever código:

1. Inspecione o repositório e identifique os arquivos existentes.
2. Verifique se já existe alguma implementação que deva ser preservada.
3. Apresente um plano de implementação dividido em etapas.
4. Identifique decisões técnicas que possam comprometer a arquitetura.
5. Não sobrescreva arquivos existentes sem compreender sua finalidade.

Implemente o projeto de maneira incremental, priorizando código funcional, testes e documentação.

**Regras obrigatórias:**

- Não implemente funcionalidades que não estejam especificadas sem justificar a necessidade.
- Não crie dependências de serviços pagos.
- Não coloque chaves de API diretamente no código.
- Não utilize IA para inventar notícias ou informações científicas.
- Não publique conteúdo sem aprovação humana.
- Não considere um artigo científico verdadeiro apenas porque foi retornado por uma API.
- Não confunda preprints com artigos revisados por pares.
- Não descarte artigos apenas por não serem de instituições famosas.
- Não faça scraping indiscriminado de sites.
- Preserve a origem e a rastreabilidade de todos os dados coletados.
- Prefira soluções simples, testáveis e extensíveis.

Quando uma decisão não estiver especificada, escolha a alternativa mais simples que preserve a arquitetura e documente a decisão.

# 2. Visão geral do produto

O UFABC Science é uma iniciativa independente de curadoria científica que identifica pesquisas recentes, organiza os conteúdos por área do conhecimento e os transforma em materiais de divulgação científica em português.

O sistema deverá descobrir artigos e pesquisas relevantes, coletar seus metadados, remover duplicatas, classificar os conteúdos, avaliar sua relevância editorial e produzir rascunhos para revisão humana.

A publicação final será uma newsletter semanal em HTML, acompanhada de um arquivo histórico das edições anteriores.

## 2.1 Público-alvo

- Estudantes da UFABC.
- Pesquisadores e integrantes de grupos de pesquisa.
- Professores.
- Pessoas interessadas em ciência, tecnologia e inovação.

## 2.2 Editorias

O sistema deverá suportar as seguintes categorias:

1. **Neurociência:** cérebro, cognição, comportamento, neurobiologia, neurotecnologia e saúde neural.
2. **Computação e Tecnologia:** inteligência artificial, ciência de dados, algoritmos, software, segurança, computação quântica e sistemas.
3. **Engenharias:** engenharia de materiais, energia, mecânica, aeroespacial, biomédica, robótica, química e áreas correlatas.
4. **Ciências Biológicas:** genética, biologia molecular, microbiologia, evolução, ecologia, biotecnologia e pesquisas biomédicas.
5. **Ciências e STEM:** física, química, matemática, astronomia, ciências ambientais e pesquisas interdisciplinares.

Um artigo poderá pertencer a mais de uma categoria.

## 2.3 Tipos de conteúdo

Cada edição poderá conter:

- Notícias científicas: apresentação de descobertas e resultados recentes.
- Explicações científicas: contextualização de conceitos necessários para compreender uma pesquisa.
- Síntese de artigos: apresentação dos objetivos, métodos, resultados e limitações de um paper.
- Destaques interdisciplinares: pesquisas que conectam duas ou mais áreas.

# 3. Stack tecnológica

Utilize:

| Camada | Tecnologia |
|---|---|
| Linguagem | Python 3.12 ou versão estável compatível |
| Gerenciamento de dependências | `pyproject.toml` |
| Banco de dados | SQLite |
| ORM | SQLAlchemy 2.x |
| Migrações | Alembic |
| Validação | Pydantic |
| Requisições HTTP | httpx |
| Feeds RSS/Atom | feedparser |
| Templates HTML | Jinja2 |
| Testes | pytest |
| Formatação e lint | Ruff |
| Configurações | pydantic-settings |
| Versionamento | Git e GitHub |
| Automação futura | GitHub Actions |
| Publicação | GitHub Pages ou hospedagem estática gratuita |

Evite adicionar bibliotecas sem necessidade. Pandas não deve ser utilizado como substituto do banco de dados ou do ORM.

A arquitetura deverá permitir substituir o SQLite por PostgreSQL no futuro sem reescrever as regras de negócio.

# 4. Arquitetura

Utilize um **monólito modular orientado a pipeline**.

Não implemente microsserviços.

O processamento deverá seguir esta sequência:

```text
FONTES CIENTÍFICAS
       |
       v
   COLLECTORS
       |
       v
  NORMALIZATION
       |
       v
  DEDUPLICATION
       |
       v
  CLASSIFICATION
       |
       v
  RELEVANCE SCORING
       |
       v
  AI CONTENT GENERATION
       |
       v
   VERIFICATION
       |
       v
  EDITORIAL REVIEW
       |
       v
  MARKDOWN APPROVAL
       |
       v
  HTML GENERATION
       |
       v
   PUBLICATION
```

Cada etapa deverá ter responsabilidades próprias e interfaces bem definidas.

A execução de uma etapa não deverá exigir a execução de todas as anteriores. Por exemplo, deve ser possível gerar novamente um rascunho sem coletar novamente os artigos.

# 5. Estrutura de diretórios

Implemente a seguinte estrutura:

```text
ufabc-science/
│
├── src/
│   └── ufabc_science/
│       ├── __init__.py
│       ├── main.py
│       ├── cli.py
│       │
│       ├── config/
│       │   ├── settings.py
│       │   └── logging.py
│       │
│       ├── domain/
│       │   ├── models.py
│       │   ├── enums.py
│       │   └── schemas.py
│       │
│       ├── collectors/
│       │   ├── base.py
│       │   ├── openalex.py
│       │   ├── pubmed.py
│       │   ├── arxiv.py
│       │   └── crossref.py
│       │
│       ├── processing/
│       │   ├── normalization.py
│       │   ├── deduplication.py
│       │   ├── classification.py
│       │   └── relevance.py
│       │
│       ├── intelligence/
│       │   ├── base.py
│       │   ├── provider.py
│       │   ├── prompts.py
│       │   ├── generation.py
│       │   └── verification.py
│       │
│       ├── editorial/
│       │   ├── workflow.py
│       │   ├── markdown.py
│       │   ├── approval.py
│       │   └── edition.py
│       │
│       ├── publisher/
│       │   ├── html.py
│       │   └── templates/
│       │       ├── base.html
│       │       ├── newsletter.html
│       │       └── article.html
│       │
│       └── infrastructure/
│           ├── database.py
│           ├── repositories/
│           └── migrations/
│
├── data/
│   ├── raw/
│   ├── exports/
│   ├── editorial/
│   │   ├── pending/
│   │   ├── approved/
│   │   └── rejected/
│   └── database/
│
├── editions/
│   ├── drafts/
│   └── published/
│
├── scripts/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│
├── .github/
│   └── workflows/
│
├── .env.example
├── .gitignore
├── alembic.ini
├── pyproject.toml
└── README.md
```

A estrutura poderá ser ajustada quando necessário, mas preserve a separação de responsabilidades.

# 6. Fontes científicas

Implemente coletores independentes. Cada coletor deverá implementar uma interface comum.

Fontes iniciais:

## 6.1 OpenAlex

Documentação: https://docs.openalex.org/

Utilização:

- Descoberta de artigos científicos.
- Identificação de autores e instituições.
- Recuperação de DOI.
- Recuperação de periódico e data de publicação.
- Consulta por temas, conceitos e palavras-chave.

É uma das principais fontes de descoberta do projeto.

## 6.2 PubMed

Documentação: https://www.ncbi.nlm.nih.gov/books/NBK25501/

Utilização:

- Neurociência.
- Ciências biológicas.
- Biomedicina.
- Genética.
- Pesquisas relacionadas à saúde.

Utilize a API oficial NCBI E-utilities.

## 6.3 arXiv

Documentação: https://info.arxiv.org/help/api/index.html

Utilização:

- Inteligência artificial.
- Computação.
- Matemática.
- Física.
- Engenharia.

Identifique explicitamente os resultados como preprints quando ainda não houver confirmação de publicação revisada por pares.

## 6.4 Crossref

Documentação: https://www.crossref.org/documentation/retrieve-metadata/rest-api/

Utilização:

- Complementação de metadados.
- Identificação de DOI.
- Recuperação de informações bibliográficas.
- Verificação de publicação.

## 6.5 Interface comum dos coletores

Cada coletor deverá oferecer uma operação equivalente a:

```python
class BaseCollector:
    def collect(self, query, start_date, end_date):
        raise NotImplementedError
```

Utilize modelos Pydantic para normalizar as respostas.

Todos os coletores devem retornar a mesma estrutura interna, independentemente da API de origem.

Requisitos:

- Timeout configurável.
- Tratamento de erros HTTP.
- Retry com backoff para falhas transitórias.
- Respeito aos limites de requisições.
- Identificação da fonte.
- Logs de execução.
- Persistência dos dados brutos quando possível.
- Execuções idempotentes.

Não faça chamadas simultâneas ilimitadas às APIs.

# 7. Modelo de dados

Implemente o banco com SQLAlchemy 2.x e migrações Alembic.

O banco deverá conter, no mínimo, as seguintes entidades:

## 7.1 Article

Representa um artigo ou pesquisa científica.

Campos:

- id
- title
- abstract
- doi
- external_id
- canonical_url
- publication_date
- collected_at
- journal
- publisher
- authors
- institutions
- article_type
- peer_review_status
- open_access
- language
- source_metadata
- raw_data_path
- created_at
- updated_at

O DOI deverá ser normalizado e único quando estiver disponível.

Quando não houver DOI, utilize identificadores externos e regras de deduplicação alternativas.

## 7.2 Source

Representa uma fonte de dados.

Campos:

- id
- name
- base_url
- source_type
- active
- created_at

## 7.3 ArticleSource

Relaciona artigos às fontes de origem.

Campos:

- id
- article_id
- source_id
- external_id
- original_url
- collected_at

Um mesmo artigo poderá ter sido encontrado em várias fontes.

## 7.4 Category

Representa as editorias.

Campos:

- id
- name
- slug
- description
- active

## 7.5 ArticleCategory

Relacionamento N:N entre artigos e categorias.

Campos:

- article_id
- category_id
- confidence
- classification_method

## 7.6 RelevanceAssessment

Armazena avaliações de relevância.

Campos:

- id
- article_id
- scientific_relevance
- originality
- potential_impact
- interdisciplinarity
- ufabc_interest
- final_score
- justification
- assessed_at

## 7.7 GeneratedContent

Armazena os conteúdos gerados pela IA.

Campos:

- id
- article_id
- version
- headline
- introduction
- context
- research_question
- methodology
- findings
- limitations
- relevance
- complete_content
- model_provider
- model_name
- prompt_version
- generated_at

## 7.8 EditorialReview

Registra a revisão humana.

Campos:

- id
- article_id
- status
- reviewer
- comments
- reviewed_at

## 7.9 NewsletterEdition

Representa uma edição semanal.

Campos:

- id
- title
- slug
- edition_number
- start_date
- end_date
- status
- created_at
- published_at

## 7.10 NewsletterItem

Relaciona os artigos selecionados a uma edição.

Campos:

- id
- edition_id
- article_id
- position
- editorial_section

## 7.11 Regras gerais do banco

- Use chaves estrangeiras.
- Defina índices para DOI, datas, status e identificadores externos.
- Utilize transações nas operações que alteram múltiplas entidades.
- Não armazene a mesma informação em várias tabelas sem justificativa.
- Preserve o histórico de versões dos conteúdos gerados.
- Não exclua artigos automaticamente quando forem rejeitados editorialmente.
- Utilize timestamps em UTC no armazenamento e converta para o horário de São Paulo na apresentação.

# 8. Coleta e normalização

O sistema deverá permitir definir um intervalo de datas para a coleta.

Exemplo:

```bash
python -m ufabc_science collect --days 7
```

O processo deverá:

1. Consultar as fontes habilitadas.
2. Recuperar artigos publicados dentro do período.
3. Salvar respostas brutas em `data/raw/`.
4. Normalizar metadados.
5. Validar os registros.
6. Persistir os artigos.
7. Registrar a fonte de cada artigo.
8. Informar quantos registros foram coletados, inseridos, atualizados e ignorados.

A coleta deverá ser incremental.

## 8.1 Deduplicação

Implemente a seguinte ordem de prioridade:

1. DOI normalizado.
2. Identificador externo associado à fonte.
3. URL canônica normalizada.
4. Comparação de títulos normalizados como fallback.

A comparação de títulos deverá considerar similaridade textual, mas não poderá excluir automaticamente artigos apenas porque possuem títulos parecidos.

Quando houver dúvida, mantenha os registros e sinalize uma possível duplicidade para análise.

# 9. Classificação científica

Cada artigo deverá receber uma ou mais categorias.

A classificação poderá combinar:

- Palavras-chave.
- Conceitos.
- Abstract.
- Título.
- Metadados das fontes.
- Classificação assistida por IA.

Implemente primeiro uma classificação determinística baseada em palavras-chave e regras configuráveis.

A IA poderá complementar essa classificação posteriormente.

Cada classificação deverá registrar:

- Categoria.
- Confiança.
- Método utilizado.
- Justificativa.

Não force um artigo a pertencer a uma categoria quando não houver evidência suficiente.

# 10. Sistema de relevância editorial

Implemente uma pontuação entre 0 e 100.

| Critério | Peso |
|---|---:|
| Relevância científica | 30% |
| Originalidade | 20% |
| Impacto potencial | 20% |
| Interdisciplinaridade | 15% |
| Interesse para estudantes da UFABC | 15% |

Fórmula:

```python
score = (
    scientific_relevance * 0.30
    + originality * 0.20
    + potential_impact * 0.20
    + interdisciplinarity * 0.15
    + ufabc_interest * 0.15
)
```

Cada critério deverá ser avaliado em uma escala de 0 a 100.

A pontuação representa uma prioridade editorial, não uma avaliação definitiva da qualidade científica.

O sistema deverá salvar a justificativa de cada nota.

Não utilize quantidade de citações, prestígio institucional ou fator de impacto como substitutos automáticos da qualidade científica.

# 11. Camada de inteligência artificial

A geração de conteúdo deverá ser independente do provedor de IA.

Implemente uma interface semelhante a:

```python
from abc import ABC, abstractmethod

class AIProvider(ABC):

    @abstractmethod
    def generate(self, prompt: str) -> str:
        pass
```

O sistema deverá permitir adicionar ou substituir provedores sem alterar a lógica editorial.

Comece com uma implementação mock para testes e desenvolvimento.

Depois, implemente um adaptador para um provedor configurável por variáveis de ambiente. A integração com serviços externos deverá ser opcional.

Não assuma que um serviço possui plano gratuito permanente. Antes de integrar um provedor, documente suas condições, limites e eventuais custos.

## 11.1 Conteúdo que a IA deverá gerar

Para cada artigo selecionado:

1. Título editorial.
2. Introdução.
3. Contextualização científica.
4. Pergunta de pesquisa.
5. Metodologia.
6. Principais resultados.
7. Limitações.
8. Relevância para o público UFABC.
9. Referência bibliográfica.
10. Link para a fonte original.

A linguagem deverá ser acessível a estudantes universitários de diferentes cursos, sem perder precisão científica.

Evite exageros, sensacionalismo e afirmações causais que não estejam sustentadas pelo estudo.

## 11.2 Restrições da geração

A IA não poderá:

- Inventar resultados.
- Inventar números ou estatísticas.
- Inventar autores ou instituições.
- Alterar conclusões.
- Apresentar hipóteses como fatos.
- Omitir limitações importantes.
- Apresentar preprints como pesquisas revisadas por pares.
- Criar links ou DOIs inexistentes.

Se não houver abstract ou texto acessível suficiente, o sistema deverá gerar um aviso de insuficiência de informação, em vez de produzir uma notícia especulativa.

A IA deverá receber os dados científicos coletados como contexto. Não deverá pesquisar ou criar fatos independentemente da fonte registrada.

## 11.3 Prompt editorial

Mantenha os prompts em arquivos separados ou em um módulo versionado.

O prompt deverá instruir o modelo a:

- Utilizar exclusivamente as informações fornecidas.
- Diferenciar resultados, hipóteses e interpretações.
- Preservar valores e unidades.
- Explicar termos técnicos.
- Declarar limitações.
- Informar quando uma informação não estiver disponível.
- Não criar citações bibliográficas.
- Retornar uma estrutura JSON validável.

Valide a saída com Pydantic antes de persistir.

# 12. Verificação de conteúdo

Implemente uma camada de verificação determinística antes da aprovação editorial.

Verificações mínimas:

- O DOI está presente e bem formatado, quando aplicável?
- O link original está disponível?
- O título corresponde ao registro coletado?
- Os autores correspondem aos metadados?
- A data está disponível?
- O tipo de publicação foi identificado?
- O conteúdo contém resultados que não aparecem no abstract ou material de origem?
- Há números ou estatísticas sem correspondência com os dados fornecidos?
- As limitações foram preservadas?
- O artigo está corretamente identificado como preprint, quando aplicável?

A verificação automatizada não comprova a veracidade científica do artigo. Ela apenas identifica inconsistências e problemas que exigem revisão.

O resultado deverá conter:

- `PASSED`
- `WARNING`
- `FAILED`

Um conteúdo com `FAILED` não poderá seguir automaticamente para aprovação.

# 13. Fluxo editorial com Markdown

Esta é uma decisão central do projeto.

**Não implemente painel administrativo no MVP.**

Os arquivos Markdown serão a interface principal entre o sistema automatizado e o editor humano.

O fluxo deverá funcionar assim:

1. O sistema coleta e processa artigos.
2. A IA gera os rascunhos.
3. O sistema cria um arquivo Markdown por artigo.
4. O editor abre o arquivo em seu editor de texto.
5. O editor revisa, modifica e aprova o conteúdo.
6. O sistema lê os arquivos aprovados.
7. O sistema monta a edição semanal.
8. O sistema gera o HTML final.

## 13.1 Estrutura do Markdown

Exemplo de arquivo:

`data/editorial/pending/article-123.md`

```markdown
---
article_id: 123
status: pending_review
categories:
  - neurociencia
  - ciencias-biologicas
source_url: "https://example.org/article"
doi: "10.xxxx/example"
peer_review_status: verified
generated_at: "2026-11-09T12:00:00Z"
---

# Título editorial

## Introdução

Texto de apresentação.

## O que foi investigado?

Descrição da pergunta científica.

## Como a pesquisa foi realizada?

Descrição da metodologia.

## Principais resultados

Síntese dos resultados.

## Limitações

Limitações identificadas no estudo.

## Por que isso importa?

Contextualização para a comunidade UFABC.

## Referência

Autores. Título original. Periódico. Ano.

[Consultar pesquisa original](https://example.org/article)
```

O sistema deverá preservar o front matter e validar os campos obrigatórios.

## 13.2 Aprovação

A aprovação será feita alterando o status no front matter:

```yaml
status: approved
```

Rejeição:

```yaml
status: rejected
```

O sistema deverá:

- Detectar arquivos novos e modificados.
- Validar o conteúdo.
- Atualizar o estado no banco.
- Preservar versões anteriores.
- Impedir publicação de artigos sem aprovação.
- Registrar a data da aprovação.
- Registrar comentários editoriais quando disponíveis.

Não confie apenas no status armazenado no banco: o arquivo Markdown aprovado também deverá ser validado no momento da publicação.

## 13.3 Montagem da edição

O sistema deverá permitir criar uma edição semanal com artigos aprovados.

Exemplo:

```bash
python -m ufabc_science edition create --week 2026-W46
```

Deverá ser possível selecionar os artigos e definir sua ordem.

A edição deverá possuir:

- Número.
- Título.
- Período de referência.
- Introdução editorial.
- Seções por categoria.
- Artigos selecionados.
- Data de publicação.

A introdução editorial poderá ser gerada como rascunho, mas também deverá passar por aprovação humana.

# 14. Publicação HTML

O sistema deverá transformar uma edição aprovada em um site estático.

O HTML deverá:

- Ser responsivo.
- Ter boa legibilidade em dispositivos móveis.
- Utilizar semântica HTML.
- Ter navegação simples.
- Exibir categorias.
- Exibir autores e fontes.
- Exibir DOI quando disponível.
- Distinguir preprints de artigos revisados por pares.
- Incluir links para os trabalhos originais.
- Ter uma página de arquivo com edições anteriores.

Utilize Jinja2 para templates.

Estrutura de saída:

```text
dist/
├── index.html
├── archive/
│   ├── index.html
│   └── edicao-001.html
├── articles/
└── assets/
    ├── css/
    ├── js/
    └── images/
```

A geração deverá ser determinística: executar novamente com os mesmos dados e templates deverá produzir resultados equivalentes.

Não dependa de JavaScript para exibir o conteúdo principal.

Não utilize imagens protegidas por direitos autorais sem autorização. Priorize imagens de domínio público, licenças compatíveis ou ausência de imagem.

# 15. CLI — Interface de linha de comando

Implemente uma CLI com os seguintes comandos:

```bash
# Inicializar o banco
python -m ufabc_science init-db

# Coletar pesquisas dos últimos sete dias
python -m ufabc_science collect --days 7

# Processar artigos coletados
python -m ufabc_science process

# Classificar artigos
python -m ufabc_science classify

# Calcular relevância
python -m ufabc_science score

# Gerar rascunhos
python -m ufabc_science generate

# Validar rascunhos e aprovações
python -m ufabc_science editorial validate

# Criar edição semanal
python -m ufabc_science edition create --week 2026-W46

# Gerar HTML
python -m ufabc_science publish --edition 1

# Executar pipeline completo até a geração dos rascunhos
python -m ufabc_science run --days 7
```

O comando `run` não poderá aprovar ou publicar automaticamente nenhum conteúdo.

Todos os comandos deverão possuir:

- Código de saída adequado.
- Logs legíveis.
- Mensagens de erro claras.
- Opções de configuração.
- Proteção contra duplicação de operações.

# 16. Configuração e variáveis de ambiente

Utilize `.env.example`:

```env
APP_ENV=development
DATABASE_URL=sqlite:///data/database/ufabc_science.db

LOG_LEVEL=INFO

AI_PROVIDER=mock
AI_API_KEY=
AI_MODEL=

OPENALEX_EMAIL=
NCBI_API_KEY=

COLLECTION_DAYS=7
MAX_ARTICLES_PER_SOURCE=100

EDITORIAL_LANGUAGE=pt-BR
TIMEZONE=America/Sao_Paulo
```

Não versione o arquivo `.env`.

Variáveis não configuradas deverão utilizar valores seguros ou desabilitar a integração correspondente.

O projeto deverá funcionar em modo de desenvolvimento sem nenhuma chave de IA.

# 17. Testes

Implemente testes unitários e de integração.

Cobertura mínima de regras críticas:

- Normalização de DOI.
- Deduplicação.
- Persistência de artigos.
- Classificação.
- Cálculo de relevância.
- Validação de conteúdo gerado.
- Identificação de preprints.
- Aprovação por Markdown.
- Bloqueio de publicação de conteúdo não aprovado.
- Geração de HTML.
- Idempotência do pipeline.

Utilize respostas mockadas das APIs para os testes.

Os testes não deverão depender de acesso à internet ou de chaves externas.

Execute:

```bash
pytest
ruff check .
ruff format --check .
```

Corrija os erros antes de considerar uma etapa concluída.

# 18. Automação e execução gratuita

A primeira versão deverá funcionar localmente.

Posteriormente, configure GitHub Actions para executar a coleta semanal.

A automação deverá:

1. Executar a coleta.
2. Processar os artigos.
3. Gerar rascunhos, caso exista um provedor de IA configurado.
4. Salvar os resultados em artefatos ou em um fluxo de trabalho apropriado.
5. Nunca aprovar ou publicar automaticamente.

Não configure a automação para fazer commits automáticos indiscriminadamente.

Considere que GitHub Actions possui limites de uso e que a disponibilidade de recursos gratuitos depende das condições da conta e do repositório.

A publicação por GitHub Pages poderá ser implementada depois que o processo editorial estiver validado.

# 19. Política editorial e integridade científica

O UFABC Science deve ser uma iniciativa de divulgação científica, não um agregador automático de manchetes.

Regras:

- Priorizar pesquisas recentes e relevantes.
- Valorizar interdisciplinaridade.
- Considerar pesquisas de diferentes instituições e países.
- Não privilegiar exclusivamente universidades de elite.
- Não utilizar popularidade como sinônimo de qualidade.
- Não exagerar resultados preliminares.
- Distinguir correlação de causalidade.
- Explicar limitações metodológicas.
- Preservar links e referências.
- Informar quando o trabalho não passou por revisão por pares.
- Não transformar pesquisas científicas em aconselhamento médico ou clínico.

A seleção editorial deverá considerar interesse para estudantes da UFABC, mas não deverá se limitar a pesquisas produzidas pela própria universidade.

# 20. Etapas obrigatórias de implementação

Implemente o projeto nas seguintes etapas:

## Etapa 1 — Fundação

- Configuração do projeto Python.
- Estrutura de diretórios.
- Configurações.
- Banco SQLite.
- SQLAlchemy.
- Alembic.
- Entidades principais.
- Testes iniciais.
- README.

**Critério de conclusão:** projeto inicializa, cria o banco e executa os testes.

## Etapa 2 — Coletores

- Interface comum.
- OpenAlex.
- PubMed.
- arXiv.
- Crossref.
- Normalização.
- Persistência.
- Deduplicação.
- Logs.

**Critério de conclusão:** o sistema coleta artigos reais e os armazena sem duplicações indevidas.

## Etapa 3 — Inteligência editorial

- Classificação.
- Sistema de relevância.
- Interface de IA.
- Implementação mock.
- Adaptador de provedor configurável.
- Geração de conteúdo.
- Verificação.

**Critério de conclusão:** o sistema consegue gerar rascunhos estruturados e validáveis a partir de artigos coletados.

## Etapa 4 — Editorial e publicação

- Exportação Markdown.
- Aprovação e rejeição.
- Validação editorial.
- Criação de edição.
- Templates Jinja2.
- Geração HTML.
- Arquivo de edições.

**Critério de conclusão:** é possível revisar um artigo em Markdown, aprová-lo e gerar uma edição HTML estática.

## Etapa 5 — Automação

- Pipeline completo.
- Comando `run`.
- GitHub Actions.
- Documentação operacional.
- Testes de integração.
- Revisão de segurança.

**Critério de conclusão:** o fluxo semanal pode ser executado com custo obrigatório zero e sem intervenção manual na coleta, mantendo a aprovação editorial humana.

# 21. Critérios de aceitação do MVP

O MVP somente será considerado funcional quando:

1. Conseguir coletar artigos de pelo menos duas fontes científicas.
2. Normalizar os metadados para uma estrutura única.
3. Identificar duplicatas sem eliminar artigos indevidamente.
4. Classificar artigos nas editorias previstas.
5. Calcular e persistir a relevância editorial.
6. Gerar rascunhos em português.
7. Preservar a referência científica original.
8. Identificar preprints.
9. Exportar artigos em Markdown.
10. Permitir aprovação e rejeição pelo arquivo.
11. Impedir publicação de artigos não aprovados.
12. Gerar HTML estático responsivo.
13. Preservar o histórico das edições.
14. Executar os testes sem serviços externos.
15. Funcionar sem uma chave de IA configurada, utilizando o modo mock para desenvolvimento.

# 22. Documentação obrigatória

O README deverá explicar:

- O que é o UFABC Science.
- Objetivo e escopo do MVP.
- Arquitetura.
- Tecnologias.
- Como instalar Python e dependências.
- Como configurar o `.env`.
- Como inicializar o banco.
- Como executar cada comando.
- Como adicionar uma fonte.
- Como configurar um provedor de IA.
- Como revisar os arquivos Markdown.
- Como aprovar uma notícia.
- Como criar uma edição.
- Como gerar o HTML.
- Como executar os testes.
- Limitações conhecidas.

Crie também:

- `docs/ARCHITECTURE.md`
- `docs/DATABASE.md`
- `docs/EDITORIAL_WORKFLOW.md`
- `docs/ADDING_SOURCES.md`
- `docs/AI_PROVIDERS.md`

# 23. Forma de trabalho do Claude Code

Não tente implementar as cinco etapas em uma única alteração extensa.

Siga este procedimento:

1. Analise o repositório.
2. Apresente o plano da etapa atual.
3. Implemente apenas a etapa atual.
4. Execute testes.
5. Corrija erros.
6. Atualize a documentação.
7. Liste arquivos criados e modificados.
8. Informe comandos para validar manualmente.
9. Apresente limitações e decisões pendentes.
10. Aguarde autorização antes de avançar para a próxima etapa.

Não declare uma funcionalidade concluída apenas porque seus arquivos foram criados. Ela precisa estar implementada, integrada e testada.

**Comece pela Etapa 1 — Fundação.**

Antes de implementar, apresente a arquitetura proposta, o modelo inicial de dados e o plano de arquivos da Etapa 1. Depois, implemente essa etapa e valide sua execução.