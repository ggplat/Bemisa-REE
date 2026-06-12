"""Dados de exemplo para testar o pipeline de renderizacao offline (sem rede).

Gera comunicados deterministicos por empresa, com URLs reais de busca da bolsa,
para validar o template e o calculo de layout sem depender das fontes externas.
"""
from __future__ import annotations

import datetime as dt
import random

from sources.base import Announcement, Company

_TITLES = [
    ("Relatório Trimestral de Atividades", "Trimestral", True, 14),
    ("Resultados de sondagem confirmam mineralização de alto teor", "Exploração", True, 8),
    ("Appendix 3B - Emissão de novas ações", "Appendix 3B", False, 2),
    ("Apresentação a investidores", "Apresentação", False, 22),
    ("Atualização sobre estimativa de recursos minerais", "Recursos", True, 31),
    ("Captação de capital concluída com sucesso", "Captação", True, 5),
    ("Trading Halt", "Trading Halt", False, 1),
    ("Resultados financeiros do semestre", "Semestral", True, 18),
]


def sample_announcements(company: Company) -> list[Announcement]:
    rng = random.Random(company.ticker)  # deterministico por ticker
    today = dt.date.today()
    out: list[Announcement] = []
    n = rng.randint(4, 8)
    for i in range(n):
        title, doc_type, ps, pages = _TITLES[(i + rng.randint(0, 3)) % len(_TITLES)]
        date = today - dt.timedelta(days=rng.randint(0, 150))
        pct = rng.choice([None] + [round(rng.uniform(-9, 9), 1) for _ in range(6)])
        out.append(Announcement(
            ticker=company.ticker,
            exchange=company.exchange,
            company_name=company.name,
            date=date,
            title=title,
            url=company.company_url,  # no exemplo, aponta para a pagina da empresa
            price_sensitive=ps,
            doc_type=doc_type,
            pages=pages,
            pct_change=pct,
        ))
    return out
