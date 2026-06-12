"""Fonte de comunicados para TSX e CSE (Canada) - BEST EFFORT.

Diferente da ASX, nao ha API publica gratuita confiavel para os comunicados de
TSX/CSE. As fontes naturais sao o SEDAR+ (sedarplus.ca) e o TMX Money, ambos com
protecao anti-bot e formatos instaveis. Esta fonte faz uma tentativa via SEDAR+ e,
se nao conseguir, retorna lista vazia SEM quebrar a coleta das demais empresas
(a empresa aparece no dashboard com aviso de 'sem comunicados').

Para cobertura garantida de TSX/CSE, a alternativa e um provedor pago (ex.: QuoteMedia)
- ver README. Este modulo isola essa decisao num unico lugar.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Optional

from .base import Announcement, Company, Source
from .classify import classify
from . import http_util

log = logging.getLogger("ree")

# Endpoint de busca de texto completo do SEDAR+ (nao documentado, pode mudar).
SEDARPLUS_SEARCH = "https://www.sedarplus.ca/csa-party/records/searchService/fullTextSearch"


class CanadaSource(Source):
    """Cobre TSX e CSE (best-effort via SEDAR+)."""

    exchange = "CA"  # generico; aplica-se a TSX e CSE

    def fetch(self, company: Company) -> list[Announcement]:
        try:
            anns = self._fetch_sedarplus(company)
        except Exception as exc:  # noqa: BLE001
            log.warning("%s %s: SEDAR+ falhou: %s", company.exchange, company.ticker, exc)
            anns = []
        if not anns:
            log.warning(
                "%s %s: sem comunicados (fonte best-effort indisponivel). "
                "Considere um provedor pago para TSX/CSE - ver README.",
                company.exchange, company.ticker,
            )
        return anns

    def _fetch_sedarplus(self, company: Company) -> list[Announcement]:
        """Tentativa via SEDAR+ full-text search.

        Mantido simples e isolado: se o endpoint exigir token de sessao ou
        retornar formato diferente, capturamos no fetch() e seguimos.
        """
        payload = {
            "keyword": company.name,
            "fromDate": (dt.date.today() - dt.timedelta(days=400)).isoformat(),
            "toDate": dt.date.today().isoformat(),
        }
        resp = http_util.get(
            SEDARPLUS_SEARCH,
            headers={"Accept": "application/json"},
            params=payload,
        )
        if resp is None:
            return []
        try:
            data = resp.json()
        except ValueError:
            return []

        rows = data.get("results") or data.get("data") or []
        out: list[Announcement] = []
        for item in rows:
            date = _parse_date(item.get("filingDate") or item.get("date") or "")
            title = (item.get("documentType") or item.get("title") or "").strip()
            url = item.get("url") or company.company_url
            if date is None or not title:
                continue
            out.append(Announcement(
                ticker=company.ticker,
                exchange=company.exchange,
                company_name=company.name,
                date=date,
                title=title,
                url=url,
                price_sensitive=False,  # SEDAR+ nao marca sensibilidade ao preco
                doc_type=classify(title),
            ))
        return out


def _parse_date(value: str) -> Optional[dt.date]:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value[:10])
    except ValueError:
        return None
