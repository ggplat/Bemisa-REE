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
  canada.py           -> TSX/CSE: feeds oficiais das empresas (RSS/site) + Yahoo
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
- **TSX/CSE** usam os **comunicados oficiais de cada empresa** (só publicações da própria
  empresa, sem ruído de setor): **EFR** (Energy Fuels) via scraping da página de press
  releases em `investors.energyfuels.com/news-releases` (cobre NYSE:UUUU / TSX:EFR);
  **ARA** (Aclara) via scraping do site oficial `aclara-re.com/news`; **API** (Appia) via
  RSS do site. A fonte de cada empresa fica em `companies.json` (campo `news`). Se uma
  fonte não retornar, a empresa aparece sem itens (sem quebrar a página). O Yahoo Finance
  segue disponível como tipo `yahoo` em `sources/canada.py` para quem precisar de um agregador.
- O **botão "atualizar"** recarrega a página. Para forçar uma nova coleta sob demanda,
  use **Run workflow** em Actions (a coleta roda no servidor, não no navegador).
