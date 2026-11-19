# Radar de passagens SP → Lisboa

> **Situação (19/11/2026):** o radar roda na VPS da Hostinger, em `/opt/radar`, separado do CRM: WAHA próprio (sessão com o número do Júnior), varredura a cada 3 horas e ponto de envio assinado em `https://radar.moovcrm.tech/enviar` (o único elo com o CRM é um bloco no Caddyfile dele, que repassa esse endereço). O agendamento do GitHub Actions está desligado. Todos os avisos vão só para a Bianca (decisão de 19/11/2026): alerta de preço até `teto_por_pessoa` e o resumo diário das 9h. Novo mínimo ou queda acima do teto e falhas técnicas não geram mensagem, ficam só no log (`$DC logs radar`).
>
> Comandos na VPS (como root):
>
> ```
> DC="docker compose -p radar -f /opt/radar/app/vps/docker-compose.yml --env-file /opt/radar/.env"
> git -C /opt/radar/app pull && $DC up -d --build     # atualizar
> $DC logs --tail 50 radar                           # ver o que aconteceu
> $DC exec radar python vps/parear.py                # reconectar o WhatsApp (QR no terminal)
> $DC exec -e WHATSAPP_DESTINO=55DDDNUMERO radar python radar.py --exemplo-alerta   # alerta de teste para outro número
> $DC exec radar python radar.py --enviar-resumo     # varredura agora + resumo para a Bianca
> ```
>
> Outros comandos assinados do mesmo jeito (corpo só com `ts` e `nonce`): POST `/precos` devolve as 10 melhores combinações da última varredura; POST `/varrer` faz uma varredura na hora e manda o resumo para a Bianca (no máximo uma a cada 30 minutos).
>
> O POST `/enviar` exige o cabeçalho `X-Assinatura` (HMAC-SHA256 do corpo com o `RELAY_SECRET` de `/opt/radar/.env`) e o corpo `{"publico": "alerta"|"interno", "texto": "...", "ts": <unix>, "nonce": "<8 a 64 caracteres>", "chave": "<opcional, evita repetir em 24h>"}`. Limite: 6 mensagens por hora e 20 por dia. Ele só envia para os números do `.env`.

Varre automaticamente, a cada 3 horas (inclusive de madrugada), todas as combinações:

- Origem: GRU, VCP e CGH
- Ida: 28, 29 ou 30/04/2027
- Volta: 20 a 25/05/2027
- Econômica, qualquer companhia, qualquer número de conexões

São 54 consultas por varredura (3 aeroportos x 3 idas x 6 voltas). O preço é sempre por pessoa; o alerta mostra também a estimativa para 2 pessoas.

## Quando ele avisa

1. Preço por pessoa abaixo do teto (`teto_por_pessoa` no `config.json`, hoje R$ 4.500). Abaixo de `teto_urgente_por_pessoa` (R$ 3.800) a mensagem sai marcada como preço excepcional.
2. Menor preço desde que o radar começou (com margem de R$ 50 para evitar ruído).
3. Queda de 10% ou mais sobre a média dos últimos 7 dias.

As regras 2 e 3 só passam a valer depois de 3 varreduras de histórico. Depois de um alerta, ele fica 24h sem repetir, a menos que o preço caia mais R$ 50.

Além dos alertas:

- Todo dia, a partir das 9h, chega um resumo com as 5 melhores combinações das últimas 24h. Serve também para saber que o radar está vivo.
- Se duas varreduras seguidas vierem sem nenhum preço, chega um aviso de falha.

Quem recebe o quê no WhatsApp:

- Alertas de oferta: `WHATSAPP_DESTINO` (a Bianca; pode incluir você, separando por vírgula).
- Resumo diário, avisos de falha e testes: só `WHATSAPP_INTERNO` (você).

Telegram e e-mail, se configurados, recebem tudo.

## Fontes de preço

- **fast-flights** (gratuita): lê o Google Flights. É a fonte principal.
- **SerpApi** (opcional, 250 buscas grátis por mês): confirma a oferta antes do alerta, informando se o Google classifica o preço como baixo, típico ou alto. Também entra como reserva se a fonte principal parar de funcionar. O script respeita um limite de 240 buscas por mês.

## Configuração (uma vez, cerca de 20 minutos)

### 1. Criar o repositório no GitHub

1. Crie uma conta em github.com, se ainda não tiver.
2. Clique em **New repository**, dê o nome `radar-passagens` e marque **Private**. Use privado: o GitHub desativa agendamentos de repositórios públicos depois de 60 dias sem atividade, e a viagem é daqui a mais de 5 meses.
3. Na página do repositório, clique em **Add file > Upload files** e envie `radar.py`, `config.json`, `requirements.txt`, `README.md` e a pasta `data`.
4. A pasta `.github` costuma ficar oculta no computador. Crie o arquivo direto no site: **Add file > Create new file**, digite no nome `.github/workflows/radar.yml` (as barras criam as pastas), cole o conteúdo do arquivo `radar.yml` e clique em **Commit changes**.

### 2. WhatsApp pelo seu número (WAHA)

O WAHA é gratuito e liga o seu WhatsApp como um "aparelho conectado", igual ao WhatsApp Web. Ele precisa ficar ligado 24h num servidor (VPS). Pode ser a mesma VPS do CRM: o WAHA aceita várias sessões.

1. Na VPS (com Docker instalado), rode:

   ```
   docker run -d --restart unless-stopped --name waha -p 3000:3000 \
     -v /root/waha-sessions:/app/.sessions \
     -e WAHA_API_KEY=CRIE_UMA_CHAVE_LONGA \
     -e WAHA_DASHBOARD_USERNAME=admin \
     -e WAHA_DASHBOARD_PASSWORD=CRIE_UMA_SENHA \
     devlikeapro/waha
   ```

2. Abra `http://IP_DA_VPS:3000/dashboard`, entre com o usuário e a senha, crie a sessão `default` e escaneie o QR code pelo celular (WhatsApp > Aparelhos conectados > Conectar aparelho).
3. O ideal é colocar um domínio com HTTPS na frente (Caddy ou Nginx), porque com `http://` a chave trafega aberta. Para começar, o IP com a porta funciona.
4. Números no formato internacional, só dígitos: `55` + DDD + número (ex.: `5561999998888`). O radar confere sozinho o problema do 9º dígito dos números antigos.

Risco: o WAHA não é a API oficial do WhatsApp. Com poucas mensagens para um contato que já conversa com você, o risco é baixo, mas não é zero. Se o seu número for o mesmo que você usa para vender, prefira um segundo chip.

### 3. Criar o bot do Telegram (opcional)

1. No Telegram, abra a conversa com **@BotFather**, envie `/newbot` e siga as instruções. Ele devolve um token parecido com `123456789:AAH...`. Guarde.
2. Abra a conversa com o seu bot recém-criado e envie qualquer mensagem (por exemplo, "oi").
3. No navegador, abra `https://api.telegram.org/botSEU_TOKEN/getUpdates`, trocando `SEU_TOKEN` pelo token. Procure `"chat":{"id":` e copie o número. Esse é o seu chat ID.
4. Para a sua chefe também receber: ela manda uma mensagem para o mesmo bot, você abre o link de novo e copia o ID dela. Os dois IDs vão no mesmo campo, separados por vírgula.

### 4. SerpApi (opcional, recomendado)

Crie uma conta em serpapi.com (plano Free) e copie a sua API key no painel.

### 5. Cadastrar os segredos no GitHub

No repositório: **Settings > Secrets and variables > Actions > New repository secret**. Crie:

| Nome | Valor |
|---|---|
| `WAHA_URL` | endereço do WAHA, ex.: `http://IP_DA_VPS:3000` |
| `WAHA_API_KEY` | a chave que você pôs em `WAHA_API_KEY` |
| `WAHA_SESSION` | `default` |
| `WHATSAPP_DESTINO` | número da Bianca (e o seu, se quiser receber os alertas também) |
| `WHATSAPP_INTERNO` | o seu número |
| `TELEGRAM_BOT_TOKEN` | token do BotFather |
| `TELEGRAM_CHAT_ID` | seu chat ID (e o da chefe, separados por vírgula) |
| `SERPAPI_KEY` | chave da SerpApi (opcional) |

E-mail é opcional e pode funcionar junto com o Telegram. Para usar, crie também:

| Nome | Valor |
|---|---|
| `EMAIL_REMETENTE` | endereço Gmail que vai enviar |
| `EMAIL_SENHA_APP` | senha de app do Gmail (Conta Google > Segurança > Senhas de app; exige verificação em duas etapas) |
| `EMAIL_DESTINO` | quem recebe, separados por vírgula |

### 6. Testar

1. Aba **Actions**. Se aparecer um aviso pedindo para habilitar workflows, habilite.
2. Clique em **Radar de passagens SP-Lisboa > Run workflow**, preencha o modo com `teste-aviso` e rode. Deve chegar uma mensagem de teste no seu WhatsApp.
3. Rode com `teste-bianca`. A mensagem de teste chega no WhatsApp da Bianca, enviada pelo seu número. Avise ela antes.
4. Rode de novo com o modo `normal`. A varredura leva uns 4 minutos. Ao terminar, o arquivo `data/historico.csv` é atualizado no repositório.

Se o passo de salvar o histórico falhar com erro de permissão: **Settings > Actions > General > Workflow permissions > Read and write permissions**.

A partir daí roda sozinho às 0h, 3h, 6h, 9h, 12h, 15h, 18h e 21h (Brasília). O GitHub pode atrasar o início em alguns minutos nos horários de pico.

## Ajustes

Tudo fica no `config.json`. Para editar, abra o arquivo no GitHub e clique no lápis:

- `teto_por_pessoa`: preço que dispara alerta direto.
- `queda_minima_pct`: queda sobre a média de 7 dias que dispara alerta.
- `origens`: tirar `CGH` reduz a varredura para 36 consultas. CGH não tem voo internacional, então sempre inclui uma conexão doméstica.
- Datas: `ida_inicio`, `ida_fim`, `volta_inicio`, `volta_fim`.

## Custos e limites

- **GitHub Actions:** cada varredura gasta cerca de 5 minutos. São cerca de 1.200 minutos por mês, dentro dos 2.000 gratuitos do plano Free para repositório privado.
- **SerpApi:** só gasta quando há alerta (1 busca) ou quando a fonte principal falha (até 18 buscas, no máximo uma vez a cada 20h).

## Pontos de atenção

- A fast-flights não é uma API oficial. Se o Google mudar o site, ela pode parar até a biblioteca ser atualizada. O aviso de falha existe para isso, e a SerpApi cobre a lacuna. Para atualizar, troque a versão no `requirements.txt`.
- O preço é o da busca. A tarifa mais barata às vezes não tem 2 assentos disponíveis. Abra o link do alerta (já vem com 2 adultos) e confira antes de comprar.
- O preço não inclui bagagem despachada.
- Depois da compra, desative o radar em **Actions > Radar de passagens SP-Lisboa > ... > Disable workflow**.

## Rodar no próprio computador (opcional)

```
pip install -r requirements.txt
python radar.py --teste          # simula preços, sem internet, para ver as mensagens
python radar.py                  # varredura real (sem segredos configurados, imprime na tela)
```
