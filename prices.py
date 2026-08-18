"""Calculo da reacao do mercado (% close-to-close) via Yahoo Finance (yfinance).

Para cada empresa baixamos UMA vez o historico diario que cobre o periodo dos
comunicados e, para cada data de comunicado, calculamos a variacao percentual do
fechamento daquele pregao em relacao ao pregao anterior.
"""
from __future__ import annotations

import datetime as dt
import logging
import threading
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import yfinance as yf

log = logging.getLogger("ree")


@dataclass
class Reaction:
    """Reacao do mercado a um comunicado (close-to-close)."""
    pct: float
    prev_close: float
    close: float
    prev_date: dt.date
    reaction_date: dt.date


class PriceProvider:
    """Thread-safe: chamado em paralelo por ree_monitor.collect_live (uma
    thread por empresa), entao o cache precisa de lock -- ainda que colisao
    real de chave entre empresas seja rara (janelas de datas diferentes)."""

    def __init__(self) -> None:
        # (symbol, start, end) -> DataFrame(index=date, columns=[Open, Close])
        self._cache: dict[tuple[str, dt.date, dt.date], "pd.DataFrame"] = {}
        self._lock = threading.Lock()

    def _history(self, symbol: str, start: dt.date, end: dt.date) -> "pd.DataFrame":
        # A janela pedida faz parte da chave: cachear so por symbol reaproveitava
        # (errado) o resultado de uma janela anterior menor/diferente.
        key = (symbol, start, end)
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        # Margem para garantir pregao anterior e dia da reacao. 45 dias corridos
        # cobre trading halts prolongados (comuns em mineradoras juniores da
        # ASX, o publico principal deste dashboard) sem tratar a volta de um
        # halt longo como se fosse o 1o pregao/estreia.
        s = start - dt.timedelta(days=45)
        e = end + dt.timedelta(days=4)
        try:
            df = yf.Ticker(symbol).history(start=s.isoformat(), end=e.isoformat(), auto_adjust=False)
        except Exception as exc:  # noqa: BLE001
            log.warning("Precos %s: download falhou: %s", symbol, exc)
            df = pd.DataFrame()
        if df.empty or "Close" not in df or "Open" not in df:
            out = pd.DataFrame(columns=["Open", "Close"])
        else:
            out = df[["Open", "Close"]].copy()
            out.index = pd.to_datetime(out.index).date
            out = out[~out.index.duplicated(keep="last")].sort_index()
        with self._lock:
            self._cache[key] = out
        return out

    def reaction(self, symbol: str, date: dt.date, *,
                 window_start: dt.date, window_end: dt.date) -> Optional[Reaction]:
        """Reacao close-to-close no pregao do comunicado vs. pregao anterior.

        Se 'date' nao for pregao, usa o proximo pregao como dia da reacao.
        Excecao: quando o comunicado cai no 1o pregao com preco disponivel (ex.:
        estreia/IPO) nao ha fechamento anterior — usa abertura -> fechamento
        desse mesmo pregao em vez de descartar a reacao.
        Retorna None quando nao ha dados suficientes.
        """
        df = self._history(symbol, window_start, window_end)
        if df.empty:
            return None
        dates = list(df.index)

        # dia da reacao: data do comunicado ou o proximo pregao disponivel
        reaction = next((d for d in dates if d >= date), None)
        if reaction is None:
            return None
        idx = dates.index(reaction)
        close = float(df["Close"].iloc[idx])
        if idx == 0:
            if reaction != date:
                return None  # comunicado e anterior ao 1o pregao com dado
            prev_close = float(df["Open"].iloc[idx])
            prev_date = reaction
        else:
            prev_close = float(df["Close"].iloc[idx - 1])
            prev_date = dates[idx - 1]
        if prev_close == 0:
            return None
        return Reaction(
            pct=(close - prev_close) / prev_close * 100.0,
            prev_close=prev_close, close=close,
            prev_date=prev_date, reaction_date=reaction,
        )
