"""Fonte de noticias/comunicados para TSX e CSE (Canada).

A fonte de cada empresa e configurada em companies.json no campo 'news':
  - {"type": "yahoo", "symbol": "UUUU"} -> feed de noticias do Yahoo Finance (yfinance)
  - {"type": "appia", "url": "https://appiareu.com/feed/"} -> RSS do site da empresa

Cada item leva direto a publicacao. Se a fonte falhar, a empresa aparece sem
itens (sem quebrar a coleta das demais). Para TSX/CSE nao ha API publica gratuita
de comunicados oficiais; usamos noticias/press releases agregados.
"""
from __future__ import annotations

import datetime as dt
import logging
from email.utils import parsedate_to_datetime
from typing import Optional
from xml.etree import ElementTree as ET

from .base import Announcement, Company, Source
from . import http_util

log = logging.getLogger("ree")

MAX_ITEMS = 40

_TYPE_LABEL = {
    "STORY": "Notícia", "VIDEO": "Vídeo",
    "PRESS_RELEASE": "Press Release", "PRESSRELEASE": "Press Release",
}


class CanadaSource(Source):
    """Cobre TSX e CSE; despacha conforme a config 'news' da empresa."""

    exchange = "CA"

    def fetch(self, company: Company) -> list[Announcement]:
        cfg = company.news or {}
        ntype = cfg.get("type", "yahoo")
        try:
            if ntype == "appia":
                anns = self._fetch_rss(company, cfg.get("url") or "https://appiareu.com/feed/")
            else:  # yahoo (default)
                anns = self._fetch_yahoo(company, cfg.get("symbol") or company.yf_symbol)
        except Exception as exc:  # noqa: BLE001
            log.warning("%s %s: fonte '%s' falhou: %s", company.exchange, company.ticker, ntype, exc)
            anns = []
        if anns:
            log.info("%s %s: %s noticias via %s", company.exchange, company.ticker, len(anns), ntype)
        else:
            log.warning("%s %s: sem noticias (fonte '%s')", company.exchange, company.ticker, ntype)
        return anns

    # --- Yahoo Finance (yfinance) ---------------------------------------
    def _fetch_yahoo(self, company: Company, symbol: str) -> list[Announcement]:
        import yfinance as yf  # import tardio
        news = yf.Ticker(symbol).news or []
        out: list[Announcement] = []
        seen: set[str] = set()
        for item in news[:MAX_ITEMS]:
            c = item.get("content", item)
            title = (c.get("title") or item.get("title") or "").strip()
            url = _yahoo_url(c) or item.get("link") or ""
            date = _parse_date(c.get("pubDate") or item.get("providerPublishTime"))
            if not title or not url or date is None or url in seen:
                continue
            seen.add(url)
            ctype = (c.get("contentType") or item.get("type") or "").upper()
            provider = ((c.get("provider") or {}).get("displayName") or item.get("publisher") or "")
            out.append(Announcement(
                ticker=company.ticker, exchange=company.exchange, company_name=company.name,
                date=date, title=title, url=url, price_sensitive=False,
                doc_type=_TYPE_LABEL.get(ctype, "Notícia"), source=provider,
            ))
        return out

    # --- RSS do site da empresa (ex.: Appia / WordPress) ----------------
    def _fetch_rss(self, company: Company, url: str) -> list[Announcement]:
        resp = http_util.get(url)
        if resp is None:
            return []
        root = ET.fromstring(resp.content)
        out: list[Announcement] = []
        seen: set[str] = set()
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            date = _parse_rss_date(item.findtext("pubDate") or "")
            if not title or not link or date is None or link in seen:
                continue
            seen.add(link)
            out.append(Announcement(
                ticker=company.ticker, exchange=company.exchange, company_name=company.name,
                date=date, title=title, url=link, price_sensitive=False,
                doc_type="Comunicado", source=company.name.split()[0],
            ))
        return out[:MAX_ITEMS]


def _yahoo_url(content: dict) -> str:
    for key in ("canonicalUrl", "clickThroughUrl"):
        node = content.get(key)
        if isinstance(node, dict) and node.get("url"):
            return node["url"]
    return ""


def _parse_date(value) -> Optional[dt.date]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return dt.datetime.utcfromtimestamp(value).date()
    s = str(value).strip()
    if not s:
        return None
    try:
        return dt.date.fromisoformat(s[:10])
    except ValueError:
        return None


def _parse_rss_date(value: str) -> Optional[dt.date]:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).date()
    except (TypeError, ValueError):
        return None
