---
schema: ufabc-science/article@1
article_id: 243
content_id: 26
content_version: 3
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
generated_at: '2026-11-16T13:59:51+00:00'
model_provider: openai_compatible
model_name: gemini-3.6-flash
prompt_version: 2026-11-v3
verification_status: warning
verification_messages:
- 'WARNING: Registro sem DOI: confirme a fonte pelo link original.'
- 'WARNING: O gerador indicou pontos para verificação humana. (O termo ''State Predictive Information
  Bottleneck'' foi traduzido como ''análise por gargalo de informação preditiva de estado''.; O termo
  ''physics-based metadynamics (CTMD)'' foi traduzido como ''metadinâmica baseada em física (CTMD)''.)'
generated_body_hash: 895abc604e93f93fdc4c624c1f70435a475a0bc6616345218211a8f0b59abcf4
reviewer: null
reviewed_at: null
editorial_notes: null
warning_justification: null
edition_slug: null
---

# Plataforma computacional ANTIOCH-VS identifica potenciais ligantes proteicos a partir da sequencia de aminoacidos

## Introdução

Pesquisadores desenvolveram a ANTIOCH-VS, uma plataforma de código aberto que automatiza a busca por moléculas capazes de se ligar a proteínas utilizando apenas a sequência de aminoácidos como ponto de partida. O sistema combina modelos de inteligência artificial com simulações computacionais de dinâmica molecular para mapear diferentes conformações de receptores. O trabalho foi publicado como um preprint no repositório arXiv e ainda não passou pelo processo de revisão por pares.

## Contexto científico

O rastreamento virtual baseado em estrutura depende do conhecimento da forma tridimensional do receptor proteico. Contudo, para a maioria dos alvos biológicos, não existem estruturas cristalográficas obtidas em complexo com ligantes. Modelos preditivos individuais ou estruturas no estado livre (apo) frequentemente não capturam os estados conformacionais aptos à ligação. Para superar essa barreira, a triagem por conjunto conformacional gera múltiplas estruturas possíveis da proteína, aumentando as chances de identificar conformações metastáveis adequadas para o acoplamento molecular (docking) com pequenas moléculas.

## O que foi investigado?

É possível automatizar o processo de triagem virtual computacional a partir de uma sequência de aminoácidos sem dados estruturais prévios com ligantes, mantendo a precisão na seleção de moléculas promissoras em comparação a modelos estruturais tradicionais?

## Como a pesquisa foi realizada?

O fluxo computacional inicia gerando conjuntos conformacionais por subamostragem de alinhamento múltiplo de sequências no ColabFold. Em seguida, o método AF2RAVE realiza simulações curtas de dinâmica molecular e análise por gargalo de informação preditiva de estado para selecionar estados metastáveis ponderados por Boltzmann. A plataforma detecta a cavidade de ligação, prepara receptores e ligantes, executa acoplamento molecular da biblioteca com DOCK6 ou AutoDock Vina, estabelece um ranking de consenso e tria as moléculas finais por metadinâmica baseada em física (CTMD).

## Principais resultados

Em testes computacionais de referência com conjuntos de dados DUD-E para os alvos JAK2 e ADRB2, a plataforma ANTIOCH-VS produziu listas dos 20 melhores candidatos enriquecidas com ligantes verdadeiros. Partindo apenas da sequência de aminoácidos, o fluxo simulado atingiu uma taxa de acerto de 20% para a quinase JAK2 e de 60% para o GPCR ADRB2, superando a taxa aleatória estimada em cerca de 1% a 2%. No caso da quinase JAK2, o desempenho simulado superou modelos individuais do AlphaFold2 e a estrutura de um cristal apo, igualando-se aos resultados obtidos com cristais complexados a ligantes.

## Limitações

As limitações específicas do sistema ou restrições do algoritmo não foram informadas explicitamente no resumo da fonte. A validação apresentada no estudo limitou-se ao teste simulado em dois alvos computacionais específicos (JAK2 e ADRB2).

## Por que isso importa?

O trabalho é relevante para a comunidade acadêmica da UFABC nas áreas de bioinformatica, ciência da computação, biotecnologia e química medicinal. A disponibilidade da plataforma como ferramenta de código aberto permite que estudantes e pesquisadores apliquem o fluxo automatizado em projetos de biologia computacional e triagem de fármacos in silico.

## Referência

Hale S. Hasdemir, Venkata Sai Sreyas Adury, Pratyush Tiwary. ANTIOCH-VS: From Sequence to Hits with Modular, Open-Source Ensemble Virtual Screening. arXiv. 2026. (Preprint, sem revisão por pares confirmada.)

[Consultar pesquisa original](https://arxiv.org/abs/2611.14287)
