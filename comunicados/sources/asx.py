"""Fonte de comunicados da ASX (Australia).

Tentamos varias estrategias em ordem e usamos a primeira que retornar resultados:

  1. Pagina de historico da ASX (statistics/announcements.do) - cobre ~6 meses
     com data, titulo, link do PDF e flag de sensibilidade ao preco.
  2. API markitdigital (a mesma que o site asx.com.au usa) - so os 5 mais recentes.

A markit limita a resposta a 5 comunicados, por isso a pagina de historico e a
fonte primaria (necessaria para mostrar comunicados desde janeiro). Cada estrategia
e isolada: se uma falhar, passamos para a proxima sem quebrar a coleta das demais.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
from typing import Optional

from bs4 import BeautifulSoup

from .base import Announcement, Company, Source
from .classify import classify
from . import http_util

log = logging.getLogger("ree")

ASX_BASE = "https://www.asx.com.au"
MARKIT_BASE = "https://asx.api.markitdigital.com"
# Token publico embutido no proprio site da ASX para baixar os PDFs dos comunicados.
MARKIT_TOKEN = "83ff96335c2d45a094df02a206a39ff4"
DEFAULT_COUNT = 100  # busca ampla; a filtragem por data (desde jan/2026) e feita depois
_DATE_RE = re.compile(r"(\d{2}/\d{2}/\d{4})")
_PAGES_RE = re.compile(r"(\d+)\s*page", re.I)
# o link da ASX inclui no fim do titulo "<n> pages <tamanho>"; removemos isso
_TITLE_SUFFIX_RE = re.compile(r"\s+\d+\s+pages?\b.*$", re.I)


def _clean_title(raw: str) -> str:
    norm = re.sub(r"\s+", " ", raw).strip()
    return _TITLE_SUFFIX_RE.sub("", norm).strip()


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
        for strategy in (self._fetch_history, self._fetch_markit):
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

    # --- estrategia 2 (fallback): API markitdigital (so os 5 mais recentes) ---
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

    # --- estrategia 1 (primaria): pagina de historico (~6 meses) --------
    def _fetch_history(self, company: Company) -> list[Announcement]:
        url = (f"{ASX_BASE}/asx/v2/statistics/announcements.do"
               f"?by=asxCode&asxCode={company.ticker}&timeframe=D&period=M6")
        resp = http_util.get(url, headers={"Referer": f"{ASX_BASE}/"})
        if resp is None:
            return []
        return parse_announcements_html(resp.text, company)


def parse_announcements_html(html: str, company: Company) -> list[Announcement]:
    """Extrai comunicados da pagina announcements.do (data, titulo, PDF, sensibilidade)."""
    # ignora a secao final "Other companies that re-used..." (anuncios de terceiros)
    html = re.split(r'name=["\']reused', html, maxsplit=1)[0]
    soup = BeautifulSoup(html, "html.parser")
    out: list[Announcement] = []
    seen: set[str] = set()
    for a in soup.select('a[href*="displayAnnouncement.do"]'):
        href = a.get("href", "")
        if "display=pdf" not in href:
            continue  # cada anuncio tem link HTML e PDF; usamos so o PDF
        title = _clean_title(a.get_text(" ", strip=True))
        row = a.find_parent("tr") or a.parent
        row_text = row.get_text(" ", strip=True) if row else title
        dm = _DATE_RE.search(row_text)
        if not title or dm is None:
            continue
        try:
            date = dt.datetime.strptime(dm.group(1), "%d/%m/%Y").date()
        except ValueError:
            continue
        key = href.split("idsId=")[-1]
        if key in seen:
            continue
        seen.add(key)
        ps = bool(row and (row.select_one('img[src*="sensitive"], img[alt*="ensitive"]')))
        pm = _PAGES_RE.search(row_text)
        out.append(Announcement(
            ticker=company.ticker,
            exchange="ASX",
            company_name=company.name,
            date=date,
            title=title,
            url=ASX_BASE + href if href.startswith("/") else href,
            price_sensitive=ps,
            doc_type=classify(title),
            pages=int(pm.group(1)) if pm else None,
        ))
    return out
