"""Testes offline do nucleo: parsing da ASX, formatacao da %, classificacao e render.

Nao dependem de rede: a resposta HTTP da ASX e simulada (mock). Rode com:
    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import render
from sources import get_source
from sources.asx import ASXSource, _parse_iso_date
from sources.base import Company
from sources.classify import classify


class FakeResp:
    def __init__(self, payload):
        self._payload = payload
    def json(self):
        return self._payload


ALV = Company(ticker="ALV", exchange="ASX", name="Alvo Minerals",
              yf_symbol="ALV.AX", company_url="https://www.asx.com.au/markets/company/ALV")


class TestASXParsing(unittest.TestCase):
    def test_markit_parses_real_schema_and_builds_pdf_links(self):
        # esquema real confirmado pelo diagnostico em CI
        payload = {"data": {"items": [
            {"date": "2026-05-29T03:24:37.000Z",
             "documentKey": "2924-03095208-3A694298",
             "headline": "Quarterly Activities Report",
             "announcementType": "QUARTERLY REPORT",
             "isPriceSensitive": True, "url": ""},
            {"date": "2026-05-19T09:00:00.000Z",
             "documentKey": "2924-9999",
             "headline": "General Company Update", "announcementType": "ADMINISTRATIVE",
             "isPriceSensitive": False,
             "url": "https://cdn.example.com/ready.pdf"},
        ]}}
        with mock.patch("sources.asx.http_util.get", return_value=FakeResp(payload)):
            anns = ASXSource()._fetch_markit(ALV)

        self.assertEqual(len(anns), 2)
        a0 = anns[0]
        # sem url -> constroi o link DIRETO de PDF do markit (HTTP 200 application/pdf)
        self.assertEqual(
            a0.url,
            "https://asx.api.markitdigital.com/asx-research/1.0/file/"
            "2924-03095208-3A694298?access_token=83ff96335c2d45a094df02a206a39ff4")
        self.assertTrue(a0.price_sensitive)
        self.assertEqual(a0.date, dt.date(2026, 5, 29))
        self.assertEqual(a0.doc_type, "Trimestral")
        # quando o item ja traz url pronta, ela e preservada; tipo via announcementType
        self.assertEqual(anns[1].url, "https://cdn.example.com/ready.pdf")
        self.assertEqual(anns[1].doc_type, "Administrative")
        self.assertFalse(anns[1].price_sensitive)

    def test_fetch_falls_back_and_never_raises(self):
        # ambas as estrategias retornam vazio -> fetch retorna [] sem erro
        with mock.patch("sources.asx.http_util.get", return_value=None):
            self.assertEqual(ASXSource().fetch(ALV), [])

    def test_parse_iso_date(self):
        self.assertEqual(_parse_iso_date("2026-06-01T10:30:00+1000"), dt.date(2026, 6, 1))
        self.assertEqual(_parse_iso_date("2026-05-19"), dt.date(2026, 5, 19))
        self.assertIsNone(_parse_iso_date(""))


class TestClassify(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(classify("Quarterly Activities Report"), "Trimestral")
        self.assertEqual(classify("Trading Halt"), "Trading Halt")
        self.assertEqual(classify("Investor Presentation"), "Apresentação")
        self.assertEqual(classify("Algo aleatório"), "Comunicado")


class TestRender(unittest.TestCase):
    def test_pct_formatting_and_classes(self):
        self.assertEqual(render._chg(5.04), ("up", "&#9650;&nbsp;5,0%"))
        self.assertEqual(render._chg(-7.0), ("down", "&#9660;&nbsp;7,0%"))
        self.assertEqual(render._chg(None), ("none", "&mdash;"))
        self.assertEqual(render._chg(0.0)[0], "flat")

    def test_date_label_pt(self):
        self.assertEqual(render._date_label(dt.date(2026, 6, 1)), "01/jun/26")

    def test_full_render_has_real_links_no_placeholder(self):
        from sources.base import Announcement
        anns = {"ALV": [Announcement(
            ticker="ALV", exchange="ASX", company_name="Alvo Minerals",
            date=dt.date(2026, 6, 1), title="Relatório Trimestral",
            url="https://www.asx.com.au/asxpdf/x.pdf", price_sensitive=True,
            doc_type="Trimestral", pages=14, pct_change=5.0)]}
        ctx = render.build_context([ALV], anns, updated=dt.datetime(2026, 6, 1, 12, 0))
        html = render.render_html(ctx)
        self.assertIn('href="https://www.asx.com.au/asxpdf/x.pdf"', html)
        self.assertNotIn('ann-title" href="#"', html)
        self.assertIn("atualizado 01/06/2026 12:00", html)
        self.assertEqual(ctx["n_announcements"], 1)
        self.assertEqual(ctx["n_ps"], 1)


class TestCanada(unittest.TestCase):
    def test_yahoo_news_parsing_and_age_filter(self):
        from sources.canada import CanadaSource
        comp = Company(ticker="EFR", exchange="TSX", name="Energy Fuels",
                       yf_symbol="EFR.TO", company_url="https://money.tmx.com/en/quote/EFR")
        today = dt.date.today().isoformat()
        news = [
            {"id": "1", "content": {
                "contentType": "STORY", "title": "Energy Fuels production update",
                "pubDate": today + "T11:03:57Z",
                "canonicalUrl": {"url": "https://finance.yahoo.com/x.html"},
                "provider": {"displayName": "Zacks"}}},
            {"id": "2", "content": {  # muito antigo -> filtrado
                "contentType": "VIDEO", "title": "Old item",
                "pubDate": "2000-01-01T00:00:00Z",
                "canonicalUrl": {"url": "https://finance.yahoo.com/old.html"}}},
        ]
        fake = mock.Mock()
        fake.news = news
        with mock.patch("yfinance.Ticker", return_value=fake):
            anns = CanadaSource().fetch(comp)
        self.assertEqual(len(anns), 1)
        a = anns[0]
        self.assertEqual(a.url, "https://finance.yahoo.com/x.html")
        self.assertEqual(a.exchange, "TSX")
        self.assertEqual(a.doc_type, "Notícia")
        self.assertEqual(a.source, "Zacks")
        self.assertIn("Zacks", a.tags)


class TestSourceRouting(unittest.TestCase):
    def test_routing(self):
        from sources.asx import ASXSource as A
        from sources.canada import CanadaSource as C
        self.assertIsInstance(get_source("ASX"), A)
        self.assertIsInstance(get_source("TSX"), C)
        self.assertIsInstance(get_source("CSE"), C)
        with self.assertRaises(ValueError):
            get_source("NYSE")


if __name__ == "__main__":
    unittest.main()
