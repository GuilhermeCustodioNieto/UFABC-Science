# UFABC Science — Etapa 2: Coletores Científicos

Leia integralmente `docs/SPECIFICATION.md` e inspecione a implementação concluída na Etapa 1.

Agora implemente exclusivamente a **Etapa 2 — Coletores**, respeitando a arquitetura, os modelos e as decisões já existentes no projeto.

Não reimplemente componentes da Etapa 1 sem necessidade. Não modifique contratos existentes sem justificar e documentar a alteração.

## 1. Objetivo

Implementar um sistema de coleta de artigos científicos de quatro fontes:

1. OpenAlex
2. PubMed
3. arXiv
4. Crossref

Os resultados deverão ser convertidos para uma estrutura interna padronizada e persistidos no banco SQLite.

O sistema deverá identificar duplicatas, preservar a origem dos registros e permitir novas execuções sem criar registros repetidos.

## 2. Primeiro: auditoria da Etapa 1

Antes de escrever código:

- Inspecione os modelos SQLAlchemy.
- Inspecione os repositórios existentes.
- Verifique a configuração do banco.
- Verifique as migrações.
- Verifique os testes.
- Identifique quais entidades já existem e quais precisam de ajustes.

Apresente um plano de implementação antes de modificar arquivos.

Não crie modelos duplicados caso já existam equivalentes.

## 3. Interface dos coletores

Implemente uma interface comum para todos os coletores.

Exemplo conceitual:

```python
from abc import ABC, abstractmethod
from datetime import date

class BaseCollector(ABC):

    @abstractmethod
    def collect(
        self,
        query: str,
        start_date: date,
        end_date: date
    ) -> list:
        pass
```

A implementação final deverá utilizar os schemas Pydantic já existentes no projeto, quando disponíveis.

Cada coletor deverá retornar uma coleção de artigos normalizados, não respostas brutas específicas da API.

Também deverá existir uma estrutura de resultado da execução contendo:

- Nome da fonte.
- Quantidade de registros encontrados.
- Quantidade de registros válidos.
- Quantidade de registros persistidos.
- Quantidade de duplicatas identificadas.
- Quantidade de erros.
- Duração da execução.
- Mensagens de erro, quando existirem.

## 4. Modelo interno normalizado

Todos os coletores deverão produzir uma estrutura equivalente a:

```python
{
    "title": str,
    "abstract": str | None,
    "doi": str | None,
    "external_id": str | None,
    "canonical_url": str | None,
    "publication_date": date | None,
    "journal": str | None,
    "publisher": str | None,
    "authors": list,
    "institutions": list,
    "article_type": str | None,
    "peer_review_status": str,
    "open_access": bool | None,
    "language": str | None,
    "source_name": str,
    "source_metadata": dict
}
```

Ajuste os campos de acordo com os modelos reais da Etapa 1.

Requisitos:

- Não inventar valores ausentes.
- Diferenciar dados desconhecidos de valores falsos.
- Preservar os identificadores originais.
- Normalizar DOI e URLs.
- Preservar os metadados específicos de cada fonte quando relevantes.
- Evitar armazenar respostas completas redundantes no banco.

## 5. Implementação dos coletores

### 5.1 OpenAlex

Documentação:

https://docs.openalex.org/

Implemente:

- Pesquisa por palavras-chave.
- Filtro por intervalo de publicação.
- Paginação.
- Limite configurável de resultados.
- Recuperação de título, abstract, DOI, autores, instituições, periódico e acesso aberto.
- Identificação da fonte.

Utilize a API oficial.

Não dependa exclusivamente de uma única consulta genérica. O coletor deverá aceitar consultas configuráveis por editoria.

Exemplos de temas:

- Neuroscience
- Artificial intelligence
- Computer science
- Robotics
- Materials science
- Biotechnology
- Evolutionary biology
- Physics
- Mathematics
- Engineering

Evite realizar dezenas de consultas redundantes sem necessidade.

### 5.2 PubMed

Documentação:

https://www.ncbi.nlm.nih.gov/books/NBK25501/

Utilize NCBI E-utilities.

Implemente:

- ESearch para descobrir identificadores.
- EFetch para recuperar os registros.
- Consulta por data.
- Paginação.
- Recuperação de título, abstract, autores, periódico, DOI e data.
- Identificação de artigos relacionados à neurociência e ciências biológicas.

A chave NCBI deverá ser opcional.

Respeite os limites oficiais de requisições.

Não classifique automaticamente todos os registros do PubMed como artigos revisados por pares sem evidência suficiente.

### 5.3 arXiv

Documentação:

https://info.arxiv.org/help/api/index.html

Implemente:

- Consulta por palavras-chave.
- Filtro temporal.
- Paginação.
- Recuperação de título, abstract, autores, categorias, identificador e URL.
- Identificação explícita como preprint quando não houver confirmação de publicação revisada por pares.

Categorias prioritárias:

- cs.AI
- cs.LG
- cs.CV
- cs.CL
- cs.SE
- cs.RO
- math.*
- physics.*
- q-bio.*

Não classifique um trabalho como revisado por pares apenas por estar disponível no arXiv.

### 5.4 Crossref

Documentação:

https://www.crossref.org/documentation/retrieve-metadata/rest-api/

Implemente:

- Pesquisa bibliográfica.
- Filtro por data.
- Paginação.
- Recuperação de DOI, título, autores, periódico, editora, data e URL.
- Complementação de metadados de registros já existentes.

O Crossref não deve ser tratado como uma fonte de abstract completo quando esse dado não estiver disponível.

Priorize o enriquecimento de artigos identificados por DOI.

## 6. Normalização

Implemente funções independentes:

```python
normalize_doi()
normalize_url()
normalize_title()
normalize_publication_date()
normalize_authors()
normalize_abstract()
```

Requisitos:

- Remover prefixos desnecessários de DOI, como `https://doi.org/`.
- Converter DOI para formato canônico em minúsculas.
- Remover parâmetros de rastreamento de URLs quando seguro.
- Normalizar espaços e caracteres em títulos.
- Tratar datas incompletas sem inventar dia ou mês.
- Tratar nomes de autores sem presumir a ordem quando a fonte não fornecer essa informação.
- Converter abstracts estruturados para texto legível, preservando o conteúdo.

A normalização deverá ser testada isoladamente.

## 7. Deduplicação

Implemente a seguinte prioridade:

1. DOI normalizado.
2. Identificador externo associado à fonte.
3. URL canônica.
4. Similaridade de títulos.

Regras:

- DOI igual representa forte evidência de identidade.
- Identificadores externos devem ser interpretados dentro do contexto da respectiva fonte.
- Títulos semelhantes não significam necessariamente o mesmo artigo.
- A similaridade de títulos deve gerar candidatos a duplicata, não exclusões automáticas quando houver ambiguidade.
- Registros encontrados em fontes diferentes deverão compartilhar o mesmo Article, mantendo suas relações ArticleSource.
- A operação deve ser transacional.

Implemente uma estratégia segura para concorrência e reexecução.

Não crie um sistema complexo de resolução de entidades nesta etapa.

## 8. Persistência

Utilize os repositórios e modelos da Etapa 1.

O fluxo deverá ser:

```text
API
 |
 v
Resposta bruta
 |
 v
Validação
 |
 v
Normalização
 |
 v
Identificação de duplicatas
 |
 v
Persistência de Article
 |
 v
Persistência de ArticleSource
 |
 v
Resultado da execução
```

Preserve os registros brutos em `data/raw/`, preferencialmente em JSON organizado por fonte e data de coleta.

A persistência deverá:

- Utilizar transações.
- Evitar duplicações.
- Preservar artigos existentes.
- Atualizar apenas metadados quando houver informação nova ou mais completa.
- Não substituir dados melhores por valores ausentes ou menos completos.
- Registrar a origem de cada informação.
- Não apagar dados manualmente editados.

## 9. Configuração

Utilize as configurações já existentes.

Se necessário, adicione:

```env
OPENALEX_EMAIL=
NCBI_API_KEY=

MAX_ARTICLES_PER_SOURCE=100
REQUEST_TIMEOUT=30
REQUEST_MAX_RETRIES=3
REQUEST_BACKOFF_FACTOR=2
```

Nenhuma chave poderá ser obrigatória para executar o projeto.

Não coloque credenciais nos arquivos versionados.

## 10. CLI

Implemente ou adapte os comandos:

```bash
# Coletar de todas as fontes habilitadas
python -m ufabc_science collect --days 7

# Coletar somente do OpenAlex
python -m ufabc_science collect --source openalex --days 7

# Coletar somente do PubMed
python -m ufabc_science collect --source pubmed --days 7

# Coletar somente do arXiv
python -m ufabc_science collect --source arxiv --days 7

# Coletar somente do Crossref
python -m ufabc_science collect --source crossref --days 7

# Consultar limite de artigos
python -m ufabc_science collect --days 7 --limit 50
```

A sintaxe poderá ser adaptada à CLI existente, desde que preserve essas funcionalidades.

O comando deverá apresentar um resumo final por fonte.

Exemplo:

```text
UFABC SCIENCE — COLLECTION REPORT

OpenAlex
  Encontrados: 120
  Válidos: 115
  Novos artigos: 90
  Duplicatas: 25
  Erros: 0

PubMed
  Encontrados: 40
  Válidos: 38
  Novos artigos: 30
  Duplicatas: 8
  Erros: 0

Total
  Novos artigos: 120
  Duplicatas: 33
  Erros: 0
```

Os números são ilustrativos. Não os utilize como valores fixos.

## 11. Testes

Crie testes unitários e de integração para:

- Cada coletor.
- Respostas vazias.
- Respostas incompletas.
- Respostas inválidas.
- Erros HTTP.
- Timeout.
- Retry.
- Paginação.
- Normalização de DOI.
- Normalização de URL.
- Normalização de datas.
- Normalização de autores.
- Deduplicação por DOI.
- Deduplicação por identificador externo.
- Candidatos a duplicatas por título.
- Artigo encontrado em fontes diferentes.
- Persistência idempotente.
- Atualização de metadados.
- Preservação de dados existentes.

Use fixtures JSON representativas das APIs.

Os testes não poderão depender de internet, credenciais ou serviços externos.

## 12. Critérios de conclusão

A Etapa 2 só poderá ser considerada concluída quando:

1. Os quatro coletores estiverem implementados.
2. Todos retornarem a estrutura normalizada.
3. A coleta aceitar intervalos de datas.
4. A paginação funcionar.
5. Os registros forem persistidos corretamente.
6. Artigos encontrados em fontes diferentes forem associados adequadamente.
7. A deduplicação não eliminar artigos apenas por semelhança superficial.
8. Os dados brutos forem preservados.
9. A execução for idempotente.
10. A CLI permitir selecionar fontes.
11. Os testes funcionarem sem internet.
12. A documentação estiver atualizada.

Execute:

```bash
pytest
ruff check .
ruff format --check .
```

Corrija todos os problemas encontrados.

## 13. Entrega

Ao terminar:

- Liste os arquivos criados e modificados.
- Explique a arquitetura dos coletores.
- Apresente o esquema de normalização.
- Explique a estratégia de deduplicação.
- Mostre como executar cada coletor.
- Apresente os resultados dos testes.
- Informe limitações conhecidas.
- Documente decisões técnicas.
- Não avance para a Etapa 3 sem autorização.

**Comece auditando a Etapa 1 e apresente o plano de implementação antes de modificar o código.**