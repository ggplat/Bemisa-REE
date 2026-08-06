"""Fontes de comunicados por bolsa."""
from __future__ import annotations

from .base import Announcement, Company, Source
from .asx import ASXSource
from .canada import CanadaSource


def get_source(exchange: str) -> Source:
    """Retorna a fonte adequada para a bolsa informada."""
    ex = exchange.upper()
    if ex == "ASX":
        return ASXSource()
    # CanadaSource despacha por companies.json[].news e nao e especifica do
    # Canada: reaproveitada aqui para NYSE American em vez de criar uma classe
    # nova so pra trocar o nome.
    if ex in ("TSX", "TSXV", "CSE", "NYSE"):
        return CanadaSource()
    raise ValueError(f"Bolsa nao suportada: {exchange}")


__all__ = ["Announcement", "Company", "Source", "get_source"]
