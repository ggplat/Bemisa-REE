"""Diagnostico (temporario) das fontes para TSX/CSE: descobre se o Yahoo Finance
(via yfinance .news) retorna comunicados/noticias com link direto para ARA, EFR e API,
e inspeciona o formato cru do item. Uso (em CI): python tools/inspect_ca.py
"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, ".")


def dump(symbol: str) -> None:
    import yfinance as yf
    print(f"\n===== {symbol} =====")
    try:
        t = yf.Ticker(symbol)
        news = t.news or []
        print("n news:", len(news))
        if news:
            print("PRIMEIRO ITEM (cru):")
            print(json.dumps(news[0], indent=2, ensure_ascii=False, default=str)[:2200])
            # tenta extrair titulo/link/data de cada item (heuristica multi-versao)
            print("\nRESUMO dos itens:")
            for it in news[:8]:
                c = it.get("content", it)
                title = c.get("title") or it.get("title")
                url = (c.get("canonicalUrl") or {}).get("url") or it.get("link") or c.get("clickThroughUrl", {}).get("url")
                date = c.get("pubDate") or it.get("providerPublishTime")
                ctype = c.get("contentType") or it.get("type")
                print(f"  - [{ctype}] {date} | {title} | {url}")
    except Exception as exc:  # noqa: BLE001
        print("ERRO:", exc)


if __name__ == "__main__":
    for s in ["ARA.TO", "EFR.TO", "API.CN"]:
        dump(s)
