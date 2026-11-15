---
schema: ufabc-science/article@1
article_id: 422
content_id: 10
content_version: 1
status: pending_review
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
generated_at: '2026-11-15T06:50:57+00:00'
model_provider: openai_compatible
model_name: gemini-3.6-flash
prompt_version: 2026-11-v1
verification_status: warning
verification_messages:
- 'WARNING: O gerador indicou pontos para verificação humana. (As limitações do modelo e do experimento
  não estão descritas no resumo e devem ser verificadas no artigo completo.; Os dados foram obtidos exclusivamente
  via simulação no MATLAB/Simscape; verificar se os autores discutem a aplicabilidade em sistemas de prensas
  físicas reais.)'
generated_body_hash: 71c948efd2e1fba68d8207eab6fa2527fc1df96d8eda02849340781286c36214
reviewer: null
reviewed_at: null
editorial_notes: null
warning_justification: null
edition_slug: null
---

# Rede neural informada pela física otimiza simulação da dinâmica de prensas híbridas

## Introdução

Um estudo publicado no periódico Robotics propõe o uso de uma rede neural profunda informada pela física (PIDNN) para prever a dinâmica de sistemas de prensa híbrida. O modelo substituto foi desenvolvido para estimar cinco respostas de engenharia a partir de seis entradas operacionais. Por se tratar de um estudo baseado em simulação computacional, os dados de treinamento e teste foram gerados sinteticamente em ambiente computacional para avaliar a precisão e a eficiência do algoritmo.

## Contexto científico

A modelagem de sistemas de prensa híbrida exige prever o comportamento mecânico sob restrições complexas. Métodos de aprendizado de máquina puramente baseados em dados podem gerar previsões que violam leis físicas fundamentais. Para resolver esse problema, a abordagem de rede neural informada pela física (PIDNN) incorpora princípios determinísticos da mecânica de multicorpos restritos diretamente no processo de otimização da rede. Isso inclui a integração de consistência cinemática, equilíbrio dinâmico, estimativa de reação de restrição, efeitos de atrito e conservação da taxa de energia.

## O que foi investigado?

É possível utilizar uma rede neural profunda informada pela física como modelo substituto para prever a dinâmica de prensas híbridas com alta precisão mecânica e menor tempo de processamento computacional em comparação às simulações tradicionais?

## Como a pesquisa foi realizada?

A pesquisa utilizou um ambiente de simulação em MATLAB/Simscape para gerar 75 trajetórias operacionais, resultando em 375.000 amostras divididas em conjuntos independentes de treinamento, validação e teste. A arquitetura PIDNN integrou o aprendizado supervisionado a restrições mecânicas determinísticas para prever cinco variáveis: deslocamento, velocidade e aceleração do cursor, força do atuador e torque requerido do motor. Também foram realizados experimentos de ablação controlada para avaliar a contribuição das restrições físicas.

## Principais resultados

A PIDNN obteve erros quadráticos médios normalizados (nRMSEs) de 0,118, 0,129, 0,154, 0,111 e 0,138 para as cinco respostas analisadas, alcançando um nRMSE médio geral de 0,130. Esse resultado representa uma redução de 41,2% no erro em comparação à rede neural artificial convencional (nRMSE de 0,221). O modelo registrou resíduo dinâmico normalizado médio quadrático de 0,018 e desequilíbrio médio de energia de 0,91%. A latência de inferência foi de 0,17 a 0,20 ms por amostra.

## Limitações

As limitações da pesquisa não foram explicitamente informadas no resumo da fonte fornecida. Cabe ressaltar que os resultados obtidos derivam inteiramente de modelos de simulação em MATLAB/Simscape, sem menção no texto a validações experimentais em bancadas físicas reais.

## Por que isso importa?

O trabalho reflete temas centrais para a comunidade acadêmica da UFABC, especialmente nos cursos de Engenharia de Modelagem, Engenharia Mecânica e Ciência da Computação. A integração de equações físicas a modelos de redes neurais profundas ilustra avanços relevantes no desenvolvimento de modelos substitutos eficientes para simulação de sistemas complexos.

## Referência

Batyrkhan Omarov, Moldir Kuatova, Amandyk Tuleshov et al. Physics-Informed Deep Neural Network Surrogate for Simulation-Based Prediction of Hybrid Press System Dynamics. Robotics. 2026. DOI: 10.3390/robotics15110236.

[Consultar pesquisa original](https://doi.org/10.3390/robotics15110236)
