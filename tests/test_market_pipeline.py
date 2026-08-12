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
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fetch_market_data as F
import ree_v6 as R
import update_dashboard as U

DASHBOARD = R.DASHBOARD


def _weekdays(year: int, month: int, count: int) -> list[dt.date]:
    out, d = [], dt.date(year, month, 1)
    while len(out) < count:
        if d.weekday() < 5:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def build_state(tickers=("ARA", "BRE", "MEI", "SGQ", "VMM"), *,
                year=2026, month=7, days=10) -> dict:
    """Estado sintético com um mês novo (jul/26) para todos os tickers."""
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
        js, _ = R.upsert_dict_entry(self.frames[0], spec.price_var, "jul/26", "4.5000")
        with self.assertRaises(U.UpdateAborted):
            U.check_frame_invariants(js, spec)

    def test_vol_data_is_valid_json_and_sorted(self):
        for spec in R.FRAMES:
            U.check_frame_invariants(self.frames[spec.frame], spec)


class TestSurgicalEditing(unittest.TestCase):

    def setUp(self):
        with open(DASHBOARD, encoding="utf-8") as fh:
            self.frames = R.extract_frames(fh.read())

    def test_insert_never_lands_after_an_inline_comment(self):
        # frame 3 (SGQ) termina sharesMap com "// provisório — aguardando...".
        # Inserir na mesma linha comentaria o dado novo — perda silenciosa.
        js = self.frames[3]
        self.assertIn("// provisório", js)
        new_js, action = R.upsert_dict_entry(js, "sharesMap", "jul/26", "3814671589",
                                             comment="forward-fill")
        self.assertEqual(action, "inserted")
        self.assertEqual(R.read_js_dict(new_js, "sharesMap")["jul/26"], 3814671589)

    def test_existing_inline_comments_survive(self):
        js = self.frames[3]
        new_js, _ = R.upsert_dict_entry(js, "sharesMap", "jul/26", "3814671589")
        self.assertIn("// provisório — aguardando confirmação de emissões", new_js)

    def test_update_existing_key_keeps_its_comment(self):
        js = self.frames[0]
        self.assertIn("// aguardando relatório Q2/2026", js)
        new_js, action = R.upsert_dict_entry(js, "cumInvK", "jun/26", "99999")
        self.assertEqual(action, "updated")
        self.assertIn("// aguardando relatório Q2/2026", new_js)
        self.assertEqual(R.read_js_dict(new_js, "cumInvK")["jun/26"], 99999)

    def test_same_value_is_a_no_op(self):
        js, action = R.upsert_dict_entry(self.frames[0], "cumInvK", "jun/26", "45048")
        self.assertEqual(action, "unchanged")
        self.assertEqual(js, self.frames[0])

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
            self.assertIn("jul/26", R.read_js_dict(after, spec.price_var))
            self.assertIn("jul/26", R.read_js_dict(after, spec.fx_var))
            self.assertGreater(len(R.read_vol_dates(after)), len(R.read_vol_dates(before)))
            # o que não pode mudar, byte a byte
            for var in R.MANUAL_VARS:
                self.assertEqual(_block_of(before, var), _block_of(after, var),
                                 f"{spec.ticker}: bloco {var} foi alterado")
                self.assertNotEqual(_block_of(before, var), "",
                                    f"{spec.ticker}: bloco {var} não foi localizado")

    def test_new_month_gets_flagged_forward_fill(self):
        self.assertEqual(self._run(), 0)
        with open(self.dash, encoding="utf-8") as fh:
            frames = R.extract_frames(fh.read())
        for spec in R.FRAMES:
            js = frames[spec.frame]
            self.assertIn("jul/26", R.read_js_dict(js, "sharesMap"))
            self.assertIn("jul/26", R.read_js_dict(js, "cumInvK"))
            self.assertIn("forward-fill automático", js)
            U.check_frame_invariants(js, spec)  # não quebrou o contrato

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


def _block_of(js: str, var: str) -> str:
    """Texto cru de um bloco `const <var> = [ ... ];` ou `{ ... };`."""
    import re
    m = re.search(r"const\s+" + re.escape(var) + r"\s*=\s*[\[{].*?\n[\]}];", js, re.DOTALL)
    return m.group(0) if m else ""


if __name__ == "__main__":
    unittest.main()
