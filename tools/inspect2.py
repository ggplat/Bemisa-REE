"""Diagnostico (temporario) para 3 questoes:
  1) markit ASX: como obter MAIS de 5 comunicados / historico (issue 'antes de abr')
  2) TMX news (Aclara/ARA): achar a fonte de noticias
  3) Appia (appiareu.com/news/): estrutura da pagina de noticias

Uso em CI: python tools/inspect2.py
"""
from __future__ import annotations

import json
import re
import sys

sys.path.insert(0, ".")
from sources import http_util

ASX_BASE = "https://www.asx.com.au"
MARKIT = "https://asx.api.markitdigital.com"


def hr(t): print(f"\n========== {t} ==========")


def markit(code: str):
    hr(f"MARKIT {code} - testando limites/paginacao")
    for qs in ["count=50&pageSize=50", "count=200", "pageSize=200", "count=50&page=2", "count=50&pageSize=50&page=2"]:
        url = f"{MARKIT}/asx-research/1.0/companies/{code}/announcements?{qs}"
        r = http_util.get(url, headers={"Accept": "application/json", "Origin": ASX_BASE,
                                        "Referer": f"{ASX_BASE}/markets/company/{code}"})
        if r is None:
            print(f"  [{qs}] sem resposta"); continue
        items = (r.json().get("data") or {}).get("items") or []
        dates = sorted(i.get("date", "")[:10] for i in items)
        print(f"  [{qs}] n={len(items)} range={dates[:1]}..{dates[-1:]}")


def tmx(code: str):
    hr(f"TMX news {code}")
    # tentativa 1: GraphQL
    gql = {
        "operationName": "getNewsForSymbol",
        "variables": {"symbol": code, "page": 1, "limit": 20, "locale": "en"},
        "query": "query getNewsForSymbol($symbol: String!, $page: Int, $limit: Int){ news(symbol:$symbol, page:$page, limit:$limit){ headline datetime source newsid } }",
    }
    try:
        r = http_util.session().post("https://app-money.tmx.com/graphql", json=gql, timeout=20,
                                     headers={"Accept": "application/json", "locale": "en",
                                              "Origin": "https://money.tmx.com",
                                              "Referer": "https://money.tmx.com/"})
        print("  GraphQL status", r.status_code, "| body:", r.text[:600])
    except Exception as exc:  # noqa: BLE001
        print("  GraphQL erro:", exc)
    # tentativa 2: HTML da pagina de noticias (procura api/links)
    r = http_util.get(f"https://money.tmx.com/en/quote/{code}/news")
    if r is not None:
        html = r.text
        print("  HTML len", len(html))
        print("  api hints:", set(re.findall(r'https://app-money\.tmx\.com/[a-z/]+', html))[:5] if re.findall(r'https://app-money\.tmx\.com/[a-z/]+', html) else 'nenhum')
        print("  __NEXT_DATA__ present:", '__NEXT_DATA__' in html)


def appia(url: str):
    hr(f"APPIA {url}")
    r = http_util.get(url)
    if r is None:
        print("  sem resposta"); return
    html = r.text
    print("  HTML len", len(html))
    # procura links de artigos e datas tipicas de listagem WordPress
    links = re.findall(r'<a[^>]+href=\"(https?://appiareu\.com/[^\"]+)\"[^>]*>([^<]{8,120})</a>', html)
    print("  amostra de links/titulos:")
    seen = set()
    for href, txt in links:
        t = txt.strip()
        if href in seen or not t or '/news' in href and t.lower() in ('news', 'read more'):
            continue
        seen.add(href)
        print("   -", t[:80], "->", href)
        if len(seen) >= 12:
            break
    # procura datas
    print("  datas (amostra):", re.findall(r'\b(\d{1,2}\s+\w+\s+20\d\d|\w+\s+\d{1,2},\s*20\d\d|20\d\d-\d\d-\d\d)\b', html)[:8])
    # procura feed RSS
    print("  rss link:", re.findall(r'href=\"([^\"]*feed[^\"]*)\"', html)[:3])


if __name__ == "__main__":
    markit("BRE")
    markit("ALV")
    tmx("ARA")
    appia("https://appiareu.com/news/")
