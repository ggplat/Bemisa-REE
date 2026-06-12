"""Diagnostico unico: imprime a estrutura crua das respostas das fontes ASX para
um ticker, para acertarmos os nomes dos campos (URL/id do documento).

Uso (em CI): python tools/inspect_source.py ALV
"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, ".")
from sources import http_util

ASX_BASE = "https://www.asx.com.au"
MARKIT_BASE = "https://asx.api.markitdigital.com"


def dump(code: str) -> None:
    print(f"===== MARKITDIGITAL {code} =====")
    url = f"{MARKIT_BASE}/asx-research/1.0/companies/{code}/announcements?count=5&pageSize=5"
    resp = http_util.get(url, headers={
        "Accept": "application/json",
        "Origin": ASX_BASE,
        "Referer": f"{ASX_BASE}/markets/company/{code}",
    })
    if resp is None:
        print("  (sem resposta / bloqueado)")
    else:
        data = resp.json()
        items = (data.get("data") or {}).get("items") or (data.get("data") or {}).get("announcements") or []
        print("  top-level keys:", list(data.keys()))
        print("  data keys:", list((data.get("data") or {}).keys()))
        print("  n items:", len(items))
        if items:
            print("  PRIMEIRO ITEM (cru):")
            print(json.dumps(items[0], indent=2, ensure_ascii=False)[:2500])

    print(f"\n===== LEGACY /asx/1/ {code} =====")
    url2 = f"{ASX_BASE}/asx/1/company/{code}/announcements?count=5&market_sensitive=false"
    resp2 = http_util.get(url2, headers={"Accept": "application/json"})
    if resp2 is None:
        print("  (sem resposta / bloqueado)")
    else:
        d2 = resp2.json()
        rows = d2.get("data", [])
        print("  n rows:", len(rows))
        if rows:
            print(json.dumps(rows[0], indent=2, ensure_ascii=False)[:1500])


if __name__ == "__main__":
    dump(sys.argv[1] if len(sys.argv) > 1 else "ALV")
