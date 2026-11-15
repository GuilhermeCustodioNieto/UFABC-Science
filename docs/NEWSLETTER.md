# Newsletter por e-mail

Sem plataforma de e-mail: o GitHub Actions envia a edição **direto pelo Gmail do projeto**
(SMTP), para uma lista pequena de assinantes guardada num secret do GitHub. Pensado para até
algumas dezenas de pessoas; o Gmail aceita cerca de 500 destinatários por dia.

```text
autopublish → site no ar → newsletter send → smtp.gmail.com → cada assinante (uma mensagem por pessoa)
```

- Toda segunda, depois que a edição é publicada e o site entra no ar, o **Pipeline semanal**
  envia a edição a todos da lista.
- Cada assinante recebe uma mensagem só para ele, então ninguém vê o endereço dos outros.
- Cada edição é enviada **uma única vez**. A marca fica em `editions/sent/<slug>.json` na
  branch `data`, apenas com contagens, sem endereços.
- Senha e endereços ficam só em *secrets* e nunca aparecem nos logs.
- Sem o secret `SMTP_PASSWORD`, o envio é pulado sem erro.

## Assinar e cancelar

- O botão **"Assinar"** do site abre um e-mail pronto, endereçado ao `CONTACT_EMAIL`, com o
  assunto "Quero assinar a newsletter UFABC Science". A pessoa só precisa enviar.
- Todo e-mail da newsletter tem no rodapé um link **"Cancelar inscrição"**, que funciona do
  mesmo jeito. O cabeçalho `List-Unsubscribe` faz o Gmail mostrar o botão "Cancelar
  inscrição" dele.
- Quando chegar um pedido, edite o secret `NEWSLETTER_RECIPIENTS`, adicionando ou removendo o
  endereço.

## Configuração (uma vez)

1. **Senha de app do Gmail do projeto.** A verificação em duas etapas precisa estar ativa.
   Entre em <https://myaccount.google.com/apppasswords> logado no Gmail do projeto, crie uma
   senha de app (nome: "UFABC Science") e copie os 16 caracteres.
2. **GitHub → Settings → Secrets and variables → Actions**:

| Tipo | Nome | Valor |
|---|---|---|
| Variable | `CONTACT_EMAIL` | o Gmail do projeto (já existe: é o remetente e o destino do botão "Assinar") |
| Secret | `SMTP_PASSWORD` | a senha de app do passo 1 |
| Secret | `NEWSLETTER_RECIPIENTS` | os e-mails dos assinantes, separados por vírgula ou um por linha |
| Secret | `NEWSLETTER_TEST_EMAIL` | opcional: seu e-mail pessoal para testes (padrão: o Gmail do projeto) |

Opcionais: `SITE_URL` (padrão `https://<usuário>.github.io/<repositório>/`), `SMTP_USERNAME`
(padrão `CONTACT_EMAIL`) e `SUBSCRIBE_URL` (para trocar o link do botão).

O botão "Assinar" aparece no site na próxima vez que ele for gerado: na segunda-feira ou numa
execução manual do **Pipeline semanal**.

## Teste

Actions → **Enviar newsletter** → *Run workflow* com `mode: teste`. A edição publicada mais
recente vai para `NEWSLETTER_TEST_EMAIL` (ou para o Gmail do projeto), com "[TESTE]" no
assunto. Nada é registrado e ninguém da lista recebe.

## Reenviar aos assinantes manualmente

Se o envio de segunda falhar (por exemplo, senha errada), corrija o problema e rode
**Enviar newsletter** com `mode: assinantes`, `edition: N` e `confirm: ENVIAR edicao-00N`.
Edições já enviadas são recusadas.

## Uso local

```bash
python -m ufabc_science newsletter preview            # gera build/preview/newsletter/<slug>.html
python -m ufabc_science newsletter send --test        # só para NEWSLETTER_TEST_EMAIL
python -m ufabc_science newsletter send --edition 3   # para a lista (uma vez)
```

## Limitações

- E-mails enviados por um Gmail novo para muitas pessoas podem cair no spam nas primeiras
  semanas. Peça aos assinantes que marquem o e-mail como "não é spam" ou adicionem o
  remetente aos contatos.
- O endereço do projeto aparece no site (botão "Assinar") e pode receber spam.
- Se o envio falhar para alguém, a edição fica marcada como enviada para não duplicar para os
  demais. O resumo da execução mostra quantas falhas houve.
