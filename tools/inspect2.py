"""Diagnostico v2: fontes historicas. Uso em CI: python tools/inspect2.py"""
from __future__ import annotations

import json
import re
import sys
from xml.etree import ElementTree as ET

sys.path.insert(0, ".")
from sources import http_util


def hr(t): print(f"\n========== {t} ==========")


def rss(url: str, label: str):
    hr(label)
    r = http_util.get(url)
    if r is None:
        print("  sem resposta"); return
    try:
        root = ET.fromstring(r.content)
    except Exception as exc:  # noqa: BLE001
        print("  parse erro:", exc, "| inicio:", r.text[:200]); return
    items = list(root.iter("item"))
    print(f"  n items: {len(items)}")
    for it in items[:6]:
        print("   -", (it.findtext('pubDate') or '')[:25], "|", (it.findtext('title') or '')[:70],
              "|", (it.findtext('link') or '')[:70])
    if items:
        dates = [ (it.findtext('pubDate') or '') for it in items ]
        print("  ultima data:", dates[-1][:25])


def tmx_introspect(code: str):
    hr(f"TMX GraphQL introspection / news {code}")
    q = {"query": "{__schema{queryType{fields{name}}}}"}
    try:
        r = http_util.session().post("https://app-money.tmx.com/graphql", json=q, timeout=20,
                                     headers={"locale": "en", "Origin": "https://money.tmx.com",
                                              "Referer": "https://money.tmx.com/"})
        if r.status_code == 200:
            fields = [f["name"] for f in r.json()["data"]["__schema"]["queryType"]["fields"]]
            print("  Query fields:", fields)
            print("  campos c/ 'news':", [f for f in fields if 'news' in f.lower()])
        else:
            print("  introspection status", r.status_code, r.text[:300])
    except Exception as exc:  # noqa: BLE001
        print("  introspection erro:", exc)
    # tenta achar news no __NEXT_DATA__ da pagina
    r = http_util.get(f"https://money.tmx.com/en/quote/{code}/news")
    if r is not None:
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
        if m:
            blob = m.group(1)
            print("  __NEXT_DATA__ chaves c/ 'news'/'headline':",
                  sorted(set(re.findall(r'"(\w*(?:news|headline|datetime|newsUrl)\w*)"', blob, re.I)))[:20])
            mm = re.search(r'"(headline|title)":"([^"]{15,90})"', blob)
            print("  exemplo:", mm.group(0) if mm else 'nenhum')


if __name__ == "__main__":
    rss("http://noisymime.org/asx/rss.php?code=BRE", "NOISYMIME RSS BRE")
    rss("https://appiareu.com/feed/", "APPIA RSS feed")
    rss("https://appiareu.com/news/feed/", "APPIA RSS /news/feed")
    tmx_introspect("ARA")
