"""Utilitario HTTP compartilhado: headers de navegador, retries e cache em disco."""
from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import Optional

import requests

log = logging.getLogger("ree")

CACHE_DIR = os.environ.get("REE_CACHE_DIR", ".cache")

# Headers realistas ajudam a passar por protecoes anti-bot simples.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_session: Optional[requests.Session] = None


def session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(BROWSER_HEADERS)
    return _session


def get(url: str, *, retries: int = 3, timeout: int = 20, **kwargs) -> Optional[requests.Response]:
    """GET com retries e backoff exponencial. Retorna None se falhar."""
    delay = 2.0
    for attempt in range(1, retries + 1):
        try:
            resp = session().get(url, timeout=timeout, **kwargs)
            if resp.status_code == 200:
                return resp
            log.warning("GET %s -> HTTP %s (tentativa %s/%s)", url, resp.status_code, attempt, retries)
        except requests.RequestException as exc:
            log.warning("GET %s falhou: %s (tentativa %s/%s)", url, exc, attempt, retries)
        if attempt < retries:
            time.sleep(delay)
            delay *= 2
    return None
