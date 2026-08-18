# Monitor de Comunicados REE

Dashboard que reúne, num só lugar, os comunicados das empresas de terras-raras
acompanhadas e mostra a **reação do mercado** (variação % do preço no dia de cada
comunicado). O dashboard é **gerado automaticamente** e cada linha de notícia
**leva direto ao comunicado** na bolsa.

- **Página publicada:** GitHub Pages (ver _Configuração_ abaixo).
- **Atualização:** automática 1×/dia útil + execução manual sob demanda.
- **Botão "atualizar"** na página recarrega a versão mais recente publicada.

## Como funciona

```
ree_monitor.py        -> coleta comunicados + calcula a % + gera docs/index.html
sources/              -> uma fonte por bolsa (interface comum, plugável)
  asx.py              -> ASX: markitdigital -> API JSON legada -> RSS (3 fontes)
  canada.py           -> TSX/CSE/NYSE American: feeds oficiais das empresas (RSS/site) + Yahoo
prices.py             -> Yahoo Finance (yfinance): variação % close-to-close
companies.json        -> empresas monitoradas (edite aqui)
templates/            -> template do dashboard (mesmo visual do original)
docs/index.html       -> SAÍDA gerada (publicada pelo GitHub Pages)
.github/workflows/    -> automação (agendada + manual)
```

A reação de mercado é a **variação % do fechamento no pregão do comunicado vs. o
pregão anterior** (close-to-close). Quando não há preço disponível, a linha mostra "—".

## Rodar localmente

```bash
pip install -r requirements.txt

# Dados reais (precisa de internet com acesso às fontes):
python ree_monitor.py --dashboard

# Dados de exemplo (offline, só para ver o visual):
python ree_monitor.py --sample

# Apenas algumas empresas:
python ree_monitor.py --dashboard --only ALV,BRE
```

Abra `docs/index.html` no navegador.

## Atualização automática (GitHub Actions)

O workflow `.github/workflows/update-dashboard.yml`:

1. Roda todo dia útil às 22:00 UTC (após o fechamento de ASX e TSX) **e** quando
   você clica em **Actions → "Atualizar dashboard" → Run workflow**.
2. Executa `python ree_monitor.py --dashboard`, commita o `docs/index.html`
   atualizado e publica no GitHub Pages.

### Configuração (uma vez)

1. **Settings → Pages →** _Build and deployment_ → **Source: GitHub Actions**.
2. Garanta que Actions tem permissão de escrita: **Settings → Actions → General →
   Workflow permissions → Read and write permissions**.
3. Pronto. O link público aparece em Settings → Pages e na aba do workflow.

## Editar a lista de empresas

Edite `companies.json` (ticker, bolsa, nome, símbolo no Yahoo Finance e link da
bolsa). Exemplo:

```json
{"ticker": "ALV", "exchange": "ASX", "name": "Alvo Minerals",
 "yf_symbol": "ALV.AX", "company_url": "https://www.asx.com.au/markets/company/ALV"}
```

## Limitações e notas

- **ASX** tem proteção anti-robô. Tentamos 3 fontes em ordem (markitdigital — a que o
  próprio site asx.com.au usa hoje —, depois a API JSON legada e, por fim, RSS por
  empresa). A primeira que responder vence. A partir do IP do GitHub Actions costuma
  funcionar; se uma fonte falhar, a coleta das demais empresas continua normalmente.
- **TSX/CSE/NYSE American** usam os **comunicados oficiais de cada empresa** (só publicações
  da própria empresa, sem ruído de setor): **EFR** (Energy Fuels) via scraping da página de
  press releases em `investors.energyfuels.com/news-releases` (cobre NYSE:UUUU / TSX:EFR);
  **ARA** (Aclara) via scraping do site oficial `aclara-re.com/news`; **API** (Appia) via
  RSS do site; **IMC** (IMC Rare Earths, NYSE American) via scraping da página de press
  releases em `ir.imcrareearths.com/news-events/news-releases` (plataforma de IR
  "Notified" — estrutura confirmada com dados reais).
  A fonte de cada empresa fica em `companies.json` (campo `news`). Se uma fonte não
  retornar, a empresa aparece sem itens (sem quebrar a página). O Yahoo Finance segue
  disponível como tipo `yahoo` em `sources/canada.py` para quem precisar de um agregador.
- O **botão "atualizar"** recarrega a página. Para forçar uma nova coleta sob demanda,
  use **Run workflow** em Actions (a coleta roda no servidor, não no navegador).
- O **menu de empresas** (chips no topo) é ordenado **alfabeticamente pelo ticker,
  ignorando a bolsa** — `companies.json` continua agrupado por bolsa só para
  facilitar a edição do arquivo.

---

# Pipeline diário — Dashboard REE v6

Automatiza **apenas as séries de mercado** do `Dashboard_REE_v6_Q2.html` (ARA,
BRE, MEI, SGQ, VMM): preço de fechamento, câmbio AUD/USD e CAD/USD, e volume
financeiro diário. Tudo o mais continua sob curadoria manual.

| Série | Quem atualiza |
|---|---|
| `stockCAD` / `stockAUD` (preço mensal) | pipeline |
| `cadusd` / `audusd` (câmbio mensal) | pipeline |
| `volData` (volume diário em USD) | pipeline |
| `sharesMap`, `cumInvK` | **você** — o pipeline só faz forward-fill sinalizado (ver abaixo) |
| `qBarK`, `issuances`, `projEvents` | **você**, sempre |

O market cap não é gravado em lugar nenhum: cada frame calcula
`shares × preço × câmbio` no navegador. Atualizar preço e câmbio basta.

## Arquivos

```
ree_v6.py               -> primitivas compartilhadas (config, meses, edição do srcdoc)
fetch_market_data.py    -> coleta via yfinance + QC -> data/market_data.json
update_dashboard.py     -> aplica os dados ao HTML, com backup e validação
notify.py               -> alerta por e-mail (Gmail SMTP)
tools/render_check.js   -> renderiza os 5 frames com jsdom + D3 e caça NaN
data/market_data.json   -> fonte de verdade, separada do HTML
logs/pipeline.jsonl     -> trilha de auditoria (uma linha JSON por execução)
```

## Rodar manualmente

```bash
pip install -r requirements.txt
npm install --no-save jsdom d3@7          # só para a checagem de renderização

python fetch_market_data.py -v            # coleta os últimos 45 dias + QC
python update_dashboard.py --dry-run      # mostra o que mudaria, sem gravar
python update_dashboard.py -v             # aplica, com backup datado
python notify.py --dry-run                # imprime o e-mail que seria enviado
```

Opções úteis:

- `--full` — rebaixa o histórico inteiro (use na primeira execução)
- `--only ARA,BRE` — limita a coleta a alguns tickers
- `--frames 0,1` — limita a aplicação a alguns frames
- `--calibrate` — compara a agregação mensal com os valores já no HTML (veja abaixo)

## Automação

O workflow **"Atualizar Dashboard REE v6"** roda às **22:30 UTC de segunda a
sexta** (após o fechamento de ASX e TSX) e também sob demanda em
_Actions → Run workflow_. Ele coleta, valida, aplica, commita e avisa por e-mail.

Segredos a configurar em _Settings → Secrets and variables → Actions_:

| Nome | Tipo | Para quê |
|---|---|---|
| `GMAIL_USER` | secret | conta remetente do alerta |
| `GMAIL_APP_PASSWORD` | secret | App Password do Gmail (não é a senha da conta) |
| `ALERT_TO` | variable | destinatário (padrão: `gisrael@bemisa.com.br`) |

Sem os segredos o pipeline **continua funcionando** — só registra no log que o
e-mail não pôde ser enviado. Dado validado não depende de alerta para ser aplicado.

O workflow antigo **"Atualizar Dashboard MCap REE"** (e `mcap_dashboard.py`/
`docs/mcap_dashboard.html`) cobria as mesmas 5 empresas e manteria duas fontes
de verdade divergentes — foi removido do repositório (ainda recuperável no
histórico do git se precisar de referência).

## Camadas de proteção

Nada é gravado no dashboard de produção sem passar por todas estas checagens:

1. **QC dos dados** — outlier, gap, valor ausente ou revisão retroativa do
   provedor. Dado reprovado não entra, e nada é interpolado ou estimado.
2. **Invariantes do frame** — todo mês presente no dict de preço tem de existir
   em `sharesMap` e `cumInvK`; `volData` tem de continuar JSON válido, ordenado
   e sem duplicatas.
3. **`node --check`** no script de cada frame alterado.
4. **Identidade visual** — falha se a contagem de `#7C9640`, `#414042`,
   `Carlito`, dos 5 iframes ou do logo base64 mudar.
5. **Renderização** — os 5 frames são desenhados com jsdom + D3 e reprovados se
   qualquer atributo SVG sair como `NaN`.
6. **Backup datado** — `Dashboard_REE_v6_Q2_backup_AAAAMMDD.html` antes de
   sobrescrever (ignorado pelo git; o histórico do repositório é o backup oficial).

Se qualquer uma falhar, a execução aborta e **o HTML de produção não é tocado**.

## Forward-fill sinalizado (leia isto)

O JS de cada frame monta a série com `monthOrder = Object.keys(stockAUD)` e
depois lê `sharesMap[m]` direto e `cumInvK[m] || 0`. Quando um mês novo abre no
preço sem entrada correspondente nesses dois dicts, o resultado é:

- `sharesMap[m]` indefinido → `mcap = NaN` → **a linha de market cap some**
- `cumInvK[m]` ausente → `0` → **a área de investimento despenca a zero**

Por isso, ao abrir um mês novo, o pipeline repete o último valor conhecido e
deixa marca no próprio código:

```js
"jul/26":246577297,  // forward-fill automático — confirmar (Appendix 2A/3B/5B)
```

Isso **repete um número já existente, não cria um número novo** — é a mesma
convenção que o arquivo já usa à mão. Mas é o seu sinal para conferir o valor
real na fonte primária (Appendix 2A/3B/5B para ações; Nota 10 e segment notes
para investimento) e substituir. O e-mail destaca cada forward-fill pendente.

## Como ler os logs

`logs/pipeline.jsonl` tem uma linha JSON por execução, com `step` igual a
`fetch` ou `update`:

```bash
tail -2 logs/pipeline.jsonl | python -m json.tool          # última execução
grep -c '"kind"' logs/pipeline.jsonl                       # total de anomalias
python -c "import json;[print(l['timestamp_utc'], l['step'], len(l.get('flags',[]))) \
  for l in map(json.loads, open('logs/pipeline.jsonl'))]"  # linha do tempo
```

Campos: `run_id`, `timestamp_utc`, `source`, `symbols`, `fetched` (o que veio do
provedor), `applied` (o que entrou no HTML), `flags` (anomalias), `backup_file`
e `duration_s`.

## Quando chega um alerta de anomalia

O e-mail lista cada anomalia e o que fazer. Em resumo:

| Flag | O que significa | O que fazer |
|---|---|---|
| `outlier_pct` | preço variou mais de 20% num pregão | confira o comunicado na ASX/SEDAR; se for real, `--force-ticker <TICKER>` |
| `outlier_fx` | câmbio variou mais de 3% num dia | quase sempre é dado ruim do provedor; confira antes de forçar |
| `revision` | o provedor mudou um valor já gravado | o valor antigo foi mantido; decida se a revisão procede |
| `gap` | o provedor parou de responder | nada foi preenchido; se persistir, verifique se o ticker mudou de código |
| `fx_missing` | sem câmbio do dia | o volume daquele dia não é calculado; nenhuma taxa é estimada |
| `volume_missing` | provedor não retornou volume | o dia fica sem barra no gráfico de volume |
| `invalid_price` | fechamento nulo, zero ou negativo | dia descartado; nem `--force` aplica |

**`--force-ticker` só depois de conferir a fonte primária.** Ele existe para
movimentos reais (um comunicado que de fato moveu o papel 30%), não para calar
o alarme.

## Agregação mensal

O valor mensal é a **média aritmética simples dos fechamentos do mês**. O mês
corrente é recalculado a cada execução; **mês fechado nunca é recalculado** —
uma vez gravado, é histórico.

Antes de confiar na série longa, rode uma vez:

```bash
python fetch_market_data.py --full && python fetch_market_data.py --calibrate
```

O gerador antigo (`mcap_dashboard.py`) usava `(anterior + fechamento) / 2`
acumulativo, que **não é média** e pesa fortemente o último dia do mês. Se os
valores históricos do dashboard vieram dali, haverá um degrau entre meses
antigos e novos. O `--calibrate` mede esse desvio e reporta — a decisão de
aceitar ou reprocessar o histórico é sua.

## Publicação

O pipeline grava `docs/dashboard_ree_v6.html` e commita; a publicação em si é
feita pelo job `deploy` do próprio `update-dashboard.yml` (`path: docs`), o
mesmo que publica o dashboard de comunicados. URL estável:
`<pages>/docs/dashboard_ree_v6.html`.

Havia um segundo workflow (`deploy-pages.yml`) publicando a raiz do repo
(`path: .`), que competia com este. Na prática nunca chegou a causar problema
porque o trigger dele era `push: branches: [main]` e todo o trabalho real
acontece em `claude/vigilant-babbage-9c6e1o` (`main` está obsoleta) — ou seja,
esse workflow tinha 0 execuções reais (confirmado via GitHub Actions). Ainda
assim era um risco latente (dispararia se alguém desse push em `main`) e
deixava um `index.html` morto na raiz do repo como pegadinha. Removidos os
dois — só sobra o publicador que já funcionava de verdade.
