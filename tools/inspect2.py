"""Diagnostico v3: ASX historico (v2 announcements.do) + TMX news (__NEXT_DATA__)."""
from __future__ import annotations

import json
import re
import sys

sys.path.insert(0, ".")
from sources import http_util


def hr(t): print(f"\n========== {t} ==========")


def asx_v2(code: str):
    hr(f"ASX v2 announcements.do {code}")
    url = (f"https://www.asx.com.au/asx/v2/statistics/announcements.do"
           f"?by=asxCode&asxCode={code}&timeframe=D&period=M6")
    r = http_util.get(url, headers={"Referer": "https://www.asx.com.au/"})
    if r is None:
        print("  sem resposta/bloqueado"); return
    html = r.text
    print("  HTML len", len(html))
    rows = re.findall(r'displayAnnouncement\.do\?display=pdf&idsId=(\d+)', html)
    print("  links displayAnnouncement:", len(rows), rows[:3])
    # datas no formato dd/mm/yyyy
    print("  datas:", re.findall(r'\d{2}/\d{2}/\d{4}', html)[:10])
    print("  trecho:", re.sub(r'\s+', ' ', html[:400]))


def tmx_news(code: str):
    hr(f"TMX __NEXT_DATA__ news {code}")
    r = http_util.get(f"https://money.tmx.com/en/quote/{code}/news")
    if r is None:
        print("  sem resposta"); return
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
    if not m:
        print("  sem __NEXT_DATA__"); return
    data = json.loads(m.group(1))

    found = []
    def walk(o, path=""):
        if isinstance(o, dict):
            keys = set(o.keys())
            if ({'headline'} & keys or {'newsUrl'} & keys) and len(found) < 3:
                found.append((path, o))
            for k, v in o.items():
                walk(v, path + "/" + k)
        elif isinstance(o, list):
            for i, v in enumerate(o[:3]):
                walk(v, f"{path}[{i}]")
    walk(data)
    print("  itens c/ headline/newsUrl encontrados:", len(found))
    for path, o in found:
        print("  PATH:", path)
        print("  KEYS:", list(o.keys()))
        print("  SAMPLE:", json.dumps({k: o[k] for k in list(o)[:12]}, ensure_ascii=False, default=str)[:700])


if __name__ == "__main__":
    asx_v2("BRE")
    tmx_news("ARA")
