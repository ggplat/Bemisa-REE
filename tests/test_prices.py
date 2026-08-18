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

    def test_cache_is_keyed_by_window_not_just_symbol(self):
        # Antes da correcao, o cache era so por 'symbol': uma segunda chamada
        # pro mesmo simbolo com uma janela diferente reaproveitava (errado) o
        # DataFrame da primeira janela, mesmo sem cobrir as novas datas.
        provider = PriceProvider()
        patcher = mock.patch("yfinance.Ticker")
        mock_ticker = patcher.start()
        self.addCleanup(patcher.stop)
        july = _fake_history([(dt.date(2026, 7, 1), 10.0, 10.5), (dt.date(2026, 7, 2), 10.5, 11.0)])
        september = _fake_history([(dt.date(2026, 9, 1), 20.0, 20.5), (dt.date(2026, 9, 2), 20.5, 21.0)])
        mock_ticker.return_value.history.side_effect = [july, september]

        r1 = provider.reaction("XYZ", dt.date(2026, 7, 2),
                               window_start=dt.date(2026, 7, 1), window_end=dt.date(2026, 7, 2))
        r2 = provider.reaction("XYZ", dt.date(2026, 9, 2),
                               window_start=dt.date(2026, 9, 1), window_end=dt.date(2026, 9, 2))

        self.assertIsNotNone(r1)
        self.assertIsNotNone(r2)  # antes da correcao vinha None (cache da janela de julho)
        self.assertEqual(r2.reaction_date, dt.date(2026, 9, 2))
        self.assertEqual(mock_ticker.return_value.history.call_count, 2)

    def test_fetch_margin_covers_prolonged_trading_halts(self):
        # Halts de mineradoras juniores da ASX podem durar semanas; a margem
        # de busca pro pregao anterior precisa ser larga o suficiente pra nao
        # confundir a volta de um halt longo com o 1o pregao/estreia.
        provider = PriceProvider()
        patcher = mock.patch("yfinance.Ticker")
        mock_ticker = patcher.start()
        self.addCleanup(patcher.stop)
        mock_ticker.return_value.history.return_value = _fake_history(
            [(dt.date(2026, 7, 1), 1.0, 1.0)])
        provider.reaction("XYZ", dt.date(2026, 7, 1),
                          window_start=dt.date(2026, 7, 1), window_end=dt.date(2026, 7, 1))
        _, kwargs = mock_ticker.return_value.history.call_args
        requested_start = dt.date.fromisoformat(kwargs["start"])
        margin_days = (dt.date(2026, 7, 1) - requested_start).days
        self.assertGreaterEqual(margin_days, 30,
                                "margem de busca curta demais pra halts prolongados")


if __name__ == "__main__":
    unittest.main()
