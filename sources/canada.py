"""Fonte de noticias/comunicados para TSX e CSE (Canada).

A fonte de cada empresa e configurada em companies.json no campo 'news':
  - {"type": "rss", "url": "...", "source": "Energy Fuels"} -> feed RSS oficial da empresa
    (ex.: EFR usa o feed de press releases da Energy Fuels em investors.energyfuels.com)
  - {"type": "aclara", "url": "https://www.aclara-re.com/news"} -> scraping do site oficial
  - {"type": "appia", "url": "https://appiareu.com/feed/"} -> RSS do site (igual a "rss")
  - {"type": "yahoo", "symbol": "UUUU"} -> feed agregado do Yahoo Finance (yfinance)

Preferimos os comunicados OFICIAIS de cada empresa (RSS proprio ou site), que so trazem
publicacoes da propria empresa - sem o ruido de setor do agregador do Yahoo. Cada item leva
direto a publicacao. Se a fonte falhar, a empresa aparece sem itens (sem quebrar a coleta
das demais).
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
from email.utils import parsedate_to_datetime
from typing import Optional
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup

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
            if ntype in ("rss", "appia"):
                anns = self._fetch_rss(company, cfg.get("url") or "https://appiareu.com/feed/",
                                       source_label=cfg.get("source"))
            elif ntype == "aclara":
                anns = self._fetch_aclara(company, cfg.get("url") or "https://www.aclara-re.com/news")
            else:  # yahoo
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

    # --- RSS oficial da empresa (Energy Fuels / Appia / WordPress) ------
    def _fetch_rss(self, company: Company, url: str,
                   source_label: Optional[str] = None) -> list[Announcement]:
        resp = http_util.get(url)
        if resp is None:
            return []
        root = ET.fromstring(resp.content)
        label = source_label or company.name.split()[0]
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
                doc_type="Comunicado", source=label,
            ))
        return out[:MAX_ITEMS]

    # --- Site oficial da Aclara (https://www.aclara-re.com/news) --------
    def _fetch_aclara(self, company: Company, url: str) -> list[Announcement]:
        resp = http_util.get(url)
        if resp is None:
            return []
        return parse_aclara_html(resp.text, company)[:MAX_ITEMS]


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


# --- Scraping do site oficial da Aclara ---------------------------------
ACLARA_BASE = "https://www.aclara-re.com"

# datas em varios formatos comuns em sites institucionais (en/pt)
_ANY_DATE_RE = re.compile(
    r"\b("
    r"\d{4}-\d{2}-\d{2}"                                  # 2026-06-11
    r"|\d{1,2}/\d{1,2}/\d{4}"                             # 11/06/2026
    r"|[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4}"              # June 11, 2026 / Jun 11 2026
    r"|\d{1,2}\s+[A-Za-z]{3,9}\.?\s+\d{4}"                # 11 June 2026
    r")\b"
)
_DATE_FORMATS = (
    "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y",
    "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y",
    "%d %B %Y", "%d %b %Y",
)


def _parse_any_date(text: str) -> Optional[dt.date]:
    m = _ANY_DATE_RE.search(text or "")
    if not m:
        return None
    raw = m.group(1).replace(".", "").strip()
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _abs_url(href: str) -> str:
    if href.startswith("http"):
        return href
    return ACLARA_BASE + (href if href.startswith("/") else "/" + href)


def parse_aclara_html(html: str, company: Company) -> list[Announcement]:
    """Extrai os comunicados da pagina de noticias da Aclara (aclara-re.com/news).

    O site pode renderizar a lista no HTML (cartoes com link + titulo + data) ou
    embutir os dados num JSON (Next.js __NEXT_DATA__). Tentamos o HTML primeiro e,
    se nada sair, o JSON. Parser tolerante: validamos via CI e ajustamos seletores.
    """
    out = _parse_aclara_cards(html, company)
    if not out:
        out = _parse_aclara_next_data(html, company)
    return out


def _parse_aclara_cards(html: str, company: Company) -> list[Announcement]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[Announcement] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        # links para a materia em si (paginas de detalhe ficam sob /news/)
        if "/news/" not in href or href.rstrip("/").endswith("/news"):
            continue
        container = a.find_parent(["article", "li", "div"]) or a
        date = _parse_any_date(container.get_text(" ", strip=True))
        title = a.get_text(" ", strip=True) or (a.get("aria-label") or "").strip()
        if not title or date is None:
            continue
        url = _abs_url(href)
        if url in seen:
            continue
        seen.add(url)
        out.append(Announcement(
            ticker=company.ticker, exchange=company.exchange, company_name=company.name,
            date=date, title=title, url=url, price_sensitive=False,
            doc_type="Comunicado", source="Aclara",
        ))
    return out


def _parse_aclara_next_data(html: str, company: Company) -> list[Announcement]:
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("script", id="__NEXT_DATA__")
    if tag is None or not tag.string:
        return []
    try:
        data = json.loads(tag.string)
    except (ValueError, TypeError):
        return []
    out: list[Announcement] = []
    seen: set[str] = set()

    def visit(node):
        if isinstance(node, dict):
            title = node.get("title") or node.get("headline") or node.get("name")
            date = _parse_any_date(str(node.get("date") or node.get("publishedAt")
                                       or node.get("pubDate") or node.get("publishDate") or ""))
            slug = node.get("slug") or node.get("url") or node.get("link")
            if isinstance(title, str) and title.strip() and date is not None and slug:
                url = _abs_url(slug if str(slug).startswith(("http", "/")) else "/news/" + str(slug))
                if url not in seen:
                    seen.add(url)
                    out.append(Announcement(
                        ticker=company.ticker, exchange=company.exchange,
                        company_name=company.name, date=date, title=title.strip(),
                        url=url, price_sensitive=False, doc_type="Comunicado", source="Aclara",
                    ))
            for v in node.values():
                visit(v)
        elif isinstance(node, list):
            for v in node:
                visit(v)

    visit(data)
    return out
