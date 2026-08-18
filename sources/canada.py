"""Fonte de noticias/comunicados para TSX, CSE e NYSE American.

A fonte de cada empresa e configurada em companies.json no campo 'news':
  - {"type": "energyfuels", "url": ".../news-releases"} -> press releases oficiais da
    Energy Fuels (scraping da pagina Q4 em investors.energyfuels.com; cobre UUUU/EFR)
  - {"type": "aclara", "url": "https://www.aclara-re.com/news"} -> scraping do site oficial
  - {"type": "imc", "url": ".../news-events/news-releases"} -> press releases oficiais da
    IMC Rare Earths (scraping da pagina de IR em ir.imcrareearths.com; cobre NYSE American: IMC)
  - {"type": "appia", "url": "..."} -> feed RSS da Appia (url e opcional, tem default)
  - {"type": "rss", "url": "...", "source": "..."} -> feed RSS generico; 'url' e
    OBRIGATORIO (sem default - evita atribuir noticias de uma empresa a outra)
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
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from .base import Announcement, Company, Source
from . import http_util

log = logging.getLogger("ree")

MAX_ITEMS = 40
# TSX/CSE fecham no fuso de Toronto, NYSE American no de Nova York -- os dois
# seguem o mesmo horario (America/New_York cobre ambos, ET). Convertido antes
# de extrair a data pra evitar que uma noticia publicada a noite (ET) caia no
# dia UTC seguinte por engano.
_EXCHANGE_TZ = ZoneInfo("America/New_York")

_TYPE_LABEL = {
    "STORY": "Notícia", "VIDEO": "Vídeo",
    "PRESS_RELEASE": "Press Release", "PRESSRELEASE": "Press Release",
}


class CanadaSource(Source):
    """Cobre TSX, CSE e NYSE American; despacha conforme a config 'news' da empresa."""

    exchange = "CA"

    def fetch(self, company: Company) -> list[Announcement]:
        cfg = company.news or {}
        ntype = cfg.get("type", "yahoo")
        try:
            if ntype == "appia":
                anns = self._fetch_rss(company, cfg.get("url") or "https://appiareu.com/feed/",
                                       source_label=cfg.get("source"))
            elif ntype == "rss":
                # Sem default aqui: um "url" ausente numa empresa nova cairia
                # silenciosamente no feed de outra (era o bug antes desta
                # checagem). "rss" generico exige 'url' explicito no config.
                url = cfg.get("url")
                if not url:
                    raise ValueError(
                        f"news type 'rss' exige 'url' em companies.json (ticker {company.ticker})")
                anns = self._fetch_rss(company, url, source_label=cfg.get("source"))
            elif ntype == "aclara":
                anns = self._fetch_html(company, cfg.get("url") or "https://www.aclara-re.com/news",
                                        parse_aclara_html)
            elif ntype == "energyfuels":
                anns = self._fetch_html(
                    company, cfg.get("url") or "https://investors.energyfuels.com/news-releases",
                    parse_energyfuels_html)
            elif ntype == "imc":
                anns = self._fetch_html(
                    company, cfg.get("url") or "https://ir.imcrareearths.com/news-events/news-releases",
                    parse_imc_html)
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
        return dt.datetime.fromtimestamp(value, tz=dt.timezone.utc).astimezone(_EXCHANGE_TZ).date()
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


def _dedupe_key(href: str) -> str:
    """Normaliza o href para dedupe entre parsers HTML: remove o fragmento
    ('#...') para nao contar duas vezes o mesmo comunicado quando a mesma URL
    aparece com e sem ancora (ex.: manchete + botao "Read More")."""
    return href.split("#")[0]


def _make_announcement(company: Company, *, date: dt.date, title: str, url: str,
                        source: str) -> Announcement:
    """Constroi o Announcement dos parsers HTML (Aclara/Energy Fuels/IMC):
    todos usam os mesmos defaults de price_sensitive/doc_type."""
    return Announcement(
        ticker=company.ticker, exchange=company.exchange, company_name=company.name,
        date=date, title=title, url=url, price_sensitive=False,
        doc_type="Comunicado", source=source,
    )


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
        key = _dedupe_key(href)
        if not title or date is None or key in seen:
            continue
        seen.add(key)
        out.append(_make_announcement(company, date=date, title=title, url=href, source="Aclara"))
    return out


# link de release da Energy Fuels: investors.energyfuels.com/AAAA-MM-DD-titulo
# Ancorado ao path inteiro (nao um .search solto): um asset estatico com data
# no nome em outro diretorio (ex. /assets/img/2024-01-01-banner.jpg) nao bate.
_EF_REL_RE = re.compile(r"^/(\d{4})-(\d{2})-(\d{2})-([^?#/]+)$")


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
        path = urlsplit(href).path
        m = _EF_REL_RE.match(path)
        if not m:
            continue
        try:
            date = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
        key = _dedupe_key(href)
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
        out.append(_make_announcement(company, date=date, title=title, url=url, source="Energy Fuels"))
    return out


# pagina de release da IMC: plataforma de IR "Notified" (classes nir-widget--*).
# Cada item lista o link duas vezes (manchete + botao "Read More"); o botao tem
# aria-label="Read more about <titulo>" e fica no mesmo bloco ("nir-widget--field--group")
# que a data ("nir-widget--news--date-time", formato "Mes DD, AAAA"). Usamos o
# botao "Read More" como ancora unica (evita contar cada noticia 2x) e buscamos a
# data no bloco-pai dele. Estrutura confirmada com HTML real (nao um chute) em
# ir.imcrareearths.com/news-events/news-releases.
_IMC_READ_MORE_PREFIX = "read more about "


_EN_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}
_IMC_DATE_RE = re.compile(r"^([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})$")


def _parse_imc_date(text: str) -> Optional[dt.date]:
    """Formato "Mes DD, AAAA" (ex.: "August 04, 2026") com nome do mes em
    ingles fixo, em vez de %B/strptime (dependente do locale do processo,
    que pode nao ser en_US no runner do CI)."""
    m = _IMC_DATE_RE.match((text or "").strip())
    if not m:
        return None
    month = _EN_MONTHS.get(m.group(1).lower())
    if month is None:
        return None
    try:
        return dt.date(int(m.group(3)), month, int(m.group(2)))
    except ValueError:
        return None


def parse_imc_html(html: str, company: Company) -> list[Announcement]:
    """Extrai os press releases oficiais da IMC Rare Earths (ir.imcrareearths.com)."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[Announcement] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if "news-release-details" not in href:
            continue
        aria = (a.get("aria-label") or "").strip()
        if not aria.lower().startswith(_IMC_READ_MORE_PREFIX):
            continue
        title = aria[len(_IMC_READ_MORE_PREFIX):].strip()
        key = _dedupe_key(href)
        if not title or key in seen:
            continue

        date = None
        group = a.find_parent(class_="nir-widget--field--group")
        if group:
            date_el = group.find(class_="nir-widget--news--date-time")
            if date_el:
                date = _parse_imc_date(date_el.get_text(" ", strip=True))
        if date is None:
            continue

        seen.add(key)
        url = href if href.startswith("http") else "https://ir.imcrareearths.com" + (
            href if href.startswith("/") else "/" + href)
        out.append(_make_announcement(company, date=date, title=title, url=url, source="IMC Rare Earths"))
    return out
