"""Diagnostico unico: descobre o link direto de PDF a partir do documentKey do markit
e confirma que o yfinance retorna precos. Uso (em CI): python tools/inspect_source.py ALV
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")
from sources import http_util

ASX_BASE = "https://www.asx.com.au"
MARKIT_BASE = "https://asx.api.markitdigital.com"
TOKEN = "83ff96335c2d45a094df02a206a39ff4"  # token publico embutido no site da ASX


def probe(url: str) -> str:
    try:
        r = http_util.session().get(url, timeout=20, allow_redirects=True, stream=True)
        ct = r.headers.get("Content-Type", "?")
        loc = r.url
        head = r.raw.read(5) if r.status_code == 200 else b""
        r.close()
        return f"HTTP {r.status_code} | type={ct} | magic={head!r} | final={loc[:80]}"
    except Exception as exc:  # noqa: BLE001
        return f"ERRO: {exc}"


def main(code: str) -> None:
    url = f"{MARKIT_BASE}/asx-research/1.0/companies/{code}/announcements?count=3&pageSize=3"
    resp = http_util.get(url, headers={"Accept": "application/json", "Origin": ASX_BASE,
                                       "Referer": f"{ASX_BASE}/markets/company/{code}"})
    items = (resp.json().get("data") or {}).get("items") or []
    print("n items:", len(items))
    if not items:
        return
    key = items[0]["documentKey"]
    print("documentKey:", key)

    candidates = {
        "A markit file": f"{MARKIT_BASE}/asx-research/1.0/file/{key}?access_token={TOKEN}",
        "B cdn gateway": f"https://cdn-api.markitdigital.com/apiman-gateway/ASX/asx-research/1.0/file/{key}?access_token={TOKEN}",
        "C displayAnn": f"{ASX_BASE}/asx/statistics/displayAnnouncement.do?display=pdf&idsId={key}",
        "D announcements pdf": f"https://announcements.asx.com.au/asxpdf/file/{key}.pdf",
    }
    for name, c in candidates.items():
        print(f"\n[{name}] {c}")
        print("   ->", probe(c))

    print("\n===== YFINANCE =====")
    try:
        import yfinance as yf
        df = yf.Ticker(f"{code}.AX").history(period="1mo", auto_adjust=False)
        print("linhas:", len(df), "| ultima close:", None if df.empty else round(float(df['Close'].iloc[-1]), 4))
    except Exception as exc:  # noqa: BLE001
        print("ERRO yfinance:", exc)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "ALV")
