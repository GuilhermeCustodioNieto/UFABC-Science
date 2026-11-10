# Como adicionar uma fonte científica

## Fontes atuais e condições de uso

| Fonte | API | Limites e custos (verifique periodicamente) |
|---|---|---|
| OpenAlex | `api.openalex.org/works` | Uso medido por orçamento diário. Sem chave, o orçamento é compartilhado por IP; uma chave gratuita (`OPENALEX_API_KEY`) dá orçamento próprio. Usamos `select` para reduzir o custo por chamada e no máximo 5 req/s. |
| PubMed | NCBI E-utilities (`esearch`/`efetch`) | 3 req/s sem chave, 10 req/s com `NCBI_API_KEY` (gratuita). Envie `tool` e e-mail. |
| arXiv | `export.arxiv.org/api/query` | 1 requisição a cada 3 s. Resultados sempre `preprint`. |
| Crossref | `api.crossref.org/works` | Pool público com limites dinâmicos (respondeu HTTP 429 em testes com 2 req/s); usamos 1 req/s e `mailto` quando `CONTACT_EMAIL` existe. |

Não presuma que esses termos são permanentes. Antes de ampliar volumes, consulte a
documentação oficial de cada serviço.

## Contrato

```python
class BaseCollector(ABC):
    name: str                 # identificador da fonte (tabela sources)
    base_url: str
    source_type: SourceType   # api | feed
    min_interval: float       # segundos entre requisições
    default_queries: tuple[str, ...]

    def collect(self, query, start_date, end_date) -> CollectionResult: ...
    def _collect_query(self, client, result, query, start_date, end_date, limit)
        -> list[NormalizedArticle]: ...
```

`collect` já trata: várias consultas, limite total (`MAX_ARTICLES_PER_SOURCE`), deduplicação
por `external_id` dentro da coleta, erros por consulta e logs. O cliente `RateLimitedClient`
aplica timeout, retry com backoff exponencial (respeitando `Retry-After`) para 408/425/429/5xx
e erros de rede, e intervalo mínimo — sempre sequencial.

## Passo a passo

1. Crie `src/ufabc_science/collectors/<fonte>.py`:

   ```python
   class MinhaFonteCollector(BaseCollector):
       name = "minhafonte"
       base_url = "https://api.exemplo.org"
       min_interval = 1.0
       default_queries = ("neuroscience",)

       def _collect_query(self, client, result, query, start_date, end_date, limit):
           response = client.get(f"{self.base_url}/search", params={...})
           raw_path = self._save_raw(result, "search", response.content, "json")
           articles = []
           for record in response.json()["items"]:
               data = parse_minhafonte(record, raw_path)  # função pura, testável
               article = self._build(result, data) if data else None
               if article:
                   articles.append(article)
           return articles[:limit]
   ```

2. A função de parsing deve devolver os campos de `NormalizedArticle` e:
   - nunca marcar `peer_review_status=verified` sem evidência de publicação em periódico;
   - identificar preprints explicitamente;
   - limpar HTML (`clean_text`), remover e-mails (`redact_emails`), normalizar DOI/ORCID/idioma;
   - guardar metadados originais relevantes em `source_metadata["<fonte>"]`.
3. Registre em `collectors/__init__.py` (`COLLECTORS`) e em `KNOWN_SOURCES`
   (`config/settings.py`). Se precisar de chave, leia-a em `collector_config` a partir de um
   `SecretStr` em `Settings` — nunca no código.
4. Salve uma resposta real pequena em `tests/fixtures/api/` (remova dados pessoais), adicione
   a rota ao `FakeApis` em `tests/conftest.py` e escreva testes de parsing e de coleta.
5. Habilite com `ENABLED_SOURCES=...,minhafonte` e rode `python -m ufabc_science collect
   --sources minhafonte --limit 5`.

Não faça scraping de páginas HTML: use somente APIs ou feeds oficiais.
