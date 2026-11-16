---
schema: ufabc-science/article@1
article_id: 338
content_id: 29
content_version: 1
status: pending_review
categories:
- ciencias-e-stem
- computacao-e-tecnologia
- engenharias
primary_category: ciencias-e-stem
source_url: https://doi.org/10.1145/3837864
doi: 10.1145/3837864
peer_review_status: verified
article_type: journal_article
original_title: Scalable Back-Propagation-Free Training of Optical Physics-Informed Neural Networks
generated_at: '2026-11-16T14:01:02+00:00'
model_provider: openai_compatible
model_name: gemini-3.6-flash
prompt_version: 2026-11-v3
verification_status: warning
verification_messages:
- 'WARNING: O gerador indicou pontos para verificação humana. (O termo ''tensor-train decomposition''
  foi traduzido como decomposição tensor-train, que é a nomenclatura usada na literatura técnica de computação
  e matemática aplicada.)'
generated_body_hash: 3e391710e2d76e6eb5b65b69937c8b103aaf7f62f18b2869a134453438580f20
reviewer: null
reviewed_at: null
editorial_notes: null
warning_justification: null
edition_slug: null
---

# Simulação indica viabilidade de treinar redes neurais informadas por física em chips fotônicos sem retropropagação

## Introdução

Engenheiros dependem da avaliação rápida de equações diferenciais parciais para tomar decisões em tempo quase real em sistemas como robôs, veículos autônomos e chips semicondutores. Redes neurais informadas por física (PINNs) ajudam a resolver essas equações em múltiplas dimensões. No entanto, o tempo de treinamento em hardwares tradicionais, como unidades de processamento gráfico, supera em ordens de grandeza a latência exigida para respostas imediatas.

## Contexto científico

A computação fotônica utiliza luz em vez de corrente elétrica para processar dados em velocidades muito elevadas, o que reduz o tempo de resposta do sistema. Apesar desse potencial, a ausência de memória fotônica integrada e o tamanho avantajado dos dispositivos impedem o treinamento de redes neurais informadas por física em chips ópticos. Além disso, o algoritmo tradicional de retropropagação exige operações encadeadas difíceis de implementar diretamente no hardware fotônico.

## O que foi investigado?

Como viabilizar o treinamento escalável de redes neurais informadas por física em plataformas fotônicas de silício sem utilizar o algoritmo de retropropagação?

## Como a pesquisa foi realizada?

Os pesquisadores desenvolveram uma estrutura composta por três elementos: um estimador de derivada de Stein em grade esparsa para calcular a perda sem retropropagação, uma otimização de ordem zero com dimensão reduzida via decomposição tensor-train, e o projeto de um acelerador fotônico em chip. A validação numérica ocorreu em testes com equações diferenciais parciais de baixa e alta dimensão. A equipe também executou simulações pré-silício com parâmetros reais de dispositivos.

## Principais resultados

Por se tratar de um estudo de simulação pré-silício, os resultados refletem modelos computacionais e não observações experimentais diretas em chips físicos. Nas simulações configuradas com parâmetros reais de hardware, o sistema demonstrou capacidade de treinamento em tempo real e redução expressiva na área ocupada pelo chip. Os testes numéricos indicaram convergência e escalabilidade no treinamento sem retropropagação para equações de diferentes dimensões.

## Limitações

O resumo da publicação não informa as limitações do estudo ou do modelo proposto.

## Por que isso importa?

O trabalho interessa a estudantes e pesquisadores das Engenharias, Ciência da Computação e Física na UFABC. O tema conecta conceitos de fotônica de silício, álgebra linear avançada e aprendizado de máquina, ilustrando como restrições físicas de hardware incentivam o desenvolvimento de novos algoritmos numéricos.

## Referência

Yequan Zhao, Xinling Yu, Xian Xiao et al. Scalable Back-Propagation-Free Training of Optical Physics-Informed Neural Networks. ACM Transactions on Design Automation of Electronic Systems. 2026. DOI: 10.1145/3837864.

[Consultar pesquisa original](https://doi.org/10.1145/3837864)
