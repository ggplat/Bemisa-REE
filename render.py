"""Monta o contexto e renderiza o dashboard HTML a partir dos comunicados."""
from __future__ import annotations

import datetime as dt
import os
from collections import defaultdict
from typing import Iterable, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from sources.base import Announcement, Company

MESES_PT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")


def _date_label(d: dt.date) -> str:
    return f"{d.day:02d}/{MESES_PT[d.month - 1]}/{d.year % 100:02d}"


def _month_label(year: int, month: int) -> str:
    return f"{MESES_PT[month - 1]}/{year % 100:02d}"


def _fmt_pct(value: float) -> str:
    # formato brasileiro: virgula decimal, 1 casa
    return f"{abs(value):.1f}".replace(".", ",")


def _chg(value: Optional[float]) -> tuple[str, str]:
    """Retorna (classe_css, html) para a variacao percentual."""
    if value is None:
        return "none", "&mdash;"
    if value > 0.05:
        return "up", f"&#9650;&nbsp;{_fmt_pct(value)}%"
    if value < -0.05:
        return "down", f"&#9660;&nbsp;{_fmt_pct(value)}%"
    return "flat", f"0,0%"


def _fmt_price(value: float) -> str:
    return f"{value:.3f}".replace(".", ",")


def _chart_url(symbol: str) -> str:
    # pagina de cotacao do Yahoo (mesmo simbolo do calculo) com grafico interativo
    return f"https://finance.yahoo.com/quote/{symbol}"


def _chg_tooltip(a: Announcement, symbol: str) -> str:
    """Texto do tooltip que confirma o valor da variacao."""
    arrow = "▲" if a.pct_change > 0.05 else ("▼" if a.pct_change < -0.05 else "=")
    when = _date_label(a.reaction_date) if a.reaction_date else _date_label(a.date)
    return (f"Reação em {when} · fech. anterior {_fmt_price(a.prev_close)} "
            f"→ {_fmt_price(a.close)} · {arrow} {_fmt_pct(a.pct_change)}% "
            f"(Yahoo Finance: {symbol})")


def _build_company(company: Company, anns: list[Announcement], *, selected: bool) -> dict:
    anns = sorted(anns, key=lambda a: a.date, reverse=True)
    groups: "defaultdict[tuple[int, int], list[Announcement]]" = defaultdict(list)
    for a in anns:
        groups[(a.date.year, a.date.month)].append(a)

    months = []
    for (year, month) in sorted(groups.keys(), reverse=True):
        items = []
        for a in groups[(year, month)]:
            chg_class, chg_html = _chg(a.pct_change)
            has_data = a.pct_change is not None and a.prev_close is not None
            items.append({
                "date_label": _date_label(a.date),
                "title": a.title,
                "url": a.url,
                "ps": a.price_sensitive,
                "data_ps": "1" if a.price_sensitive else "0",
                "data_text": a.title.lower(),  # autoescape do Jinja cuida do atributo
                "chg_class": chg_class,
                "chg_html": chg_html,
                "chg_url": _chart_url(company.yf_symbol) if has_data else None,
                "chg_title": _chg_tooltip(a, company.yf_symbol) if has_data else "",
                "tags": a.tags,
            })
        months.append({
            "key": f"{year}-{month:02d}",
            "label": _month_label(year, month),
            "count": len(items),
            "entries": items,
        })

    projects = [
        {"name": p.get("name", ""),
         "tier": p.get("tier", "secundario"),
         "is_main": p.get("tier", "secundario") == "principal"}
        for p in (company.projects or [])
    ]

    return {
        "ticker": company.ticker,
        "exchange": company.exchange,
        "exchange_lower": company.exchange.lower(),
        "name": company.name,
        "company_url": company.company_url,
        "projects": projects,
        "count": len(anns),
        "selected": selected,
        "months": months,
    }


def build_context(companies: list[Company],
                  anns_by_ticker: dict[str, list[Announcement]],
                  *, updated: Optional[dt.datetime] = None) -> dict:
    updated = updated or dt.datetime.now()
    company_views = []
    total = 0
    total_ps = 0
    for i, company in enumerate(companies):
        anns = anns_by_ticker.get(company.ticker, [])
        total += len(anns)
        total_ps += sum(1 for a in anns if a.price_sensitive)
        company_views.append(_build_company(company, anns, selected=(i == 0)))

    return {
        "updated": updated.strftime("%d/%m/%Y %H:%M"),
        "n_companies": len(companies),
        "n_announcements": total,
        "n_ps": total_ps,
        "companies": company_views,
    }


def render_html(context: dict) -> str:
    env = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "j2"]),
    )
    template = env.get_template("dashboard.html.j2")
    return template.render(**context)
