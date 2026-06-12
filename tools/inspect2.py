"""Diagnostico v4: estrutura da linha do ASX v2 + tentativa REST de noticias TMX."""
from __future__ import annotations

import re
import sys

sys.path.insert(0, ".")
from sources import http_util


def hr(t): print(f"\n========== {t} ==========")


def asx_row(code: str):
    hr(f"ASX v2 linha {code}")
    url = (f"https://www.asx.com.au/asx/v2/statistics/announcements.do"
           f"?by=asxCode&asxCode={code}&timeframe=D&period=M6")
    r = http_util.get(url, headers={"Referer": "https://www.asx.com.au/"})
    if r is None:
        print("  sem resposta"); return
    html = r.text
    # acha o primeiro link de anuncio e mostra a linha <tr> ao redor
    for pat in ['displayAnnouncement', 'idsId', 'pdf']:
        i = html.find(pat)
        print(f"  primeira ocorrencia '{pat}': {i}")
    # mostra o trecho da primeira data 2026 ate +600
    m = re.search(r'<tr[^>]*>(?:(?!</tr>).){0,40}?\d{2}/\d{2}/2026', html, re.S)
    if m:
        start = m.start()
        print("  TR amostra:", re.sub(r'\s+', ' ', html[start:start+700]))
    else:
        # fallback: trecho ao redor da primeira data
        d = re.search(r'\d{2}/\d{2}/2026', html)
        if d:
            print("  trecho data:", re.sub(r'\s+', ' ', html[max(0,d.start()-300):d.start()+400]))


def tmx_rest(code: str):
    hr(f"TMX REST news {code}")
    for url in [
        f"https://app-money.tmx.com/news?symbol={code}&locale=en",
        f"https://app-money.tmx.com/api/news?symbol={code}",
        f"https://app-money.tmx.com/symbol/{code}/news",
    ]:
        try:
            r = http_util.session().get(url, timeout=15,
                                        headers={"Accept": "application/json", "locale": "en",
                                                 "Origin": "https://money.tmx.com",
                                                 "Referer": "https://money.tmx.com/"})
            print(f"  {url} -> {r.status_code} | {r.text[:160]}")
        except Exception as exc:  # noqa: BLE001
            print(f"  {url} -> erro {exc}")


if __name__ == "__main__":
    asx_row("BRE")
    tmx_rest("ARA")
