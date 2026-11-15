---
schema: ufabc-science/article@1
article_id: 126
content_id: 5
content_version: 1
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
generated_at: '2026-11-15T06:49:25+00:00'
model_provider: openai_compatible
model_name: gemini-3.6-flash
prompt_version: 2026-11-v1
verification_status: warning
verification_messages:
- 'WARNING: O abstract menciona limitações, mas o texto diz que elas não foram informadas.'
- 'WARNING: O gerador indicou pontos para verificação humana. (As limitações específicas do algoritmo
  scMINA não constam no resumo fornecido e precisam ser verificadas no artigo completo.; A disponibilidade
  de código-fonte ou pacote de software não foi especificada no texto.)'
generated_body_hash: b51aff82479a942be398c027e7f5159b5a1f7e2acc1a90b8ffe8334bbf7b6077
reviewer: null
reviewed_at: null
editorial_notes: null
warning_justification: null
edition_slug: null
---

# scMINA: novo fluxo de trabalho interpretável para integração de dados multiômicos de célula única

## Introdução

Um estudo publicado no periódico NAR genomics and bioinformatics apresentou o scMINA (Single-cell Multimodal Integration and Network Attribution), um fluxo de trabalho analítico modular e interpretável. A ferramenta foi desenvolvida para a análise de dados pareados de sequenciamento de RNA de célula única (scRNA-seq) e acessibilidade da cromatina (scATAC-seq). O objetivo principal é investigar a heterogeneidade celular e os mecanismos de regulação gênica associados a doenças complexas.

## Contexto científico

Tecnologias multiômicas de célula única que analisam simultaneamente estados transcriptômicos e epigenômicos oferecem oportunidades para compreender o funcionamento celular. No entanto, a análise de dados pareados de scRNA-seq e scATAC-seq apresenta desafios computacionais significativos. Esses desafios incluem variações técnicas específicas de cada modalidade, alta complexidade na integração dos dados e interpretabilidade limitada na inferência dos mecanismos regulatórios downstream.

## O que foi investigado?

Como realizar a integração computacional e a interpretação biológica de dados pareados de scRNA-seq e scATAC-seq, contornando variações técnicas e priorizando fatores regulatórios associados a estados celulares e doenças?

## Como a pesquisa foi realizada?

O scMINA é composto por módulos coordenados destinados à integração multimodal, correção de covariáveis técnicas e priorização de recursos regulatórios. A metodologia utiliza estratégias de atribuição baseadas em inteligência artificial explicável para priorizar genes candidatos e fatores de transcrição. Para testar o fluxo de trabalho, os pesquisadores aplicaram o scMINA a dados multiômicos de célula única provenientes do Seattle Alzheimer's Disease Brain Cell Atlas.

## Principais resultados

Na aplicação aos dados do Seattle Alzheimer's Disease Brain Cell Atlas, o scMINA resolveu de forma robusta as principais populações de células gliais. Além disso, o fluxo de trabalho identificou características regulatórias associadas à patologia da doença de Alzheimer. Os resultados demonstraram que o scMINA combina integração multimodal com priorização regulatória interpretável para a análise sistemática de conjuntos de dados pareados de scRNA-seq e scATAC-seq.

## Limitações

As limitações do estudo e da ferramenta não foram informadas nos dados fornecidos na fonte.

## Por que isso importa?

O estudo é relevante para a comunidade da UFABC por conectar biologia computacional, bioinformática, inteligência artificial e neurociência. A abordagem pode interessar a estudantes e pesquisadores dedicados ao desenvolvimento de algoritmos para análise de dados biológicos complexos e modelagem de redes regulatórias.

## Referência

Shuwen Zhang, Hongru Hu, Xue Wang et al. scMINA: an interpretable workflow for paired scRNA-scATAC multiome integration and regulatory prioritization. NAR genomics and bioinformatics. 2026. DOI: 10.1093/nargab/lqag140.

[Consultar pesquisa original](https://doi.org/10.1093/nargab/lqag140)
