---
schema: ufabc-science/article@1
article_id: 243
content_id: 7
content_version: 1
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
generated_at: '2026-11-15T06:50:01+00:00'
model_provider: openai_compatible
model_name: gemini-3.6-flash
prompt_version: 2026-11-v1
verification_status: warning
verification_messages:
- 'WARNING: Registro sem DOI: confirme a fonte pelo link original.'
- 'WARNING: O gerador indicou pontos para verificação humana. (Verificar se a publicação em preprint já
  avançou para revisão por pares em periódico acadêmico.; Garantir que as taxas de acerto (20% para JAK2
  e 60% para ADRB2) sejam interpretadas estritamente como métricas de benchmark in silico (DUD-E), sem
  inferir eficácia biológica in vitro/in vivo.; Confirmar se no texto completo do artigo são detalhadas
  limitações técnicas do software que não constam no resumo.)'
generated_body_hash: 9c3ec384df533aff893dc3d4dbab1c56f2c103497819b8aac711395ce77406d0
reviewer: null
reviewed_at: null
editorial_notes: null
warning_justification: null
edition_slug: null
---

# Framework de código aberto ANTIOCH-VS automatiza triagem virtual de ligantes a partir da sequência de proteínas

## Introdução

Pesquisadores apresentaram o ANTIOCH-VS, um framework computacional de código aberto projetado para executar campanhas completas de triagem virtual de ligantes a partir apenas da sequência de uma proteína. A ferramenta simula computacionalmente todo o fluxo de trabalho, desde a geração de estruturas até a classificação de candidatos a ligantes. Por se tratar de um estudo disponibilizado em formato preprint, o trabalho ainda não passou pelo processo de revisão por pares.

## Contexto científico

A triagem virtual baseada em estrutura busca identificar moléculas capazes de se ligar a receptores específicos. Contudo, muitas proteínas não possuem estruturas cristalinas resolvidas em complexo com ligantes, e modelos estáticos únicos frequentemente falham em capturar os estados conformacionais adequados para a ligação. Para contornar esse problema, o ANTIOCH-VS emprega subamostragem de alinhamentos múltiplos de sequências via ColabFold e utiliza o protocolo AlphaFold2-RAVE (AF2RAVE) — que combina simulações curtas de dinâmica molecular e análise estatística — para selecionar estados metaestáveis adequados para o acoplamento molecular.

## O que foi investigado?

Como integrar etapas computacionais em um fluxo de trabalho automatizado capaz de gerar conjuntos conformacionais e identificar candidatos a ligantes usando unicamente a sequência de aminoácidos de uma proteína?

## Como a pesquisa foi realizada?

O ANTIOCH-VS gera ensembles conformacionais no ColabFold e aplica o AF2RAVE para identificar estados metaestáveis ponderados por Boltzmann. O sistema detecta o sítio de ligação, prepara receptores e ligantes, realiza a acoplagem molecular da biblioteca com DOCK6 ou AutoDock Vina, constrói um ranking de consenso e filtra os melhores resultados usando metadinâmica (CTMD). O teste do sistema foi realizado em simulações com os alvos JAK2 e ADRB2 utilizando os conjuntos de validação do banco DUD-E.

## Principais resultados

Nas simulações realizadas partindo apenas da sequência proteica, os conjuntos gerados pelo AF2RAVE produziram listas dos 20 melhores candidatos fortemente enriquecidas por ligantes verdadeiros. A taxa de acerto simulada foi de 20% para a quinase JAK2 e de 60% para o receptores ADRB2, em comparação com uma taxa aleatória estimada entre ~1% e 2%. Os resultados simulados do framework atingiram desempenho equivalente ao de cristais ligados a ligantes e, no caso da JAK2, superaram modelos únicos do AlphaFold e estruturas cristalinas apo.

## Limitações

O resumo da fonte original não informa explicitamente as limitações do framework ANTIOCH-VS ou de seus algoritmos. Por se tratar de um estudo baseado exclusivamente em simulações computacionais e benchmarks virtuais, os resultados não representam validação experimental direta em laboratório.

## Por que isso importa?

O tema é de interesse para alunos e pesquisadores da UFABC vinculados às ciências biológicas, computação, química e engenharia. A disponibilidade de um código aberto para triagem virtual abre oportunidades para o desenvolvimento de projetos acadêmicos em bioinformática, modelagem molecular e biofísica computacional.

## Referência

Hale S. Hasdemir, Venkata Sai Sreyas Adury, Pratyush Tiwary. ANTIOCH-VS: From Sequence to Hits with Modular, Open-Source Ensemble Virtual Screening. arXiv. 2026. (Preprint, sem revisão por pares confirmada.)

[Consultar pesquisa original](https://arxiv.org/abs/2611.14287)
