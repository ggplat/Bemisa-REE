"""Gera docs/mcap_dashboard.html com dados ao vivo via yfinance.

Uso:
    python mcap_dashboard.py

Saída: docs/mcap_dashboard.html (publicado pelo GitHub Pages)
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
from typing import Optional

import pandas as pd
import yfinance as yf

log = logging.getLogger("mcap")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

MESES_PT = ["jan", "fev", "mar", "abr", "mai", "jun",
            "jul", "ago", "set", "out", "nov", "dez"]

def month_key(year: int, month: int) -> str:
    return f"{MESES_PT[month - 1]}/{year % 100:02d}"

def today_month_key() -> str:
    t = dt.date.today()
    return month_key(t.year, t.month)

# ── HISTORICAL DATA ───────────────────────────────────────────────────────────

ARA_SHARES: dict[str, int] = {
    "jan/23":163223177,"fev/23":163223177,"mar/23":163223177,
    "abr/23":163223177,"mai/23":163223177,"jun/23":163223177,
    "jul/23":163223177,"ago/23":163223177,"set/23":163223177,
    "out/23":163223177,"nov/23":163311439,"dez/23":163311439,
    "jan/24":163311439,"fev/24":163311439,"mar/24":163311439,
    "abr/24":166409223,"mai/24":166409223,"jun/24":166409223,
    "jul/24":166409223,"ago/24":166409223,"set/24":166409223,
    "out/24":166409223,"nov/24":166409223,"dez/24":166409223,
    "jan/25":166409223,"fev/25":217712796,"mar/25":217712796,
    "abr/25":219985221,"mai/25":219985221,"jun/25":219985221,
    "jul/25":219985221,"ago/25":219985221,"set/25":219985221,
    "out/25":219985221,"nov/25":219985221,"dez/25":219985221,
    "jan/26":219985221,"fev/26":219985221,"mar/26":219985221,
}
ARA_CADUSD: dict[str, float] = {
    "jan/23":0.7450,"fev/23":0.7435,"mar/23":0.7310,
    "abr/23":0.7417,"mai/23":0.7398,"jun/23":0.7528,
    "jul/23":0.7566,"ago/23":0.7419,"set/23":0.7384,
    "out/23":0.7293,"nov/23":0.7296,"dez/23":0.7457,
    "jan/24":0.7455,"fev/24":0.7409,"mar/24":0.7388,
    "abr/24":0.7314,"mai/24":0.7316,"jun/24":0.7297,
    "jul/24":0.7291,"ago/24":0.7322,"set/24":0.7384,
    "out/24":0.7270,"nov/24":0.7158,"dez/24":0.7013,
    "jan/25":0.6948,"fev/25":0.6999,"mar/25":0.6968,
    "abr/25":0.7158,"mai/25":0.7212,"jun/25":0.7312,
    "jul/25":0.7307,"ago/25":0.7247,"set/25":0.7230,
    "out/25":0.7146,"nov/25":0.7116,"dez/25":0.7252,
    "jan/26":0.7259,"fev/26":0.7326,"mar/26":0.7338,
}
ARA_PRICE_CAD: dict[str, float] = {
    "jan/23":0.4386,"fev/23":0.4658,"mar/23":0.4596,
    "abr/23":0.4228,"mai/23":0.4605,"jun/23":0.5236,
    "jul/23":0.3780,"ago/23":0.3995,"set/23":0.3905,
    "out/23":0.4100,"nov/23":0.4152,"dez/23":0.4700,
    "jan/24":0.5159,"fev/24":0.4542,"mar/24":0.4479,
    "abr/24":0.5018,"mai/24":0.5458,"jun/24":0.5405,
    "jul/24":0.5357,"ago/24":0.5137,"set/24":0.5055,
    "out/24":0.4829,"nov/24":0.4480,"dez/24":0.4550,
    "jan/25":0.5186,"fev/25":0.5211,"mar/25":0.5220,
    "abr/25":0.6329,"mai/25":0.7267,"jun/25":0.9595,
    "jul/25":1.2591,"ago/25":1.4745,"set/25":1.9752,
    "out/25":3.2505,"nov/25":2.5230,"dez/25":2.2967,
    "jan/26":3.4100,"fev/26":3.3642,"mar/26":3.1514,
}
ARA_CUM_INV_K: dict[str, float] = {
    "jan/24":0,"fev/24":0,"mar/24":3338,
    "abr/24":3338,"mai/24":3338,"jun/24":6841,
    "jul/24":6841,"ago/24":6841,"set/24":11289,
    "out/24":11289,"nov/24":11289,"dez/24":19688,
    "jan/25":19688,"fev/25":19688,"mar/25":25368,
    "abr/25":25368,"mai/25":25368,"jun/25":35439,
    "jul/25":35439,"ago/25":35439,"set/25":43308,
    "out/25":43308,"nov/25":43308,"dez/25":43308,
    "jan/26":43308,"fev/26":43308,"mar/26":43308,
}
ARA_QBAR_K: dict[str, float] = {
    "mar/24":3338,"jun/24":3503,"set/24":4448,"dez/24":8399,
    "mar/25":5680,"jun/25":10071,"set/25":7869,
}
ARA_ISSUANCES = [
    {"month":"jan/23","label":"RSUs Executivos<br>+624k ações @ CAD 0,34","shares":624015},
    {"month":"nov/23","label":"RSU<br>+88k ações @ CAD 0,46","shares":88262},
    {"month":"abr/24","label":"RSU<br>+3,1M ações @ CAD 0,48","shares":3097784},
    {"month":"fev/25","label":"Placement CAP SA<br>+51,3M ações @ CAD 0,49","shares":51303573},
    {"month":"abr/25","label":"RSU<br>+2,3M ações @ CAD 0,51","shares":2272425},
]
ARA_PROJ_EVENTS = [
    {"month":"mar/23","label":"Anúncio Exploração Brasil","color":"#63b3ed"},
    {"month":"out/23","label":"Descoberta Depósito Carina","color":"#e8c97a"},
    {"month":"jan/24","label":"PEA Positivo Carina","color":"#68d391"},
    {"month":"fev/24","label":"100% Direitos Minerários","color":"#68d391"},
    {"month":"mai/24","label":"Hatch Ltd contratada — PFS","color":"#f6ad55"},
    {"month":"ago/24","label":"+77% Recurso Inferido + MoU Gov.","color":"#e8c97a"},
    {"month":"set/24","label":"Atualização PEA","color":"#f6ad55"},
    {"month":"abr/25","label":"Inauguração Planta Piloto","color":"#b794f4"},
    {"month":"mai/25","label":"Aplicação Licença Prévia","color":"#b794f4"},
    {"month":"nov/25","label":"Entrega PFS","color":"#68d391"},
]
ARA_PHASE_BANDS = [
    {"s":"jan/23","e":"dez/23","label":"EXPLORAÇÃO INICIAL","c":"rgba(201,168,76,0.03)"},
    {"s":"jan/24","e":"dez/24","label":"PEA · ESTUDOS · LICENCIAMENTO","c":"rgba(92,168,224,0.03)"},
    {"s":"jan/25","e":"mar/26","label":"PFS · PLANTA PILOTO · LICENÇA","c":"rgba(107,201,138,0.03)"},
]
ARA_FOOTNOTE = (
    "<strong>PORTFÓLIO:</strong> Investimento consolidado inclui Penco Module (Chile), Carina Project (Brasil) "
    "e, a partir de set/2025, U.S. Separation Project (EUA). Total representado (US$43,3M) reflete jan/2024–set/2025. "
    "&nbsp;·&nbsp; <strong>AÇÕES:</strong> base jan/2023 = 162.599.162; RSUs jan/2023 (+624k); RSU nov/2023 (+88k); "
    "RSU abr/2024 (+3,1M); Placement fev/2025 (+51,3M @ CAD 0,49); RSU abr/2025 (+2,3M). "
    "&nbsp;·&nbsp; <strong>FX:</strong> CAD/USD médio mensal histórico + dados ao vivo yfinance. "
    "&nbsp;·&nbsp; <strong>MARKET CAP:</strong> Cotação CAD (TSX: ARA) × CAD/USD × ações em circulação."
)

# ── BRE ──────────────────────────────────────────────────────────────────────

BRE_SHARES: dict[str, int] = {
    "jan/21":180100000,"fev/21":180100000,"mar/21":180100000,
    "abr/21":180100000,"mai/21":180100000,"jun/21":180100000,
    "jul/21":180100000,"ago/21":180100000,"set/21":180100000,
    "out/21":180100000,"nov/21":180100000,"dez/21":180100000,
    "jan/22":180100000,"fev/22":180100000,"mar/22":180100000,
    "abr/22":180100000,"mai/22":180100000,"jun/22":180100000,
    "jul/22":180100000,"ago/22":180100000,"set/22":180100000,
    "out/22":180100000,"nov/22":180100000,"dez/22":180100000,
    "jan/23":180100000,"fev/23":180100000,"mar/23":180100000,
    "abr/23":180100000,"mai/23":180100000,"jun/23":180100000,
    "jul/23":180100000,"ago/23":180100000,"set/23":180100000,
    "out/23":180100000,"nov/23":180100000,"dez/23":214113606,
    "jan/24":214113606,"fev/24":214113606,"mar/24":214113606,
    "abr/24":222113606,"mai/24":222113606,"jun/24":246313606,
    "jul/24":246313606,"ago/24":250113606,"set/24":250113606,
    "out/24":250113606,"nov/24":250113606,"dez/24":250113606,
    "jan/25":250113606,"fev/25":250113606,"mar/25":250113606,
    "abr/25":250113606,"mai/25":250113606,"jun/25":250113606,
    "jul/25":250113606,"ago/25":250113606,"set/25":250113606,
    "out/25":275713606,"nov/25":275713606,"dez/25":275713606,
}
BRE_AUDUSD: dict[str, float] = {
    "jan/21":0.752,"fev/21":0.752,"mar/21":0.752,"abr/21":0.752,"mai/21":0.752,"jun/21":0.752,
    "jul/21":0.752,"ago/21":0.752,"set/21":0.752,"out/21":0.752,"nov/21":0.752,"dez/21":0.752,
    "jan/22":0.694,"fev/22":0.694,"mar/22":0.694,"abr/22":0.694,"mai/22":0.694,"jun/22":0.694,
    "jul/22":0.694,"ago/22":0.694,"set/22":0.694,"out/22":0.694,"nov/22":0.694,"dez/22":0.694,
    "jan/23":0.6985,"fev/23":0.6893,"mar/23":0.6705,
    "abr/23":0.6712,"mai/23":0.6649,"jun/23":0.6782,
    "jul/23":0.6680,"ago/23":0.6430,"set/23":0.6426,
    "out/23":0.6330,"nov/23":0.6476,"dez/23":0.6590,
    "jan/24":0.6588,"fev/24":0.6553,"mar/24":0.6527,
    "abr/24":0.6455,"mai/24":0.6612,"jun/24":0.6669,
    "jul/24":0.6590,"ago/24":0.6635,"set/24":0.6753,
    "out/24":0.6565,"nov/24":0.6484,"dez/24":0.6274,
    "jan/25":0.6197,"fev/25":0.6282,"mar/25":0.6294,
    "abr/25":0.6349,"mai/25":0.6440,"jun/25":0.6525,
    "jul/25":0.6440,"ago/25":0.6393,"set/25":0.6440,
    "out/25":0.6450,"nov/25":0.6435,"dez/25":0.6310,
}
BRE_PRICE_AUD: dict[str, float] = {
    "jan/21":0,"fev/21":0,"mar/21":0,"abr/21":0,"mai/21":0,"jun/21":0,
    "jul/21":0,"ago/21":0,"set/21":0,"out/21":0,"nov/21":0,"dez/21":0,
    "jan/22":0,"fev/22":0,"mar/22":0,"abr/22":0,"mai/22":0,"jun/22":0,
    "jul/22":0,"ago/22":0,"set/22":0,"out/22":0,"nov/22":0,"dez/22":0,
    "jan/23":0,"fev/23":0,"mar/23":0,"abr/23":0,"mai/23":0,"jun/23":0,
    "jul/23":0,"ago/23":0,"set/23":0,"out/23":0,"nov/23":0,
    "dez/23":1.470,
    "jan/24":2.130,"fev/24":1.860,"mar/24":2.340,
    "abr/24":2.620,"mai/24":3.080,"jun/24":3.490,
    "jul/24":3.450,"ago/24":4.200,"set/24":4.360,
    "out/24":3.980,"nov/24":3.580,"dez/24":3.690,
    "jan/25":3.540,"fev/25":3.800,"mar/25":3.650,
    "abr/25":4.100,"mai/25":4.380,"jun/25":4.900,
    "jul/25":5.100,"ago/25":5.300,"set/25":5.150,
    "out/25":4.680,"nov/25":4.500,"dez/25":4.650,
}
BRE_CUM_INV_K: dict[str, float] = {
    "dez/21":416,"dez/22":3459,
    "mar/23":3459,"jun/23":4109,"set/23":5059,"dez/23":7809,
    "mar/24":11259,"jun/24":20559,"set/24":29859,"dez/24":37459,
    "mar/25":43059,"jun/25":50459,"set/25":52459,"dez/25":52459,
}
BRE_QBAR_K: dict[str, float] = {
    "jun/23":650,"set/23":950,"dez/23":2750,
    "mar/24":3450,"jun/24":9300,"set/24":9300,"dez/24":7600,
    "mar/25":5600,"jun/25":7400,"set/25":2000,
}
BRE_ISSUANCES = [
    {"month":"dez/23","label":"IPO ASX<br>+34M ações @ AUD 1,47","shares":34013606},
    {"month":"abr/24","label":"Sulista Acquisition<br>+8M ações","shares":8000000},
    {"month":"jun/24","label":"Placement<br>+24,2M ações @ AUD 3,30","shares":24200000},
    {"month":"ago/24","label":"Opções exercidas<br>~3,8M ações","shares":3800000},
    {"month":"out/25","label":"Placement<br>+25,6M ações @ AUD 4,68","shares":25600000},
]
BRE_PROJ_EVENTS = [
    {"month":"mar/21","label":"Fundação da Empresa","color":"#63b3ed"},
    {"month":"dez/22","label":"Captação AUD 20M — notas conversíveis","color":"#c9a84c"},
    {"month":"dez/23","label":"IPO na ASX","color":"#68d391"},
    {"month":"abr/24","label":"Aquisição Tenements Sulista","color":"#e8c97a"},
    {"month":"mai/24","label":"Recurso JORC Classe 2 Monte Alto","color":"#68d391"},
    {"month":"set/24","label":"Atualização Recursos + MoU USDOE","color":"#f6ad55"},
    {"month":"out/25","label":"Acordo 10 anos Carester + AUD 120M","color":"#f6ad55"},
]
BRE_PHASE_BANDS = [
    {"s":"jan/21","e":"nov/23","label":"PRÉ-IPO","c":"rgba(201,168,76,0.03)"},
    {"s":"dez/23","e":"dez/24","label":"IPO · EXPLORAÇÃO","c":"rgba(92,168,224,0.03)"},
    {"s":"jan/25","e":"dez/25","label":"SCOPING STUDY · ACORDOS","c":"rgba(107,201,138,0.03)"},
]
BRE_FOOTNOTE = (
    "<strong>INVESTIMENTO:</strong> Gastos E&amp;E convertidos para USD pelas taxas AUD/USD médias. "
    "Total acumulado: USD 52M (dez/2021–dez/2025). &nbsp;·&nbsp; "
    "<strong>AÇÕES:</strong> IPO dez/2023 (214,1M); Sulista abr/2024 (+8M); Placement jun/2024 (+24,2M @ AUD 3,30); "
    "Opções ago/2024 (~3,8M); Placement out/2025 (+25,6M @ AUD 4,68); total 275,8M. "
    "&nbsp;·&nbsp; <strong>MARKET CAP:</strong> Exibido a partir do IPO (dez/2023). "
    "&nbsp;·&nbsp; <strong>FX:</strong> AUD/USD médio mensal histórico + dados ao vivo yfinance."
)

# ── MEI ──────────────────────────────────────────────────────────────────────

MEI_SHARES: dict[str, int] = {
    "abr/23":1532306450,"mai/23":1532306450,"jun/23":1557306450,
    "jul/23":1557306450,"ago/23":1557306450,"set/23":1557306450,
    "out/23":1557306450,"nov/23":1557306450,"dez/23":1606306450,
    "jan/24":1606306450,"fev/24":1606306450,"mar/24":1606306450,
    "abr/24":1606306450,"mai/24":1606306450,"jun/24":1606306450,
    "jul/24":1606306450,"ago/24":1836306450,"set/24":1836306450,
    "out/24":1836306450,"nov/24":1836306450,"dez/24":1836306450,
    "jan/25":1836306450,"fev/25":1930306450,"mar/25":2030306450,
    "abr/25":2130306450,"mai/25":2230306450,"jun/25":2330306450,
    "jul/25":2646398877,"ago/25":2646398877,"set/25":2646398877,
    "out/25":2646398877,"nov/25":2646398877,"dez/25":2646398877,
}
MEI_AUDUSD: dict[str, float] = {
    "abr/23":0.6712,"mai/23":0.6649,"jun/23":0.6782,
    "jul/23":0.6680,"ago/23":0.6430,"set/23":0.6426,
    "out/23":0.6330,"nov/23":0.6476,"dez/23":0.6590,
    "jan/24":0.6588,"fev/24":0.6553,"mar/24":0.6527,
    "abr/24":0.6455,"mai/24":0.6612,"jun/24":0.6669,
    "jul/24":0.6590,"ago/24":0.6635,"set/24":0.6753,
    "out/24":0.6565,"nov/24":0.6484,"dez/24":0.6274,
    "jan/25":0.6197,"fev/25":0.6282,"mar/25":0.6294,
    "abr/25":0.6349,"mai/25":0.6440,"jun/25":0.6525,
    "jul/25":0.6440,"ago/25":0.6393,"set/25":0.6440,
    "out/25":0.6450,"nov/25":0.6435,"dez/25":0.6310,
}
MEI_PRICE_AUD: dict[str, float] = {
    "abr/23":0.0180,"mai/23":0.0173,"jun/23":0.0167,
    "jul/23":0.0135,"ago/23":0.0106,"set/23":0.0109,
    "out/23":0.0167,"nov/23":0.0335,"dez/23":0.0503,
    "jan/24":0.0515,"fev/24":0.0398,"mar/24":0.0328,
    "abr/24":0.0355,"mai/24":0.0330,"jun/24":0.0273,
    "jul/24":0.0277,"ago/24":0.0272,"set/24":0.0320,
    "out/24":0.0291,"nov/24":0.0265,"dez/24":0.0275,
    "jan/25":0.0290,"fev/25":0.0319,"mar/25":0.0360,
    "abr/25":0.0438,"mai/25":0.0580,"jun/25":0.0780,
    "jul/25":0.1020,"ago/25":0.1150,"set/25":0.1050,
    "out/25":0.0960,"nov/25":0.0890,"dez/25":0.0920,
}
MEI_CUM_AUD_K: dict[str, float] = {
    "jun/23":4900,"set/23":6700,"dez/23":9200,
    "mar/24":12000,"jun/24":15200,"set/24":18900,"dez/24":22500,
    "mar/25":26800,"jun/25":32000,"set/25":38500,"dez/25":38500,
}
MEI_QUARTERLY_AUD_K: dict[str, float] = {
    "jun/23":4900,"set/23":1800,"dez/23":2500,
    "mar/24":2800,"jun/24":3200,"set/24":3700,"dez/24":3600,
    "mar/25":4300,"jun/25":5200,"set/25":6500,
}
MEI_ISSUANCES = [
    {"month":"abr/23","label":"Placement A$25M<br>+200M ações","shares":200000000},
    {"month":"jun/23","label":"Exercício opções MEIAW<br>+~25M ações @ A$0.10","shares":25000000},
    {"month":"dez/23","label":"Exercício opções MEIAW<br>+~49M ações @ A$0.10","shares":49000000},
    {"month":"ago/24","label":"Placement A$30,9M<br>+~230M ações","shares":230000000},
    {"month":"jul/25","label":"Placement A$42,5M<br>+304M ações","shares":304092427},
]
MEI_PROJ_EVENTS = [
    {"month":"abr/23","label":"Placement + Início Perfuração Caldeira","color":"#63b3ed"},
    {"month":"out/23","label":"Recurso Inferido JORC 2.7Gt @ 2.670 ppm TREO","color":"#e8c97a"},
    {"month":"mai/24","label":"Recurso Indicado + Scoping Study","color":"#68d391"},
    {"month":"ago/24","label":"Placement + Recurso 3.3Gt","color":"#f6ad55"},
    {"month":"fev/25","label":"Recurso 4.6Gt — Maior do Mundo","color":"#68d391"},
    {"month":"jul/25","label":"Placement A$42,5M + Início PFS","color":"#b794f4"},
]
MEI_PHASE_BANDS = [
    {"s":"abr/23","e":"set/23","label":"EXPLORAÇÃO INICIAL","c":"rgba(201,168,76,0.03)"},
    {"s":"out/23","e":"jun/24","label":"RECURSOS JORC · ESTUDOS","c":"rgba(92,168,224,0.03)"},
    {"s":"jul/24","e":"dez/25","label":"PFS · ESCALA · ACORDOS","c":"rgba(107,201,138,0.03)"},
]
MEI_FOOTNOTE = (
    "<strong>AÇÕES:</strong> Appendix 3B abr/2023 (1.332M pré-placement); Placement A$25M (+200M); "
    "Opções MEIAW jun/2023 (+25M) e dez/2023 (+49M); Placement A$30,9M ago/2024 (+230M); "
    "Emissões residuais ~206M em 2025; Placement A$42,5M jul/2025 (+304M). "
    "&nbsp;·&nbsp; <strong>FX:</strong> AUD/USD médio mensal + dados ao vivo yfinance. "
    "&nbsp;·&nbsp; <strong>INVESTIMENTO:</strong> Despesas Appendix 5B (ASX), convertidos a USD pela taxa do trimestre."
)

# ── SGQ ──────────────────────────────────────────────────────────────────────

SGQ_SHARES: dict[str, int] = {
    "jan/22":1062244808,"fev/22":1062244808,"mar/22":1062244808,
    "abr/22":1062244808,"mai/22":1062244808,"jun/22":1062244808,
    "jul/22":1062244808,"ago/22":1062244808,"set/22":1062244808,
    "out/22":1062244808,"nov/22":1062244808,"dez/22":1062244808,
    "jan/23":1062244808,"fev/23":1062244808,"mar/23":1062244808,
    "abr/23":1062244808,"mai/23":1062244808,"jun/23":1062244808,
    "jul/23":1062244808,"ago/23":1062244808,"set/23":1062244808,
    "out/23":1062244808,"nov/23":1062244808,"dez/23":1062244808,
    "jan/24":1062244808,"fev/24":1062244808,"mar/24":1062244808,
    "abr/24":1062244808,"mai/24":1062244808,"jun/24":1062244808,
    "jul/24":1062244808,"ago/24":1062244808,"set/24":1062244808,
    "out/24":1062244808,"nov/24":1062244808,"dez/24":1124244808,
    "jan/25":1124244808,"fev/25":1124244808,"mar/25":1124244808,
    "abr/25":1124244808,"mai/25":1124244808,"jun/25":1124244808,
    "jul/25":1124244808,"ago/25":1124244808,"set/25":1124244808,
    "out/25":1124244808,"nov/25":1124244808,"dez/25":1124244808,
}
SGQ_AUDUSD: dict[str, float] = {
    "jan/22":0.7170,"fev/22":0.7178,"mar/22":0.7427,
    "abr/22":0.7390,"mai/22":0.7103,"jun/22":0.6930,
    "jul/22":0.6886,"ago/22":0.6964,"set/22":0.6547,
    "out/22":0.6490,"nov/22":0.6641,"dez/22":0.6705,
    "jan/23":0.6985,"fev/23":0.6893,"mar/23":0.6705,
    "abr/23":0.6712,"mai/23":0.6649,"jun/23":0.6782,
    "jul/23":0.6680,"ago/23":0.6430,"set/23":0.6426,
    "out/23":0.6330,"nov/23":0.6476,"dez/23":0.6590,
    "jan/24":0.6588,"fev/24":0.6553,"mar/24":0.6527,
    "abr/24":0.6455,"mai/24":0.6612,"jun/24":0.6669,
    "jul/24":0.6590,"ago/24":0.6635,"set/24":0.6753,
    "out/24":0.6565,"nov/24":0.6484,"dez/24":0.6274,
    "jan/25":0.6197,"fev/25":0.6282,"mar/25":0.6294,
    "abr/25":0.6349,"mai/25":0.6440,"jun/25":0.6525,
    "jul/25":0.6440,"ago/25":0.6393,"set/25":0.6440,
    "out/25":0.6450,"nov/25":0.6435,"dez/25":0.6310,
}
# None = trading suspended
SGQ_PRICE_AUD: dict[str, Optional[float]] = {
    "jan/22":0.0300,"fev/22":0.0380,"mar/22":0.0300,
    "abr/22":0.0290,"mai/22":0.0250,"jun/22":0.0210,
    "jul/22":0.0210,"ago/22":0.0220,"set/22":0.0220,
    "out/22":0.0220,"nov/22":0.0230,"dez/22":0.0230,
    "jan/23":0.0280,"fev/23":0.0290,"mar/23":0.0290,
    "abr/23":0.0260,"mai/23":0.0280,"jun/23":0.0350,
    "jul/23":0.0360,"ago/23":0.0310,
    "set/23":None,"out/23":None,"nov/23":None,"dez/23":None,
    "jan/24":None,"fev/24":None,"mar/24":None,"abr/24":None,
    "mai/24":None,"jun/24":None,"jul/24":None,"ago/24":None,
    "set/24":None,"out/24":None,"nov/24":None,"dez/24":None,
    "jan/25":None,"fev/25":None,"mar/25":None,"abr/25":None,
    "mai/25":None,"jun/25":None,"jul/25":None,"ago/25":None,
    "set/25":0.0380,"out/25":0.0420,"nov/25":0.0450,"dez/25":0.0430,
}
SGQ_CUM_INV_K: dict[str, float] = {
    "jun/22":500,"dez/22":1100,
    "mar/23":1500,"jun/23":2000,"set/23":2600,"dez/23":3200,
    "mar/24":3900,"jun/24":4700,"set/24":5600,"dez/24":6600,
    "mar/25":7700,"jun/25":8900,"set/25":10200,"dez/25":10200,
}
SGQ_QBAR_K: dict[str, float] = {
    "jun/22":500,"dez/22":600,
    "mar/23":400,"jun/23":500,"set/23":600,"dez/23":600,
    "mar/24":700,"jun/24":800,"set/24":900,"dez/24":1000,
    "mar/25":1100,"jun/25":1200,"set/25":1300,
}
SGQ_ISSUANCES = [
    {"month":"dez/24","label":"Placement<br>+62M ações","shares":62000000},
]
SGQ_PROJ_EVENTS = [
    {"month":"jan/22","label":"Início Exploração Araxá","color":"#63b3ed"},
    {"month":"out/22","label":"Descoberta Sistema REE Araxá","color":"#e8c97a"},
    {"month":"mai/23","label":"Recurso Inferido JORC Araxá","color":"#68d391"},
    {"month":"set/23","label":"Negociação aquisição — suspensão de trading","color":"#e05c5c"},
    {"month":"set/25","label":"Retomada de trading","color":"#68d391"},
]
SGQ_PHASE_BANDS = [
    {"s":"jan/22","e":"ago/23","label":"EXPLORAÇÃO · RECURSOS","c":"rgba(201,168,76,0.03)"},
    {"s":"set/23","e":"ago/25","label":"SUSPENSA — AQUISIÇÃO","c":"rgba(224,92,92,0.04)"},
    {"s":"set/25","e":"dez/25","label":"RETOMADA","c":"rgba(107,201,138,0.03)"},
]
SGQ_FOOTNOTE = (
    "<strong>FX:</strong> AUD/USD médio mensal histórico + dados ao vivo yfinance. &nbsp;·&nbsp; "
    "<strong>MARKET CAP:</strong> Cotação AUD (ASX: SGQ) × AUD/USD × ações em circulação. "
    "Investimento convertido a USD pela taxa do fim de cada trimestre. "
    "&nbsp;·&nbsp; <strong>SUSPENSÃO:</strong> Trading suspenso set/2023–ago/2025 durante negociação de aquisição."
)

# ── VMM ──────────────────────────────────────────────────────────────────────

VMM_SHARES: dict[str, int] = {
    "jan/22":453350000,"fev/22":453350000,"mar/22":453350000,
    "abr/22":453350000,"mai/22":453350000,"jun/22":453350000,
    "jul/22":453350000,"ago/22":453350000,"set/22":453350000,
    "out/22":453350000,"nov/22":453350000,"dez/22":453350000,
    "jan/23":453350000,"fev/23":453350000,"mar/23":453350000,
    "abr/23":453350000,"mai/23":453350000,"jun/23":453350000,
    "jul/23":453350000,"ago/23":453350000,"set/23":453350000,
    "out/23":453350000,"nov/23":453350000,"dez/23":453350000,
    "jan/24":453350000,"fev/24":453350000,"mar/24":453350000,
    "abr/24":453350000,"mai/24":453350000,"jun/24":453350000,
    "jul/24":453350000,"ago/24":453350000,"set/24":453350000,
    "out/24":478350000,"nov/24":478350000,"dez/24":478350000,
    "jan/25":478350000,"fev/25":478350000,"mar/25":478350000,
    "abr/25":478350000,"mai/25":478350000,"jun/25":478350000,
    "jul/25":503350000,"ago/25":503350000,"set/25":503350000,
    "out/25":503350000,"nov/25":503350000,"dez/25":503350000,
}
VMM_AUDUSD: dict[str, float] = {
    "jan/22":0.7170,"fev/22":0.7178,"mar/22":0.7427,
    "abr/22":0.7390,"mai/22":0.7103,"jun/22":0.6930,
    "jul/22":0.6886,"ago/22":0.6964,"set/22":0.6547,
    "out/22":0.6490,"nov/22":0.6641,"dez/22":0.6705,
    "jan/23":0.6985,"fev/23":0.6893,"mar/23":0.6705,
    "abr/23":0.6712,"mai/23":0.6649,"jun/23":0.6782,
    "jul/23":0.6680,"ago/23":0.6430,"set/23":0.6426,
    "out/23":0.6330,"nov/23":0.6476,"dez/23":0.6590,
    "jan/24":0.6588,"fev/24":0.6553,"mar/24":0.6527,
    "abr/24":0.6455,"mai/24":0.6612,"jun/24":0.6669,
    "jul/24":0.6590,"ago/24":0.6635,"set/24":0.6753,
    "out/24":0.6565,"nov/24":0.6484,"dez/24":0.6274,
    "jan/25":0.6197,"fev/25":0.6282,"mar/25":0.6294,
    "abr/25":0.6349,"mai/25":0.6440,"jun/25":0.6525,
    "jul/25":0.6440,"ago/25":0.6393,"set/25":0.6440,
    "out/25":0.6450,"nov/25":0.6435,"dez/25":0.6310,
}
VMM_PRICE_AUD: dict[str, float] = {
    "jan/22":0.0380,"fev/22":0.0420,"mar/22":0.0440,
    "abr/22":0.0360,"mai/22":0.0310,"jun/22":0.0270,
    "jul/22":0.0270,"ago/22":0.0290,"set/22":0.0250,
    "out/22":0.0260,"nov/22":0.0280,"dez/22":0.0300,
    "jan/23":0.0360,"fev/23":0.0390,"mar/23":0.0410,
    "abr/23":0.0390,"mai/23":0.0400,"jun/23":0.0490,
    "jul/23":0.0510,"ago/23":0.0470,"set/23":0.0430,
    "out/23":0.0420,"nov/23":0.0440,"dez/23":0.0480,
    "jan/24":0.0540,"fev/24":0.0520,"mar/24":0.0500,
    "abr/24":0.0520,"mai/24":0.0560,"jun/24":0.0590,
    "jul/24":0.0560,"ago/24":0.0550,"set/24":0.0590,
    "out/24":0.0540,"nov/24":0.0510,"dez/24":0.0540,
    "jan/25":0.0610,"fev/25":0.0650,"mar/25":0.0620,
    "abr/25":0.0730,"mai/25":0.0850,"jun/25":0.1050,
    "jul/25":0.1350,"ago/25":0.1480,"set/25":0.1350,
    "out/25":0.1200,"nov/25":0.1100,"dez/25":0.1200,
}
VMM_CUM_INV_K: dict[str, float] = {
    "jun/22":800,"dez/22":1700,
    "mar/23":2300,"jun/23":3000,"set/23":3800,"dez/23":4700,
    "mar/24":5800,"jun/24":7000,"set/24":8400,"dez/24":10000,
    "mar/25":11800,"jun/25":13800,"set/25":16000,"dez/25":16000,
}
VMM_QBAR_K: dict[str, float] = {
    "jun/22":800,"dez/22":900,
    "mar/23":600,"jun/23":700,"set/23":800,"dez/23":900,
    "mar/24":1100,"jun/24":1200,"set/24":1400,"dez/24":1600,
    "mar/25":1800,"jun/25":2000,"set/25":2200,
}
VMM_ISSUANCES = [
    {"month":"out/24","label":"Placement<br>+25M ações @ AUD 0,056","shares":25000000},
    {"month":"jul/25","label":"Placement<br>+25M ações","shares":25000000},
]
VMM_PROJ_EVENTS = [
    {"month":"mar/22","label":"Aquisição Colossus Project","color":"#63b3ed"},
    {"month":"set/22","label":"Início Perfuração Colossus","color":"#63b3ed"},
    {"month":"mai/23","label":"Recurso Inferido Inicial 2.16Gt","color":"#e8c97a"},
    {"month":"fev/24","label":"Recurso Atualizado 3.46Gt","color":"#68d391"},
    {"month":"set/24","label":"Recurso 4.86Gt + Início Scoping Study","color":"#f6ad55"},
    {"month":"abr/25","label":"Scoping Study Positivo","color":"#68d391"},
    {"month":"set/25","label":"Início PFS","color":"#b794f4"},
]
VMM_PHASE_BANDS = [
    {"s":"jan/22","e":"dez/22","label":"AQUISIÇÃO · EXPLORAÇÃO","c":"rgba(201,168,76,0.03)"},
    {"s":"jan/23","e":"dez/23","label":"RECURSOS INICIAIS","c":"rgba(92,168,224,0.03)"},
    {"s":"jan/24","e":"dez/25","label":"PFS · ESTUDOS AVANÇADOS","c":"rgba(107,201,138,0.03)"},
]
VMM_FOOTNOTE = (
    "<strong>FX:</strong> AUD/USD médio mensal histórico + dados ao vivo yfinance. &nbsp;·&nbsp; "
    "<strong>MARKET CAP:</strong> Cotação AUD (ASX: VMM) × AUD/USD × ações em circulação. "
    "Investimento convertido a USD pela taxa do fim de cada trimestre."
)


# ── LIVE DATA FETCHING ────────────────────────────────────────────────────────

def _fetch_history(symbol: str, days: int = 400) -> pd.DataFrame:
    """Busca histórico OHLCV via yfinance. Retorna DataFrame vazio em caso de erro."""
    start = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    try:
        df = yf.Ticker(symbol).history(start=start, auto_adjust=False)
        if df.empty:
            log.warning("%s: histórico vazio", symbol)
            return pd.DataFrame()
        df.index = pd.to_datetime(df.index).date
        return df
    except Exception as exc:  # noqa: BLE001
        log.warning("%s: falha no download: %s", symbol, exc)
        return pd.DataFrame()


def _monthly_avg_close(df: pd.DataFrame) -> dict[str, float]:
    """Retorna média de fechamento por chave 'mes/aa'."""
    if df.empty or "Close" not in df.columns:
        return {}
    result: dict[str, float] = {}
    for d, row in df.iterrows():
        k = month_key(d.year, d.month)
        prev = result.get(k)
        result[k] = row["Close"] if prev is None else (prev + row["Close"]) / 2
    return result


def _monthly_avg_fx(df: pd.DataFrame) -> dict[str, float]:
    """Igual a _monthly_avg_close mas para série de FX (coluna Close)."""
    return _monthly_avg_close(df)


def _daily_vol_usd(df_stock: pd.DataFrame, df_fx: pd.DataFrame) -> list[dict]:
    """Gera lista [{d, v}] com volume financeiro diário em USD."""
    if df_stock.empty or "Close" not in df_stock.columns or "Volume" not in df_stock.columns:
        return []
    rows = []
    fx_series = df_fx["Close"] if not df_fx.empty and "Close" in df_fx.columns else pd.Series(dtype=float)
    for d, row in df_stock.iterrows():
        # FX: tenta exato, depois próximo pregão disponível
        fx = None
        if not fx_series.empty:
            try:
                fx = float(fx_series.asof(d))
            except Exception:
                pass
        if not fx or pd.isna(fx):
            fx = 0.65  # fallback AUD/USD
        vol_usd = float(row["Volume"]) * float(row["Close"]) * fx
        rows.append({"d": d.isoformat(), "v": round(vol_usd, 2)})
    return rows


def fetch_live(stock_sym: str, fx_sym: str, days: int = 400) -> dict:
    """Retorna dados ao vivo para uma empresa: preços mensais, FX mensais, vol diário."""
    log.info("Buscando %s e %s...", stock_sym, fx_sym)
    df_stock = _fetch_history(stock_sym, days)
    df_fx    = _fetch_history(fx_sym, days)
    return {
        "monthly_price": _monthly_avg_close(df_stock),
        "monthly_fx":    _monthly_avg_fx(df_fx),
        "daily_vol_usd": _daily_vol_usd(df_stock, df_fx),
        "last_close":    float(df_stock["Close"].iloc[-1]) if not df_stock.empty and "Close" in df_stock.columns else None,
        "last_fx":       float(df_fx["Close"].iloc[-1])   if not df_fx.empty   and "Close" in df_fx.columns else None,
        "last_date":     df_stock.index[-1].isoformat() if not df_stock.empty else None,
    }


def merge_prices(hist: dict[str, float], live: dict[str, float], months: list[str]) -> dict[str, float]:
    """Mescla preços históricos com dados ao vivo (live sobrescreve meses recentes)."""
    merged = dict(hist)
    for m in months:
        if m in live and live[m] and m not in hist:
            merged[m] = live[m]
        elif m in live and live[m]:
            # sobrescreve apenas se for mais recente que o último mês histórico
            merged[m] = live[m]
    return merged


def build_month_list(price_dict: dict[str, Optional[float]], fx_dict: dict[str, float],
                     shares_dict: dict[str, int], cum_inv_k: dict[str, float],
                     qbar_k: dict[str, float], live_month: str) -> list[dict]:
    """Monta lista de pontos mensais para os gráficos."""
    all_months = list(price_dict.keys())
    rows = []
    last_shares = list(shares_dict.values())[-1]
    last_cum = max(cum_inv_k.values()) if cum_inv_k else 0
    for m in all_months:
        p = price_dict.get(m)
        fx = fx_dict.get(m, 0.65)
        shares = shares_dict.get(m, last_shares)
        cum_k = cum_inv_k.get(m, last_cum if m > max(cum_inv_k.keys(), default="") else 0)
        qbar = qbar_k.get(m)
        mcap = (shares * p * fx / 1e6) if p else None
        cum_usdm = cum_k / 1000
        ratio = (mcap / cum_usdm) if mcap and cum_usdm > 0.5 else None
        rows.append({
            "month": m, "priceLocal": p, "fx": fx, "shares": shares,
            "mcapUSDm": mcap, "cumUSDm": cum_usdm,
            "qBarUSDm": qbar / 1000 if qbar else None,
            "ratio": ratio,
            "isLive": m == live_month,
        })
    return rows


# ── HTML GENERATION ───────────────────────────────────────────────────────────

CSS = """
:root {
  --bg: #07090f; --surface: #0d1018; --border: rgba(255,255,255,0.07);
  --text: #e8e4dc; --muted: #7a7670; --gold: #c9a84c; --teal: #4ec9b0;
  --green: #6bc98a; --blue: #5ca8e0; --purple: #b08ae0;
  --orange: #e8a55c; --red: #e05c5c;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: var(--bg); color: var(--text); font-family: 'DM Sans', sans-serif;
       font-size: 13px; min-height: 100vh; }
.nav { display: flex; gap: 0; padding: 16px 40px 0 40px;
       border-bottom: 1px solid var(--border); background: var(--bg);
       position: sticky; top: 0; z-index: 100; }
.tab { font-family: 'DM Mono', monospace; font-size: 11px; letter-spacing: 0.08em;
       text-transform: uppercase; color: var(--muted); background: none;
       border: none; border-bottom: 2px solid transparent;
       padding: 12px 24px; cursor: pointer; transition: all 0.25s ease; white-space: nowrap; }
.tab:hover { color: var(--text); background: rgba(255,255,255,0.02); }
.tab.active { color: var(--gold); border-bottom-color: var(--gold); }
.panel { display: none; padding: 40px; }
.panel.active { display: block; }
.header { display: flex; justify-content: space-between; align-items: flex-start;
          margin-bottom: 32px; border-bottom: 1px solid var(--border); padding-bottom: 24px; }
.header-left h1 { font-family: 'Cormorant Garamond', serif; font-size: 30px;
                  font-weight: 300; letter-spacing: 0.02em; line-height: 1.15; }
.header-left h1 em { color: var(--gold); font-style: italic; }
.header-left p { color: var(--muted); font-size: 11px; margin-top: 6px;
                 font-family: 'DM Mono', monospace; letter-spacing: 0.06em; }
.kpi-row { display: flex; gap: 24px; align-items: flex-start; flex-wrap: wrap; }
.kpi { display: flex; flex-direction: column; align-items: flex-end; }
.kpi-label { font-family: 'DM Mono', monospace; font-size: 9px; color: var(--muted);
             letter-spacing: 0.12em; text-transform: uppercase; margin-bottom: 3px; }
.kpi-value { font-family: 'Cormorant Garamond', serif; font-size: 21px; font-weight: 300; }
.kpi-value.gold { color: var(--gold); }
.kpi-value.teal { color: var(--teal); }
.kpi-value.green { color: var(--green); }
.kpi-value.muted { color: var(--muted); font-size: 17px; }
.kpi-value.live-badge { font-family: 'DM Mono', monospace; font-size: 10px;
                        color: var(--green); border: 1px solid var(--green);
                        border-radius: 2px; padding: 2px 6px; opacity: 0.8; }
.card { background: var(--surface); border: 1px solid var(--border);
        border-radius: 2px; padding: 22px 22px 14px 22px; margin-bottom: 18px; }
.card-title { font-family: 'DM Mono', monospace; font-size: 10px; color: var(--muted);
              letter-spacing: 0.12em; text-transform: uppercase; margin-bottom: 14px; }
.legend { display: flex; gap: 24px; flex-wrap: wrap;
          margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--border); }
.legend-item { display: flex; align-items: center; gap: 7px; font-size: 11px; color: var(--muted); }
.leg-line { width: 20px; height: 2px; border-radius: 1px; }
.leg-bar { width: 10px; height: 10px; border-radius: 1px; opacity: 0.65; }
.leg-dot { width: 8px; height: 8px; border-radius: 50%; }
.tooltip { position: fixed; background: #131820; border: 1px solid rgba(255,255,255,0.13);
           border-radius: 3px; padding: 12px 16px; pointer-events: none; opacity: 0;
           transition: opacity 0.1s; z-index: 1000; min-width: 240px;
           box-shadow: 0 8px 40px rgba(0,0,0,0.75); }
.tooltip.on { opacity: 1; }
.tt-month { font-family: 'DM Mono', monospace; font-size: 11px; color: var(--muted);
            margin-bottom: 9px; letter-spacing: 0.08em; }
.tt-event { font-size: 11px; margin-bottom: 8px; padding: 4px 8px;
            background: rgba(255,255,255,0.04); border-radius: 2px; line-height: 1.4; }
.tt-row { display: flex; justify-content: space-between; gap: 16px;
          margin-bottom: 4px; font-size: 12px; }
.tt-row .l { color: var(--muted); }
.tt-row .v { font-family: 'DM Mono', monospace; color: var(--text); }
.tt-row .v.teal { color: var(--teal); }
.tt-row .v.gold { color: var(--gold); }
.tt-row .v.green { color: var(--green); }
.tt-row .v.red { color: var(--red); }
.tt-div { border: none; border-top: 1px solid var(--border); margin: 7px 0; }
.footnote { font-size: 10px; color: var(--muted); font-family: 'DM Mono', monospace;
            margin-top: 6px; line-height: 1.9; border-top: 1px solid var(--border); padding-top: 14px; }
.footnote strong { color: rgba(255,255,255,0.3); }
.updated { font-family: 'DM Mono', monospace; font-size: 9px; color: var(--muted);
           letter-spacing: 0.1em; text-align: center; padding: 10px 0 4px; opacity: 0.6; }
"""

JS_COMMON = """
function switchTab(idx) {
  document.querySelectorAll('.tab').forEach((t,i) => t.classList.toggle('active', i===idx));
  document.querySelectorAll('.panel').forEach((p,i) => p.classList.toggle('active', i===idx));
}
const tooltip = document.getElementById('tooltip');
function showTT(event, html) {
  tooltip.innerHTML = html; tooltip.classList.add('on'); moveTT(event);
}
function moveTT(event) {
  let lx = event.clientX + 18, ty = event.clientY - 80;
  if (lx + 270 > window.innerWidth) lx = event.clientX - 280;
  if (ty < 10) ty = 10;
  tooltip.style.left = lx+'px'; tooltip.style.top = ty+'px';
}
function hideTT() { tooltip.classList.remove('on'); }
function fmtM(v) { return v >= 1000 ? '$'+(v/1000).toFixed(2)+'B' : '$'+v.toFixed(0)+'M'; }
function fmtMs(v) { return (v/1e6).toFixed(1)+'M'; }
function fmtLocal(v, cur) { return v != null ? cur+' '+v.toFixed(4) : '— suspensa'; }
"""

def _js_array(data: list[dict]) -> str:
    return json.dumps(data, ensure_ascii=False)

def _js_obj(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False)

def _build_panel(
    tab_id: str,
    title: str,
    subtitle: str,
    currency_label: str,  # "CAD" or "AUD"
    months: list[dict],
    issuances: list[dict],
    proj_events: list[dict],
    phase_bands: list[dict],
    footnote: str,
    daily_vol: list[dict],
    grad_id: str,
    live_month: str,
    last_close: Optional[float],
    last_fx: Optional[float],
    last_date: Optional[str],
) -> str:
    months_js = _js_array(months)
    iss_js    = _js_array(issuances)
    ev_js     = _js_array(proj_events)
    bands_js  = _js_array(phase_bands)
    vol_js    = _js_array(daily_vol[-400:] if len(daily_vol) > 400 else daily_vol)

    live_price_str = f"{currency_label} {last_close:.4f}" if last_close else "—"
    live_fx_str    = f"{last_fx:.4f}" if last_fx else "—"
    live_date_str  = last_date or "—"

    return f"""
<div class="panel" id="panel-{tab_id}">
  <div class="header">
    <div class="header-left">
      <h1>{title}</h1>
      <p>{subtitle}</p>
    </div>
    <div class="kpi-row" id="kpis-{tab_id}">
      <div class="kpi">
        <span class="kpi-label">Preço Atual</span>
        <span class="kpi-value gold" id="live-price-{tab_id}">{live_price_str}</span>
      </div>
      <div class="kpi">
        <span class="kpi-label">FX Atual</span>
        <span class="kpi-value muted" id="live-fx-{tab_id}">{live_fx_str}</span>
      </div>
      <div class="kpi">
        <span class="kpi-label">Atualizado</span>
        <span class="kpi-value live-badge">{live_date_str}</span>
      </div>
    </div>
  </div>

  <div id="kpis-calc-{tab_id}" class="kpi-row" style="margin-bottom:24px;justify-content:flex-end;gap:24px;"></div>

  <div class="card">
    <div class="card-title"></div>
    <svg id="chart-main-{tab_id}"></svg>
    <div class="legend">
      <div class="legend-item"><div class="leg-line" style="background:var(--teal)"></div><span>Market Cap (USD)</span></div>
      <div class="legend-item"><div class="leg-bar" style="background:var(--gold)"></div><span>Investimento Trimestral (USD)</span></div>
      <div class="legend-item"><div class="leg-line" style="background:var(--gold);opacity:.5"></div><span>Investimento Acumulado (USD)</span></div>
      <div class="legend-item"><div class="leg-dot" style="background:var(--blue)"></div><span>Emissão de Ações</span></div>
    </div>
  </div>

  <div class="card">
    <div class="card-title">Ações em Circulação (Milhões) — Evolução da Base Acionária</div>
    <svg id="chart-shares-{tab_id}"></svg>
  </div>

  <div class="card">
    <div class="card-title">Volume Financeiro Diário (USD) · Barras Diárias + Média Móvel 20 Dias</div>
    <svg id="chart-volume-{tab_id}"></svg>
    <div class="legend">
      <div class="legend-item"><div class="leg-bar" style="background:#e8a55c;opacity:.55"></div><span>Volume Diário (USD)</span></div>
      <div class="legend-item"><div class="leg-line" style="background:#e8a55c"></div><span>Média Móvel 20 Dias</span></div>
    </div>
  </div>

  <div class="card">
    <div class="card-title">Razão Market Cap / Investimento Acumulado — Retorno Implícito do Capital (×)</div>
    <svg id="chart-ratio-{tab_id}"></svg>
  </div>

  <div class="footnote">{footnote}</div>
</div>

<script>
(function() {{
  const DATA      = {months_js};
  const ISSUANCES = {iss_js};
  const EVENTS    = {ev_js};
  const BANDS     = {bands_js};
  const VOL_DATA  = {vol_js};
  const LIVE_M    = "{live_month}";
  const CUR_LABEL = "{currency_label}";
  const TID       = "{tab_id}";
  const BG        = "#07090f";

  const monthOrder = DATA.map(d => d.month);

  // Computed KPIs
  const listed = DATA.filter(d => d.mcapUSDm != null);
  if (listed.length) {{
    const peak   = listed.reduce((a,b) => a.mcapUSDm > b.mcapUSDm ? a : b);
    const pkR    = DATA.filter(d => d.ratio).reduce((a,b) => a.ratio > b.ratio ? a : b, {{ratio:0}});
    const lastD  = listed[listed.length - 1];
    const totInv = Math.max(...DATA.map(d => d.cumUSDm));
    document.getElementById('kpis-calc-'+TID).innerHTML = `
      <div class="kpi"><span class="kpi-label">Total Investido</span><span class="kpi-value gold">USD ${{totInv.toFixed(0)}}M</span></div>
      <div class="kpi"><span class="kpi-label">Market Cap Pico</span><span class="kpi-value teal">USD ${{peak.mcapUSDm.toFixed(0)}}M</span></div>
      <div class="kpi"><span class="kpi-label">Pico em</span><span class="kpi-value muted">${{peak.month}}</span></div>
      ${{pkR.ratio ? `<div class="kpi"><span class="kpi-label">Múltiplo Pico</span><span class="kpi-value green">${{pkR.ratio.toFixed(1)}}×</span></div>` : ''}}
      ${{lastD.ratio != null ? `<div class="kpi"><span class="kpi-label">Múltiplo Atual</span><span class="kpi-value muted">${{lastD.ratio.toFixed(1)}}×</span></div>` : ''}}
    `;
  }}

  // ── MAIN CHART ──────────────────────────────────────────────────────────────
  function drawMain() {{
    const cont = document.getElementById('chart-main-'+TID).parentElement;
    const W = cont.clientWidth - 44, H = 440;
    const mg = {{top:28, right:84, bottom:50, left:84}};
    const w = W - mg.left - mg.right, h = H - mg.top - mg.bottom;
    const svg = d3.select('#chart-main-'+TID).attr('width',W).attr('height',H);
    const g   = svg.append('g').attr('transform',`translate(${{mg.left}},${{mg.top}})`);

    const x  = d3.scalePoint().domain(monthOrder).range([0,w]).padding(0.08);
    const listedD = DATA.filter(d => d.mcapUSDm != null);
    const yL = d3.scaleLinear().domain([0, d3.max(listedD, d => d.mcapUSDm)*1.18]).range([h,0]);
    const yR = d3.scaleLinear().domain([0, Math.max(
      d3.max(DATA, d => d.cumUSDm||0),
      d3.max(DATA, d => d.qBarUSDm||0)
    )*1.22]).range([h,0]);

    // Phase bands
    BANDS.forEach(b => {{
      const x0=x(b.s), x1=x(b.e); if(!x0||!x1) return;
      g.append('rect').attr('x',x0-x.step()*0.4).attr('width',x1-x0+x.step()*0.8)
        .attr('y',0).attr('height',h).attr('fill',b.c);
      g.append('text').attr('x',(x0+x1)/2).attr('y',13).attr('text-anchor','middle')
        .attr('fill','#8a8480').attr('font-size','9px')
        .attr('font-family','DM Mono,monospace').attr('letter-spacing','0.09em').text(b.label);
    }});

    // Gridlines
    yL.ticks(7).forEach(t => {{
      g.append('line').attr('x1',0).attr('x2',w).attr('y1',yL(t)).attr('y2',yL(t))
        .attr('stroke','rgba(255,255,255,0.035)').attr('stroke-width',1);
    }});

    // Quarterly bars
    const bw = Math.max(5, x.step()*0.36);
    DATA.filter(d=>d.qBarUSDm!=null).forEach(d => {{
      g.append('rect').attr('x',x(d.month)-bw/2).attr('width',bw)
        .attr('y',yR(d.qBarUSDm)).attr('height',h-yR(d.qBarUSDm))
        .attr('fill','rgba(201,168,76,0.45)').attr('rx',1);
    }});

    // Cumulative dashed line
    g.append('path').datum(DATA).attr('fill','none')
      .attr('stroke','rgba(201,168,76,0.45)').attr('stroke-width',1.5).attr('stroke-dasharray','5,3')
      .attr('d', d3.line().x(d=>x(d.month)).y(d=>yR(d.cumUSDm)).defined(d=>d.cumUSDm!=null).curve(d3.curveMonotoneX));

    // MCap area
    const defs = svg.append('defs');
    const gr = defs.append('linearGradient').attr('id','mcg-'+TID).attr('x1',0).attr('y1',0).attr('x2',0).attr('y2',1);
    gr.append('stop').attr('offset','0%').attr('stop-color','#4ec9b0').attr('stop-opacity',0.2);
    gr.append('stop').attr('offset','100%').attr('stop-color','#4ec9b0').attr('stop-opacity',0.02);

    const mcapDefined = d => d.mcapUSDm != null;
    g.append('path').datum(DATA).attr('fill','url(#mcg-'+TID+')')
      .attr('d', d3.area().x(d=>x(d.month)).y0(h).y1(d=>yL(d.mcapUSDm||0)).defined(mcapDefined).curve(d3.curveMonotoneX));
    g.append('path').datum(DATA).attr('fill','none').attr('stroke','#4ec9b0').attr('stroke-width',2)
      .attr('d', d3.line().x(d=>x(d.month)).y(d=>yL(d.mcapUSDm)).defined(mcapDefined).curve(d3.curveMonotoneX));

    // Project events
    EVENTS.forEach(ev => {{
      const xp = x(ev.month); if(!xp) return;
      const dp = DATA.find(d=>d.month===ev.month);
      g.append('line').attr('x1',xp).attr('x2',xp).attr('y1',0).attr('y2',h)
        .attr('stroke',ev.color).attr('stroke-width',1).attr('stroke-opacity',0.22).attr('stroke-dasharray','3,4');
      if(dp && dp.mcapUSDm) g.append('circle').attr('cx',xp).attr('cy',yL(dp.mcapUSDm))
        .attr('r',3).attr('fill',ev.color).attr('stroke',BG).attr('stroke-width',1.5);
    }});

    // Issuance markers
    ISSUANCES.forEach(iv => {{
      const xp = x(iv.month); if(!xp) return;
      g.append('line').attr('x1',xp).attr('x2',xp).attr('y1',0).attr('y2',h)
        .attr('stroke','#5ca8e0').attr('stroke-width',1).attr('stroke-opacity',0.35).attr('stroke-dasharray','1,3');
      const ds=5;
      g.append('polygon').attr('points',`${{xp}},${{h+ds}} ${{xp+ds}},${{h+ds*2}} ${{xp}},${{h+ds*3}} ${{xp-ds}},${{h+ds*2}}`)
        .attr('fill','#5ca8e0').attr('opacity',0.8);
    }});

    // Live dot
    const liveD = DATA.find(d => d.month === LIVE_M);
    if (liveD && liveD.mcapUSDm) {{
      g.append('circle').attr('cx',x(LIVE_M)).attr('cy',yL(liveD.mcapUSDm))
        .attr('r',5).attr('fill','#6bc98a').attr('stroke',BG).attr('stroke-width',2);
      g.append('text').attr('x',x(LIVE_M)+8).attr('y',yL(liveD.mcapUSDm)-8)
        .attr('fill','#6bc98a').attr('font-size','9px').attr('font-family','DM Mono,monospace').text('● LIVE');
    }}

    // Peak
    if (listedD.length) {{
      const peak = listedD.reduce((a,b) => a.mcapUSDm > b.mcapUSDm ? a : b);
      g.append('circle').attr('cx',x(peak.month)).attr('cy',yL(peak.mcapUSDm))
        .attr('r',5).attr('fill','none').attr('stroke','#4ec9b0').attr('stroke-width',1.5).attr('stroke-dasharray','3,2');
      const px = x(peak.month) > w*0.7 ? x(peak.month)-8 : x(peak.month)+8;
      g.append('text').attr('x',px).attr('y',yL(peak.mcapUSDm)-9)
        .attr('text-anchor', x(peak.month)>w*0.7?'end':'start')
        .attr('fill','#4ec9b0').attr('font-size','10px').attr('font-family','DM Mono,monospace')
        .text(`${{fmtM(peak.mcapUSDm)}} (${{peak.month}})`);
    }}

    // Axes
    g.append('g').attr('transform',`translate(0,${{h}})`).call(
      d3.axisBottom(x).tickValues(monthOrder.filter((_,i)=>i%3===0)).tickSize(4)
    ).call(ax=>{{
      ax.select('.domain').attr('stroke','rgba(255,255,255,0.1)');
      ax.selectAll('.tick line').attr('stroke','rgba(255,255,255,0.1)');
      ax.selectAll('.tick text').attr('fill','#7a7670').attr('font-size','10px').attr('font-family','DM Mono,monospace').attr('dy','1.2em');
    }});
    g.append('g').call(d3.axisLeft(yL).ticks(7).tickFormat(d=>fmtM(d)).tickSize(4)).call(ax=>{{
      ax.select('.domain').attr('stroke','rgba(255,255,255,0.08)');
      ax.selectAll('.tick line').attr('stroke','rgba(255,255,255,0.05)');
      ax.selectAll('.tick text').attr('fill','#4ec9b0').attr('font-size','10px').attr('font-family','DM Mono,monospace');
    }});
    g.append('g').attr('transform',`translate(${{w}},0)`).call(
      d3.axisRight(yR).ticks(7).tickFormat(d=>`$${{d.toFixed(0)}}M`).tickSize(4)
    ).call(ax=>{{
      ax.select('.domain').attr('stroke','rgba(255,255,255,0.08)');
      ax.selectAll('.tick line').attr('stroke','rgba(255,255,255,0.05)');
      ax.selectAll('.tick text').attr('fill','rgba(201,168,76,0.75)').attr('font-size','10px').attr('font-family','DM Mono,monospace');
    }});

    // Axis labels
    g.append('text').attr('transform','rotate(-90)').attr('x',-h/2).attr('y',-68)
      .attr('text-anchor','middle').attr('fill','#4ec9b0').attr('font-size','10px')
      .attr('font-family','DM Mono,monospace').attr('letter-spacing','0.1em').text('MARKET CAP (USD)');
    g.append('text').attr('transform','rotate(90)').attr('x',h/2).attr('y',-(w+68))
      .attr('text-anchor','middle').attr('fill','rgba(201,168,76,0.75)').attr('font-size','10px')
      .attr('font-family','DM Mono,monospace').attr('letter-spacing','0.1em').text('INVESTIMENTO (USD)');

    // Hover
    const hLine = g.append('line').attr('y1',0).attr('y2',h)
      .attr('stroke','rgba(255,255,255,0.1)').attr('stroke-width',1).style('display','none').attr('pointer-events','none');

    g.append('rect').attr('width',w).attr('height',h).attr('fill','transparent').attr('cursor','crosshair')
      .on('mousemove', function(event) {{
        const [mx] = d3.pointer(event);
        let ni=0, md=Infinity;
        monthOrder.forEach((m,i)=>{{ const d2=Math.abs(x(m)-mx); if(d2<md){{md=d2;ni=i;}} }});
        const d = DATA[ni];
        hLine.style('display',null).attr('x1',x(d.month)).attr('x2',x(d.month));
        const ev  = EVENTS.find(e=>e.month===d.month);
        const iss = ISSUANCES.find(e=>e.month===d.month);
        const evH  = ev  ? `<div class="tt-event" style="border-left:2px solid ${{ev.color}};color:${{ev.color}}">${{ev.label}}</div>` : '';
        const isH  = iss ? `<div class="tt-event" style="border-left:2px solid var(--blue);color:var(--blue)">${{iss.label}}</div>` : '';
        const liveH = d.isLive ? '<div class="tt-event" style="border-left:2px solid #6bc98a;color:#6bc98a">● Dado ao vivo</div>' : '';
        showTT(event, `
          <div class="tt-month">${{d.month.toUpperCase()}}</div>
          ${{evH}}${{isH}}${{liveH}}
          <div class="tt-row"><span class="l">Ações em circulação</span><span class="v">${{fmtMs(d.shares)}}</span></div>
          <div class="tt-row"><span class="l">Cotação</span><span class="v">${{d.priceLocal != null ? CUR_LABEL+' '+d.priceLocal.toFixed(4) : '— suspensa'}}</span></div>
          <div class="tt-row"><span class="l">${{CUR_LABEL}}/USD</span><span class="v">${{d.fx.toFixed(4)}}</span></div>
          <div class="tt-row"><span class="l">Market Cap</span><span class="v teal">${{d.mcapUSDm != null ? fmtM(d.mcapUSDm) : '—'}}</span></div>
          <hr class="tt-div">
          <div class="tt-row"><span class="l">Invest. Acumulado</span><span class="v gold">$${{d.cumUSDm.toFixed(1)}}M</span></div>
          ${{d.qBarUSDm!=null?`<div class="tt-row"><span class="l">Invest. Trimestral</span><span class="v">$${{d.qBarUSDm.toFixed(1)}}M</span></div>`:''}}
          <hr class="tt-div">
          <div class="tt-row"><span class="l">MCap / Acumulado</span><span class="v ${{d.ratio!=null&&d.ratio>=1?'green':'red'}}">${{d.ratio!=null?d.ratio.toFixed(2)+'×':'—'}}</span></div>
        `);
      }})
      .on('mousemove.move', moveTT)
      .on('mouseleave', ()=>{{ hLine.style('display','none'); hideTT(); }});
  }}

  // ── SHARES CHART ─────────────────────────────────────────────────────────
  function drawShares() {{
    const cont = document.getElementById('chart-shares-'+TID).parentElement;
    const W = cont.clientWidth - 44, H = 180;
    const mg = {{top:20, right:84, bottom:48, left:84}};
    const w = W - mg.left - mg.right, h = H - mg.top - mg.bottom;
    const svg = d3.select('#chart-shares-'+TID).attr('width',W).attr('height',H);
    const g   = svg.append('g').attr('transform',`translate(${{mg.left}},${{mg.top}})`);

    const x = d3.scalePoint().domain(monthOrder).range([0,w]).padding(0.08);
    const y = d3.scaleLinear()
      .domain([d3.min(DATA,d=>d.shares)*0.93, d3.max(DATA,d=>d.shares)*1.07])
      .range([h,0]);

    y.ticks(4).forEach(t => {{
      g.append('line').attr('x1',0).attr('x2',w).attr('y1',y(t)).attr('y2',y(t))
        .attr('stroke','rgba(255,255,255,0.035)').attr('stroke-width',1);
    }});

    const defs2 = svg.append('defs');
    const gr2 = defs2.append('linearGradient').attr('id','shg-'+TID).attr('x1',0).attr('y1',0).attr('x2',0).attr('y2',1);
    gr2.append('stop').attr('offset','0%').attr('stop-color','#5ca8e0').attr('stop-opacity',0.2);
    gr2.append('stop').attr('offset','100%').attr('stop-color','#5ca8e0').attr('stop-opacity',0.02);

    g.append('path').datum(DATA).attr('fill','url(#shg-'+TID+')')
      .attr('d', d3.area().x(d=>x(d.month)).y0(h).y1(d=>y(d.shares)).curve(d3.curveStepAfter));
    g.append('path').datum(DATA).attr('fill','none').attr('stroke','#5ca8e0').attr('stroke-width',1.5)
      .attr('d', d3.line().x(d=>x(d.month)).y(d=>y(d.shares)).curve(d3.curveStepAfter));

    ISSUANCES.forEach(iv => {{
      const xp = x(iv.month); if(!xp) return;
      const dp = DATA.find(d=>d.month===iv.month); if(!dp) return;
      g.append('line').attr('x1',xp).attr('x2',xp).attr('y1',0).attr('y2',h)
        .attr('stroke','#5ca8e0').attr('stroke-width',1).attr('stroke-opacity',0.4).attr('stroke-dasharray','2,3');
      g.append('circle').attr('cx',xp).attr('cy',y(dp.shares)).attr('r',4)
        .attr('fill','#5ca8e0').attr('stroke',BG).attr('stroke-width',1.5);
      const addedM = (iv.shares/1e6).toFixed(iv.shares>1e6?1:2);
      const lx = xp > w*0.8 ? xp-6 : xp+6;
      g.append('text').attr('x',lx).attr('y',y(dp.shares)-9)
        .attr('text-anchor', xp>w*0.8?'end':'start')
        .attr('fill','#5ca8e0').attr('font-size','9px').attr('font-family','DM Mono,monospace')
        .text(`+${{addedM}}M`);
    }});

    g.append('g').attr('transform',`translate(0,${{h}})`).call(
      d3.axisBottom(x).tickValues(monthOrder.filter((_,i)=>i%3===0)).tickSize(4)
    ).call(ax=>{{
      ax.select('.domain').attr('stroke','rgba(255,255,255,0.1)');
      ax.selectAll('.tick line').attr('stroke','rgba(255,255,255,0.1)');
      ax.selectAll('.tick text').attr('fill','#7a7670').attr('font-size','10px').attr('font-family','DM Mono,monospace').attr('dy','1.2em');
    }});
    g.append('g').call(d3.axisLeft(y).ticks(4).tickFormat(d=>`${{(d/1e6).toFixed(0)}}M`).tickSize(4)).call(ax=>{{
      ax.select('.domain').attr('stroke','rgba(255,255,255,0.08)');
      ax.selectAll('.tick line').attr('stroke','rgba(255,255,255,0.05)');
      ax.selectAll('.tick text').attr('fill','#5ca8e0').attr('font-size','10px').attr('font-family','DM Mono,monospace');
    }});
    g.append('text').attr('transform','rotate(-90)').attr('x',-h/2).attr('y',-68)
      .attr('text-anchor','middle').attr('fill','#5ca8e0').attr('font-size','10px')
      .attr('font-family','DM Mono,monospace').attr('letter-spacing','0.1em').text('AÇÕES EM CIRCULAÇÃO');
  }}

  // ── VOLUME CHART ─────────────────────────────────────────────────────────
  function drawVolume() {{
    if (!VOL_DATA.length) return;
    const cont = document.getElementById('chart-volume-'+TID).parentElement;
    const W = cont.clientWidth - 44, H = 220;
    const mg = {{top:22, right:84, bottom:48, left:84}};
    const w = W - mg.left - mg.right, h = H - mg.top - mg.bottom;
    const svg = d3.select('#chart-volume-'+TID).attr('width',W).attr('height',H);
    const g   = svg.append('g').attr('transform',`translate(${{mg.left}},${{mg.top}})`);

    const parseDate = d3.timeParse('%Y-%m-%d');
    const vd = VOL_DATA.map(r => ({{...r, date: parseDate(r.d)}})).filter(r => r.date);
    vd.sort((a,b) => a.date - b.date);

    const x = d3.scaleTime().domain(d3.extent(vd, d=>d.date)).range([0,w]);
    const y = d3.scaleLinear().domain([0, d3.max(vd,d=>d.v)*1.18]).range([h,0]);

    const bw = Math.max(1, w / vd.length * 0.8);
    vd.forEach(d => {{
      g.append('rect').attr('x', x(d.date)-bw/2).attr('width',bw)
        .attr('y',y(d.v)).attr('height',h-y(d.v)).attr('fill','rgba(232,165,92,0.45)').attr('rx',0.5);
    }});

    // 20-day moving average
    const ma20 = vd.map((d,i) => {{
      if (i < 19) return null;
      const slice = vd.slice(i-19, i+1);
      return {{date: d.date, avg: d3.mean(slice, s=>s.v)}};
    }}).filter(Boolean);

    if (ma20.length > 1) {{
      g.append('path').datum(ma20).attr('fill','none').attr('stroke','#e8a55c').attr('stroke-width',1.5)
        .attr('d', d3.line().x(d=>x(d.date)).y(d=>y(d.avg)).curve(d3.curveMonotoneX));
    }}

    g.append('g').attr('transform',`translate(0,${{h}})`).call(
      d3.axisBottom(x).ticks(8).tickSize(4)
    ).call(ax=>{{
      ax.select('.domain').attr('stroke','rgba(255,255,255,0.1)');
      ax.selectAll('.tick line').attr('stroke','rgba(255,255,255,0.1)');
      ax.selectAll('.tick text').attr('fill','#7a7670').attr('font-size','10px').attr('font-family','DM Mono,monospace').attr('dy','1.2em');
    }});
    g.append('g').call(d3.axisLeft(y).ticks(5).tickFormat(d=>{{
      if (d >= 1e6) return '$'+(d/1e6).toFixed(1)+'M';
      if (d >= 1e3) return '$'+(d/1e3).toFixed(0)+'k';
      return '$'+d.toFixed(0);
    }}).tickSize(4)).call(ax=>{{
      ax.select('.domain').attr('stroke','rgba(255,255,255,0.08)');
      ax.selectAll('.tick line').attr('stroke','rgba(255,255,255,0.05)');
      ax.selectAll('.tick text').attr('fill','#e8a55c').attr('font-size','10px').attr('font-family','DM Mono,monospace');
    }});
    g.append('text').attr('transform','rotate(-90)').attr('x',-h/2).attr('y',-72)
      .attr('text-anchor','middle').attr('fill','#e8a55c').attr('font-size','10px')
      .attr('font-family','DM Mono,monospace').attr('letter-spacing','0.1em').text('VOLUME (USD)');
  }}

  // ── RATIO CHART ──────────────────────────────────────────────────────────
  function drawRatio() {{
    const rData = DATA.filter(d => d.ratio != null && d.cumUSDm > 0.5);
    if (!rData.length) return;
    const cont = document.getElementById('chart-ratio-'+TID).parentElement;
    const W = cont.clientWidth - 44, H = 200;
    const mg = {{top:22, right:84, bottom:48, left:84}};
    const w = W - mg.left - mg.right, h = H - mg.top - mg.bottom;
    const svg = d3.select('#chart-ratio-'+TID).attr('width',W).attr('height',H);
    const g   = svg.append('g').attr('transform',`translate(${{mg.left}},${{mg.top}})`);

    const x = d3.scalePoint().domain(monthOrder).range([0,w]).padding(0.08);
    const y = d3.scaleLinear().domain([0, d3.max(rData,d=>d.ratio)*1.12]).range([h,0]);

    g.append('line').attr('x1',0).attr('x2',w).attr('y1',y(1)).attr('y2',y(1))
      .attr('stroke','rgba(255,255,255,0.13)').attr('stroke-width',1).attr('stroke-dasharray','4,4');
    g.append('text').attr('x',w+5).attr('y',y(1)+4).attr('fill','#7a7670')
      .attr('font-size','9px').attr('font-family','DM Mono,monospace').text('1×');

    const defs3 = svg.append('defs');
    const gr3 = defs3.append('linearGradient').attr('id','ratg-'+TID).attr('x1',0).attr('y1',0).attr('x2',0).attr('y2',1);
    gr3.append('stop').attr('offset','0%').attr('stop-color','#6bc98a').attr('stop-opacity',0.25);
    gr3.append('stop').attr('offset','100%').attr('stop-color','#6bc98a').attr('stop-opacity',0.02);

    g.append('path').datum(rData).attr('fill','url(#ratg-'+TID+')')
      .attr('d', d3.area().x(d=>x(d.month)).y0(h).y1(d=>y(d.ratio)).curve(d3.curveMonotoneX));
    g.append('path').datum(rData).attr('fill','none').attr('stroke','#6bc98a').attr('stroke-width',2)
      .attr('d', d3.line().x(d=>x(d.month)).y(d=>y(d.ratio)).curve(d3.curveMonotoneX));

    const pk = rData.reduce((a,b)=>a.ratio>b.ratio?a:b);
    g.append('circle').attr('cx',x(pk.month)).attr('cy',y(pk.ratio)).attr('r',4.5).attr('fill','#6bc98a');
    const pkx = x(pk.month)>w*0.7?x(pk.month)-8:x(pk.month)+8;
    g.append('text').attr('x',pkx).attr('y',y(pk.ratio)-8)
      .attr('text-anchor',x(pk.month)>w*0.7?'end':'start')
      .attr('fill','#6bc98a').attr('font-size','10px').attr('font-family','DM Mono,monospace')
      .text(`${{pk.ratio.toFixed(1)}}× (${{pk.month}})`);

    const lrd = rData[rData.length-1];
    g.append('circle').attr('cx',x(lrd.month)).attr('cy',y(lrd.ratio)).attr('r',3.5).attr('fill','#6bc98a').attr('opacity',0.7);
    g.append('text').attr('x',x(lrd.month)-8).attr('y',y(lrd.ratio)-9)
      .attr('text-anchor','end').attr('fill','rgba(107,201,138,0.65)').attr('font-size','10px')
      .attr('font-family','DM Mono,monospace').text(`${{lrd.ratio.toFixed(1)}}× atual`);

    g.append('g').attr('transform',`translate(0,${{h}})`).call(
      d3.axisBottom(x).tickValues(monthOrder.filter((_,i)=>i%3===0)).tickSize(4)
    ).call(ax=>{{
      ax.select('.domain').attr('stroke','rgba(255,255,255,0.1)');
      ax.selectAll('.tick line').attr('stroke','rgba(255,255,255,0.1)');
      ax.selectAll('.tick text').attr('fill','#7a7670').attr('font-size','10px').attr('font-family','DM Mono,monospace').attr('dy','1.2em');
    }});
    g.append('g').call(d3.axisLeft(y).ticks(5).tickFormat(d=>`${{d.toFixed(1)}}×`).tickSize(4)).call(ax=>{{
      ax.select('.domain').attr('stroke','rgba(255,255,255,0.08)');
      ax.selectAll('.tick line').attr('stroke','rgba(255,255,255,0.05)');
      ax.selectAll('.tick text').attr('fill','#6bc98a').attr('font-size','10px').attr('font-family','DM Mono,monospace');
    }});
  }}

  drawMain(); drawShares(); drawVolume(); drawRatio();
  window.addEventListener('resize', () => {{
    d3.select('#chart-main-'+TID).selectAll('*').remove();
    d3.select('#chart-shares-'+TID).selectAll('*').remove();
    d3.select('#chart-volume-'+TID).selectAll('*').remove();
    d3.select('#chart-ratio-'+TID).selectAll('*').remove();
    drawMain(); drawShares(); drawVolume(); drawRatio();
  }});
}})();
</script>
"""


def generate_html(companies: list[dict], updated: str) -> str:
    tabs_html = "".join(
        f'<button class="tab{" active" if i==0 else ""}" onclick="switchTab({i})">'
        f'{c["label"]}</button>'
        for i, c in enumerate(companies)
    )
    panels_html = "".join(c["panel_html"] for c in companies)

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dashboard REE — Market Cap vs. Investimento</title>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;0,600;1,300&family=DM+Mono:wght@300;400&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.8.5/d3.min.js"></script>
<style>{CSS}</style>
</head>
<body>

<div class="nav">
{tabs_html}
</div>

{panels_html}

<div id="tooltip" class="tooltip"></div>
<div class="updated">Dados ao vivo via Yahoo Finance · Atualizado em {updated}</div>

<script>
{JS_COMMON}
// activate first panel
document.querySelectorAll('.panel')[0].classList.add('active');
</script>
</body>
</html>"""


# ── MAIN ──────────────────────────────────────────────────────────────────────

COMPANIES_CONFIG = [
    {
        "id":      "ara",
        "label":   "ARA — Carina",
        "title":   "ARA — <em>Investimento no Portfólio vs. Market Cap</em>",
        "subtitle":"ACLARA RESOURCES INC. · CARINA PROJECT (BRASIL) · TSX: ARA · USD · AÇÕES CORRIGIDAS POR EMISSÃO",
        "currency":"CAD",
        "yf_stock":"ARA.TO",
        "yf_fx":   "CADUSD=X",
        "shares":  ARA_SHARES,
        "hist_price": ARA_PRICE_CAD,
        "hist_fx":    ARA_CADUSD,
        "cum_inv_k":  ARA_CUM_INV_K,
        "qbar_k":     ARA_QBAR_K,
        "issuances":  ARA_ISSUANCES,
        "proj_events":ARA_PROJ_EVENTS,
        "phase_bands":ARA_PHASE_BANDS,
        "footnote":   ARA_FOOTNOTE,
    },
    {
        "id":      "bre",
        "label":   "BRE — Rocha da Rocha",
        "title":   "BRE — <em>Investimento no Projeto vs. Market Cap</em>",
        "subtitle":"BRAZILIAN RARE EARTHS LTD. · ASX: BRE · USD · AÇÕES CORRIGIDAS POR EMISSÃO",
        "currency":"AUD",
        "yf_stock":"BRE.AX",
        "yf_fx":   "AUDUSD=X",
        "shares":  BRE_SHARES,
        "hist_price": BRE_PRICE_AUD,
        "hist_fx":    BRE_AUDUSD,
        "cum_inv_k":  BRE_CUM_INV_K,
        "qbar_k":     BRE_QBAR_K,
        "issuances":  BRE_ISSUANCES,
        "proj_events":BRE_PROJ_EVENTS,
        "phase_bands":BRE_PHASE_BANDS,
        "footnote":   BRE_FOOTNOTE,
    },
    {
        "id":      "mei",
        "label":   "MEI — Caldeira",
        "title":   "MEI — <em>Investimento no Projeto vs. Market Cap</em>",
        "subtitle":"METEORIC RESOURCES NL · CALDEIRA PROJECT (BRASIL) · ASX: MEI · USD · AÇÕES CORRIGIDAS POR EMISSÃO",
        "currency":"AUD",
        "yf_stock":"MEI.AX",
        "yf_fx":   "AUDUSD=X",
        "shares":  MEI_SHARES,
        "hist_price": MEI_PRICE_AUD,
        "hist_fx":    MEI_AUDUSD,
        "cum_inv_k":  {k: v * MEI_AUDUSD.get(k, 0.65) for k, v in MEI_CUM_AUD_K.items()},
        "qbar_k":     {k: v * MEI_AUDUSD.get(k, 0.65) for k, v in MEI_QUARTERLY_AUD_K.items()},
        "issuances":  MEI_ISSUANCES,
        "proj_events":MEI_PROJ_EVENTS,
        "phase_bands":MEI_PHASE_BANDS,
        "footnote":   MEI_FOOTNOTE,
    },
    {
        "id":      "sgq",
        "label":   "SGQ — Araxá",
        "title":   "SGQ — <em>Investimento no Araxá vs. Market Cap</em>",
        "subtitle":"ST. GEORGE MINING LTD. · ARAXÁ PROJECT (BRASIL) · ASX: SGQ · USD · AÇÕES CORRIGIDAS POR EMISSÃO",
        "currency":"AUD",
        "yf_stock":"SGQ.AX",
        "yf_fx":   "AUDUSD=X",
        "shares":  SGQ_SHARES,
        "hist_price": SGQ_PRICE_AUD,
        "hist_fx":    SGQ_AUDUSD,
        "cum_inv_k":  SGQ_CUM_INV_K,
        "qbar_k":     SGQ_QBAR_K,
        "issuances":  SGQ_ISSUANCES,
        "proj_events":SGQ_PROJ_EVENTS,
        "phase_bands":SGQ_PHASE_BANDS,
        "footnote":   SGQ_FOOTNOTE,
    },
    {
        "id":      "vmm",
        "label":   "VMM — Colossus",
        "title":   "VMM — <em>Investimento no Colossus vs. Market Cap</em>",
        "subtitle":"VIRIDIS MINING AND MINERALS LTD. · COLOSSUS PROJECT (BRASIL) · ASX: VMM · USD · AÇÕES CORRIGIDAS POR EMISSÃO",
        "currency":"AUD",
        "yf_stock":"VMM.AX",
        "yf_fx":   "AUDUSD=X",
        "shares":  VMM_SHARES,
        "hist_price": VMM_PRICE_AUD,
        "hist_fx":    VMM_AUDUSD,
        "cum_inv_k":  VMM_CUM_INV_K,
        "qbar_k":     VMM_QBAR_K,
        "issuances":  VMM_ISSUANCES,
        "proj_events":VMM_PROJ_EVENTS,
        "phase_bands":VMM_PHASE_BANDS,
        "footnote":   VMM_FOOTNOTE,
    },
]

# Pre-convert MEI cum/qbar to USD (done above inline)


def main() -> None:
    now = dt.datetime.utcnow()
    updated_str = now.strftime("%d/%m/%Y %H:%M UTC")
    cur_month = today_month_key()

    # Fetch FX once (AUD/USD shared by BRE, MEI, SGQ, VMM)
    live_cache: dict[str, dict] = {}

    companies_out = []
    for cfg in COMPANIES_CONFIG:
        live_key = f"{cfg['yf_stock']}|{cfg['yf_fx']}"
        if live_key not in live_cache:
            live_cache[live_key] = fetch_live(cfg["yf_stock"], cfg["yf_fx"])
        live = live_cache[live_key]

        # Merge historical + live monthly prices
        price = dict(cfg["hist_price"])
        for mk, pv in live["monthly_price"].items():
            if mk not in price or mk >= cur_month:
                price[mk] = pv

        fx = dict(cfg["hist_fx"])
        for mk, fv in live["monthly_fx"].items():
            if mk not in fx or mk >= cur_month:
                fx[mk] = fv

        # Ensure shares dict covers all price months (extend with last known)
        shares = dict(cfg["shares"])
        last_s = list(shares.values())[-1]
        for mk in price:
            if mk not in shares:
                shares[mk] = last_s

        # Extend cum_inv with last known value
        cum_inv = dict(cfg["cum_inv_k"])
        last_cum = max(cum_inv.values()) if cum_inv else 0
        for mk in sorted(price.keys()):
            if mk not in cum_inv and mk > max(cum_inv.keys(), default=""):
                cum_inv[mk] = last_cum

        months_data = build_month_list(
            price, fx, shares, cum_inv, cfg["qbar_k"], cur_month
        )

        # Determine live info
        lc = live["last_close"]
        lf = live["last_fx"]
        ld = live["last_date"]

        panel = _build_panel(
            tab_id=cfg["id"],
            title=cfg["title"],
            subtitle=cfg["subtitle"],
            currency_label=cfg["currency"],
            months=months_data,
            issuances=cfg["issuances"],
            proj_events=cfg["proj_events"],
            phase_bands=cfg["phase_bands"],
            footnote=cfg["footnote"],
            daily_vol=live["daily_vol_usd"],
            grad_id=cfg["id"],
            live_month=cur_month,
            last_close=lc,
            last_fx=lf,
            last_date=ld,
        )
        companies_out.append({"label": cfg["label"], "panel_html": panel})

    html = generate_html(companies_out, updated_str)
    out_path = os.path.join(os.path.dirname(__file__), "docs", "mcap_dashboard.html")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    log.info("Gerado: %s (%d bytes)", out_path, len(html))


if __name__ == "__main__":
    main()
