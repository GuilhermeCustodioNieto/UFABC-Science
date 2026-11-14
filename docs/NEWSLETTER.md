# Newsletter por e-mail

Toda segunda-feira, depois que a edição é publicada e o site entra no ar, o workflow
**Pipeline semanal** agenda a edição no [Kit](https://kit.com/) para todos os assinantes. O
envio sai cerca de 2 minutos depois.

O plano gratuito do Kit permite até 10.000 assinantes, envios ilimitados, formulários e
acesso à API ([central de ajuda do Kit](https://intercom.help/convertkit/en/articles/16627071-the-kit-free-plan)).
O Kit hospeda o formulário de inscrição e cuida do descadastro, então o projeto não guarda
nenhum endereço de assinante.

```text
autopublish → site no ar → newsletter send → POST /v4/broadcasts (Kit) → todos os assinantes
```

- Cada edição é enviada **uma única vez**. A marca fica em `editions/sent/<slug>.json`, na
  branch `data`.
- O e-mail usa o mesmo texto aprovado do site, com links para as páginas do site. O template
  padrão do Kit envolve esse conteúdo e acrescenta o link de descadastro e o endereço
  exigidos por lei.
- As edições publicadas automaticamente levam o aviso de que não houve revisão humana.
- Sem o secret `KIT_API_KEY`, o envio é pulado sem erro e o resto do pipeline segue normal.

## 1. Kit (uma vez)

Os nomes de menu do painel mudam com o tempo; procure pelos termos abaixo.

1. Crie uma conta gratuita em <https://kit.com/> com o e-mail do projeto. Confirme o
   remetente (*sending email address*) quando o Kit pedir. Os envios saem dele.
2. Crie um **formulário** ou uma **landing page** de inscrição e copie o **link público**
   dela. Esse link é o `SUBSCRIBE_URL`.
3. Gere uma **chave de API v4** nas configurações de desenvolvedor da conta (*Developer* /
   *API*). Essa chave é o `KIT_API_KEY`.
4. (Opcional, para testes) Crie uma **tag** chamada "teste", aplique-a ao seu próprio
   cadastro e anote o **ID numérico** da tag (aparece na URL da página da tag). Esse ID é o
   `KIT_TEST_TAG_ID`.

## 2. GitHub

**Settings → Secrets and variables → Actions**:

| Tipo | Nome | Valor |
|---|---|---|
| Secret | `KIT_API_KEY` | chave de API v4 do passo 1.3 |
| Variable | `SUBSCRIBE_URL` | link do formulário do passo 1.2 (exibe o botão "Assinar" no site) |
| Variable | `KIT_TEST_TAG_ID` | opcional, ID da tag do passo 1.4 |
| Variable | `NEWSLETTER_SENDER_EMAIL` | opcional; o padrão é o remetente da conta Kit |
| Variable | `SITE_URL` | opcional; o padrão é `https://<usuário>.github.io/<repositório>/` |

O botão "Assinar" aparece no site na próxima vez que ele for gerado: na segunda-feira ou numa
execução manual do **Pipeline semanal**.

## 3. Primeiro envio de teste

**Sem tag:** inscreva-se pelo seu próprio formulário e confirme o e-mail. Enquanto você for o
único assinante, rode Actions → **Enviar newsletter** com `mode: assinantes`, `edition: N` e
`confirm: ENVIAR edicao-00N` (N é a edição mais recente publicada). Isso marca a edição N
como enviada; as próximas edições continuam saindo normalmente às segundas.

**Com tag** (depois que houver outros assinantes): `mode: teste`. O envio vai só para quem
tem a tag `KIT_TEST_TAG_ID`, com "[TESTE]" no assunto, e nada é registrado.

## 4. Reenviar aos assinantes manualmente

Se o envio de segunda falhar (por exemplo, chave errada), corrija o problema e rode
**Enviar newsletter** com `mode: assinantes`, `edition: N` e `confirm: ENVIAR edicao-00N`.
Edições já enviadas são recusadas.

## Uso local

```bash
python -m ufabc_science newsletter preview            # gera build/preview/newsletter/<slug>.html
python -m ufabc_science newsletter send --test        # assinantes com a tag de teste
python -m ufabc_science newsletter send --edition 3   # todos os assinantes (uma vez)
```

## Limitações conhecidas

- Os limites do plano gratuito são definidos pelo Kit e podem mudar.
- Não está verificado se o Kit aceita um `@gmail.com` como remetente sem prejudicar a
  entrega, nem se o plano gratuito exibe a marca do Kit no e-mail.
- O agendamento usa `send_at` alguns minutos no futuro. Se o Kit devolver a newsletter como
  rascunho, o comando falha e não marca a edição como enviada.
