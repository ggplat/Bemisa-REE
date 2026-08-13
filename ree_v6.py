"""Primitivas compartilhadas do pipeline do Dashboard REE v6.

Concentra o que `fetch_market_data.py` e `update_dashboard.py` precisam em
comum: configuração das 5 empresas, helpers de mês no formato do dashboard
("mmm/aa") e a manipulação cirúrgica do HTML dos iframes `srcdoc`.

Regra de ouro deste módulo: **round-trip byte-idêntico**. Extrair um frame,
desescapar, reescapar e reinserir sem alterar dado nenhum tem de produzir o
arquivo original byte a byte. Os testes em `tests/test_market_pipeline.py`
travam esse contrato.
"""
from __future__ import annotations

import datetime as dt
import html
import os
import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo

BRASILIA_TZ = ZoneInfo("America/Sao_Paulo")

ROOT = os.path.dirname(os.path.abspath(__file__))
DASHBOARD = os.path.join(ROOT, "Dashboard_REE_v6_Q2.html")
DOCS_COPY = os.path.join(ROOT, "docs", "dashboard_ree_v6.html")
DATA_FILE = os.path.join(ROOT, "data", "market_data.json")
LOG_FILE = os.path.join(ROOT, "logs", "pipeline.jsonl")

# ── MESES ─────────────────────────────────────────────────────────────────────

MESES_PT = ["jan", "fev", "mar", "abr", "mai", "jun",
            "jul", "ago", "set", "out", "nov", "dez"]


def month_key(year: int, month: int) -> str:
    """(2026, 7) → 'jul/26' — o formato de chave usado nos dicts do dashboard."""
    return f"{MESES_PT[month - 1]}/{year % 100:02d}"


def month_key_of(d: dt.date) -> str:
    return month_key(d.year, d.month)


def today_month_key() -> str:
    return month_key_of(dt.date.today())


def month_to_int(mk: str) -> int:
    """'jul/26' → 202607, para ordenação cronológica correta."""
    m, y = mk.split("/")
    return (2000 + int(y)) * 100 + MESES_PT.index(m) + 1


# ── CONFIGURAÇÃO DAS EMPRESAS ────────────────────────────────────────────────

@dataclass(frozen=True)
class FrameSpec:
    """Uma empresa e o mapeamento dela para o frame e as variáveis JS."""
    ticker: str
    frame: int
    yf_symbol: str
    currency: str          # moeda local de negociação
    fx_pair: str           # chave do par no market_data.json
    fx_yf: str             # símbolo do par no Yahoo Finance
    price_var: str         # nome da variável JS de preço no srcdoc
    fx_var: str            # nome da variável JS de câmbio no srcdoc


FRAMES: list[FrameSpec] = [
    FrameSpec("ARA", 0, "ARA.TO", "CAD", "CADUSD", "CADUSD=X", "stockCAD", "cadusd"),
    FrameSpec("BRE", 1, "BRE.AX", "AUD", "AUDUSD", "AUDUSD=X", "stockAUD", "audusd"),
    FrameSpec("MEI", 2, "MEI.AX", "AUD", "AUDUSD", "AUDUSD=X", "stockAUD", "audusd"),
    FrameSpec("SGQ", 3, "SGQ.AX", "AUD", "AUDUSD", "AUDUSD=X", "stockAUD", "audusd"),
    FrameSpec("VMM", 4, "VMM.AX", "AUD", "AUDUSD", "AUDUSD=X", "stockAUD", "audusd"),
]

BY_TICKER = {f.ticker: f for f in FRAMES}

# Séries sob curadoria manual — o pipeline nunca escreve nelas por conta própria.
# `sharesMap` e `cumInvK` são exceção parcial: recebem forward-fill sinalizado
# quando um mês novo abre (ver `update_dashboard.py`), porque o JS quebra sem eles.
MANUAL_VARS = ("qBarK", "issuances", "projEvents")

# Identidade visual Bemisa — verificada a cada gravação.
BRAND_TOKENS = ("#7C9640", "#414042", "Carlito")


# ── IFRAMES / SRCDOC ─────────────────────────────────────────────────────────

FRAME_RE = re.compile(r'id="frame-(\d)"[^>]*srcdoc="(.*?)"></iframe>', re.DOTALL)


def unescape_srcdoc(escaped: str) -> str:
    return html.unescape(escaped)


def escape_srcdoc(plain: str) -> str:
    """Reescapa para caber num atributo HTML com aspas duplas.

    A ordem importa: `&` primeiro, senão as entidades geradas nos passos
    seguintes seriam escapadas de novo.

    Não escapamos apóstrofo. Dentro de um atributo delimitado por aspas duplas
    ele é seguro, e o `srcdoc` original os mantém crus — acrescentar o passo
    `' → &#x27;` reescreveria milhares de caracteres por frame já na primeira
    execução, destruindo a legibilidade do diff. Sem esse passo o round-trip é
    byte-idêntico nos 5 frames.
    """
    return (plain.replace("&", "&amp;")
                 .replace("<", "&lt;")
                 .replace(">", "&gt;")
                 .replace('"', "&quot;"))


def extract_frames(doc: str) -> dict[int, str]:
    """Retorna {índice do frame: HTML interno já desescapado}."""
    return {int(m.group(1)): unescape_srcdoc(m.group(2)) for m in FRAME_RE.finditer(doc)}


def replace_frames(doc: str, new_inner: dict[int, str]) -> str:
    """Reinsere o HTML interno dos frames indicados, reescapando.

    Frames ausentes de `new_inner` ficam intocados byte a byte.
    """
    def _sub(m: re.Match) -> str:
        idx = int(m.group(1))
        if idx not in new_inner:
            return m.group(0)
        return m.group(0).replace(m.group(2), escape_srcdoc(new_inner[idx]), 1)

    return FRAME_RE.sub(_sub, doc)


# ── DOCUMENTO EXTERNO (fora dos iframes) ─────────────────────────────────────

OUTER_TIMESTAMP_RE = re.compile(r'(<span class="last-updated" id="last-updated">)(.*?)(</span>)')


def set_last_updated(doc: str, when: dt.datetime) -> str:
    """Atualiza o texto do indicador de última atualização, na barra de nav.

    `when` é convertido para o horário de Brasília (UTC-3 fixo — o Brasil
    não tem mais horário de verão desde 2019) antes de formatar; o público
    do dashboard é brasileiro, e a execução do pipeline roda em UTC.

    Diferente dos frames, o documento externo é HTML bruto — não um atributo
    escapado — então não há passo de unescape/escape aqui.
    """
    local = when.astimezone(BRASILIA_TZ)
    text = f"Atualizado em {local:%d/%m/%Y %H:%M} (horário de Brasília)"
    return OUTER_TIMESTAMP_RE.sub(lambda m: m.group(1) + text + m.group(3), doc, count=1)


# ── DICTS JS DENTRO DO SRCDOC ────────────────────────────────────────────────

ENTRY_RE = re.compile(r'"([a-z]{3}/\d{2})"\s*:\s*(-?[\d.]+(?:[eE][-+]?\d+)?)')


def _dict_body_span(js: str, var: str) -> tuple[int, int]:
    """Posições de início/fim do corpo de `const <var> = { ... \\n};`.

    Os dicts do dashboard não têm chaves aninhadas, então o terminador
    `\\n};` é inequívoco.
    """
    m = re.search(r"const\s+" + re.escape(var) + r"\s*=\s*\{", js)
    if not m:
        raise KeyError(f"variável JS '{var}' não encontrada no frame")
    end = js.find("\n};", m.end())
    if end < 0:
        raise ValueError("fim do dict '%s' não encontrado (esperado '\\n};')" % var)
    return m.end(), end


def read_js_dict(js: str, var: str) -> dict[str, float]:
    """Lê um dict mensal do JS. Comentários `//` são ignorados na leitura."""
    start, end = _dict_body_span(js, var)
    body = re.sub(r"//[^\n]*", "", js[start:end])
    return {k: float(v) for k, v in ENTRY_RE.findall(body)}


def upsert_dict_entry(js: str, var: str, key: str, value: str,
                      comment: str | None = None) -> tuple[str, str]:
    """Insere ou atualiza uma entrada `"mmm/aa":valor`, preservando o resto.

    Edição cirúrgica: o texto fora da entrada tocada — indentação, quebras de
    linha e comentários inline — sai idêntico. Retorna (js novo, ação), onde
    ação é 'inserted', 'updated' ou 'unchanged'.
    """
    start, end = _dict_body_span(js, var)
    body = js[start:end]

    existing = re.search(r'("' + re.escape(key) + r'"\s*:\s*)(-?[\d.]+(?:[eE][-+]?\d+)?)', body)
    if existing:
        if existing.group(2) == value:
            return js, "unchanged"
        new_body = body[:existing.start(2)] + value + body[existing.end(2):]
        return js[:start] + new_body + js[end:], "updated"

    entry = f'"{key}":{value},'
    if comment:
        entry += f"  // {comment}"

    # Onde inserir: a última linha do corpo manda no estilo.
    lines = body.split("\n")
    last = lines[-1]
    indent = re.match(r"\s*", last).group(0) or "  "
    # Uma linha com comentário nunca recebe entrada nova ao lado: o texto novo
    # cairia depois do `//` e viraria comentário — perda silenciosa de dado.
    has_comment = "//" in last
    n_entries = len(ENTRY_RE.findall(re.sub(r"//[^\n]*", "", last)))

    if has_comment or n_entries >= 3 or not last.rstrip().endswith(","):
        new_body = body + "\n" + indent + entry
    else:
        new_body = body + entry

    return js[:start] + new_body + js[end:], "inserted"


# ── volData (SÉRIE DIÁRIA) ───────────────────────────────────────────────────

VOL_RE = re.compile(r"(const\s+volData\s*=\s*\[)(.*?)(\];)", re.DOTALL)


def read_vol_dates(js: str) -> list[str]:
    """Datas ISO já presentes em `volData`, na ordem em que aparecem."""
    m = VOL_RE.search(js)
    if not m:
        raise KeyError("variável JS 'volData' não encontrada no frame")
    return re.findall(r'"d"\s*:\s*"(\d{4}-\d{2}-\d{2})"', m.group(2))


def format_vol_point(date_iso: str, vol_usd: float) -> str:
    return '{"d":"%s","v":%s}' % (date_iso, f"{vol_usd:.2f}")


def append_vol_points(js: str, points: list[tuple[str, float]]) -> str:
    """Acrescenta pontos ao fim de `volData`, sem reordenar o que já existe."""
    if not points:
        return js
    m = VOL_RE.search(js)
    if not m:
        raise KeyError("variável JS 'volData' não encontrada no frame")
    extra = ",".join(format_vol_point(d, v) for d, v in points)
    body = m.group(2).rstrip()
    sep = "," if body else ""
    return js[:m.start(2)] + body + sep + extra + js[m.end(2):]
