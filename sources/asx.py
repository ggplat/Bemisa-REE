"""Fonte de comunicados da ASX (Australia).

A ASX protege seus endpoints contra robos (anti-bot/CAPTCHA desde 2024), por isso
tentamos varias estrategias em ordem e usamos a primeira que retornar resultados:

  1. API markitdigital (a mesma que o site asx.com.au usa hoje)
  2. API JSON legada da ASX (asx.com.au/asx/1/company/{code}/announcements)
  3. Feed RSS por empresa (noisymime.org) como fallback

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
MARKIT_BASE = "https://asx.api.markitdigital.com"
# Token publico embutido no proprio site da ASX para baixar os PDFs dos comunicados.
MARKIT_TOKEN = "83ff96335c2d45a094df02a206a39ff4"
DEFAULT_COUNT = 100  # busca ampla; a filtragem por data (desde jan/2026) e feita depois


def _markit_doc_url(item: dict) -> str:
    """Link DIRETO para o PDF do comunicado (confirmado: HTTP 200 application/pdf)."""
    url = (item.get("url") or "").strip()
    if url:
        return ASX_BASE + url if url.startswith("/") else url
    key = item.get("documentKey") or item.get("id") or ""
    if key:
        return f"{MARKIT_BASE}/asx-research/1.0/file/{key}?access_token={MARKIT_TOKEN}"
    return ""


def _doc_type(item: dict, title: str) -> str:
    """Tag do comunicado: classifica pelo titulo; usa announcementType se necessario."""
    label = classify(title)
    if label == "Comunicado":
        atype = (item.get("announcementType") or "").strip()
        if atype:
            return atype.title()
    return label


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
        for strategy in (self._fetch_markit, self._fetch_rss):
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

    # --- estrategia 1: API markitdigital (a que o site asx.com.au usa hoje) ---
    def _fetch_markit(self, company: Company) -> list[Announcement]:
        url = (
            f"{MARKIT_BASE}/asx-research/1.0/companies/{company.ticker}/announcements"
            f"?count={DEFAULT_COUNT}&pageSize={DEFAULT_COUNT}"
        )
        resp = http_util.get(url, headers={
            "Accept": "application/json",
            "Origin": ASX_BASE,
            "Referer": f"{ASX_BASE}/markets/company/{company.ticker}",
        })
        if resp is None:
            return []
        data = resp.json().get("data", {}) or {}
        items = data.get("items") or data.get("announcements") or []
        out: list[Announcement] = []
        for item in items:
            date = _parse_iso_date(item.get("date") or item.get("documentDate") or "")
            if date is None:
                continue
            title = (item.get("headline") or item.get("header") or item.get("title") or "").strip()
            out.append(Announcement(
                ticker=company.ticker,
                exchange="ASX",
                company_name=company.name,
                date=date,
                title=title,
                url=_markit_doc_url(item) or company.company_url,
                price_sensitive=bool(item.get("isPriceSensitive") or item.get("isSensitive")),
                doc_type=_doc_type(item, title),
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
