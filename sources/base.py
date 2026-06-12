"""Modelo de dados e interface comum das fontes de comunicados."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Company:
    ticker: str
    exchange: str          # ASX | TSX | CSE
    name: str
    yf_symbol: str
    company_url: str


@dataclass
class Announcement:
    """Um comunicado de uma empresa."""
    ticker: str
    exchange: str
    company_name: str
    date: dt.date
    title: str
    url: str                          # link direto para o comunicado (PDF/landing)
    price_sensitive: bool = False
    doc_type: str = "Comunicado"      # tag principal (ex.: 'Trimestral', 'Appendix 3B')
    pages: Optional[int] = None
    pct_change: Optional[float] = None  # variacao % close-to-close no dia (None = sem dado)

    @property
    def tags(self) -> list[str]:
        out: list[str] = []
        if self.doc_type:
            out.append(self.doc_type)
        if self.pages:
            out.append(f"{self.pages}p")
        return out


class Source:
    """Interface comum. Cada bolsa implementa fetch()."""

    exchange: str = ""

    def fetch(self, company: Company) -> list[Announcement]:
        raise NotImplementedError
