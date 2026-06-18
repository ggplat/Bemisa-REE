"""
dashboard.py — Gera docs/index.html com dados ao vivo das ações REE via yfinance.

Uso:
    python dashboard.py

Saída: docs/index.html (publicado pelo GitHub Pages)
"""
from __future__ import annotations

import datetime as dt
import logging
import os
from typing import Optional

import yfinance as yf

log = logging.getLogger("dashboard")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

# ── CONFIGURAÇÃO DAS AÇÕES ────────────────────────────────────────────────────

STOCKS = [
    {"id": "ara", "yf": "ARA.TO", "ticker": "ARA", "exchange": "TSX", "currency": "CAD",
     "name": "Aclara Resources Inc.",           "project": "Carina · Brasil"},
    {"id": "bre", "yf": "BRE.AX", "ticker": "BRE", "exchange": "ASX", "currency": "AUD",
     "name": "Brazilian Rare Earths Ltd.",       "project": "BRE · Brasil"},
    {"id": "mei", "yf": "MEI.AX", "ticker": "MEI", "exchange": "ASX", "currency": "AUD",
     "name": "Meteoric Resources NL",            "project": "Caldeira · Brasil"},
    {"id": "rau", "yf": "RAU.AX", "ticker": "RAU", "exchange": "ASX", "currency": "AUD",
     "name": "Resouro Strategic Metals Ltd.",    "project": "Itamogi · Brasil"},
    {"id": "sgq", "yf": "SGQ.AX", "ticker": "SGQ", "exchange": "ASX", "currency": "AUD",
     "name": "St. George Mining Ltd.",           "project": "Araxá · Brasil"},
    {"id": "vmm", "yf": "VMM.AX", "ticker": "VMM", "exchange": "ASX", "currency": "AUD",
     "name": "Viridis Mining and Minerals Ltd.", "project": "Colossus · Brasil"},
]

FX_SYMBOLS = {
    "CAD": "CADUSD=X",
    "AUD": "AUDUSD=X",
}

# Último fechamento conhecido — fallback quando yfinance não está disponível.
# Atualizado automaticamente pelo GitHub Actions; usado como seed inicial.
FALLBACK: dict[str, dict] = {
    "fx": {
        "CAD": 0.7338,   # mar/2026
        "AUD": 0.6310,   # dez/2025
    },
    "stocks": {
        "ara": {"price": 3.1514, "date": "2026-03-31", "shares": 219985221},
        "bre": {"price": 4.6500, "date": "2025-12-31", "shares": 275713606},
        "mei": {"price": 0.0920, "date": "2025-12-31", "shares": 2646398877},
        "rau": {"price": None,   "date": None,          "shares": None},
        "sgq": {"price": 0.0430, "date": "2025-12-31", "shares": 1124244808},
        "vmm": {"price": 0.1200, "date": "2025-12-31", "shares": 503350000},
    },
}

# ── FETCH ─────────────────────────────────────────────────────────────────────

def fetch_last_close(yf_symbol: str) -> tuple[Optional[float], Optional[str]]:
    """Retorna (preço de fechamento, data ISO) do último pregão disponível."""
    try:
        hist = yf.Ticker(yf_symbol).history(period="5d", auto_adjust=False)
        if hist.empty:
            log.warning("%s: histórico vazio", yf_symbol)
            return None, None
        price = float(hist["Close"].iloc[-1])
        date  = hist.index[-1].date().isoformat()
        log.info("  %s: %.4f (%s)", yf_symbol, price, date)
        return price, date
    except Exception as e:
        log.error("%s: %s", yf_symbol, e)
        return None, None


def fetch_shares(yf_symbol: str) -> Optional[int]:
    """Retorna ações em circulação via .info."""
    try:
        info = yf.Ticker(yf_symbol).info
        val = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
        return int(val) if val else None
    except Exception as e:
        log.error("%s shares: %s", yf_symbol, e)
        return None


def fetch_all() -> dict:
    """
    Retorna dict com:
      fx[currency] = float
      stocks[id]   = {price, date, shares, mcap_usd_m}

    Usa FALLBACK para qualquer valor que yfinance não consiga retornar,
    garantindo que o HTML sempre exibe dados (ao menos os mais recentes hardcoded).
    """
    # FX — yfinance tem prioridade; fallback se falhar
    fx: dict[str, Optional[float]] = {}
    for cur, sym in FX_SYMBOLS.items():
        if any(s["currency"] == cur for s in STOCKS):
            log.info("Buscando FX %s/USD...", cur)
            rate, _ = fetch_last_close(sym)
            fx[cur] = rate or FALLBACK["fx"].get(cur)

    # Ações
    stocks: dict[str, dict] = {}
    for s in STOCKS:
        log.info("Buscando %s (%s)...", s["ticker"], s["yf"])
        fb = FALLBACK["stocks"].get(s["id"], {})
        price, date = fetch_last_close(s["yf"])
        shares      = fetch_shares(s["yf"])
        # Aplica fallback por campo individualmente
        price  = price  or fb.get("price")
        date   = date   or fb.get("date")
        shares = shares or fb.get("shares")
        rate   = fx.get(s["currency"])
        mcap   = (price * shares * rate / 1e6) if (price and shares and rate) else None
        stocks[s["id"]] = {
            "price":      price,
            "date":       date,
            "shares":     shares,
            "fx":         rate,
            "mcap_usd_m": mcap,
        }

    return {"fx": fx, "stocks": stocks}


# ── HTML ──────────────────────────────────────────────────────────────────────

CSS = """
:root {
  --bg: #07090f; --surface: #0d1018; --surface2: #131720;
  --border: rgba(255,255,255,0.07); --text: #e8e4dc;
  --muted: #6b6760; --gold: #c9a84c; --teal: #4ec9b0;
  --green: #6bc98a; --blue: #5ca8e0;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--bg); color: var(--text);
  font-family: 'DM Sans', sans-serif; font-size: 13px;
  min-height: 100vh; padding: 40px 32px 60px;
}
header {
  display: flex; justify-content: space-between; align-items: flex-end;
  margin-bottom: 40px; padding-bottom: 20px;
  border-bottom: 1px solid var(--border);
}
header h1 {
  font-family: 'Cormorant Garamond', serif; font-size: 26px;
  font-weight: 300; letter-spacing: 0.04em;
}
header h1 em { color: var(--gold); font-style: italic; }
.updated {
  font-family: 'DM Mono', monospace; font-size: 9px;
  color: var(--muted); letter-spacing: 0.1em; text-align: right;
}
.updated span { color: var(--green); }
table {
  width: 100%; border-collapse: collapse; table-layout: fixed;
}
th {
  font-family: 'DM Mono', monospace; font-size: 9px; font-weight: 400;
  letter-spacing: 0.13em; text-transform: uppercase; color: var(--muted);
  padding: 10px 16px; text-align: right; border-bottom: 1px solid var(--border);
}
th:first-child { text-align: left; }
td {
  padding: 18px 16px; border-bottom: 1px solid rgba(255,255,255,0.04);
  vertical-align: middle;
}
tr:last-child td { border-bottom: none; }
tr:hover td { background: rgba(255,255,255,0.018); }
.company { display: flex; flex-direction: column; gap: 3px; }
.company-ticker {
  font-family: 'DM Mono', monospace; font-size: 14px;
  font-weight: 400; color: var(--gold); letter-spacing: 0.06em;
}
.company-name { font-size: 12px; color: var(--text); font-weight: 300; }
.company-project { font-size: 10px; color: var(--muted); font-family: 'DM Mono', monospace; letter-spacing: 0.05em; }
.exchange-badge {
  display: inline-block; font-family: 'DM Mono', monospace; font-size: 9px;
  letter-spacing: 0.1em; padding: 2px 7px;
  border: 1px solid var(--border); border-radius: 2px; color: var(--muted);
}
.num {
  font-family: 'Cormorant Garamond', serif; font-size: 20px;
  font-weight: 300; text-align: right;
}
.num.price { color: var(--text); }
.num.fx    { color: var(--muted); font-size: 17px; }
.num.mcap  { color: var(--teal); }
.num sup   { font-size: 11px; color: var(--muted); margin-right: 2px; font-family: 'DM Mono', monospace; }
.num.na    { color: var(--muted); font-size: 13px; font-family: 'DM Mono', monospace; }
.date-badge {
  font-family: 'DM Mono', monospace; font-size: 9px;
  color: var(--green); border: 1px solid rgba(107,201,138,0.3);
  border-radius: 2px; padding: 2px 6px; white-space: nowrap;
}
"""

def fmt_price(price: Optional[float], currency: str) -> str:
    if price is None:
        return '<span class="num na">—</span>'
    return f'<span class="num price"><sup>{currency}</sup>{price:.4f}</span>'

def fmt_fx(rate: Optional[float], currency: str) -> str:
    if rate is None:
        return '<span class="num na">—</span>'
    return f'<span class="num fx">{rate:.4f}</span>'

def fmt_mcap(mcap: Optional[float]) -> str:
    if mcap is None:
        return '<span class="num na">—</span>'
    if mcap >= 1000:
        return f'<span class="num mcap"><sup>USD</sup>{mcap/1000:.2f}<small style="font-size:13px;color:var(--muted)">B</small></span>'
    return f'<span class="num mcap"><sup>USD</sup>{mcap:.0f}<small style="font-size:13px;color:var(--muted)">M</small></span>'

def fmt_date(date: Optional[str]) -> str:
    if not date:
        return '<span class="num na">—</span>'
    return f'<span class="date-badge">{date}</span>'


def render_html(data: dict, updated: str) -> str:
    rows_html = ""
    for s in STOCKS:
        d = data["stocks"][s["id"]]
        rows_html += f"""
  <tr>
    <td>
      <div class="company">
        <span class="company-ticker">{s["ticker"]}</span>
        <span class="company-name">{s["name"]}</span>
        <span class="company-project">{s["project"]}</span>
      </div>
    </td>
    <td style="text-align:center"><span class="exchange-badge">{s["exchange"]}</span></td>
    <td>{fmt_date(d["date"])}</td>
    <td>{fmt_price(d["price"], s["currency"])}</td>
    <td>{fmt_fx(d["fx"], s["currency"])}</td>
    <td>{fmt_mcap(d["mcap_usd_m"])}</td>
  </tr>"""

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>REE Monitor — Market Cap Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;1,300&family=DM+Mono:wght@300;400&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head>
<body>
<header>
  <h1>REE Monitor &mdash; <em>Market Cap Dashboard</em></h1>
  <div class="updated">
    Dados via Yahoo Finance<br>
    Atualizado em <span>{updated}</span>
  </div>
</header>

<table>
  <thead>
    <tr>
      <th style="width:28%">Empresa</th>
      <th style="width:8%;text-align:center">Bolsa</th>
      <th style="width:12%">Fechamento</th>
      <th style="width:16%">Preço Último Fech.</th>
      <th style="width:14%">Câmbio / USD</th>
      <th style="width:16%">Market Cap</th>
    </tr>
  </thead>
  <tbody>{rows_html}
  </tbody>
</table>
</body>
</html>"""


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main() -> None:
    now = dt.datetime.utcnow()
    updated_str = now.strftime("%d/%m/%Y %H:%M UTC")

    data = fetch_all()

    html = render_html(data, updated_str)
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "index.html")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    log.info("Gerado: %s (%d bytes)", out_path, len(html))


if __name__ == "__main__":
    main()
