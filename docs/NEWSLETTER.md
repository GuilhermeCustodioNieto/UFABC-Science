# Newsletter por e-mail

Toda segunda-feira, depois que a edição é publicada e o site entra no ar, o workflow
**Pipeline semanal** envia a edição por e-mail a todos os assinantes. O envio usa o
[Brevo](https://www.brevo.com/), que tem plano gratuito (cerca de 300 e-mails por dia, com a
marca do Brevo no rodapé; confira os limites atuais no site deles). O Brevo hospeda o
formulário de inscrição, a confirmação por e-mail (*double opt-in*) e o descadastro: o projeto
não guarda nenhum endereço de assinante.

```text
autopublish → site no ar → newsletter send → campanha no Brevo → lista de assinantes
```

- Cada edição é enviada **uma única vez** (marca em `editions/sent/<slug>.json` na branch
  `data`).
- O e-mail tem o mesmo texto aprovado do site, com links para as páginas do site.
- Edições publicadas automaticamente levam o aviso de que não houve revisão humana.
- Sem `BREVO_LIST_ID`, o envio simplesmente não acontece (o resto do pipeline segue normal).

## 1. Configurar o Brevo (uma vez)

1. Crie uma conta gratuita em <https://www.brevo.com/> com o e-mail do projeto.
2. **Remetente:** *Senders, Domains & Dedicated IPs* → *Senders* → adicione o e-mail do projeto
   e confirme o código que chega nele. Remetentes de domínios gratuitos (Gmail) podem ter a
   entrega afetada; o Brevo explica as opções na própria tela.
3. **Lista:** *Contacts* → *Lists* → *Create a list* (ex.: "Assinantes UFABC Science"). Anote
   o **ID** da lista (número que aparece na listagem).
4. **Formulário de inscrição:** *Contacts* → *Forms* → *Create a subscription form*: escolha a
   lista do passo 3 e ative a confirmação por e-mail (*double opt-in*). Ao final, copie o **link
   do formulário** (algo como `https://xxxx.sibforms.com/serve/...`).
5. **Chave da API:** menu do perfil → *SMTP & API* → *API Keys* → *Generate a new API key*.

## 2. Configurar o GitHub

**Settings → Secrets and variables → Actions**:

| Tipo | Nome | Valor |
|---|---|---|
| Secret | `BREVO_API_KEY` | chave do passo 1.5 |
| Secret | `NEWSLETTER_TEST_EMAIL` | seu e-mail pessoal, para envios de teste |
| Variable | `BREVO_LIST_ID` | ID da lista do passo 1.3 |
| Variable | `SUBSCRIBE_URL` | link do formulário do passo 1.4 (mostra o botão "Assinar" no site) |
| Variable | `NEWSLETTER_SENDER_EMAIL` | opcional; padrão `CONTACT_EMAIL` (deve ser o remetente verificado) |
| Variable | `SITE_URL` | opcional; padrão `https://<usuário>.github.io/<repositório>/` |

O botão "Assinar" aparece no site na próxima vez que ele for gerado (segunda-feira ou uma
execução manual do **Pipeline semanal**).

## 3. Enviar um teste

Actions → **Enviar newsletter** → *Run workflow* com `mode: teste` (os outros campos podem
ficar vazios). A edição publicada mais recente chega só no `NEWSLETTER_TEST_EMAIL`, com
"[TESTE]" no assunto. Nada é enviado aos assinantes e nada é registrado.

## 4. Reenviar aos assinantes manualmente

Se o envio de segunda falhar (ex.: chave errada), corrija e rode **Enviar newsletter** com
`mode: assinantes`, `edition: N` e `confirm: ENVIAR edicao-00N`. Edições já enviadas são
recusadas.

## Uso local

```bash
python -m ufabc_science newsletter preview                 # gera build/preview/newsletter/<slug>.html
python -m ufabc_science newsletter send --test --to voce@exemplo.org
python -m ufabc_science newsletter send --edition 3        # aos assinantes (uma vez)
```
