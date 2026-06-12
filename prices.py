"""Calculo da reacao do mercado (% close-to-close) via Yahoo Finance (yfinance).

Para cada empresa baixamos UMA vez o historico diario que cobre o periodo dos
comunicados e, para cada data de comunicado, calculamos a variacao percentual do
fechamento daquele pregao em relacao ao pregao anterior.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Optional

import pandas as pd
import yfinance as yf

log = logging.getLogger("ree")


class PriceProvider:
    def __init__(self) -> None:
        # symbol -> Series(date -> close ordenado por data)
        self._cache: dict[str, "pd.Series"] = {}

    def _history(self, symbol: str, start: dt.date, end: dt.date) -> "pd.Series":
        if symbol in self._cache:
            return self._cache[symbol]
        # margem para garantir pregao anterior e dia da reacao
        s = start - dt.timedelta(days=10)
        e = end + dt.timedelta(days=4)
        try:
            df = yf.Ticker(symbol).history(start=s.isoformat(), end=e.isoformat(), auto_adjust=False)
        except Exception as exc:  # noqa: BLE001
            log.warning("Precos %s: download falhou: %s", symbol, exc)
            df = pd.DataFrame()
        if df.empty or "Close" not in df:
            series = pd.Series(dtype="float64")
        else:
            series = df["Close"].copy()
            series.index = pd.to_datetime(series.index).date
            series = series[~series.index.duplicated(keep="last")].sort_index()
        self._cache[symbol] = series
        return series

    def pct_change(self, symbol: str, date: dt.date, *,
                   window_start: dt.date, window_end: dt.date) -> Optional[float]:
        """Variacao % do fechamento no pregao do comunicado vs. pregao anterior.

        Se 'date' nao for pregao, usa o proximo pregao como dia da reacao.
        Retorna None quando nao ha dados suficientes.
        """
        series = self._history(symbol, window_start, window_end)
        if series.empty:
            return None
        dates = list(series.index)

        # dia da reacao: data do comunicado ou o proximo pregao disponivel
        reaction = next((d for d in dates if d >= date), None)
        if reaction is None:
            return None
        idx = dates.index(reaction)
        if idx == 0:
            return None
        prev_close = float(series.iloc[idx - 1])
        close = float(series.iloc[idx])
        if prev_close == 0:
            return None
        return (close - prev_close) / prev_close * 100.0
