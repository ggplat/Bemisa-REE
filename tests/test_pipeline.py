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
from sources.asx import ASXSource, _clean_title, _parse_iso_date, parse_announcements_html
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

    def test_title_suffix_cleanup_does_not_truncate_legitimate_text(self):
        # a regex antiga era gulosa (".*$") e apagava tudo a partir da PRIMEIRA
        # ocorrencia de "N page(s)" -- mesmo quando isso e texto legitimo do
        # titulo, nao o sufixo real da ASX (que sempre vem com tamanho KB/MB).
        title = _clean_title("Presentation covers 5 pages of updates and future outlook for the Company")
        self.assertIn("future outlook", title)
        # o sufixo real da ASX (numero + "pages" + tamanho KB/MB) continua sendo removido
        self.assertEqual(_clean_title("Quarterly Activities Report 14\n\t\t pages 13.8MB"),
                         "Quarterly Activities Report")
        self.assertEqual(_clean_title("Appendix 3B 2 pages 226.8KB"), "Appendix 3B")

    def test_warns_when_no_price_sensitive_marker_found_anywhere(self):
        # pagina sem NENHUM indicador de sensibilidade em lugar nenhum -- pode
        # ser normal (empresa sem PS no periodo) ou o seletor da ASX mudou;
        # de qualquer forma, tem que logar para investigacao manual.
        html = """
        <table>
          <tr><td>05/06/2026 10:30 AM</td><td></td>
              <td><a href="/asx/v2/statistics/displayAnnouncement.do?display=pdf&idsId=1">Sem PS</a></td></tr>
        </table>
        """
        with self.assertLogs("ree", level="WARNING") as cm:
            anns = parse_announcements_html(html, ALV)
        self.assertEqual(len(anns), 1)
        self.assertTrue(any("sensibilidade ao preco" in msg for msg in cm.output))


class TestClassify(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(classify("Quarterly Activities Report"), "Trimestral")
        self.assertEqual(classify("Trading Halt"), "Trading Halt")
        self.assertEqual(classify("Investor Presentation"), "Apresentação")
        self.assertEqual(classify("Algo aleatório"), "Comunicado")

    def test_no_false_positive_by_substring(self):
        # regex sem \b casava por substring dentro de outras palavras
        self.assertEqual(classify("Company Announces New Headquarters in Sao Paulo"), "Comunicado")
        self.assertEqual(classify("Appointment of New Board Representative"), "Comunicado")
        self.assertEqual(classify("Interconnection agreement signed with utility"), "Comunicado")

    def test_still_matches_intended_words_with_suffixes(self):
        # o \b so bloqueia contaminacao por prefixo colado a outra palavra;
        # continua casando a palavra em si e variacoes/sufixos legitimos.
        self.assertEqual(classify("Quarterly Activities Report"), "Trimestral")
        self.assertEqual(classify("Investor Presentation - August 2026"), "Apresentação")
        self.assertEqual(classify("High-grade intercept confirmed at depth"), "Exploração")
        self.assertEqual(classify("Trading halt requested pending announcement"), "Trading Halt")


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
    def test_yahoo_timestamp_uses_exchange_timezone_not_utc(self):
        from sources.canada import _parse_date
        # 10/06 23:30 no horario de Nova York (bolsa) = 11/06 03:30 UTC.
        # Sem converter pro fuso da bolsa, a data virava 11/06 por engano.
        epoch_late_night_et = 1781148600.0  # 2026-06-10T23:30:00-04:00 (EDT)
        self.assertEqual(_parse_date(epoch_late_night_et), dt.date(2026, 6, 10))

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
        # tipo 'rss' generico: a tag de fonte vem do campo 'source' (e nao do nome)
        comp = Company(ticker="XYZ", exchange="TSX", name="Exemplo Mining Corp",
                       yf_symbol="XYZ.TO", company_url="https://money.tmx.com/en/quote/XYZ",
                       news={"type": "rss", "source": "Exemplo IR",
                             "url": "https://exemplo.com/feed"})
        rss = (b'<?xml version="1.0"?><rss><channel>'
               b'<item><title>Primeiro comunicado</title>'
               b'<link>https://exemplo.com/a</link>'
               b'<pubDate>Thu, 26 Feb 2026 11:30:00 +0000</pubDate></item>'
               b'<item><title>Segundo comunicado</title>'
               b'<link>https://exemplo.com/b</link>'
               b'<pubDate>Wed, 11 Jun 2026 12:00:00 +0000</pubDate></item>'
               b'</channel></rss>')
        with mock.patch("sources.canada.http_util.get", return_value=FakeRespBytes(rss)):
            anns = CanadaSource().fetch(comp)
        self.assertEqual(len(anns), 2)
        self.assertEqual(anns[0].url, "https://exemplo.com/a")
        self.assertEqual(anns[1].date, dt.date(2026, 6, 11))
        self.assertEqual(anns[0].source, "Exemplo IR")  # rotulo explicito, nao "Exemplo"
        self.assertIn("Exemplo IR", anns[0].tags)

    def test_rss_generic_without_url_returns_empty_not_appia_feed(self):
        from sources.canada import CanadaSource
        # 'rss' generico sem 'url' nao pode cair no default da Appia -- tem
        # que falhar (lista vazia), nunca atribuir noticias de outra empresa.
        comp = Company(ticker="XYZ", exchange="TSX", name="Exemplo Mining Corp",
                       yf_symbol="XYZ.TO", company_url="https://money.tmx.com/en/quote/XYZ",
                       news={"type": "rss"})  # sem 'url'
        with mock.patch("sources.canada.http_util.get") as fake_get:
            anns = CanadaSource().fetch(comp)
        fake_get.assert_not_called()  # nunca deve tentar buscar nada (nem o feed da Appia)
        self.assertEqual(anns, [])

    def test_aclara_html_parsing(self):
        from sources.canada import parse_aclara_html
        comp = Company(ticker="ARA", exchange="TSX", name="Aclara Resources",
                       yf_symbol="ARA.TO", company_url="https://money.tmx.com/en/quote/ARA",
                       news={"type": "aclara", "url": "https://www.aclara-re.com/news"})
        # estrutura real da colecao Webflow (aclara-re.com/news)
        html = """
        <html><body>
          <div class="news-list w-dyn-items">
            <a class="news-item-box w-inline-block" href="#">
              <div class="div-block-211">
                <div class="text-block-66">1/6/2026</div>
                <div class="news-item-title">Aclara Receives Favourable Consolidated Evaluation Report</div>
              </div>
            </a>  <!-- cartao destaque sem link real: ignorado -->
            <div class="news-list-item w-dyn-item" role="listitem">
              <a class="news-item-box w-inline-block" target="_blank"
                 href="https://cdn.prod.website-files.com/x/Press%20Release%20ICE.pdf">
                <div class="div-block-211">
                  <div class="text-block-66">1/6/2026</div>
                  <div class="news-item-title">Aclara Receives Favourable Consolidated Evaluation Report</div>
                </div>
              </a>
            </div>
            <div class="news-list-item w-dyn-item" role="listitem">
              <a class="news-item-box w-inline-block" target="_blank"
                 href="https://cdn.prod.website-files.com/x/Tranche2.pdf">
                <div class="div-block-211">
                  <div class="text-block-66">13/5/2026</div>
                  <div class="news-item-title">Aclara announces closing of tranche 2</div>
                </div>
              </a>
            </div>
          </div>
        </body></html>
        """
        anns = parse_aclara_html(html, comp)
        self.assertEqual(len(anns), 2)
        self.assertEqual(anns[0].title, "Aclara Receives Favourable Consolidated Evaluation Report")
        self.assertEqual(anns[0].url, "https://cdn.prod.website-files.com/x/Press%20Release%20ICE.pdf")
        self.assertEqual(anns[0].date, dt.date(2026, 6, 1))    # 1/6/2026 = 1 de junho
        self.assertEqual(anns[1].date, dt.date(2026, 5, 13))   # 13/5/2026 = 13 de maio
        self.assertEqual(anns[0].exchange, "TSX")
        self.assertEqual(anns[0].source, "Aclara")

    def test_energyfuels_html_parsing(self):
        from sources.canada import parse_energyfuels_html
        comp = Company(ticker="EFR", exchange="TSX", name="Energy Fuels",
                       yf_symbol="EFR.TO", company_url="https://money.tmx.com/en/quote/EFR",
                       news={"type": "energyfuels"})
        # links de release da pagina Q4: /AAAA-MM-DD-<titulo>
        html = """
        <html><body>
          <div class="wd_newsfeed_releases">
            <div class="wd_item">
              <div class="wd_date">June 11, 2026</div>
              <a href="https://investors.energyfuels.com/2026-06-11-Energy-Fuels-Expects-to-Achieve-Full-Year-Uranium-Production-Guidance-by-Mid-Year">
                 Energy Fuels Expects to Achieve Full-Year Uranium Production Guidance by Mid-Year</a>
            </div>
            <div class="wd_item">
              <a href="https://investors.energyfuels.com/2026-05-06-Energy-Fuels-Announces-Q1-2026-Results#assets_43_459-3">
                 Energy Fuels Announces Q1 2026 Results</a>
            </div>
          </div>
        </body></html>
        """
        anns = parse_energyfuels_html(html, comp)
        self.assertEqual(len(anns), 2)
        self.assertEqual(anns[0].date, dt.date(2026, 6, 11))
        self.assertEqual(anns[0].title,
                         "Energy Fuels Expects to Achieve Full-Year Uranium Production Guidance by Mid-Year")
        self.assertEqual(anns[1].date, dt.date(2026, 5, 6))
        # o fragmento #assets... nao deve gerar duplicata
        self.assertEqual(anns[1].url,
                         "https://investors.energyfuels.com/2026-05-06-Energy-Fuels-Announces-Q1-2026-Results#assets_43_459-3")
        self.assertEqual(anns[0].source, "Energy Fuels")
        self.assertEqual(anns[0].exchange, "TSX")

    def test_imc_html_parsing(self):
        from sources.canada import parse_imc_html
        comp = Company(ticker="IMC", exchange="NYSE", name="IMC Rare Earths",
                       yf_symbol="IMC", company_url="https://www.nyse.com/quote/XASE:IMC",
                       news={"type": "imc"})
        # estrutura real da plataforma de IR "Notified" (ir.imcrareearths.com/news-events/news-releases):
        # o link aparece 2x (manchete + botao "Read More"); usamos o aria-label do
        # "Read More" como titulo e buscamos a data no mesmo bloco "field--group".
        html = """
        <html><body>
          <div class="llf-col-md-12 llf-px-0 lfg-details">
            <div class="nir-widget--field" data-label="Title">
              <div class="nir-widget--field nir-widget--news--headline">
                <a href="/news-releases/news-release-details/imc-rare-earths-begins-trading-nyse-american-under-ticker-symbol" hreflang="en">IMC Rare Earths Begins Trading on NYSE American Under Ticker Symbol &#8220;IMC&#8221;</a>
              </div>
              <div class="nir-widget--field nir-widget--news--teaser" data-label="Teaser">
                <p>Company seeking to establish one of the largest rare earth deposits outside China...</p>
              </div>
            </div>
          </div>
          <div class="nir-widget--field--group llf-row">
            <div class="llf-col-6 llf-col-sm-8 llf-d-flex llf-align-items-center">
              <div class="nir-widget--field nir-widget--news--date-time">
                July 29, 2026
              </div>
            </div>
            <div class="llf-col-6 llf-col-sm-4 llf-d-flex llf-align-items-center llf-justify-content-end">
              <div class="mt-auto text-end">
                <a aria-label="Read more about IMC Rare Earths Begins Trading on NYSE American Under Ticker Symbol &#8220;IMC&#8221;" class="btn-galaxy-plus-primary" href="/news-releases/news-release-details/imc-rare-earths-begins-trading-nyse-american-under-ticker-symbol">Read More</a>
              </div>
            </div>
          </div>
          <div class="llf-col-md-12 llf-px-0 lfg-details">
            <div class="nir-widget--field" data-label="Title">
              <div class="nir-widget--field nir-widget--news--headline">
                <a href="/news-releases/news-release-details/imc-rare-earths-ltd-announces-pricing-initial-public-offering" hreflang="en">IMC Rare Earths Ltd Announces Pricing of Initial Public Offering</a>
              </div>
            </div>
          </div>
          <div class="nir-widget--field--group llf-row">
            <div class="llf-col-6 llf-col-sm-8 llf-d-flex llf-align-items-center">
              <div class="nir-widget--field nir-widget--news--date-time">
                July 28, 2026
              </div>
            </div>
            <div class="llf-col-6 llf-col-sm-4 llf-d-flex llf-align-items-center llf-justify-content-end">
              <div class="mt-auto text-end">
                <a aria-label="Read more about IMC Rare Earths Ltd Announces Pricing of Initial Public Offering" class="btn-galaxy-plus-primary" href="/news-releases/news-release-details/imc-rare-earths-ltd-announces-pricing-initial-public-offering">Read More</a>
              </div>
            </div>
          </div>
        </body></html>
        """
        anns = parse_imc_html(html, comp)
        # o link de cada noticia aparece 2x (manchete + Read More); nao deve duplicar
        self.assertEqual(len(anns), 2)
        self.assertEqual(anns[0].date, dt.date(2026, 7, 29))
        self.assertEqual(anns[0].title,
                         "IMC Rare Earths Begins Trading on NYSE American Under Ticker Symbol “IMC”")
        self.assertEqual(anns[0].url,
                         "https://ir.imcrareearths.com/news-releases/news-release-details/"
                         "imc-rare-earths-begins-trading-nyse-american-under-ticker-symbol")
        self.assertEqual(anns[1].date, dt.date(2026, 7, 28))
        self.assertEqual(anns[1].title, "IMC Rare Earths Ltd Announces Pricing of Initial Public Offering")
        self.assertEqual(anns[0].source, "IMC Rare Earths")
        self.assertEqual(anns[0].exchange, "NYSE")

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
        self.assertIsInstance(get_source("NYSE"), C)
        with self.assertRaises(ValueError):
            get_source("NASDAQ")


if __name__ == "__main__":
    unittest.main()
