"""Fonte de noticias/comunicados para TSX e CSE (Canada).

A fonte de cada empresa e configurada em companies.json no campo 'news':
  - {"type": "energyfuels", "url": ".../news-releases"} -> press releases oficiais da
    Energy Fuels (scraping da pagina Q4 em investors.energyfuels.com; cobre UUUU/EFR)
  - {"type": "aclara", "url": "https://www.aclara-re.com/news"} -> scraping do site oficial
  - {"type": "rss"/"appia", "url": "...", "source": "..."} -> feed RSS do site da empresa
  - {"type": "yahoo", "symbol": "UUUU"} -> feed agregado do Yahoo Finance (yfinance)

Preferimos os comunicados OFICIAIS de cada empresa (RSS proprio ou site), que so trazem
publicacoes da propria empresa - sem o ruido de setor do agregador do Yahoo. Cada item leva
direto a publicacao. Se a fonte falhar, a empresa aparece sem itens (sem quebrar a coleta
das demais).
"""
from __future__ import annotations

import datetime as dt
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
                anns = self._fetch_html(company, cfg.get("url") or "https://www.aclara-re.com/news",
                                        parse_aclara_html)
            elif ntype == "energyfuels":
                anns = self._fetch_html(
                    company, cfg.get("url") or "https://investors.energyfuels.com/news-releases",
                    parse_energyfuels_html)
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

    # --- Sites oficiais (Aclara / Energy Fuels) via scraping ------------
    def _fetch_html(self, company: Company, url: str, parser) -> list[Announcement]:
        resp = http_util.get(url)
        if resp is None:
            return []
        return parser(resp.text, company)[:MAX_ITEMS]


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


# --- Scraping de sites oficiais (Aclara / Energy Fuels) -----------------
# datas d/m/aaaa (Aclara) ou textuais; o dia vem antes do mes (uso CA/CL/BR)
_DMY_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")


def _parse_dmy(text: str) -> Optional[dt.date]:
    m = _DMY_RE.search(text or "")
    if not m:
        return None
    day, month, year = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def parse_aclara_html(html: str, company: Company) -> list[Announcement]:
    """Extrai os comunicados do site oficial da Aclara (aclara-re.com/news).

    Cada item da colecao Webflow e um '<a class="news-item-box">' com a data
    ('.text-block-66', formato d/m/aaaa), o titulo ('.news-item-title') e o link
    direto para o PDF/pagina do comunicado.
    """
    soup = BeautifulSoup(html, "html.parser")
    out: list[Announcement] = []
    seen: set[str] = set()
    for box in soup.select("a.news-item-box"):
        href = (box.get("href") or "").strip()
        # ignora cartao "destaque" sem link real (href vazio/ancora '#')
        if not href or href.startswith("#"):
            continue
        title_el = box.select_one(".news-item-title")
        title = title_el.get_text(" ", strip=True) if title_el else box.get_text(" ", strip=True)
        date = _parse_dmy(box.get_text(" ", strip=True))
        if not title or date is None or href in seen:
            continue
        seen.add(href)
        out.append(Announcement(
            ticker=company.ticker, exchange=company.exchange, company_name=company.name,
            date=date, title=title, url=href, price_sensitive=False,
            doc_type="Comunicado", source="Aclara",
        ))
    return out


# link de release da Energy Fuels: investors.energyfuels.com/AAAA-MM-DD-titulo
_EF_REL_RE = re.compile(r"/(\d{4})-(\d{2})-(\d{2})-([^?#/]+)")


def parse_energyfuels_html(html: str, company: Company) -> list[Announcement]:
    """Extrai os press releases oficiais da Energy Fuels (investors.energyfuels.com).

    A pagina Q4 lista cada comunicado num link '/AAAA-MM-DD-<titulo>'; a data vem
    na propria URL e o texto do link e a manchete.
    """
    soup = BeautifulSoup(html, "html.parser")
    out: list[Announcement] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        m = _EF_REL_RE.search(href)
        if not m:
            continue
        try:
            date = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
        key = href.split("#")[0]
        if key in seen:
            continue
        url = href if href.startswith("http") else "https://investors.energyfuels.com" + (
            href if href.startswith("/") else "/" + href)
        title = a.get_text(" ", strip=True)
        if len(title) < 6:  # link sem manchete: deriva do slug da URL
            title = m.group(4).replace("-", " ").strip()
        if not title:
            continue
        seen.add(key)
        out.append(Announcement(
            ticker=company.ticker, exchange=company.exchange, company_name=company.name,
            date=date, title=title, url=url, price_sensitive=False,
            doc_type="Comunicado", source="Energy Fuels",
        ))
    return out
