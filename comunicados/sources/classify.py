"""Classificacao simples do tipo de comunicado a partir do titulo."""
from __future__ import annotations

import re

# (regex, rotulo) - primeiro match vence. Cobre EN e PT.
_RULES = [
    (r"appendix\s*3b|appendix\s*2a|emiss(a|ã)o de (novas )?a(c|ç)(o|õ)es", "Appendix 3B"),
    (r"appendix\s*4c|quarterly cash|fluxo de caixa", "Appendix 4C"),
    (r"quarter|trimestr", "Trimestral"),
    (r"half[- ]year|interim|semestr", "Semestral"),
    (r"annual report|relat(o|ó)rio anual", "Relatório Anual"),
    (r"present|apresenta(c|ç)", "Apresentação"),
    (r"drill|sondagem|assay|interc|mineraliz", "Exploração"),
    (r"placement|capital rais|entitlement|capta(c|ç)", "Captação"),
    (r"trading halt|halt", "Trading Halt"),
    (r"resource|recurso|reserva|JORB|JORC|mineral resource", "Recursos"),
    (r"dividend|dividendo", "Dividendo"),
    (r"agm|egm|assembleia|meeting", "Assembleia"),
]


def classify(title: str) -> str:
    t = title.lower()
    for pattern, label in _RULES:
        if re.search(pattern, t):
            return label
    return "Comunicado"
