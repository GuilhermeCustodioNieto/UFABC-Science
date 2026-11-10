# ETAPA 5 — AUTOMAÇÃO, GITHUB ACTIONS E PUBLICAÇÃO GRATUITA
## Projeto: UFABC Science

Você está trabalhando no projeto UFABC Science, uma newsletter científica independente voltada exclusivamente à comunidade da Universidade Federal do ABC.

Sua tarefa é implementar a Etapa 5: automação do pipeline, integração com GitHub Actions e preparação da infraestrutura de publicação gratuita.

**IMPORTANTE:** Antes de começar, audite integralmente o projeto e as Etapas 1, 2, 3 e 4. Não presuma que funcionalidades estão implementadas apenas porque estão documentadas. Verifique o código, os testes, os comandos disponíveis, o banco de dados e a estrutura real dos diretórios.

---

# 1. OBJETIVO DA ETAPA

Implementar uma infraestrutura que permita:

1. Executar automaticamente a coleta de artigos científicos semanalmente.
2. Processar os novos artigos utilizando as funcionalidades já implementadas.
3. Classificar e pontuar os artigos.
4. Gerar conteúdos editoriais em Markdown para revisão humana.
5. Preservar os dados entre diferentes execuções.
6. Permitir execução manual pelo GitHub Actions.
7. Preparar a publicação gratuita do site estático.
8. Publicar somente quando houver autorização editorial explícita.

A automação deve reduzir o trabalho operacional, sem retirar o controle editorial humano.

# 2. PRINCÍPIOS OBRIGATÓRIOS

- Custo obrigatório: R$ 0.
- Não contratar servidores, bancos de dados ou serviços pagos.
- Não depender de APIs de IA pagas.
- Não assumir que planos gratuitos possuem limites permanentes ou ilimitados.
- Não reimplementar funcionalidades já existentes.
- Não criar microsserviços.
- Não introduzir complexidade desnecessária.
- Preservar a arquitetura atual.
- Manter compatibilidade com execução local.
- Permitir que o projeto funcione mesmo sem GitHub Actions.
- Nunca publicar automaticamente conteúdo gerado por IA.
- Nunca aprovar artigos automaticamente.
- Nunca modificar o conteúdo editorial aprovado sem invalidar sua aprovação.

# 3. AUDITORIA INICIAL

Antes de modificar qualquer arquivo:

1. Inspecione toda a estrutura do projeto.
2. Verifique as funcionalidades das Etapas 1–4.
3. Identifique os comandos CLI existentes.
4. Verifique como o SQLite é inicializado e persistido.
5. Analise os diretórios `data/`, `editions/`, `dist/` e `.github/`.
6. Verifique se já existem workflows.
7. Execute a suíte de testes.
8. Identifique problemas de idempotência e persistência.

Apresente um relatório contendo:

- O que já está implementado.
- O que está funcionando.
- O que precisa ser ajustado.
- Quais arquivos serão criados ou modificados.
- Como os dados serão preservados entre execuções.

Aguarde a conclusão da auditoria antes de implementar.

# 4. GITHUB ACTIONS — AUTOMAÇÃO SEMANAL

Criar um workflow em:

`.github/workflows/weekly_pipeline.yml`

O workflow deverá executar semanalmente, preferencialmente às segundas-feiras, em um horário adequado considerando o fuso `America/Sao_Paulo`.

O GitHub Actions utiliza agendamento em UTC. Portanto, documente a conversão do horário e considere mudanças de horário ao longo do ano.

O workflow deverá permitir:

- Execução agendada.
- Execução manual pelo `workflow_dispatch`.
- Parâmetros configuráveis para período de coleta.
- Seleção opcional de fontes científicas.
- Limite máximo de artigos por execução.
- Identificação da execução e registro dos resultados.

## 4.1. Pipeline automatizado

A execução deverá respeitar a sequência:

1. Preparar ambiente Python.
2. Instalar dependências.
3. Recuperar os dados persistentes.
4. Validar a configuração.
5. Executar coleta científica.
6. Normalizar e deduplicar os registros.
7. Classificar os artigos.
8. Calcular pontuação de relevância.
9. Selecionar artigos elegíveis.
10. Gerar conteúdos editoriais.
11. Executar verificações automatizadas.
12. Exportar os arquivos Markdown pendentes.
13. Preservar os dados e registrar o resultado da execução.

Não executar aprovação editorial, criação automática de edição final ou publicação nesta rotina.

A execução deverá continuar mesmo que uma fonte apresente erro, desde que seja possível registrar a falha e processar as demais fontes.

Ao final, apresentar um resumo:

- Fontes consultadas.
- Artigos encontrados.
- Artigos novos.
- Artigos duplicados.
- Artigos classificados.
- Artigos selecionados.
- Conteúdos gerados.
- Conteúdos com falhas de verificação.
- Erros de coleta.
- Duração total.

# 5. PERSISTÊNCIA DOS DADOS

Este é um dos pontos mais importantes da etapa.

Os runners do GitHub Actions são efêmeros. Arquivos locais, incluindo SQLite, não devem ser tratados como persistentes entre execuções.

Não implemente uma solução que dependa de um banco SQLite criado em uma execução e presumidamente disponível na seguinte.

Analise as seguintes alternativas:

**Alternativa A — Persistência versionada no Git**

- Manter o banco SQLite e os arquivos editoriais em um repositório privado ou em uma branch dedicada.
- Recuperar os dados antes da execução.
- Atualizar os dados ao final.
- Fazer commit apenas das alterações necessárias.
- Evitar commits quando não houver mudanças.
- Preservar o histórico de versões.

**Alternativa B — Artefatos do GitHub Actions**

- Utilizar artifacts para transportar resultados entre etapas ou disponibilizar arquivos para download.
- Não tratar artifacts temporários como banco de dados permanente.
- Documentar limites de retenção e armazenamento.

**Alternativa C — Execução local como fonte principal de persistência**

- Manter o SQLite local como armazenamento principal.
- Utilizar GitHub Actions apenas para tarefas que não dependam de estado persistente, quando apropriado.
- Permitir sincronização controlada dos dados editoriais.

Escolha a alternativa mais simples, segura e sustentável dentro do orçamento de R$ 0.

Não implemente todas as alternativas simultaneamente.

Se optar por versionar SQLite, documente os riscos de concorrência, conflitos de merge, corrupção e exposição de dados. Não permita duas execuções concorrentes modificando o mesmo banco.

## 5.1. Proteção dos dados

- Não armazenar tokens ou segredos dentro do banco.
- Não armazenar chaves de API em arquivos versionados.
- Não versionar `.env`.
- Não versionar caches ou arquivos temporários.
- Não sobrescrever dados editoriais melhores com dados incompletos.
- Preservar histórico de revisão.
- Garantir recuperação em caso de falha durante a execução.

# 6. GITHUB ACTIONS — SEGURANÇA

Configurar permissões mínimas necessárias.

Considerar:

- `permissions` explícitas.
- Uso de `secrets` para credenciais.
- `concurrency` para evitar execuções simultâneas.
- Limites de execução.
- Timeout por job.
- Cache de dependências Python.
- Logs sem exposição de credenciais.
- Controle de versões das Actions utilizadas.

Não conceder permissões de escrita ao repositório se a execução não precisar delas.

Caso a automação precise criar commits ou atualizar uma branch, conceder somente as permissões necessárias e documentar a justificativa.

Não utilizar tokens pessoais de longa duração quando o `GITHUB_TOKEN` for suficiente.

# 7. PUBLICAÇÃO GRATUITA — GITHUB PAGES

Preparar a publicação do site estático por meio do GitHub Pages, desde que seja compatível com a estrutura atual.

A publicação deverá utilizar os arquivos HTML já produzidos pela Etapa 4.

Não reimplementar a geração de HTML.

Criar um workflow separado:

`.github/workflows/deploy_pages.yml`

Esse workflow deverá ser executado somente por uma ação explícita de publicação.

A publicação deverá exigir:

1. Edição editorial existente.
2. Edição validada.
3. Artigos aprovados.
4. Nenhum artigo com verificação `FAILED`.
5. Justificativas registradas para eventuais avisos `WARNING`.
6. Confirmação explícita de publicação.
7. Geração do site estático.
8. Publicação no GitHub Pages.

Não permitir que a execução semanal acione esse workflow automaticamente.

Não utilizar a existência de novos arquivos Markdown como autorização de publicação.

## 7.1. Separação entre geração e publicação

O sistema deverá distinguir:

- Gerar HTML localmente.
- Validar uma edição.
- Preparar artefatos de publicação.
- Publicar efetivamente no GitHub Pages.

Essas operações não devem ser equivalentes.

Gerar HTML não significa publicar.

Uma edição em estado `READY` não significa que foi publicada.

Somente a operação explícita de publicação poderá alterar o estado para `PUBLISHED`, respeitando as regras da Etapa 4.

# 8. FLUXO DE REVISÃO HUMANA

O fluxo esperado será:

1. O GitHub Actions executa a coleta semanal.
2. Os artigos são processados.
3. Os conteúdos são gerados em Markdown.
4. Os arquivos ficam disponíveis em `data/editorial/pending/`.
5. O usuário revisa os conteúdos.
6. O usuário edita, aprova ou rejeita os artigos.
7. Os artigos aprovados podem ser adicionados a uma edição.
8. A edição é validada.
9. O usuário solicita explicitamente a publicação.
10. O GitHub Actions publica a edição no GitHub Pages.

A automação não deve ultrapassar a etapa 4 sem autorização humana.

# 9. EXECUÇÃO MANUAL

Além da execução semanal, disponibilizar uma opção de execução manual pelo GitHub Actions.

Permitir configurar:

- Período de coleta.
- Fontes.
- Limite de artigos.
- Execução completa ou parcial do pipeline.

A execução manual não poderá aprovar nem publicar conteúdo.

Se algum parâmetro não for informado, utilizar os valores padrão definidos na configuração do projeto.

# 10. OBSERVABILIDADE E RECUPERAÇÃO

Criar registros estruturados das execuções.

Cada execução deverá possuir:

- Identificador único.
- Data e horário.
- Status.
- Fontes consultadas.
- Quantidade de registros processados.
- Quantidade de novos artigos.
- Quantidade de erros.
- Duração.
- Mensagens relevantes.

Status possíveis:

- `RUNNING`
- `SUCCESS`
- `PARTIAL_SUCCESS`
- `FAILED`

Implementar:

- Logs claros.
- Tratamento de exceções.
- Retentativas controladas.
- Recuperação de execução interrompida.
- Idempotência.
- Identificação de tarefas concluídas.
- Prevenção de processamento duplicado.

Não implementar monitoramento pago.

Se houver necessidade de notificação, priorizar mecanismos gratuitos já disponíveis no GitHub, como logs e notificações nativas da plataforma.

# 11. CONFIGURAÇÃO E VARIÁVEIS DE AMBIENTE

Revisar `.env.example` e a configuração existente.

Documentar todas as variáveis necessárias.

Separar:

- Configurações obrigatórias.
- Configurações opcionais.
- Credenciais.
- Parâmetros do pipeline.
- Configurações de publicação.

A aplicação deverá funcionar em modo local sem credenciais externas sempre que os recursos utilizados permitirem.

O provider de IA mock deverá continuar funcional.

Não colocar valores secretos em arquivos de configuração versionados.

# 12. TESTES

Criar testes para:

- Configuração do pipeline.
- Execução parcial e completa.
- Execução manual.
- Idempotência.
- Recuperação após falha.
- Falha de uma fonte sem interromper as demais.
- Persistência entre execuções.
- Proteção contra concorrência.
- Ausência de credenciais.
- Bloqueio de aprovação automática.
- Bloqueio de publicação automática.
- Bloqueio de conteúdo não aprovado.
- Validação de edição.
- Publicação somente mediante autorização explícita.
- Integridade do histórico editorial.

Os testes não devem depender de chamadas reais a APIs externas.

Validar a sintaxe dos arquivos YAML dos workflows.

Se possível, utilizar ferramentas locais gratuitas para validar workflows sem executar publicações reais.

# 13. DOCUMENTAÇÃO

Atualizar o README e criar:

`docs/AUTOMATION_GUIDE.md`

`docs/GITHUB_SETUP.md`

`docs/PERSISTENCE_STRATEGY.md`

Documentar:

- Como configurar o repositório.
- Como habilitar GitHub Actions.
- Como configurar o GitHub Pages.
- Como configurar secrets.
- Como executar manualmente.
- Como funciona o agendamento semanal.
- Como os dados são preservados.
- Como recuperar uma execução com falha.
- Como revisar os artigos gerados.
- Como criar e validar uma edição.
- Como autorizar uma publicação.
- Quais são os limites e riscos da infraestrutura gratuita.

Deixar claro quais etapas continuam dependendo de ação humana.

# 14. CRITÉRIOS DE ACEITAÇÃO

A Etapa 5 somente poderá ser considerada concluída quando:

- [ ] A execução local continuar funcionando.
- [ ] O workflow semanal estiver implementado.
- [ ] A execução manual estiver disponível.
- [ ] A automação executar o pipeline sem aprovação humana.
- [ ] Os dados persistirem corretamente entre execuções.
- [ ] A solução não depender de armazenamento efêmero.
- [ ] Não houver credenciais expostas.
- [ ] A publicação estiver separada da coleta.
- [ ] O GitHub Pages estiver preparado.
- [ ] A publicação depender de autorização explícita.
- [ ] Conteúdos não aprovados forem bloqueados.
- [ ] Os testes forem aprovados.
- [ ] A documentação estiver atualizada.
- [ ] O custo operacional previsto permanecer em R$ 0.

Não declarar que o sistema está publicado ou configurado em produção se isso não tiver sido efetivamente realizado.

# 15. FORMA DE EXECUÇÃO

Trabalhe incrementalmente.

**Fase 1 — Auditoria**

Inspecione o projeto e apresente o diagnóstico.

**Fase 2 — Planejamento**

Apresente os arquivos que serão criados ou modificados e a estratégia de persistência escolhida.

**Fase 3 — Implementação**

Implemente somente a Etapa 5, preservando as etapas anteriores.

**Fase 4 — Testes**

Execute os testes existentes e os novos testes. Corrija regressões.

**Fase 5 — Documentação**

Atualize as instruções de instalação, configuração, execução e publicação.

**Fase 6 — Relatório**

Apresente:

- Funcionalidades implementadas.
- Arquivos criados e modificados.
- Estratégia de persistência adotada.
- Testes executados e resultados.
- Configurações que ainda dependem de mim.
- Limitações conhecidas.
- Instruções para testar o fluxo completo.

Não avance para uma eventual Etapa 6 sem minha autorização.

---

**REGRA FUNDAMENTAL DO PROJETO:** o UFABC Science deve funcionar como um sistema de curadoria científica assistida por IA, não como um gerador automático de notícias. A IA auxilia na descoberta, organização, análise e redação. A responsabilidade editorial e a decisão de publicação permanecem humanas.