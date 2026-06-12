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
    if ex in ("TSX", "TSXV", "CSE"):
        return CanadaSource()
    raise ValueError(f"Bolsa nao suportada: {exchange}")


__all__ = ["Announcement", "Company", "Source", "get_source"]
