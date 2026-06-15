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
from sources.asx import ASXSource, _parse_iso_date, parse_announcements_html
from sources.base import Company
from sources.classify import classify


class FakeResp:
    def __init__(self, payload):
        self._payload = payload
    def json(self):
        return self._payload


class FakeRespBytes:
    def __init__(self, content):
        self.content = content


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

    def test_history_html_parser(self):
        # estrutura da pagina announcements.do (historico ~6 meses)
        html = """
        <table>
          <tr><td>05/06/2026 10:30 AM</td>
              <td><img src="/img/price_sensitive.gif" alt="price sensitive"></td>
              <td><a href="/asx/v2/statistics/displayAnnouncement.do?display=pdf&idsId=02800001">
                  Quarterly Activities Report 14\n\t\t pages 13.8MB</a></td></tr>
          <tr><td>20/01/2026 09:00 AM</td><td></td>
              <td><a href="/asx/v2/statistics/displayAnnouncement.do?display=pdf&idsId=02800002">
                  Appendix 3B 2 pages 226.8KB</a></td></tr>
        </table>
        <a name="reused"></a>
        <tr><td>01/01/2020</td><td><a href="/asx/v2/statistics/displayAnnouncement.do?display=pdf&idsId=09999999">
            Outra empresa</a></td></tr>
        """
        anns = parse_announcements_html(html, ALV)
        self.assertEqual(len(anns), 2)  # a secao 'reused' e ignorada
        # titulo limpo: sem o "<n> pages <tamanho>" que vem no link da ASX
        self.assertEqual(anns[0].title, "Quarterly Activities Report")
        self.assertEqual(anns[1].title, "Appendix 3B")
        self.assertEqual(anns[0].date, dt.date(2026, 6, 5))
        self.assertTrue(anns[0].url.startswith(
            "https://www.asx.com.au/asx/v2/statistics/displayAnnouncement.do?display=pdf&idsId=02800001"))
        self.assertTrue(anns[0].price_sensitive)   # detectado pelo img alt
        self.assertEqual(anns[0].pages, 14)
        self.assertEqual(anns[0].doc_type, "Trimestral")
        self.assertEqual(anns[1].date, dt.date(2026, 1, 20))
        self.assertFalse(anns[1].price_sensitive)
        self.assertEqual(anns[1].doc_type, "Appendix 3B")

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

    def test_pct_is_link_with_tooltip_when_data(self):
        from sources.base import Announcement
        anns = {"ALV": [
            Announcement(ticker="ALV", exchange="ASX", company_name="Alvo Minerals",
                         date=dt.date(2026, 6, 1), title="Com preço", url="https://x/a.pdf",
                         pct_change=5.7, prev_close=1.23, close=1.30,
                         reaction_date=dt.date(2026, 6, 1)),
            Announcement(ticker="ALV", exchange="ASX", company_name="Alvo Minerals",
                         date=dt.date(2026, 6, 2), title="Sem preço", url="https://x/b.pdf",
                         pct_change=None),
        ]}
        html = render.render_html(render.build_context([ALV], anns))
        # linha com dado: % vira link para o grafico do Yahoo (yf_symbol) + tooltip
        self.assertIn('<a class="ann-chg up" href="https://finance.yahoo.com/quote/ALV.AX"', html)
        self.assertIn("fech. anterior 1,230 → 1,300", html)
        # linha sem dado: continua como span (sem href)
        self.assertIn('<span class="ann-chg none">', html)

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
    def test_yahoo_news_uses_override_symbol(self):
        from sources.canada import CanadaSource
        # tipo 'yahoo' (agregador) continua disponivel e respeita o symbol override
        comp = Company(ticker="XYZ", exchange="TSX", name="Exemplo Mining",
                       yf_symbol="XYZ.TO", company_url="https://money.tmx.com/en/quote/XYZ",
                       news={"type": "yahoo", "symbol": "XYZ"})
        news = [{"id": "1", "content": {
            "contentType": "STORY", "title": "Exemplo production update",
            "pubDate": "2026-06-11T11:03:57Z",
            "canonicalUrl": {"url": "https://finance.yahoo.com/x.html"},
            "provider": {"displayName": "Zacks"}}}]
        fake = mock.Mock()
        fake.news = news
        captured = {}

        def fake_ticker(sym):
            captured["sym"] = sym
            return fake
        with mock.patch("yfinance.Ticker", side_effect=fake_ticker):
            anns = CanadaSource().fetch(comp)
        self.assertEqual(captured["sym"], "XYZ")  # usou o ticker de noticias do override
        self.assertEqual(len(anns), 1)
        a = anns[0]
        self.assertEqual(a.url, "https://finance.yahoo.com/x.html")
        self.assertEqual(a.exchange, "TSX")   # exibicao mantida como TSX
        self.assertEqual(a.source, "Zacks")
        self.assertIn("Zacks", a.tags)

    def test_rss_generic_uses_source_label(self):
        from sources.canada import CanadaSource
        # EFR (Energy Fuels): RSS oficial; a tag de fonte vem do campo 'source'
        comp = Company(ticker="EFR", exchange="TSX", name="Energy Fuels",
                       yf_symbol="EFR.TO", company_url="https://money.tmx.com/en/quote/EFR",
                       news={"type": "rss", "source": "Energy Fuels",
                             "url": "https://investors.energyfuels.com/index.php?s=95&rsspage=43"})
        rss = (b'<?xml version="1.0"?><rss><channel>'
               b'<item><title>Energy Fuels Announces 2025 Results and 2026 Guidance</title>'
               b'<link>https://investors.energyfuels.com/2026-02-26-results</link>'
               b'<pubDate>Thu, 26 Feb 2026 11:30:00 +0000</pubDate></item>'
               b'<item><title>Energy Fuels Provides Mid-Year Update</title>'
               b'<link>https://investors.energyfuels.com/2026-06-11-update</link>'
               b'<pubDate>Wed, 11 Jun 2026 12:00:00 +0000</pubDate></item>'
               b'</channel></rss>')
        with mock.patch("sources.canada.http_util.get", return_value=FakeRespBytes(rss)):
            anns = CanadaSource().fetch(comp)
        self.assertEqual(len(anns), 2)
        self.assertEqual(anns[0].url, "https://investors.energyfuels.com/2026-02-26-results")
        self.assertEqual(anns[1].date, dt.date(2026, 6, 11))
        self.assertEqual(anns[0].exchange, "TSX")
        self.assertEqual(anns[0].source, "Energy Fuels")  # rotulo explicito, nao "Energy"
        self.assertIn("Energy Fuels", anns[0].tags)

    def test_aclara_html_parsing(self):
        from sources.canada import parse_aclara_html
        comp = Company(ticker="ARA", exchange="TSX", name="Aclara Resources",
                       yf_symbol="ARA.TO", company_url="https://money.tmx.com/en/quote/ARA",
                       news={"type": "aclara", "url": "https://www.aclara-re.com/news"})
        html = """
        <html><body>
          <a href="/news">News</a>  <!-- link para a propria listagem: ignorado -->
          <div class="news-list">
            <article>
              <a href="/news/aclara-gains-eia-approval-for-penco-module">
                 Aclara gains EIA approval for Penco Module project</a>
              <span class="date">June 11, 2026</span>
            </article>
            <article>
              <a href="https://www.aclara-re.com/news/feasibility-study-carina">
                 Aclara Files Results Of Feasibility Study For Carina</a>
              <time>2026-05-20</time>
            </article>
          </div>
        </body></html>
        """
        anns = parse_aclara_html(html, comp)
        self.assertEqual(len(anns), 2)
        self.assertEqual(anns[0].title, "Aclara gains EIA approval for Penco Module project")
        self.assertEqual(anns[0].url,
                         "https://www.aclara-re.com/news/aclara-gains-eia-approval-for-penco-module")
        self.assertEqual(anns[0].date, dt.date(2026, 6, 11))
        self.assertEqual(anns[1].date, dt.date(2026, 5, 20))
        self.assertEqual(anns[0].exchange, "TSX")
        self.assertEqual(anns[0].source, "Aclara")

    def test_appia_rss_parsing(self):
        from sources.canada import CanadaSource
        comp = Company(ticker="API", exchange="CSE", name="Appia Rare Earths & Uranium",
                       yf_symbol="API.CN", company_url="https://thecse.com/en/listings?search=API",
                       news={"type": "appia", "url": "https://appiareu.com/feed/"})
        rss = (b'<?xml version="1.0"?><rss><channel>'
               b'<item><title>Appia Mobilizes for Summer Drill Program</title>'
               b'<link>https://appiareu.com/appia-mobilizes/</link>'
               b'<pubDate>Thu, 04 Jun 2026 11:30:00 +0000</pubDate></item>'
               b'</channel></rss>')
        with mock.patch("sources.canada.http_util.get", return_value=FakeRespBytes(rss)):
            anns = CanadaSource().fetch(comp)
        self.assertEqual(len(anns), 1)
        self.assertEqual(anns[0].url, "https://appiareu.com/appia-mobilizes/")
        self.assertEqual(anns[0].date, dt.date(2026, 6, 4))
        self.assertEqual(anns[0].exchange, "CSE")


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
