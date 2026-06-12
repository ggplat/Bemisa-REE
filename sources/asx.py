"""Fonte de comunicados da ASX (Australia).

A ASX protege seus endpoints contra robos (anti-bot/CAPTCHA desde 2024), por isso
tentamos varias estrategias em ordem e usamos a primeira que retornar resultados:

  1. API JSON oficial da ASX (asx.com.au/asx/1/company/{code}/announcements)
  2. Feed RSS por empresa (noisymime.org) como fallback

Cada estrategia e isolada: se uma falhar (HTTP 403, formato mudou, etc.), passamos
para a proxima sem quebrar a coleta das demais empresas.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Optional
from xml.etree import ElementTree as ET

from .base import Announcement, Company, Source
from .classify import classify
from . import http_util

log = logging.getLogger("ree")

ASX_BASE = "https://www.asx.com.au"
DEFAULT_COUNT = 25


def _parse_iso_date(value: str) -> Optional[dt.date]:
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(value[:len(value)], fmt).date()
        except ValueError:
            continue
    # tenta apenas a parte da data
    try:
        return dt.date.fromisoformat(value[:10])
    except ValueError:
        return None


class ASXSource(Source):
    exchange = "ASX"

    def fetch(self, company: Company) -> list[Announcement]:
        for strategy in (self._fetch_official_json, self._fetch_rss):
            try:
                anns = strategy(company)
            except Exception as exc:  # noqa: BLE001 - estrategia isolada
                log.warning("ASX %s: estrategia %s falhou: %s", company.ticker, strategy.__name__, exc)
                anns = []
            if anns:
                log.info("ASX %s: %s comunicados via %s", company.ticker, len(anns), strategy.__name__)
                return anns
        log.warning("ASX %s: nenhuma estrategia retornou comunicados", company.ticker)
        return []

    # --- estrategia 1: API JSON oficial ---------------------------------
    def _fetch_official_json(self, company: Company) -> list[Announcement]:
        url = (
            f"{ASX_BASE}/asx/1/company/{company.ticker}/announcements"
            f"?count={DEFAULT_COUNT}&market_sensitive=false"
        )
        resp = http_util.get(url, headers={"Accept": "application/json"})
        if resp is None:
            return []
        data = resp.json().get("data", [])
        out: list[Announcement] = []
        for item in data:
            date = _parse_iso_date(item.get("document_date") or item.get("date") or "")
            if date is None:
                continue
            doc_url = item.get("url") or ""
            if doc_url.startswith("/"):
                doc_url = ASX_BASE + doc_url
            title = (item.get("header") or item.get("title") or "").strip()
            out.append(Announcement(
                ticker=company.ticker,
                exchange="ASX",
                company_name=company.name,
                date=date,
                title=title,
                url=doc_url or company.company_url,
                price_sensitive=bool(item.get("market_sensitive")),
                doc_type=classify(title),
                pages=item.get("number_of_pages"),
            ))
        return out

    # --- estrategia 2: RSS (fallback) -----------------------------------
    def _fetch_rss(self, company: Company) -> list[Announcement]:
        url = f"http://noisymime.org/asx/rss.php?code={company.ticker}"
        resp = http_util.get(url)
        if resp is None:
            return []
        root = ET.fromstring(resp.content)
        out: list[Announcement] = []
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub = item.findtext("pubDate") or ""
            date = _parse_rss_date(pub)
            if date is None or not title:
                continue
            # RSS costuma marcar sensiveis ao preco com '*' ou '[PS]' no titulo
            ps = "*" in title or "price sensitive" in title.lower()
            title = title.replace("*", "").strip()
            out.append(Announcement(
                ticker=company.ticker,
                exchange="ASX",
                company_name=company.name,
                date=date,
                title=title,
                url=link or company.company_url,
                price_sensitive=ps,
                doc_type=classify(title),
            ))
        return out


def _parse_rss_date(value: str) -> Optional[dt.date]:
    value = value.strip()
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y"):
        try:
            return dt.datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None
