"""Testes offline do pipeline diário do Dashboard REE v6.

Não dependem de rede: a coleta é substituída por séries sintéticas. Rode com:
    python -m unittest discover -s tests -v

O teste mais importante é o de round-trip byte-idêntico. Ele é a rede de
segurança de tudo: se extrair e reinserir os `srcdoc` sem alterar dado nenhum
não devolver o arquivo original byte a byte, qualquer atualização automática
passa a corromper o dashboard silenciosamente.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fetch_market_data as F
import ree_v6 as R
import update_dashboard as U

DASHBOARD = R.DASHBOARD

# Um mês daqui a alguns anos, garantidamente ausente do dashboard real (que o
# pipeline diário mantém sempre atualizado até "hoje"). Os testes que
# precisam simular "um mês novo que ainda não existe" usam esta constante em
# vez de uma string fixa como "jul/26" — que deixou de ser nova assim que o
# pipeline passou a rodar de verdade.
NEW_MONTH = R.month_key(dt.date.today().year + 5, 1)


def _weekdays(year: int, month: int, count: int) -> list[dt.date]:
    out, d = [], dt.date(year, month, 1)
    while len(out) < count:
        if d.weekday() < 5:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def build_state(tickers=("ARA", "BRE", "MEI", "SGQ", "VMM"), *,
                year=None, month=None, days=10) -> dict:
    """Estado sintético com um mês novo (NEW_MONTH) para todos os tickers."""
    if year is None or month is None:
        mon_abbr, yy = NEW_MONTH.split("/")
        year, month = 2000 + int(yy), R.MESES_PT.index(mon_abbr) + 1
    state = {"schema": 1, "source": "test", "updated_utc": "2026-08-12T22:00:00Z",
             "fx": {}, "tickers": {}, "flags": []}
    dates = _weekdays(year, month, days)

    for pair in ("CADUSD", "AUDUSD"):
        base = 0.72 if pair == "CADUSD" else 0.69
        daily = {d.isoformat(): round(base + 0.0005 * i, 6) for i, d in enumerate(dates)}
        state["fx"][pair] = {"yf_symbol": f"{pair}=X", "daily": daily,
                             "monthly": F.monthly_mean(daily, set())}

    for ticker in tickers:
        spec = R.BY_TICKER[ticker]
        fx_daily = state["fx"][spec.fx_pair]["daily"]
        closes = {d.isoformat(): round(1.0 + 0.01 * i, 6) for i, d in enumerate(dates)}
        state["tickers"][ticker] = {
            "frame": spec.frame, "yf_symbol": spec.yf_symbol,
            "currency": spec.currency, "fx_pair": spec.fx_pair,
            "daily": {d: {"close": c, "volume": 100000,
                          "vol_usd": round(100000 * c * fx_daily[d], 2)}
                      for d, c in closes.items()},
            "monthly": F.monthly_mean(closes, set()),
        }
    return state


class TestSrcdocRoundTrip(unittest.TestCase):
    """O contrato que sustenta todo o resto."""

    def setUp(self):
        with open(DASHBOARD, encoding="utf-8") as fh:
            self.doc = fh.read()

    def test_round_trip_is_byte_identical(self):
        frames = R.extract_frames(self.doc)
        self.assertEqual(sorted(frames), [0, 1, 2, 3, 4])
        self.assertEqual(R.replace_frames(self.doc, frames), self.doc)

    def test_escape_does_not_touch_apostrophes(self):
        # Apóstrofo é seguro dentro de atributo com aspas duplas. Escapá-lo
        # reescreveria milhares de caracteres por frame sem ganho nenhum.
        self.assertEqual(R.escape_srcdoc("font-family: 'Carlito'"),
                         "font-family: 'Carlito'")

    def test_escape_order_handles_ampersand_first(self):
        self.assertEqual(R.escape_srcdoc('a & b < c > d "e"'),
                         "a &amp; b &lt; c &gt; d &quot;e&quot;")

    def test_untouched_frames_are_preserved_exactly(self):
        frames = R.extract_frames(self.doc)
        js, _ = R.upsert_dict_entry(frames[0], "stockCAD", "jul/26", "4.5000")
        out = R.replace_frames(self.doc, {0: js})
        for idx in (1, 2, 3, 4):
            self.assertEqual(R.extract_frames(out)[idx], frames[idx])

    def test_volume_chart_x_domain_end_is_derived_from_vol_data(self):
        # Regressão: o frame do BRE tinha o fim do eixo X do gráfico de volume
        # fixo em "2026-06-30" (`d3.timeParse(...)("2026-06-30")`) em vez de
        # derivado da última data de volData. Isso é invisível hoje — só
        # quebra (barras saindo da tela) no primeiro dia em que volData
        # ganhar um ponto além dessa data fixa. O início do eixo (parseStart)
        # pode continuar fixo — é assim que o gráfico de volume alinha seu
        # começo com o de main/shares/ratio quando volData começa depois do
        # preço (caso do BRE); só o FIM precisa ser dinâmico.
        frames = R.extract_frames(self.doc)
        for spec in R.FRAMES:
            js = frames[spec.frame]
            m = re.search(r"const x = d3\.scaleTime\(\)\.domain\((.*?)\)\.range", js)
            self.assertIsNotNone(m, f"{spec.ticker}: escala de tempo do volume não encontrada")
            domain_expr = m.group(1)
            # O fim pode vir inline (d3.extent/d3.max) ou por uma variável
            # (ex.: "parseEnd") — nesse caso resolve a definição dela.
            end_ref = domain_expr.split(",")[-1].strip().strip("[]() ")
            end_def = domain_expr
            if re.fullmatch(r"[A-Za-z_$][\w$]*", end_ref):
                defn = re.search(r"const\s+" + re.escape(end_ref) + r"\s*=\s*(.*?);", js)
                self.assertIsNotNone(defn, f"{spec.ticker}: '{end_ref}' não definido")
                end_def = defn.group(1)
            self.assertTrue(
                "d3.extent(parsed" in end_def or "d3.max(parsed" in end_def,
                f"{spec.ticker}: fim do eixo X do volume não deriva de volData: "
                f"domínio={domain_expr!r} definição='{end_def}'")


class TestLastUpdated(unittest.TestCase):
    """Indicador de última atualização na barra de nav (fora dos iframes)."""

    def setUp(self):
        with open(DASHBOARD, encoding="utf-8") as fh:
            self.doc = fh.read()

    def test_marker_exists_exactly_once(self):
        self.assertEqual(self.doc.count('id="last-updated"'), 1)

    def test_set_last_updated_converts_utc_to_brasilia_time(self):
        # UTC-3 fixo (Brasil não tem mais horário de verão desde 2019).
        when = dt.datetime(2026, 8, 13, 14, 30, tzinfo=dt.timezone.utc)
        out = R.set_last_updated(self.doc, when)
        self.assertIn("Atualizado em 13/08/2026 11:30 (horário de Brasília)", out)
        # nada fora do proprio span pode mudar
        before = R.OUTER_TIMESTAMP_RE.sub("X", self.doc)
        after = R.OUTER_TIMESTAMP_RE.sub("X", out)
        self.assertEqual(before, after)

    def test_does_not_touch_iframe_content(self):
        when = dt.datetime(2026, 8, 13, 14, 30, tzinfo=dt.timezone.utc)
        out = R.set_last_updated(self.doc, when)
        before_frames = R.extract_frames(self.doc)
        after_frames = R.extract_frames(out)
        self.assertEqual(before_frames, after_frames)

    def test_check_brand_rejects_marker_removal(self):
        # Remove o span inteiro pelo regex (nao por texto fixo): o pipeline
        # ja preenche esse span com a data real a cada execucao, entao um
        # placeholder hardcoded (ex. "--/--/----") fica obsoleto assim que
        # roda pela primeira vez de verdade.
        stripped = R.OUTER_TIMESTAMP_RE.sub("", self.doc, count=1)
        self.assertNotEqual(stripped, self.doc)
        with self.assertRaises(U.UpdateAborted):
            U.check_brand(self.doc, stripped)


class TestAxisTickLabels(unittest.TestCase):
    """O eixo X só mostra um rótulo por trimestre — nunca força o mês mais
    recente a aparecer se ele não cair nesse ritmo. Isso não afeta os
    dados plotados (a série inteira continua desenhada); só o texto do
    eixo pode omitir o mês corrente.
    """

    def setUp(self):
        with open(DASHBOARD, encoding="utf-8") as fh:
            self.doc = fh.read()
        self.frames = R.extract_frames(self.doc)

    def test_categorical_charts_never_force_the_last_month(self):
        forced = "monthOrder[monthOrder.length-1]"
        for spec in R.FRAMES:
            self.assertNotIn(forced, self.frames[spec.frame],
                             f"{spec.ticker}: ainda força o último mês no eixo X")

    def test_volume_chart_never_forces_the_domain_end(self):
        for spec in R.FRAMES:
            js = self.frames[spec.frame]
            m = re.search(r"tickValues\((.*?)\)\.tickSize\(4\)\.tickFormat", js)
            self.assertIsNotNone(m, f"{spec.ticker}: tickValues do volume não encontrado")
            self.assertNotIn("auto.push(end)", m.group(1),
                             f"{spec.ticker}: ainda força a data final no eixo X do volume")

    def test_dataset_is_never_filtered_by_the_label_cadence(self):
        # A correção é só de exibição: `data` (o que os 3 gráficos
        # categóricos desenham) tem de continuar mapeando o `monthOrder`
        # inteiro, nunca uma versão já filtrada a cada 3 meses — senão o
        # ritmo trimestral do rótulo vazaria para o dado plotado.
        for spec in R.FRAMES:
            js = self.frames[spec.frame]
            self.assertIn("const data = monthOrder.map(m =>", js,
                         f"{spec.ticker}: 'data' não mapeia mais o monthOrder completo")


class TestDashboardInvariants(unittest.TestCase):
    """Sem estas condições o JS do frame produz NaN e some com a série."""

    def setUp(self):
        with open(DASHBOARD, encoding="utf-8") as fh:
            self.frames = R.extract_frames(fh.read())

    def test_month_order_is_covered_by_shares_and_investment(self):
        for spec in R.FRAMES:
            js = self.frames[spec.frame]
            months = set(R.read_js_dict(js, spec.price_var))
            for var in ("sharesMap", "cumInvK"):
                self.assertLessEqual(months, set(R.read_js_dict(js, var)),
                                     f"{spec.ticker}: {var} não cobre todos os meses de preço")

    def test_invariant_check_rejects_uncovered_month(self):
        spec = R.BY_TICKER["ARA"]
        js, _ = R.upsert_dict_entry(self.frames[0], spec.price_var, NEW_MONTH, "4.5000")
        with self.assertRaises(U.UpdateAborted):
            U.check_frame_invariants(js, spec)

    def test_vol_data_is_valid_json_and_sorted(self):
        for spec in R.FRAMES:
            U.check_frame_invariants(self.frames[spec.frame], spec)


class TestNullMonths(unittest.TestCase):
    """stockAUD do SGQ (frame 3) usa 'null' pra marcar negociacao suspensa.

    'null' e um valor tao legitimo quanto um numero: precisa ser lido pelo
    parser e contar como mes ja existente (protegido), senao o pipeline
    reprocessa e sobrescreve silenciosamente um dado curado.
    """

    def setUp(self):
        with open(DASHBOARD, encoding="utf-8") as fh:
            self.frames = R.extract_frames(fh.read())
        self.js = self.frames[R.BY_TICKER["SGQ"].frame]
        # nov/24 e dez/24 sao os meses reais marcados null no dashboard hoje.
        self.assertIn('"nov/24":null', self.js)

    def test_read_js_dict_sees_null_entries(self):
        d = R.read_js_dict(self.js, "stockAUD")
        self.assertIn("nov/24", d)
        self.assertIsNone(d["nov/24"])

    def test_null_month_is_protected_not_writable(self):
        self.assertFalse(U._is_writable(self.js, "stockAUD", "nov/24"))

    def test_upsert_on_null_month_updates_in_place_no_duplicate(self):
        new_js, action = R.upsert_dict_entry(self.js, "stockAUD", "nov/24", "0.0500")
        self.assertEqual(action, "updated")
        start, end = R._dict_body_span(new_js, "stockAUD")
        body = new_js[start:end]
        self.assertEqual(body.count('"nov/24"'), 1)
        self.assertEqual(R.read_js_dict(new_js, "stockAUD")["nov/24"], 0.05)
        # dez/24 continua null, intocado.
        self.assertIsNone(R.read_js_dict(new_js, "stockAUD")["dez/24"])


class TestSurgicalEditing(unittest.TestCase):
    """Mecanica de upsert_dict_entry, testada contra fixtures sinteticas.

    Deliberadamente NAO le comentarios/valores do Dashboard_REE_v6_Q2.html de
    producao aqui: esse conteudo e editorial e muda com o tempo (ex.: "//
    aguardando relatório Q2/2026" deixa de ser verdade assim que o relatorio
    sair). Testes que dependessem do texto exato quebrariam por uma edição de
    conteúdo sem relação com um bug real no pipeline -- e como a suíte roda
    antes da coleta/aplicação no workflow, isso bloquearia a atualização
    diária inteira (mesma classe do bug já corrigido em
    test_check_brand_rejects_marker_removal). As fixtures abaixo isolam
    exatamente o mecanismo testado, sem depender de nenhum dado real.
    """

    FAKE_JS_WITH_COMMENT = (
        'const sharesMap = {\n'
        '  "jan/26":1000000,"fev/26":1000000,\n'
        '  "mar/26":1000000  // provisório — fixture de teste\n'
        '};\n'
    )
    FAKE_JS_CUMINVK = (
        'const cumInvK = {\n'
        '  "mai/26":40000,\n'
        '  "jun/26":45048  // aguardando confirmação (fixture de teste)\n'
        '};\n'
    )

    def setUp(self):
        with open(DASHBOARD, encoding="utf-8") as fh:
            self.frames = R.extract_frames(fh.read())

    def test_insert_never_lands_after_an_inline_comment(self):
        # Inserir na mesma linha de um comentário comentaria o dado novo —
        # perda silenciosa. mar/26 (última entrada) tem comentário inline.
        new_js, action = R.upsert_dict_entry(self.FAKE_JS_WITH_COMMENT, "sharesMap",
                                             NEW_MONTH, "3814671589", comment="forward-fill")
        self.assertEqual(action, "inserted")
        self.assertEqual(R.read_js_dict(new_js, "sharesMap")[NEW_MONTH], 3814671589)

    def test_existing_inline_comments_survive(self):
        new_js, _ = R.upsert_dict_entry(self.FAKE_JS_WITH_COMMENT, "sharesMap",
                                        NEW_MONTH, "3814671589")
        self.assertIn("// provisório — fixture de teste", new_js)

    def test_update_existing_key_keeps_its_comment(self):
        new_js, action = R.upsert_dict_entry(self.FAKE_JS_CUMINVK, "cumInvK", "jun/26", "99999")
        self.assertEqual(action, "updated")
        self.assertIn("// aguardando confirmação (fixture de teste)", new_js)
        self.assertEqual(R.read_js_dict(new_js, "cumInvK")["jun/26"], 99999)

    def test_same_value_is_a_no_op(self):
        js, action = R.upsert_dict_entry(self.FAKE_JS_CUMINVK, "cumInvK", "jun/26", "45048")
        self.assertEqual(action, "unchanged")
        self.assertEqual(js, self.FAKE_JS_CUMINVK)

    def test_vol_points_are_appended_in_order(self):
        js = self.frames[0]
        before = R.read_vol_dates(js)
        new_js = R.append_vol_points(js, [("2026-07-01", 1234.567), ("2026-07-02", 10.0)])
        after = R.read_vol_dates(new_js)
        self.assertEqual(after[:len(before)], before)
        self.assertEqual(after[-2:], ["2026-07-01", "2026-07-02"])
        self.assertIn('{"d":"2026-07-01","v":1234.57}', new_js)


class TestQualityControl(unittest.TestCase):

    def test_large_jump_is_blocked_small_one_passes(self):
        fetched = {"2026-07-01": {"close": 4.00, "volume": 1000},
                   "2026-07-02": {"close": 4.20, "volume": 1000},   # +5%
                   "2026-07-03": {"close": 5.25, "volume": 1000}}   # +25%
        accepted, flags = F.qc_series("TST", fetched, {}, F.MAX_DAILY_PCT,
                                      is_fx=False, force=False)
        self.assertIn("2026-07-02", accepted)
        self.assertNotIn("2026-07-03", accepted)
        self.assertIn("outlier_pct", {f["kind"] for f in flags})

    def test_outlier_does_not_cascade(self):
        # A comparação é com o vizinho da série do provedor, não com o último
        # dia aceito — um pico isolado não invalida tudo que vem depois.
        fetched = {"2026-07-01": {"close": 4.00, "volume": 1},
                   "2026-07-02": {"close": 5.25, "volume": 1},   # pico
                   "2026-07-03": {"close": 5.30, "volume": 1}}   # +1% vs. o pico
        accepted, _ = F.qc_series("TST", fetched, {}, F.MAX_DAILY_PCT,
                                  is_fx=False, force=False)
        self.assertNotIn("2026-07-02", accepted)
        self.assertIn("2026-07-03", accepted)

    def test_fx_uses_a_tighter_threshold(self):
        fetched = {"2026-07-01": {"close": 0.70, "volume": None},
                   "2026-07-02": {"close": 0.74, "volume": None}}  # +5,7%
        accepted, flags = F.qc_series("AUDUSD", fetched, {}, F.MAX_FX_PCT,
                                      is_fx=True, force=False)
        self.assertNotIn("2026-07-02", accepted)
        self.assertIn("outlier_fx", {f["kind"] for f in flags})

    def test_invalid_price_is_dropped_even_with_force(self):
        fetched = {"2026-07-01": {"close": 0, "volume": 10}}
        accepted, flags = F.qc_series("TST", fetched, {}, F.MAX_DAILY_PCT,
                                      is_fx=False, force=True)
        self.assertEqual(accepted, {})
        self.assertIn("invalid_price", {f["kind"] for f in flags})

    def test_provider_revision_keeps_the_stored_value(self):
        stored = {"2026-07-01": {"close": 4.00}}
        fetched = {"2026-07-01": {"close": 4.50, "volume": 10}}
        accepted, flags = F.qc_series("TST", fetched, stored, F.MAX_DAILY_PCT,
                                      is_fx=False, force=False)
        self.assertEqual(accepted, {})
        self.assertIn("revision", {f["kind"] for f in flags})

    def test_gap_is_flagged_and_never_filled(self):
        old = (dt.date.today() - dt.timedelta(days=30)).isoformat()
        accepted, flags = F.qc_series("TST", {old: {"close": 4.0, "volume": 1}}, {},
                                      F.MAX_DAILY_PCT, is_fx=False, force=False)
        self.assertIn("gap", {f["kind"] for f in flags})
        self.assertEqual(list(accepted), [old])  # nenhum dia inventado

    def test_empty_series_is_flagged(self):
        _, flags = F.qc_series("TST", {}, {}, F.MAX_DAILY_PCT, is_fx=False, force=False)
        self.assertIn("no_data", {f["kind"] for f in flags})

    def test_outlier_check_looks_past_an_invalid_neighbor(self):
        # Se o vizinho imediato tiver close invalido (glitch do provedor), a
        # checagem de outlier tem que continuar comparando com o vizinho
        # valido mais proximo -- nao pular a validacao do dia seguinte.
        fetched = {"2026-07-01": {"close": 4.00, "volume": 1},
                   "2026-07-02": {"close": 0, "volume": 1},        # glitch (invalido)
                   "2026-07-03": {"close": 40.00, "volume": 1}}    # +900% vs. 01/07
        accepted, flags = F.qc_series("TST", fetched, {}, F.MAX_DAILY_PCT,
                                      is_fx=False, force=False)
        self.assertNotIn("2026-07-02", accepted)  # invalid_price
        self.assertNotIn("2026-07-03", accepted)  # outlier vs. 01/07, nao passa direto
        kinds = {f["kind"] for f in flags}
        self.assertIn("invalid_price", kinds)
        self.assertIn("outlier_pct", kinds)


class TestStatePersistence(unittest.TestCase):
    """save_state/load_state de data/market_data.json."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.path = os.path.join(self.tmp, "sub", "market_data.json")

    def test_save_then_load_round_trips(self):
        state = {"schema": 1, "tickers": {"ARA": {"daily": {}}}}
        F.save_state(self.path, state)
        self.assertEqual(F.load_state(self.path), state)

    def test_save_is_atomic_no_leftover_temp_file_on_success(self):
        F.save_state(self.path, {"a": 1})
        leftovers = [f for f in os.listdir(os.path.dirname(self.path)) if f != "market_data.json"]
        self.assertEqual(leftovers, [])

    def test_failed_save_does_not_corrupt_existing_file(self):
        F.save_state(self.path, {"a": 1})
        with mock.patch("json.dump", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                F.save_state(self.path, {"a": 2, "b": [1] * 100})
        # o arquivo original continua intacto -- nunca foi truncado/sobrescrito
        self.assertEqual(F.load_state(self.path), {"a": 1})
        leftovers = [f for f in os.listdir(os.path.dirname(self.path)) if f != "market_data.json"]
        self.assertEqual(leftovers, [], "arquivo temporario orfao nao foi limpo")

    def test_load_corrupted_json_raises_clear_error(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write('{"schema": 1, "tickers": {')  # JSON truncado
        with self.assertRaises(RuntimeError) as cm:
            F.load_state(self.path)
        self.assertIn("corrompido", str(cm.exception))


class TestMonthlyAggregation(unittest.TestCase):

    def test_arithmetic_mean(self):
        daily = {"2026-07-01": 4.0, "2026-07-02": 4.2, "2026-07-03": 4.4}
        out = F.monthly_mean(daily, skip_closed=set())
        self.assertAlmostEqual(out["jul/26"]["mean"], 4.2)
        self.assertEqual(out["jul/26"]["n_days"], 3)

    def test_closed_months_are_never_recomputed(self):
        daily = {"2026-07-01": 4.0}
        self.assertEqual(F.monthly_mean(daily, skip_closed={"jul/26"}), {})

    def test_month_key_helpers(self):
        self.assertEqual(R.month_key(2026, 7), "jul/26")
        self.assertEqual(R.month_to_int("jul/26"), 202607)
        self.assertLess(R.month_to_int("dez/25"), R.month_to_int("jan/26"))

    def test_today_brasilia_does_not_use_raw_utc_date(self):
        # 01:00 UTC de 01/ago ainda e 31/jul as 22:00 em Brasilia (UTC-3) --
        # se a conversao nao acontecer, today_month_key() acha que ago/26 ja
        # comecou 2h mais cedo do que deveria (afeta qual mes fica protegido).
        fake_now = dt.datetime(2026, 8, 1, 1, 0, tzinfo=dt.timezone.utc)
        with mock.patch("ree_v6.dt.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            self.assertEqual(R.today_brasilia(), dt.date(2026, 7, 31))
            self.assertEqual(R.today_month_key(), "jul/26")

        fake_now_later = dt.datetime(2026, 8, 1, 4, 0, tzinfo=dt.timezone.utc)
        with mock.patch("ree_v6.dt.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now_later
            self.assertEqual(R.today_brasilia(), dt.date(2026, 8, 1))
            self.assertEqual(R.today_month_key(), "ago/26")


class TestEndToEndUpdate(unittest.TestCase):
    """Aplica um estado sintético num dashboard de trabalho e confere o efeito."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dash = os.path.join(self.tmp, "dash.html")
        shutil.copy(DASHBOARD, self.dash)
        with open(DASHBOARD, encoding="utf-8") as fh:
            self.before = fh.read()

        self._saved = (R.DASHBOARD, R.DOCS_COPY, R.DATA_FILE, R.LOG_FILE)
        R.DASHBOARD = self.dash
        R.DOCS_COPY = os.path.join(self.tmp, "docs.html")
        R.DATA_FILE = os.path.join(self.tmp, "state.json")
        R.LOG_FILE = os.path.join(self.tmp, "pipeline.jsonl")
        with open(R.DATA_FILE, "w", encoding="utf-8") as fh:
            json.dump(build_state(), fh)

    def tearDown(self):
        R.DASHBOARD, R.DOCS_COPY, R.DATA_FILE, R.LOG_FILE = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, **kw):
        opts = {"dry_run": False, "frames": None, "no_render_check": True, "verbose": False}
        opts.update(kw)
        return U.run(type("A", (), opts)())

    def test_market_series_change_and_manual_series_do_not(self):
        self.assertEqual(self._run(), 0)
        with open(self.dash, encoding="utf-8") as fh:
            after_frames = R.extract_frames(fh.read())
        before_frames = R.extract_frames(self.before)

        for spec in R.FRAMES:
            before, after = before_frames[spec.frame], after_frames[spec.frame]
            # o que deve mudar
            self.assertIn(NEW_MONTH, R.read_js_dict(after, spec.price_var))
            self.assertIn(NEW_MONTH, R.read_js_dict(after, spec.fx_var))
            self.assertGreater(len(R.read_vol_dates(after)), len(R.read_vol_dates(before)))
            # o que não pode mudar, byte a byte
            for var in R.MANUAL_VARS:
                self.assertEqual(_block_of(before, var), _block_of(after, var),
                                 f"{spec.ticker}: bloco {var} foi alterado")
                self.assertNotEqual(_block_of(before, var), "",
                                    f"{spec.ticker}: bloco {var} não foi localizado")

    def test_last_updated_stamped_only_when_something_changes(self):
        self.assertEqual(self._run(), 0)
        with open(self.dash, encoding="utf-8") as fh:
            stamped = fh.read()
        # o placeholder inicial some assim que ha uma mudanca real de dado
        self.assertNotIn("--/--/---- --:--", stamped)
        self.assertRegex(stamped, r"Atualizado em \d{2}/\d{2}/\d{4} \d{2}:\d{2} \(horário de Brasília\)")

        # segunda execucao: nada novo em market_data.json -> no-op -> `run()`
        # retorna antes mesmo de chegar em set_last_updated (ver early-return
        # "if not updated"), entao o arquivo inteiro fica byte-identico —
        # inclusive o timestamp, que so seria diferente se a stampagem
        # tivesse rodado de novo por engano.
        self.assertEqual(self._run(), 0)
        with open(self.dash, encoding="utf-8") as fh:
            twice = fh.read()
        self.assertEqual(stamped, twice)

    def test_new_month_gets_flagged_forward_fill(self):
        self.assertEqual(self._run(), 0)
        with open(self.dash, encoding="utf-8") as fh:
            frames = R.extract_frames(fh.read())
        for spec in R.FRAMES:
            js = frames[spec.frame]
            self.assertIn(NEW_MONTH, R.read_js_dict(js, "sharesMap"))
            self.assertIn(NEW_MONTH, R.read_js_dict(js, "cumInvK"))
            self.assertIn("forward-fill automático", js)
            U.check_frame_invariants(js, spec)  # não quebrou o contrato

    def test_first_run_never_overwrites_a_month_already_in_the_dashboard(self):
        # Regressão real: na primeira execução em produção, um mês já FECHADO
        # e curado à mão no dashboard (jun/26) foi recalculado a partir de
        # só 2 pregões disponíveis na janela de busca — sem histórico prévio
        # em market_data.json para protegê-lo — e sobrescreveu o valor
        # original com até 13% de diferença. `apply_frame` deve recusar
        # qualquer mês que já exista no dashboard, mesmo que seja a primeira
        # vez que o pipeline roda e mesmo que venha marcado "closed": true.
        spec = R.BY_TICKER["ARA"]
        js = R.extract_frames(open(self.dash, encoding="utf-8").read())[spec.frame]
        existing_month = "jun/26"
        original_price = R.read_js_dict(js, spec.price_var)[existing_month]

        state = {"tickers": {"ARA": {"monthly": {
            existing_month: {"mean": original_price * 3, "n_days": 2, "closed": True},
        }}}, "fx": {"CADUSD": {"monthly": {}}}}

        new_js, changes = U.apply_frame(js, spec, state)
        self.assertEqual(new_js, js, "mês já existente foi reescrito")
        self.assertIn(existing_month, changes["protected"])
        self.assertEqual(changes["price"], {})

    def test_second_run_is_a_no_op(self):
        self.assertEqual(self._run(), 0)
        with open(self.dash, encoding="utf-8") as fh:
            once = fh.read()
        self.assertEqual(self._run(), 0)
        with open(self.dash, encoding="utf-8") as fh:
            twice = fh.read()
        self.assertEqual(once, twice)

    def test_dry_run_writes_nothing(self):
        self.assertEqual(self._run(dry_run=True), 0)
        with open(self.dash, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), self.before)

    def test_backup_is_created_before_overwrite(self):
        self.assertEqual(self._run(), 0)
        backups = [f for f in os.listdir(self.tmp) if "_backup_" in f]
        self.assertEqual(len(backups), 1)
        with open(os.path.join(self.tmp, backups[0]), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), self.before)

    def test_brand_guard_rejects_visual_drift(self):
        with self.assertRaises(U.UpdateAborted):
            U.check_brand(self.before, self.before.replace("#7C9640", "#FF0000", 1))


class TestMainTimeoutHandling(unittest.TestCase):
    def test_subprocess_timeout_is_caught_cleanly(self):
        # node --check / render_check.js travado: antes disso, um traceback
        # cru subia ate o topo (sem log limpo, sem entrada no pipeline.jsonl).
        import subprocess
        with mock.patch("update_dashboard.run",
                        side_effect=subprocess.TimeoutExpired(cmd=["node", "--check", "x.js"], timeout=60)):
            with self.assertLogs("ree.update", level="ERROR") as cm:
                code = U.main([])
        self.assertEqual(code, 1)
        self.assertTrue(any("nao respondeu" in msg for msg in cm.output))


def _block_of(js: str, var: str) -> str:
    """Texto cru de um bloco `const <var> = [ ... ];` ou `{ ... };`."""
    import re
    m = re.search(r"const\s+" + re.escape(var) + r"\s*=\s*[\[{].*?\n[\]}];", js, re.DOTALL)
    return m.group(0) if m else ""


if __name__ == "__main__":
    unittest.main()
