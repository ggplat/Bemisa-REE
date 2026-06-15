"""Diagnostico temporario: inspeciona os feeds reais da EFR (RSS) e Aclara (HTML).

Roda na CI (rede aberta) para descobrir a URL correta do RSS da Energy Fuels e a
estrutura do DOM de aclara-re.com/news. Removido apos o ajuste dos parsers.
"""
import re
from collections import Counter

from sources import http_util


def show(url):
    r = http_util.get(url, retries=1)
    ct = r.headers.get("content-type") if r is not None else None
    print(f"\n### URL {url} -> {None if r is None else r.status_code}  ct={ct}")
    return r


print("==================== ENERGY FUELS (RSS) ====================")
for u in [
    "https://investors.energyfuels.com/index.php?s=95&rsspage=43",
    "https://investors.energyfuels.com/rss/news-releases.xml",
    "https://investors.energyfuels.com/rss",
    "https://investors.energyfuels.com/news-releases?format=rss",
    "https://www.energyfuels.com/feed",
]:
    r = show(u)
    if r is not None:
        txt = r.text
        print("--- primeiros 1200 chars ---")
        print(txt[:1200])
        print(f"--- tem <item>? {'<item' in txt}  tem <rss? {'<rss' in txt[:600]} ---")

print("\n==================== ACLARA (/news HTML) ====================")
r = show("https://www.aclara-re.com/news")
if r is not None:
    html = r.text
    print("len", len(html), " __NEXT_DATA__:", "__NEXT_DATA__" in html,
          " webflow:", "webflow" in html.lower())
    hrefs = re.findall(r'href="([^"]+)"', html)
    print("total hrefs:", len(hrefs))
    # prefixos de href mais comuns (ate 2 niveis)
    pref = Counter("/".join(h.split("/")[:3]) for h in hrefs if h.startswith("/"))
    print("prefixos de href:", pref.most_common(20))
    print("hrefs unicos contendo 'news':", sorted({h for h in hrefs if 'news' in h.lower()})[:40])
    # datas no texto
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    dates = re.findall(r"[A-Z][a-z]+ \d{1,2},? \d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}", text)
    print("amostras de datas no texto:", dates[:20])
    if "__NEXT_DATA__" in html:
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
        if m:
            print("--- __NEXT_DATA__ (primeiros 2000 chars) ---")
            print(m.group(1)[:2000])
    else:
        # imprime um trecho do body com a listagem
        print("--- texto (primeiras 40 linhas) ---")
        print("\n".join(text.splitlines()[:40]))
