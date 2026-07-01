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
     "name": "Resouro Strategic Metals Ltd.",    "project": "Tiros · Brasil"},
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
        "rau": {"price": 0.3200, "date": "2026-06-17",   "shares": None},
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
:root{
  --bg:#f4f5ef; --panel:#ffffff; --panel2:#eef1e6; --line:#e0e3d6;
  --txt:#414042; --mut:#6f7168; --dim:#9a9c92;
  --asx:#6f8a36; --tsx:#00557f;
  --up:#4f7a1f; --down:#c0392b;
  --mark:#7c9640;
}
html[data-theme="dark"]{
  --bg:#1b1d17; --panel:#23261e; --panel2:#2a2d23; --line:#393c30;
  --txt:#eef0e4; --mut:#abada0; --dim:#76786b;
  --asx:#a7af39; --tsx:#6bb3dd;
  --up:#9ccc4e; --down:#e5736b;
  --mark:#a7af39;
}
*{box-sizing:border-box;margin:0;padding:0}
body{
  background:var(--bg); color:var(--txt);
  font-family:Calibri,"Segoe UI",Carlito,system-ui,-apple-system,sans-serif;
  font-size:15px; line-height:1.45; -webkit-font-smoothing:antialiased;
  padding-bottom:50px;
}
header{
  position:sticky; top:0; z-index:30; background:var(--bg);
  background-image:linear-gradient(118deg,color-mix(in srgb,var(--mark) 12%,transparent),transparent 45%);
  border-bottom:1px solid var(--line); padding:13px 16px 10px;
}
.title-row{display:flex; align-items:flex-start; justify-content:space-between; gap:10px}
.wordmark{display:flex; align-items:center; gap:6px; font-weight:700; font-size:11px;
  letter-spacing:2.5px; color:var(--txt); margin-bottom:3px}
.wm-mark{width:9px; height:9px; background:var(--mark); display:inline-block}
h1{font-size:18px; font-weight:700; letter-spacing:-.2px; color:var(--txt)}
h1 .sub{color:var(--mut); font-weight:600}
.head-actions{display:flex; gap:6px; align-items:center}
.theme-btn{
  background:var(--panel); color:var(--mut); border:1px solid var(--line);
  border-radius:7px; padding:5px 10px; font-size:13px; cursor:pointer;
  font-family:inherit;
}
.theme-btn:hover{color:var(--txt); border-color:var(--mut)}
.stats{display:flex; gap:16px; margin-top:9px; font-size:12.5px; color:var(--mut);
  flex-wrap:wrap; font-variant-numeric:tabular-nums}
.stats b{color:var(--txt); font-weight:700}
main{padding:12px 16px}
table{
  width:100%; border-collapse:collapse;
  background:var(--panel); border:1px solid var(--line);
  border-radius:12px; overflow:hidden;
}
thead tr{background:var(--panel2)}
th{
  padding:10px 14px; text-align:right;
  font-size:11px; font-weight:700; letter-spacing:.6px;
  text-transform:uppercase; color:var(--mut);
  border-bottom:1px solid var(--line); white-space:nowrap;
}
th:first-child{text-align:left; padding-left:18px}
th:last-child{padding-right:18px}
td{
  padding:14px 14px; border-bottom:1px solid var(--line);
  vertical-align:middle; text-align:right;
}
td:first-child{text-align:left; padding-left:0}
td:last-child{padding-right:18px}
tbody tr:last-child td{border-bottom:none}
tbody tr:hover td{background:color-mix(in srgb,var(--mark) 5%,transparent)}
.co-cell{
  display:flex; align-items:center; gap:0;
  border-left:3px solid var(--excolor,var(--mut));
  padding-left:15px;
}
.co-info{display:flex; flex-direction:column; gap:2px}
.co-tk{font-weight:700; font-size:15px; letter-spacing:.4px; color:var(--txt)}
.co-name{font-size:12px; color:var(--mut)}
.co-proj{font-size:11px; color:var(--dim)}
.co-meta{display:flex; align-items:center; gap:8px; margin-top:3px}
.co-meta .val{font-size:12px}
.badge{
  display:inline-block; font-size:10px; font-weight:700; padding:2px 7px;
  border-radius:5px; letter-spacing:.4px; white-space:nowrap;
}
.badge.ex-asx{color:var(--asx); background:color-mix(in srgb,var(--asx) 14%,transparent)}
.badge.ex-tsx{color:var(--tsx); background:color-mix(in srgb,var(--tsx) 14%,transparent)}
.val{font-variant-numeric:tabular-nums; font-size:14px; font-weight:600; color:var(--txt)}
.val.price{}
.val.fx{color:var(--mut); font-weight:400}
.val.mcap{color:var(--asx)}
.val.mcap.tsx{color:var(--tsx)}
.val-unit{font-size:11px; font-weight:400; color:var(--dim); margin-right:2px}
.val-suffix{font-size:11px; font-weight:400; color:var(--mut); margin-left:1px}
.val.na{color:var(--dim); font-weight:400}
.date-tag{
  display:inline-block; font-size:11px; color:var(--mut);
  font-variant-numeric:tabular-nums;
}
"""

JS_HEAD = """
(function(){
  try {
    const t = localStorage.getItem('theme');
    if(t) document.documentElement.setAttribute('data-theme', t);
  } catch(e){}
})();
"""

JS_BODY = """
function toggleTheme(){
  const h = document.documentElement;
  const dark = h.getAttribute('data-theme') === 'dark';
  h.setAttribute('data-theme', dark ? 'light' : 'dark');
  document.getElementById('themeBtn').textContent = dark ? 'escuro' : 'claro';
  try { localStorage.setItem('theme', dark ? 'light' : 'dark'); } catch(e){}
}
(function(){
  try {
    const t = localStorage.getItem('theme');
    if(t){
      const btn = document.getElementById('themeBtn');
      if(btn) btn.textContent = t === 'dark' ? 'claro' : 'escuro';
    }
  } catch(e){}
})();
"""

def fmt_price(price: Optional[float], currency: str) -> str:
    if price is None:
        return '<span class="val na">—</span>'
    return (f'<span class="val price">'
            f'<span class="val-unit">{currency}</span>{price:.4f}</span>')

def fmt_fx(rate: Optional[float], currency: str) -> str:
    if rate is None:
        return '<span class="val na">—</span>'
    return (f'<span class="val fx">{rate:.4f}'
            f'<span class="val-suffix">{currency}/USD</span></span>')

def fmt_mcap(mcap: Optional[float], exchange: str) -> str:
    if mcap is None:
        return '<span class="val na">—</span>'
    cls = "tsx" if exchange == "TSX" else ""
    if mcap >= 1000:
        return (f'<span class="val mcap {cls}">'
                f'<span class="val-unit">USD</span>{mcap/1000:.2f}'
                f'<span class="val-suffix">B</span></span>')
    return (f'<span class="val mcap {cls}">'
            f'<span class="val-unit">USD</span>{mcap:.0f}'
            f'<span class="val-suffix">M</span></span>')

def fmt_date(date: Optional[str]) -> str:
    if not date:
        return '<span class="val na">—</span>'
    # Convert ISO date to dd/mm/yyyy for display
    try:
        parts = date.split("-")
        display = f"{parts[2]}/{parts[1]}/{parts[0]}"
    except Exception:
        display = date
    return f'<span class="date-tag">{display}</span>'


def render_html(data: dict, updated: str) -> str:
    rows_html = ""
    for s in STOCKS:
        d = data["stocks"][s["id"]]
        ex_lower = s["exchange"].lower()
        ex_color = "var(--asx)" if s["exchange"] == "ASX" else "var(--tsx)"
        rows_html += f"""
    <tr>
      <td>
        <div class="co-cell" style="--excolor:{ex_color}">
          <div class="co-info">
            <span class="co-tk">{s["ticker"]}</span>
            <span class="co-name">{s["name"]}</span>
            <span class="co-proj">{s["project"]}</span>
            <div class="co-meta">
              <span class="badge ex-{ex_lower}">{s["exchange"]}</span>
              {fmt_mcap(d["mcap_usd_m"], s["exchange"])}
            </div>
          </div>
        </div>
      </td>
      <td style="text-align:left"><span class="badge ex-{ex_lower}">{s["exchange"]}</span></td>
      <td>{fmt_date(d["date"])}</td>
      <td>{fmt_price(d["price"], s["currency"])}</td>
      <td>{fmt_fx(d["fx"], s["currency"])}</td>
      <td>{fmt_mcap(d["mcap_usd_m"], s["exchange"])}</td>
    </tr>"""

    n_live = sum(1 for s in STOCKS if data["stocks"][s["id"]]["date"] is not None)

    return f"""<!DOCTYPE html>
<html lang="pt-BR" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Market Cap Monitor &middot; REE</title>
<style>{CSS}</style>
<script>{JS_HEAD}</script>
</head>
<body>
<header>
  <div class="title-row">
    <div>
      <div class="wordmark"><span class="wm-mark"></span>BEMISA</div>
      <h1>Market Cap Monitor <span class="sub">&middot; REE</span></h1>
    </div>
    <div class="head-actions">
      <button class="theme-btn" id="themeBtn" onclick="toggleTheme()">escuro</button>
    </div>
  </div>
  <div class="stats">
    <span><b>{len(STOCKS)}</b> empresas</span>
    <span><b>{n_live}</b> com dados</span>
    <span>atualizado {updated}</span>
  </div>
</header>

<main>
<table>
  <thead>
    <tr>
      <th style="width:30%; text-align:left; padding-left:18px">Empresa</th>
      <th style="width:7%; text-align:left">Bolsa</th>
      <th style="width:12%">Último Fech.</th>
      <th style="width:17%">Preço</th>
      <th style="width:17%">Câmbio</th>
      <th style="width:17%">Market Cap</th>
    </tr>
  </thead>
  <tbody>{rows_html}
  </tbody>
</table>
</main>
<script>{JS_BODY}</script>
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
