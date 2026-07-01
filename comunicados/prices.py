"""Calculo da reacao do mercado (% close-to-close) via Yahoo Finance (yfinance).

Para cada empresa baixamos UMA vez o historico diario que cobre o periodo dos
comunicados e, para cada data de comunicado, calculamos a variacao percentual do
fechamento daquele pregao em relacao ao pregao anterior.
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import yfinance as yf

log = logging.getLogger("ree")

# Moeda de negociacao por bolsa (para converter o market cap para USD).
CURRENCY_BY_EXCHANGE = {"ASX": "AUD", "TSX": "CAD", "CSE": "CAD"}
FX_SYMBOLS = {"AUD": "AUDUSD=X", "CAD": "CADUSD=X"}


@dataclass
class MarketCap:
    """Market cap de uma empresa, convertido para USD."""
    price: float
    currency: str
    fx_rate: float
    shares: int
    usd_millions: float


@dataclass
class Reaction:
    """Reacao do mercado a um comunicado (close-to-close)."""
    pct: float
    prev_close: float
    close: float
    prev_date: dt.date
    reaction_date: dt.date


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

    def reaction(self, symbol: str, date: dt.date, *,
                 window_start: dt.date, window_end: dt.date) -> Optional[Reaction]:
        """Reacao close-to-close no pregao do comunicado vs. pregao anterior.

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
        return Reaction(
            pct=(close - prev_close) / prev_close * 100.0,
            prev_close=prev_close, close=close,
            prev_date=dates[idx - 1], reaction_date=reaction,
        )


def _fetch_last_close(symbol: str) -> Optional[float]:
    try:
        hist = yf.Ticker(symbol).history(period="5d", auto_adjust=False)
        if hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception as exc:  # noqa: BLE001
        log.warning("Ultimo fechamento %s: %s", symbol, exc)
        return None


def _fetch_shares(symbol: str) -> Optional[int]:
    try:
        info = yf.Ticker(symbol).info
        val = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
        return int(val) if val else None
    except Exception as exc:  # noqa: BLE001
        log.warning("Acoes em circulacao %s: %s", symbol, exc)
        return None


def fetch_market_caps(companies: list) -> dict[str, Optional[MarketCap]]:
    """Retorna, por ticker, o market cap em USD (None quando indisponivel)."""
    fx_cache: dict[str, Optional[float]] = {}
    result: dict[str, Optional[MarketCap]] = {}
    for company in companies:
        currency = CURRENCY_BY_EXCHANGE.get(company.exchange)
        fx_rate = None
        if currency:
            if currency not in fx_cache:
                fx_cache[currency] = _fetch_last_close(FX_SYMBOLS[currency])
            fx_rate = fx_cache[currency]

        price = _fetch_last_close(company.yf_symbol)
        shares = _fetch_shares(company.yf_symbol)
        if price and shares and fx_rate:
            result[company.ticker] = MarketCap(
                price=price, currency=currency, fx_rate=fx_rate,
                shares=shares, usd_millions=price * shares * fx_rate / 1e6,
            )
        else:
            result[company.ticker] = None
    return result
