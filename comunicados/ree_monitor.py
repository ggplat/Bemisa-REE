#!/usr/bin/env python3
"""Monitor de Comunicados REE - coleta comunicados, calcula a reacao do mercado
e gera o dashboard HTML.

Uso:
    python ree_monitor.py --dashboard      # coleta dados reais e gera docs/comunicados/index.html
    python ree_monitor.py --sample         # gera com dados de exemplo (offline, p/ teste)
    python ree_monitor.py --dashboard --only ALV,BRE   # apenas algumas empresas
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import sys

import render
from sources import Company, get_source
from sources.base import Announcement

log = logging.getLogger("ree")

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(ROOT)
OUTPUT = os.path.join(REPO_ROOT, "docs", "comunicados", "index.html")

# Coletamos apenas publicacoes a partir desta data (janeiro de 2026).
SINCE = dt.date(2026, 1, 1)


def _filter_since(anns: list[Announcement]) -> list[Announcement]:
    return [a for a in anns if a.date >= SINCE]


def load_companies(path: str = None) -> list[Company]:
    path = path or os.path.join(ROOT, "companies.json")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return [Company(**{k: v for k, v in c.items()}) for c in data["companies"]]


def collect_live(companies: list[Company]) -> dict[str, list[Announcement]]:
    """Coleta comunicados reais e calcula a reacao de mercado (%)."""
    from prices import PriceProvider  # import tardio: yfinance so e necessario aqui
    prices = PriceProvider()
    result: dict[str, list[Announcement]] = {}

    for company in companies:
        log.info("Coletando %s (%s)...", company.ticker, company.exchange)
        try:
            source = get_source(company.exchange)
            anns = source.fetch(company)
        except Exception as exc:  # noqa: BLE001 - uma empresa nao derruba o resto
            log.error("Falha ao coletar %s: %s", company.ticker, exc)
            anns = []

        anns = _filter_since(anns)
        if anns:
            dates = [a.date for a in anns]
            wstart, wend = min(dates), max(dates)
            for a in anns:
                try:
                    r = prices.reaction(
                        company.yf_symbol, a.date, window_start=wstart, window_end=wend)
                except Exception as exc:  # noqa: BLE001
                    log.warning("Preco %s %s: %s", company.ticker, a.date, exc)
                    r = None
                if r is not None:
                    a.pct_change = r.pct
                    a.prev_close = r.prev_close
                    a.close = r.close
                    a.reaction_date = r.reaction_date
        result[company.ticker] = anns

    return result


def collect_sample(companies: list[Company]) -> dict[str, list[Announcement]]:
    from sample import sample_announcements
    return {c.ticker: _filter_since(sample_announcements(c)) for c in companies}


def main(argv: list[str] = None) -> int:
    parser = argparse.ArgumentParser(description="Monitor de Comunicados REE")
    parser.add_argument("--dashboard", action="store_true", help="coleta dados reais e gera o HTML")
    parser.add_argument("--sample", action="store_true", help="gera com dados de exemplo (offline)")
    parser.add_argument("--only", help="lista de tickers separados por virgula (ex.: ALV,BRE)")
    parser.add_argument("--output", default=OUTPUT, help="caminho do HTML de saida")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    if not (args.dashboard or args.sample):
        parser.error("informe --dashboard (dados reais) ou --sample (dados de exemplo)")

    companies = load_companies()
    if args.only:
        wanted = {t.strip().upper() for t in args.only.split(",")}
        companies = [c for c in companies if c.ticker in wanted]
        if not companies:
            parser.error(f"nenhuma empresa encontrada para: {args.only}")

    if args.sample:
        anns_by_ticker = collect_sample(companies)
    else:
        anns_by_ticker = collect_live(companies)

    from prices import fetch_market_caps  # import tardio: yfinance so e necessario aqui
    market_caps = fetch_market_caps(companies)

    context = render.build_context(companies, anns_by_ticker, updated=dt.datetime.now(),
                                    market_caps=market_caps)
    html_out = render.render_html(context)

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        fh.write(html_out)

    total = context["n_announcements"]
    log.info("OK: %s comunicados de %s empresas -> %s",
             total, context["n_companies"], args.output)
    if total == 0 and args.dashboard:
        log.warning("Nenhum comunicado coletado. Verifique as fontes (anti-bot/rede).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
