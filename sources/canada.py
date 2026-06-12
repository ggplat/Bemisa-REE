"""Fonte de noticias/comunicados para TSX e CSE (Canada).

Diferente da ASX, nao ha API publica gratuita confiavel dos comunicados oficiais
(SEDAR+/TMX tem anti-bot e formatos instaveis). Usamos o feed de noticias do Yahoo
Finance (via yfinance), que retorna publicacoes recentes com LINK DIRETO para a
materia/press release - confirmado funcionando em CI para ARA.TO, EFR.TO e API.CN.

Observacao: sao noticias/press releases agregados pelo Yahoo (nem sempre o filing
oficial da bolsa). Cada item leva direto a fonte. Se o feed falhar, a empresa
aparece sem comunicados, sem quebrar a coleta das demais.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Optional

from .base import Announcement, Company, Source

log = logging.getLogger("ree")

MAX_ITEMS = 25
MAX_AGE_DAYS = 400

_TYPE_LABEL = {
    "STORY": "Notícia",
    "VIDEO": "Vídeo",
    "PRESS_RELEASE": "Press Release",
    "PRESSRELEASE": "Press Release",
}


class CanadaSource(Source):
    """Cobre TSX e CSE via feed de noticias do Yahoo Finance."""

    exchange = "CA"

    def fetch(self, company: Company) -> list[Announcement]:
        try:
            anns = self._fetch_yahoo_news(company)
        except Exception as exc:  # noqa: BLE001
            log.warning("%s %s: Yahoo news falhou: %s", company.exchange, company.ticker, exc)
            anns = []
        if anns:
            log.info("%s %s: %s noticias via Yahoo", company.exchange, company.ticker, len(anns))
        else:
            log.warning("%s %s: sem noticias no Yahoo (cobertura limitada p/ TSX/CSE)",
                        company.exchange, company.ticker)
        return anns

    def _fetch_yahoo_news(self, company: Company) -> list[Announcement]:
        import yfinance as yf  # import tardio
        news = yf.Ticker(company.yf_symbol).news or []
        cutoff = dt.date.today() - dt.timedelta(days=MAX_AGE_DAYS)
        out: list[Announcement] = []
        seen: set[str] = set()
        for item in news[:MAX_ITEMS]:
            c = item.get("content", item)  # formato novo aninha em 'content'
            title = (c.get("title") or item.get("title") or "").strip()
            url = _extract_url(c) or item.get("link") or ""
            date = _parse_date(c.get("pubDate") or item.get("providerPublishTime"))
            if not title or not url or date is None or date < cutoff:
                continue
            if url in seen:
                continue
            seen.add(url)
            ctype = (c.get("contentType") or item.get("type") or "").upper()
            provider = ((c.get("provider") or {}).get("displayName")
                        or item.get("publisher") or "")
            out.append(Announcement(
                ticker=company.ticker,
                exchange=company.exchange,
                company_name=company.name,
                date=date,
                title=title,
                url=url,
                price_sensitive=False,  # Yahoo nao marca sensibilidade ao preco
                doc_type=_TYPE_LABEL.get(ctype, "Notícia"),
                source=provider,
            ))
        return out


def _extract_url(content: dict) -> str:
    for key in ("canonicalUrl", "clickThroughUrl"):
        node = content.get(key)
        if isinstance(node, dict) and node.get("url"):
            return node["url"]
    return ""


def _parse_date(value) -> Optional[dt.date]:
    if value is None:
        return None
    # epoch (formato antigo)
    if isinstance(value, (int, float)):
        return dt.datetime.utcfromtimestamp(value).date()
    s = str(value).strip()
    if not s:
        return None
    try:
        return dt.date.fromisoformat(s[:10])
    except ValueError:
        return None
