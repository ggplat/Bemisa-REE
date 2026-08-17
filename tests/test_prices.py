"""Testes offline de prices.py (reacao de mercado, close-to-close).

Nao dependem de rede: yfinance e simulado (mock). Rode com:
    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import unittest
from unittest import mock

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prices import PriceProvider


def _fake_history(rows: list[tuple[dt.date, float, float]]) -> "pd.DataFrame":
    """rows: [(data, abertura, fechamento), ...] no formato que o yfinance retorna."""
    idx = [pd.Timestamp(d) for d, _, _ in rows]
    return pd.DataFrame(
        {"Open": [o for _, o, _ in rows], "Close": [c for _, _, c in rows]},
        index=idx,
    )


class TestReaction(unittest.TestCase):
    def _provider(self, rows):
        provider = PriceProvider()
        patcher = mock.patch("yfinance.Ticker")
        mock_ticker = patcher.start()
        self.addCleanup(patcher.stop)
        mock_ticker.return_value.history.return_value = _fake_history(rows)
        return provider

    def test_close_to_close_uses_previous_close(self):
        rows = [
            (dt.date(2026, 7, 1), 10.0, 10.5),
            (dt.date(2026, 7, 2), 10.5, 11.0),
        ]
        provider = self._provider(rows)
        r = provider.reaction("XYZ", dt.date(2026, 7, 2),
                               window_start=dt.date(2026, 7, 1), window_end=dt.date(2026, 7, 2))
        self.assertIsNotNone(r)
        self.assertAlmostEqual(r.prev_close, 10.5)
        self.assertAlmostEqual(r.close, 11.0)
        self.assertEqual(r.prev_date, dt.date(2026, 7, 1))
        self.assertEqual(r.reaction_date, dt.date(2026, 7, 2))

    def test_first_session_same_day_uses_open_to_close(self):
        # Estreia/IPO: comunicado cai no proprio 1o pregao com preco disponivel
        # -> sem fechamento anterior, usa abertura->fechamento desse mesmo dia.
        rows = [(dt.date(2026, 7, 29), 5.0, 5.75)]
        provider = self._provider(rows)
        r = provider.reaction("IMC", dt.date(2026, 7, 29),
                               window_start=dt.date(2026, 7, 29), window_end=dt.date(2026, 7, 29))
        self.assertIsNotNone(r)
        self.assertAlmostEqual(r.prev_close, 5.0)  # abertura
        self.assertAlmostEqual(r.close, 5.75)
        self.assertEqual(r.prev_date, r.reaction_date)  # sinaliza "abertura" no tooltip
        self.assertAlmostEqual(r.pct, 15.0)

    def test_news_before_first_session_returns_none(self):
        # Comunicado anterior a listagem: nao existe preco nenhum antes do 1o
        # pregao, entao nao ha reacao de mercado real pra mostrar.
        rows = [(dt.date(2026, 7, 29), 5.0, 5.75)]
        provider = self._provider(rows)
        r = provider.reaction("IMC", dt.date(2026, 6, 30),
                               window_start=dt.date(2026, 6, 30), window_end=dt.date(2026, 7, 29))
        self.assertIsNone(r)

    def test_no_history_returns_none(self):
        provider = self._provider([])
        r = provider.reaction("XYZ", dt.date(2026, 7, 2),
                               window_start=dt.date(2026, 7, 1), window_end=dt.date(2026, 7, 2))
        self.assertIsNone(r)


if __name__ == "__main__":
    unittest.main()
