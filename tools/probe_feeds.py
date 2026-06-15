"""Diagnostico temporario v2: captura a estrutura repetida dos itens de noticia.

- Aclara (Webflow): coleta os itens da colecao (w-dyn-item) e mostra o HTML de exemplo.
- Energy Fuels (Q4 IR): pagina investors.energyfuels.com/news-releases (classes wd_*).
Removido apos o ajuste dos parsers.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bs4 import BeautifulSoup
from sources import http_util


def get(url):
    r = http_util.get(url, retries=1)
    print(f"\n### {url} -> {None if r is None else r.status_code}"
          f" ct={None if r is None else r.headers.get('content-type')}")
    return r


print("==================== ACLARA (Webflow collection) ====================")
r = get("https://www.aclara-re.com/news")
if r is not None:
    soup = BeautifulSoup(r.text, "html.parser")
    items = soup.select(".w-dyn-item")
    print("w-dyn-item count:", len(items))
    lists = soup.select(".w-dyn-list")
    print("w-dyn-list count:", len(lists))
    # mostra os 2 primeiros itens que contenham uma data d/m/yyyy
    shown = 0
    for it in items:
        txt = it.get_text(" ", strip=True)
        if re.search(r"\d{1,2}/\d{1,2}/\d{4}", txt) and shown < 3:
            print(f"\n----- ITEM {shown} (prettify, 1800 chars) -----")
            print(it.prettify()[:1800])
            shown += 1
    if shown == 0 and items:
        print("\n----- primeiro w-dyn-item (sem data detectada) -----")
        print(items[0].prettify()[:1800])

print("\n\n==================== ENERGY FUELS (Q4 news-releases) ====================")
for url in [
    "https://investors.energyfuels.com/news-releases",
    "https://www.energyfuels.com/news/feed/",
    "https://www.energyfuels.com/category/news/feed/",
    "https://www.energyfuels.com/press-releases/feed/",
]:
    r = get(url)
    if r is None:
        continue
    txt = r.text
    ct = r.headers.get("content-type", "")
    if "xml" in ct or txt.lstrip().startswith("<?xml"):
        print("  RSS? <item> count:", txt.count("<item"))
        for m in re.findall(r"<title>(.*?)</title>", txt)[:4]:
            print("    title:", m[:70])
        continue
    soup = BeautifulSoup(txt, "html.parser")
    # Q4 usa classes wd_*; coletar candidatos a item/titulo/data
    items = soup.select('[class*="wd_item"], [class*="news"], article')
    print("  candidatos a item:", len(items))
    for it in items[:3]:
        print(f"\n  ----- item (prettify 1200) -----\n", it.prettify()[:1200])
    # tambem mostra alguns hrefs que parecem release
    hrefs = [a.get("href") for a in soup.find_all("a", href=True)]
    rel = [h for h in hrefs if re.search(r"/20\d\d-\d\d-\d\d|news-release|press", h or "", re.I)]
    print("  hrefs de release (amostra):", sorted(set(rel))[:12])
