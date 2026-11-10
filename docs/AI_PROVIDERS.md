# Provedores de IA

A lógica editorial depende apenas da interface `AIProvider`
(`src/ufabc_science/intelligence/base.py`):

```python
class AIProvider(ABC):
    name: str
    model: str | None
    def generate_structured(self, prompt: str, response_schema: dict, *, system=None) -> AIResponse
```

`AIResponse` traz `data` (objeto JSON), `provider`, `model` e `usage` (tokens, quando o
provedor informa; o sistema acrescenta `attempts`). Tudo é gravado em `generated_contents`
para controle de custos e rastreabilidade.

## Provedores incluídos

### `mock` (padrão)

Sem rede e sem chave. Produz rascunhos **extrativos**: reorganiza trechos do abstract
(em inglês) nas seções e marca o título com `[Rascunho mock]`. Serve para testar o fluxo
completo; **não** é texto editorial.

### `openai_compatible`

Qualquer serviço com `POST {AI_BASE_URL}/chat/completions` no formato OpenAI. Envia
`response_format: json_object`, `temperature` e `max_tokens` (omitidos quando vazios, para
modelos que não os aceitam), com timeout e retry limitado para 408/429/5xx e erros de rede.
Erros nunca incluem a chave.

```env
AI_PROVIDER=openai_compatible
AI_BASE_URL=http://localhost:11434/v1     # obrigatório
AI_MODEL=nome-do-modelo                   # obrigatório
AI_API_KEY=                               # opcional (serviços locais não exigem)
AI_TIMEOUT=60
AI_MAX_RETRIES=2
AI_TEMPERATURE=0.2                        # deixe vazio se o modelo não aceitar
AI_MAX_TOKENS=2000
```

## Opções e custos

| Opção | Custo | Observações |
|---|---|---|
| **Ollama** ou **LM Studio** (local) | R$ 0 em serviços; usa CPU/GPU da sua máquina | Servidor OpenAI-compatível local (`http://localhost:11434/v1` no Ollama, `http://localhost:1234/v1` no LM Studio). Não funciona no GitHub Actions (o runner não acessa sua máquina). Qualidade depende do modelo baixado. **Medido neste projeto** (`qwen2.5:7b`, notebook do desenvolvedor): ~4 min por rascunho; abstracts longos podem exceder 300 s (use `AI_TIMEOUT=300` ou mais). Um lote de 10 leva ~40 min: gere com `--limit` pequeno ou deixe rodando. |
| Serviço hospedado com API OpenAI-compatível | Varia | Muitos oferecem cotas gratuitas temporárias ou com limites de requisições/tokens que **mudam sem aviso**. Antes de configurar, registre aqui: provedor, modelo, limites, preço por token, política de uso de dados enviados e data da consulta. |

Regras do projeto: nenhum provedor pago é obrigatório; o sistema sempre funciona com `mock`;
não presuma gratuidade permanente; nunca coloque chaves em arquivos versionados (use `.env`
local ou *secrets* do GitHub).

### Registro de avaliação de provedores

| Data | Provedor/modelo | Limites | Custo | Uso de dados | Decisão |
|---|---|---|---|---|---|
| — | (preencher antes de integrar) | | | | |

## Como os prompts protegem a geração

- Prompts versionados em `intelligence/prompts.py` (`article_generation_prompt`,
  `classification_prompt`, `relevance_prompt`); mudar o texto exige mudar `version`.
- Dados externos vão apenas dentro de `<dados_nao_confiaveis>`; o modelo é instruído a ignorar
  instruções contidas neles, e o bloco não pode ser "fechado" pelo conteúdo.
- O modelo **não** produz referência, link ou DOI — o sistema monta a partir dos metadados.
- A saída é validada por Pydantic (`AIArticleDraft`): campos obrigatórios, tipos, limites de
  tamanho, conteúdo vazio. Respostas inválidas não são persistidas; o erro é devolvido ao
  modelo em até `AI_MAX_RETRIES + 1` tentativas.
- O texto passa pela verificação determinística (`intelligence/verification.py`).

## Adicionar outro provedor

Implemente `AIProvider` em `intelligence/provider.py`, devolva `AIResponse` com o JSON já
decodificado, trate timeout/erros como `AIProviderError`, registre em `build_provider` e em
`KNOWN_AI_PROVIDERS` (`config/settings.py`), e teste com `httpx.MockTransport`.

## Classificação assistida

`python -m ufabc_science classify --ai` consulta a IA apenas para artigos sem categoria ou com
classificação ambígua. Sugestões com categorias desconhecidas são descartadas, a confiança é
limitada a 0,75 e ficam marcadas como incertas; categorias atribuídas com boa confiança pelas
regras não são substituídas.
