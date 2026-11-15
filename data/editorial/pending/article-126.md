---
schema: ufabc-science/article@1
article_id: 126
content_id: 15
content_version: 2
status: pending_review
categories:
- ciencias-biologicas
- computacao-e-tecnologia
- neurociencia
primary_category: ciencias-biologicas
source_url: https://doi.org/10.1093/nargab/lqag140
doi: 10.1093/nargab/lqag140
peer_review_status: verified
article_type: journal_article
original_title: 'scMINA: an interpretable workflow for paired scRNA-scATAC multiome integration and regulatory
  prioritization.'
generated_at: '2026-11-15T06:56:47+00:00'
model_provider: openai_compatible
model_name: gemini-3.6-flash
prompt_version: 2026-11-v2
verification_status: warning
verification_messages:
- 'WARNING: O abstract menciona limitações, mas o texto diz que elas não foram informadas.'
generated_body_hash: a53d7c88f51c0dad71908250500afea8436d01e1c4cf9a342cfa1ff1a0ee863f
reviewer: null
reviewed_at: null
editorial_notes: null
warning_justification: null
edition_slug: null
---

# scMINA: novo fluxo de trabalho para integração e interpretação de dados multiômicos de célula única

## Introdução

As tecnologias multiômicas de célula única permitem analisar simultaneamente o transcriptoma e o estado epigenômico celular. No entanto, a análise conjunta de dados pareados de sequenciamento de RNA de célula única (scRNA-seq) e acessibilidade da cromatina (scATAC-seq) enfrenta grandes desafios computacionais devido a variações técnicas específicas e à complexidade de integração. Para contornar essas limitações, pesquisadores desenvolveram o scMINA (sigla em inglês para single-cell Multimodal Integration and Network Attribution), um fluxo de trabalho analítico modular e interpretável focado no estudo dessas duas modalidades celulares.

## Contexto científico

O estudo simultâneo do RNA celular e da estrutura da cromatina é essencial para entender a heterogeneidade celular e os mecanismos de regulação gênica em doenças complexas. Contudo, combinar scRNA-seq e scATAC-seq gera dificuldades de interpretação biológica sobre como os genes e fatores de transcrição atuam. O scMINA utiliza estratégias baseadas em inteligência artificial explicável para priorizar genes candidatos e fatores de transcrição ligados às alterações regulatórias e à variabilidade dos estados celulares. A ferramenta corrige variações técnicas e covariáveis, organizando a análise em módulos coordenados para integrar as informações transcriptômicas e epigenômicas de forma sistemática.

## O que foi investigado?

Como integrar eficientemente dados pareados de scRNA-seq e scATAC-seq de célula única e priorizar de forma interpretável os fatores de transcrição e genes candidatos associados à heterogeneidade celular e alterações regulatórias relacionadas a doenças?

## Como a pesquisa foi realizada?

A ferramenta scMINA é estruturada em módulos coordenados voltados para integração multimodal, correção de covariáveis técnicas e priorização de recursos regulatórios. Ela incorpora técnicas de inteligência artificial explicável para atrelar a atribuição de rede à identificação de genes e fatores de transcrição. Para testar o fluxo de trabalho, os autores aplicaram o scMINA em dados de multiômica de célula única obtidos do Seattle Alzheimer's Disease Brain Cell Atlas, focando na caracterização de populações celulares e feições regulatórias.

## Principais resultados

A aplicação do scMINA aos dados do Seattle Alzheimer's Disease Brain Cell Atlas demonstrou que o fluxo de trabalho foi capaz de resolver de forma robusta as principais populações de células gliais. Além disso, a ferramenta identificou com sucesso características regulatórias diretamente associadas à patologia da doença de Alzheimer. Ao unir a integração multimodal à priorização regulatória interpretável, o scMINA forneceu um fluxo de trabalho prático para a análise sistemática e a interpretação biológica de conjuntos de dados que combinam sequenciamento de RNA e acessibilidade da cromatina em nível de célula única.

## Limitações

As limitações específicas do fluxo de trabalho scMINA, bem como eventuais restrições técnicas, computacionais ou de generalização para outros tecidos e conjuntos de dados, não foram informadas na fonte disponibilizada.

## Por que isso importa?

O desenvolvimento do scMINA é de grande interesse para estudantes e pesquisadores da UFABC nas áreas de computação, biotecnologia, neurociência e bioinformática. A combinação de técnicas de inteligência artificial explicável com biologia molecular oferece um exemplo prático de como algoritmos avançados ajudam a desvendar mecanismos de doenças complexas, como o Alzheimer.

## Referência

Shuwen Zhang, Hongru Hu, Xue Wang et al. scMINA: an interpretable workflow for paired scRNA-scATAC multiome integration and regulatory prioritization. NAR genomics and bioinformatics. 2026. DOI: 10.1093/nargab/lqag140.

[Consultar pesquisa original](https://doi.org/10.1093/nargab/lqag140)
