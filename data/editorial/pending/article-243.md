---
schema: ufabc-science/article@1
article_id: 243
content_id: 17
content_version: 2
status: pending_review
categories:
- ciencias-biologicas
- ciencias-e-stem
- computacao-e-tecnologia
primary_category: ciencias-e-stem
source_url: https://arxiv.org/abs/2611.14287
doi: null
peer_review_status: preprint
article_type: preprint
original_title: 'ANTIOCH-VS: From Sequence to Hits with Modular, Open-Source Ensemble Virtual Screening'
generated_at: '2026-11-15T06:57:22+00:00'
model_provider: openai_compatible
model_name: gemini-3.6-flash
prompt_version: 2026-11-v2
verification_status: warning
verification_messages:
- 'WARNING: Registro sem DOI: confirme a fonte pelo link original.'
generated_body_hash: c9c5539938eef68e7bc5ec70b5657d641c1ede2acde54da965eb001bc1fd5ab4
reviewer: null
reviewed_at: null
editorial_notes: null
warning_justification: null
edition_slug: null
---

# ANTIOCH-VS: nova ferramenta de código aberto automatiza a triagem virtual de candidatos a fármacos a partir da sequência de proteínas

## Introdução

Um estudo recente, disponibilizado como preprint (ainda sem revisão por pares), apresentou o ANTIOCH-VS, um arcabouço computacional de código aberto para triagem virtual in silico. A ferramenta automatiza todo o processo de identificação de candidatos a ligantes a partir apenas da sequência de aminoácidos da proteína-alvo. O objetivo é contornar a escassez de estruturas cristalinas ligadas a moléculas no banco de dados publicamente disponível, permitindo realizar campanhas integradas de varredura molecular sem intervenção manual.

## Contexto científico

A triagem virtual baseada na estrutura de receptores é uma etapa fundamental na descoberta computacional de medicamentos. No entanto, a maioria dos alvos terapêuticos não possui estruturas cristalizadas ligadas a ligantes. Utilizar apenas uma estrutura cristalina sem ligante (apo) ou um único modelo previsto por computador pode falhar em capturar a conformação exata necessária para a ligação química. Para resolver isso, o ANTIOCH-VS integra subamostragem por alinhamento múltiplo de sequências reduzido via ColabFold com o AF2RAVE — método que combina simulações de dinâmica molecular curtas e análise estatística — para gerar e selecionar estados conformacionais metastáveis adequados para acoplamento (docking).

## O que foi investigado?

É possível desenvolver um fluxo de trabalho computacional automatizado e de código aberto que, utilizando exclusivamente a sequência de uma proteína, gere conjuntos de conformações capazes de prever e ranquear com precisão ligantes promissores, alcançando desempenho comparável ao de estruturas obtidas por difração de raios X ligadas a moléculas?

## Como a pesquisa foi realizada?

Os pesquisadores construíram o fluxo integrado ANTIOCH-VS. O processo inicia na sequência da proteína, gera um conjunto conformacional via ColabFold e seleciona estados relevantes via AF2RAVE. Em seguida, detecta a cavidade de ligação, prepara ligantes e receptores, realiza o acoplamento molecular da biblioteca usando DOCK6 ou AutoDock Vina, gera um ranqueamento de consenso e tria os melhores candidatos por metadinâmica (CTMD). Para testar o sistema simulado, utilizaram conjuntos de dados do benchmark DUD-E para dois alvos distintos: a quinase JAK2 e o receptor GPCR ADRB2.

## Principais resultados

Por se tratar de um estudo de simulação computacional, os resultados refletem o desempenho do modelo in silico nos testes de validação. Partindo unicamente da sequência proteica e sem intervenção manual, a ferramenta gerou listas dos 20 melhores candidatos altamente enriquecidas com ligantes verdadeiros. A taxa de acerto simulada foi de 20% para a quinase JAK2 e de 60% para o receptor ADRB2, em comparação com uma taxa aleatória estimada de 1% a 2%. O desempenho obtido pelas simulações ficou no mesmo patamar do uso de estruturas cristalinas ligadas a ligantes e, no caso da JAK2, superou os resultados de modelos isolados do AlphaFold2 e de estruturas cristalinas sem ligante.

## Limitações

As limitações específicas da metodologia computacional ou os limites de aplicabilidade a outras classes de proteínas não foram informados no resumo fornecido. Além disso, por se tratar de um trabalho disponibilizado em formato preprint, o estudo ainda não passou pelo processo formal de revisão por pares pela comunidade científica.

## Por que isso importa?

A pesquisa é de grande interesse para estudantes e pesquisadores da UFABC nas áreas de bioinformática, biociências, química medicinal e computação. Por ser uma ferramenta modular de código aberto, o ANTIOCH-VS permite que alunos executem simulações de triagem virtual de alta precisão em estações de trabalho ou computadores de alto desempenho, impulsionando projetos de pesquisa em modelagem molecular.

## Referência

Hale S. Hasdemir, Venkata Sai Sreyas Adury, Pratyush Tiwary. ANTIOCH-VS: From Sequence to Hits with Modular, Open-Source Ensemble Virtual Screening. arXiv. 2026. (Preprint, sem revisão por pares confirmada.)

[Consultar pesquisa original](https://arxiv.org/abs/2611.14287)
