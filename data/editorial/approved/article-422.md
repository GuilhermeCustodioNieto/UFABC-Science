---
schema: ufabc-science/article@1
article_id: 422
content_id: 20
content_version: 2
status: approved
categories:
- computacao-e-tecnologia
- engenharias
primary_category: computacao-e-tecnologia
source_url: https://doi.org/10.3390/robotics15110236
doi: 10.3390/robotics15110236
peer_review_status: verified
article_type: journal_article
original_title: Physics-Informed Deep Neural Network Surrogate for Simulation-Based Prediction of Hybrid
  Press System Dynamics
generated_at: '2026-11-15T06:58:14+00:00'
model_provider: openai_compatible
model_name: gemini-3.6-flash
prompt_version: 2026-11-v2
verification_status: passed
verification_messages: []
generated_body_hash: 3162a990d0c02b049e5557a6811f42819c62e6b87eeb68c170f36ba520a48a56
reviewer: Publicação automática
reviewed_at: '2026-11-15T06:58:15+00:00'
editorial_notes: null
warning_justification: null
edition_slug: null
---

# Rede neural informada por física é proposta para simulação dinâmica de prensas híbridas

## Introdução

Estudar a dinâmica de prensas híbridas exige a integração entre modelagem baseada em dados e os princípios da mecânica de multicorpos com restrições. Em artigo publicado no periódico Robotics, pesquisadores propuseram uma rede neural profunda informada por física (PIDNN) como modelo substituto (surrogate model) para prever respostas de engenharia desses sistemas. O objetivo é estimar o comportamento dinâmico a partir de variáveis de operação, mantendo a consistência física sem depender exclusivamente de simulações numéricas tradicionais.

## Contexto científico

A modelagem precisa de sistemas mecânicos complexos, como as prensas híbridas, frequentemente depende de simulações por integração numérica computacionalmente intensivas. Redes neurais artificiais convencionais baseadas apenas em dados podem acelerar as previsões, mas correm o risco de gerar resultados fisicamente inconsistentes. A abordagem de redes neurais informadas por física (PIDNN) busca resolver essa limitação ao integrar o aprendizado supervisionado a restrições determinísticas, incorporando consistência cinemática, equilíbrio dinâmico, estimativa de reações de restrição, efeitos de atrito e conservação da taxa de energia em uma função de otimização unificada.

## O que foi investigado?

É possível utilizar uma rede neural profunda informada por física para prever a dinâmica de um sistema de prensa híbrida a partir de dados simulados, mantendo precisão, consistência com as leis mecânicas e eficiência computacional?

## Como a pesquisa foi realizada?

O estudo foi realizado inteiramente por meio de simulação computacional. Os pesquisadores utilizaram o ambiente MATLAB/Simscape para gerar 75 trajetórias operacionais, totalizando 375.000 amostras divididas em conjuntos de treinamento, validação e teste. A arquitetura PIDNN foi configurada para prever cinco respostas de engenharia (deslocamento, velocidade e aceleração do cursor, força do atuador e torque exigido do motor) a partir de seis entradas operacionais, integrando as equações mecânicas diretamente ao objetivo de otimização.

## Principais resultados

Nas avaliações simuladas, a PIDNN alcançou erros quadráticos médios normalizados (nRMSE) de 0,118, 0,129, 0,154, 0,111 e 0,138 para as cinco respostas analisadas. A média geral do nRMSE foi de 0,130, o que representa uma redução de 41,2% no erro de previsão em comparação à rede neural artificial convencional (nRMSE médio de 0,221). O modelo proposto apresentou resíduo dinâmico normalizado médio quadrático de 0,018 e desequilíbrio médio de energia de 0,91%. Além disso, a latência de inferência por amostra única foi de 0,17 a 0,20 ms, indicando vantagem computacional frente à integração numérica convencional.

## Limitações

As limitações específicas do modelo ou do estudo não foram detalhadas no texto da fonte. Vale ressaltar que os resultados apresentados derivam exclusivamente de dados gerados por simulação no MATLAB/Simscape, não representando medições em bancadas físicas reais.

## Por que isso importa?

O trabalho é relevante para estudantes e pesquisadores da UFABC ligados às Engenharias (como Engenharia Mecânica e de Modelagem) e à Ciência da Computação. Ele ilustra como a combinação de inteligência artificial com princípios físicos fundamentais pode otimizar a simulação e o projeto de sistemas mecânicos e industriais complexos.

## Referência

Batyrkhan Omarov, Moldir Kuatova, Amandyk Tuleshov et al. Physics-Informed Deep Neural Network Surrogate for Simulation-Based Prediction of Hybrid Press System Dynamics. Robotics. 2026. DOI: 10.3390/robotics15110236.

[Consultar pesquisa original](https://doi.org/10.3390/robotics15110236)
