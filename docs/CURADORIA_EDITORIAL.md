# Curadoria editorial

Esta é a política que decide **o que** vira matéria na UFABC Science e **como** ela é escrita.
Princípio: rigor acadêmico na seleção, acessibilidade na comunicação e curiosidade como princípio
de descoberta. É melhor publicar menos matérias excelentes do que muitas medianas.

## Por que mudou (diagnóstico da versão anterior)

| Etapa | Antes | Problema |
|---|---|---|
| Busca | 3 a 5 consultas genéricas por fonte ("engineering", "physics", "ecology"). | Sem astronomia, aeroespacial, medicina clínica, psicologia, economia ou humanidades. |
| Seleção | Heurística sobre metadados (tamanho do abstract, palavras como "novel", acesso aberto). Qualquer artigo com abstract virava candidato e os 10 primeiros eram escritos. | Nada media curiosidade. Não havia corte de qualidade nem regra de rejeição. |
| Editorias | 5 áreas amplas atribuídas por palavras-chave. | Pertencer a uma editoria bastava. Interdisciplinaridade era só um número. |
| Redação | Um prompt único com 7 seções acadêmicas (contexto, pergunta de pesquisa, metodologia...). | Texto com cara de resumo de artigo, técnico e pouco interessante. |
| Validação | Só checagens determinísticas (números, DOI, links). | A primeira resposta do modelo era sempre aceita; clareza e interesse nunca eram avaliados. |

## Pipeline

```text
coleta (consultas por editoria) → normalização/deduplicação → classificação por regras
→ pré-filtro heurístico (todas as pesquisas, sem IA, com regras de rejeição)
→ curadoria por IA (lista curta: descoberta central, editorias, conexões, 5 notas)
→ decisão pelo código (nota ponderada + regras + travas dos metadados)
→ seleção das melhores (corte 65, sem cota por editoria, limite de dominância)
→ redação na estrutura nova → revisão editorial por IA (linguagem + fidelidade)
→ reescrita se reprovada (até EDITORIAL_REVIEW_ROUNDS vezes)
→ verificação determinística → Markdown → aprovação (humana ou automática)
```

Etapas do comando `run`: `collect, enrich, classify, score, curate, generate`. Sem IA
configurada (provedor `mock`), a etapa `curate` é pulada e o pré-filtro heurístico decide.

## Critérios e pontuação

| Critério | Peso | O que mede |
|---|---:|---|
| Potencial de curiosidade | 30 | É surpreendente? Um leigo teria interesse? Desperta perguntas? |
| Relevância científica | 25 | Há pesquisa real, documentada, em fonte confiável? |
| Grau de novidade | 20 | É inédito? Método novo? Desafia o que se sabia? |
| Potencial de impacto | 15 | Pode transformar uma área, gerar tecnologia, mudar a compreensão? |
| Qualidade das evidências | 10 | Revisado por pares? Preprint? Laboratório, animais, hipótese? |

Faixas: **85-100** prioridade máxima · **75-84** publicar · **65-74** avaliar se houver espaço ·
**abaixo de 65** rejeitar. A nota final é calculada pelo código, nunca pelo modelo.

### Regras de rejeição (rejeitam com qualquer nota)

`atualizacao_menor`, `resultado_trivial`, `especifico_demais`, `sem_novidade`,
`noticia_empresarial`, `opiniao_como_descoberta`, `sem_fonte_verificavel`, `pesquisa_antiga`,
`sensacionalista`, `correlacao_como_causa`, `hipotese_como_fato` e `informacao_insuficiente`.
As verificáveis por texto (erratas, editoriais, notas de versão, protocolos sem resultado,
notícias de mercado, pesquisa com mais de 540 dias, sem DOI nem link, abstract curto) são
aplicadas sem IA. As demais são indicadas pela IA.

### Travas dos metadados

- Evidências de **preprint** ficam limitadas a 60; revisão por pares não confirmada, a 75;
  repositório sem triagem (Zenodo, OSF, Figshare), a 30. O modelo não pode ultrapassar esses tetos.
- **Fonte:** periódicos e anais reconhecidos (Nature, Science, Cell, Lancet, NEJM, JAMA, PNAS,
  Physical Review, IEEE, ACM, NeurIPS e equivalentes por área, lista aberta em
  `processing/curation.py`) pesam a favor em relevância e evidências. Isso substitui a regra
  antiga "sem critério de fonte", a pedido da política editorial (seção 4). Citações continuam
  fora da conta.
- **Outras Ciências** (matemática, física, química, biologia, geologia...) só entram com nota 85+.

### Diversidade

Nenhuma editoria ocupa mais da metade das vagas de uma execução, salvo descoberta de prioridade
máxima. Vagas que sobram são preenchidas pela nota, sem cota artificial: se só houver boas
descobertas de IA, publica-se IA.

## Editorias

Computação e IA · Engenharia Aeroespacial · Astronomia e Universo · Medicina e Biotecnologia ·
Neurociência e Psicologia · Filosofia, Sociologia e Arte · Economia · **Intersecções
Científicas** · Outras Ciências.

Intersecções não é categoria residual: uma pesquisa entra nela quando duas áreas diferentes
aparecem com confiança nas regras (`rules-v3`, confiança ≥ 0,7) ou quando a curadoria aponta
conexões explícitas (`interdisciplinary_links`). Nesses casos ela é a editoria principal da
matéria, e o redator recebe as conexões para destacá-las.

As editorias da primeira versão continuam no banco, **inativas**, porque edições já publicadas as
referenciam. `init-db` cria as novas e desativa as antigas.

## Estrutura da matéria

1. **Título**: concreto, curto (até 110 caracteres), sem dois-pontos, sem pergunta, sem clickbait.
2. **Subtítulo**: uma frase que contextualiza e diz por que importa (linha `> ...` no Markdown).
3. **A descoberta**: o que foi descoberto e como os pesquisadores chegaram lá.
4. **Como funciona**: o mecanismo, com analogia quando ajudar.
5. **Por que isso importa?**: consequências e aplicações, sem exagero.
6. **Limitações e próximos passos**: maturidade do estudo, o que falta demonstrar.
7. **Referência**: montada pelo sistema a partir dos metadados (nunca pela IA).

Matérias antigas (7 seções) continuam válidas e são exibidas no formato original.

## Prompts (`intelligence/prompts.py`)

| Prompt | Etapa | Responsabilidade |
|---|---|---|
| `curation_prompt` | curadoria | Descoberta central, nível de evidência, editorias, conexões entre áreas, 5 notas justificadas, regras de rejeição. |
| `classification_prompt` | classificação (opcional, `--ai-classification`) | Casos que as regras não resolvem. |
| `article_generation_prompt` | redação | Matéria na estrutura nova, com regras de linguagem, títulos e maturidade científica. |
| `editorial_review_prompt` | revisão | Notas 0-10 de linguagem/interesse (clareza, naturalidade, jargão, interesse, título, coerência) e de fidelidade (precisão, fidelidade ao estudo, fato × hipótese), com instruções de correção. |

Descoberta, classificação e avaliação ficam num único prompt de curadoria, em passos separados
na mesma chamada, e as revisões de linguagem e de fatos também, para caber no tempo do GitHub
Actions e na cota gratuita da IA (cada chamada com raciocínio pode levar mais de 1 minuto).

### Revisão editorial

Qualquer nota abaixo de 7 reprova a versão. Linguagem baixa pede **versão mais simples**;
precisão baixa pede **correção da precisão**; interesse/título baixo pede **nova abertura e
título**. A matéria é reescrita com as instruções do revisor, até `EDITORIAL_REVIEW_ROUNDS`
vezes. Se a última versão ainda for reprovada, a verificação marca WARNING e a matéria não é
publicada automaticamente.

### Verificação determinística (além das checagens anteriores)

- clichês e fórmulas proibidas, travessões;
- título longo, com dois-pontos ou em forma de pergunta;
- frases longas (média acima de 30 palavras ou alguma acima de 50);
- estudo em animais ou de laboratório sem dizer isso ao leitor;
- resultado preliminar apresentado como tratamento ou eficácia comprovada;
- revisão editorial reprovada.

## Explicando decisões

```bash
python -m ufabc_science explain --decision reject      # por que cada artigo foi rejeitado
python -m ufabc_science explain --article-id 42        # notas, motivos, descoberta central
python -m ufabc_science curate --limit 10              # curadoria por IA, com explicação
python -m ufabc_science shortlist                      # ranking com a decisão de cada artigo
```

O resumo da execução no GitHub Actions lista as decisões da curadoria, e o front matter de cada
rascunho traz `curation` (decisão e notas) e `editorial_review` (resultado da revisão).

## Configuração

| Variável | Padrão | Efeito |
|---|---|---|
| `CURATION_MIN_SCORE` | 65 | Nota mínima para virar matéria. |
| `CURATION_LIMIT` | 15 | Candidatos avaliados pela IA por execução (1 chamada cada). |
| `CURATION_MAX_AGE_DAYS` | 60 | Idade máxima de publicação para ir à curadoria por IA. |
| `EDITORIAL_REVIEW_ROUNDS` | 1 | Reescritas que a revisão pode pedir (0 a 3). |
| `PRIORITY_*` | 85 / 75 / 65 | Faixas exibidas no `shortlist`. |

Custo por execução com IA: até `CURATION_LIMIT` + `GENERATION_LIMIT` × (2 + 2 × rodadas)
chamadas. Com os padrões, no pior caso 15 + 10 × 4 = 55. O tempo limite do job subiu para 90 min.

## Limitações conhecidas

- O pré-filtro heurístico mede curiosidade por sinais de texto: é um filtro grosso. Ele decide
  sozinho só quando não há IA (e rascunhos do `mock` nunca são publicados automaticamente).
- Os prompts foram testados com provedores simulados. A calibração das notas do modelo real
  deve ser acompanhada nas primeiras execuções com `explain`.
- A lista de periódicos reconhecidos é aberta e deve ser revisada pelo responsável editorial.
- As fontes continuam sendo OpenAlex, PubMed, arXiv e Crossref. NASA, ESA e comunicados de
  universidades ainda não são coletados.
