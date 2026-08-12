#!/usr/bin/env python3
"""Coleta diária de dados de mercado do Dashboard REE v6.

Busca fechamento, volume e câmbio via Yahoo Finance (yfinance), valida tudo
antes de gravar e mantém `data/market_data.json` como fonte de verdade,
separada do HTML.

Uso:
    python fetch_market_data.py                  # incremental (últimos 45 dias)
    python fetch_market_data.py --full           # rebaixa o histórico inteiro
    python fetch_market_data.py --dry-run        # não grava nada
    python fetch_market_data.py --calibrate      # compara agregação vs. HTML
    python fetch_market_data.py --only ARA,BRE

Princípios inegociáveis do QC: nunca interpolar, nunca estimar, nunca preencher
gap. Dia que não passa na validação simplesmente não entra no JSON — fica
registrado no log e vira alerta.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import sys
import uuid

import ree_v6 as R

log = logging.getLogger("ree.fetch")

SCHEMA = 1
SOURCE = "yfinance"

# ── LIMITES DO QC ────────────────────────────────────────────────────────────
MAX_DAILY_PCT = 20.0     # salto de preço num pregão (%) acima disso não é aplicado
MAX_FX_PCT = 3.0         # câmbio não salta 3% num dia; se saltou, é dado ruim
REVISION_PCT = 0.5       # divergência vs. valor já gravado que merece registro
MAX_STALE_BDAYS = 3      # pregões sem retorno antes de virar flag de gap


# ── COLETA ───────────────────────────────────────────────────────────────────

def _fetch_history(symbol: str, start: dt.date | None) -> dict[str, dict]:
    """Histórico diário via yfinance → {'AAAA-MM-DD': {'close':.., 'volume':..}}.

    Converte para tipos nativos na saída: o resto do pipeline não deve depender
    de pandas. Falha de rede não derruba a execução — devolve dict vazio e o
    ticker vira flag.
    """
    import pandas as pd
    import yfinance as yf

    try:
        ticker = yf.Ticker(symbol)
        if start:
            df = ticker.history(start=start.isoformat(), auto_adjust=False)
        else:
            df = ticker.history(period="max", auto_adjust=False)
    except Exception as exc:  # noqa: BLE001 - um símbolo não derruba os demais
        log.error("%s: download falhou: %s", symbol, exc)
        return {}

    if df.empty or "Close" not in df.columns:
        log.warning("%s: histórico vazio", symbol)
        return {}

    df.index = pd.to_datetime(df.index).date
    out: dict[str, dict] = {}
    for d, row in df.iterrows():
        close = row.get("Close")
        if close is None or pd.isna(close):
            continue
        vol = row.get("Volume")
        out[d.isoformat()] = {
            "close": round(float(close), 6),
            "volume": None if vol is None or pd.isna(vol) else int(vol),
        }
    return out


# ── QC ───────────────────────────────────────────────────────────────────────

def _business_days_between(a: dt.date, b: dt.date) -> int:
    n, cur = 0, a
    while cur < b:
        cur += dt.timedelta(days=1)
        if cur.weekday() < 5:
            n += 1
    return n


def qc_series(label: str, fetched: dict[str, dict], stored: dict[str, dict],
              max_pct: float, *, is_fx: bool, force: bool) -> tuple[dict, list[dict]]:
    """Valida a série buscada. Devolve (dias aceitos, flags).

    A variação é medida contra o **vizinho cronológico da própria série do
    provedor**, não contra o último dia aceito. Assim um pico isolado reprova
    só os dias envolvidos, em vez de invalidar em cascata tudo que vem depois.
    """
    accepted: dict[str, dict] = {}
    flags: list[dict] = []
    dates = sorted(fetched)

    for i, date in enumerate(dates):
        rec = fetched[date]
        close = rec.get("close")

        if close is None or close <= 0:
            flags.append({"kind": "invalid_price", "series": label, "date": date,
                          "detail": f"fechamento inválido: {close!r}"})
            continue

        vol = rec.get("volume")
        if vol is not None and vol < 0:
            flags.append({"kind": "invalid_volume", "series": label, "date": date,
                          "detail": f"volume negativo: {vol}"})
            vol = None

        # Divergência contra o que já está gravado: o provedor revisou o passado.
        # Mantemos o valor antigo — reescrever histórico exige decisão humana.
        old = stored.get(date, {}).get("close")
        if old and abs(close - old) / old * 100 > REVISION_PCT:
            flags.append({"kind": "revision", "series": label, "date": date,
                          "detail": f"provedor revisou {old} → {close} "
                                    f"({(close - old) / old * 100:+.2f}%); mantido o valor gravado"})
            if not force:
                continue

        # Outlier contra o pregão anterior da própria série.
        if i > 0:
            prev = fetched[dates[i - 1]].get("close")
            if prev and prev > 0:
                pct = (close - prev) / prev * 100
                if abs(pct) > max_pct:
                    kind = "outlier_fx" if is_fx else "outlier_pct"
                    flags.append({"kind": kind, "series": label, "date": date,
                                  "detail": f"variação de {pct:+.1f}% vs. {dates[i - 1]} "
                                            f"({prev} → {close}); limite {max_pct}%"})
                    if not force:
                        continue

        accepted[date] = {"close": close, "volume": vol}

    # Gap: o provedor parou de responder há mais pregões do que o tolerável.
    if dates:
        last = dt.date.fromisoformat(dates[-1])
        stale = _business_days_between(last, dt.date.today())
        if stale > MAX_STALE_BDAYS:
            flags.append({"kind": "gap", "series": label, "date": dates[-1],
                          "detail": f"último dado há {stale} pregões "
                                    f"({dates[-1]}); nada foi preenchido"})
    else:
        flags.append({"kind": "no_data", "series": label, "date": None,
                      "detail": "provedor não retornou nenhum dado"})

    return accepted, flags


# ── AGREGAÇÃO MENSAL ─────────────────────────────────────────────────────────

def monthly_mean(daily: dict[str, float], skip_closed: set[str]) -> dict[str, dict]:
    """Média aritmética simples dos fechamentos de cada mês.

    Meses já marcados como fechados não são recalculados: uma vez gravado, o
    valor de um mês encerrado é histórico e não se mexe mais.
    """
    buckets: dict[str, list[float]] = {}
    for date, value in daily.items():
        mk = R.month_key_of(dt.date.fromisoformat(date))
        if mk in skip_closed:
            continue
        buckets.setdefault(mk, []).append(value)

    today_mk = R.today_month_key()
    out: dict[str, dict] = {}
    for mk, values in buckets.items():
        out[mk] = {
            "mean": round(sum(values) / len(values), 6),
            "n_days": len(values),
            "closed": R.month_to_int(mk) < R.month_to_int(today_mk),
        }
    return out


# ── ESTADO ───────────────────────────────────────────────────────────────────

def load_state(path: str) -> dict:
    if not os.path.exists(path):
        return {"schema": SCHEMA, "updated_utc": None, "source": SOURCE,
                "fx": {}, "tickers": {}, "flags": []}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save_state(path: str, state: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")


def append_log(entry: dict) -> None:
    os.makedirs(os.path.dirname(R.LOG_FILE), exist_ok=True)
    with open(R.LOG_FILE, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


# ── CALIBRAÇÃO ───────────────────────────────────────────────────────────────

def calibrate(state: dict) -> None:
    """Compara a média aritmética recomputada com o que já está no HTML.

    Serve para descobrir se os valores históricos do dashboard foram gerados
    por outra regra de agregação — o gerador antigo (`mcap_dashboard.py:531`)
    usava `(anterior + fechamento) / 2` acumulativo, que não é média. Se o
    desvio for grande, há um degrau entre meses antigos e novos, e a decisão
    de reprocessar (ou aceitar) é humana. Este comando só reporta.
    """
    with open(R.DASHBOARD, encoding="utf-8") as fh:
        frames = R.extract_frames(fh.read())
    print(f"{'ticker':7} {'mês':8} {'no HTML':>12} {'média aritm.':>13} {'desvio':>9}")
    print("-" * 54)
    worst = 0.0
    for spec in R.FRAMES:
        tk = state["tickers"].get(spec.ticker)
        if not tk:
            continue
        html_px = R.read_js_dict(frames[spec.frame], spec.price_var)
        daily = {d: v["close"] for d, v in tk["daily"].items()}
        recomputed = monthly_mean(daily, skip_closed=set())
        for mk, info in sorted(recomputed.items(), key=lambda kv: R.month_to_int(kv[0])):
            if mk not in html_px or not info["closed"]:
                continue
            old, new = html_px[mk], info["mean"]
            dev = (new - old) / old * 100 if old else 0.0
            worst = max(worst, abs(dev))
            if abs(dev) > 1.0:
                print(f"{spec.ticker:7} {mk:8} {old:12.4f} {new:13.4f} {dev:+8.2f}%")
    print("-" * 54)
    print(f"maior desvio: {worst:.2f}%")
    if worst > 1.0:
        print("\nATENÇÃO: os valores históricos do HTML não batem com média aritmética.")
        print("Decida antes de automatizar: aceitar o degrau entre meses antigos e")
        print("novos, ou reprocessar o histórico. O pipeline não decide isso sozinho.")


# ── MAIN ─────────────────────────────────────────────────────────────────────

def run(args) -> dict:
    started = dt.datetime.now(dt.timezone.utc)
    run_id = uuid.uuid4().hex[:12]
    state = load_state(R.DATA_FILE)
    state["schema"] = SCHEMA
    state["source"] = SOURCE

    specs = list(R.FRAMES)
    if args.only:
        wanted = {t.strip().upper() for t in args.only.split(",")}
        specs = [s for s in specs if s.ticker in wanted]
        if not specs:
            raise SystemExit(f"nenhuma empresa encontrada para: {args.only}")

    forced = {t.strip().upper() for t in args.force_ticker.split(",")} if args.force_ticker else set()
    start = None if args.full else dt.date.today() - dt.timedelta(days=args.days)
    flags: list[dict] = []
    fetched_summary: dict[str, dict] = {}

    # ── câmbio primeiro: é insumo do volume financeiro de todo mundo ──
    pairs = {s.fx_pair: s.fx_yf for s in specs}
    for pair, symbol in sorted(pairs.items()):
        log.info("Buscando câmbio %s (%s)...", pair, symbol)
        raw = _fetch_history(symbol, start)
        node = state["fx"].setdefault(pair, {"yf_symbol": symbol, "daily": {}, "monthly": {}})
        stored = {d: {"close": v} for d, v in node["daily"].items()}
        accepted, fx_flags = qc_series(pair, raw, stored, MAX_FX_PCT,
                                       is_fx=True, force=pair in forced)
        flags += fx_flags
        for d, rec in accepted.items():
            node["daily"][d] = round(rec["close"], 6)
        closed = {mk for mk, i in node.get("monthly", {}).items() if i.get("closed")}
        node["monthly"].update(monthly_mean(node["daily"], closed))
        fetched_summary[pair] = {"dias_buscados": len(raw), "dias_aceitos": len(accepted),
                                 "ultimo": max(accepted) if accepted else None,
                                 "ultimo_valor": accepted[max(accepted)]["close"] if accepted else None}
        log.info("  → %s: %d dias aceitos de %d", pair, len(accepted), len(raw))

    # ── ações ──
    for spec in specs:
        log.info("Buscando %s (%s)...", spec.ticker, spec.yf_symbol)
        raw = _fetch_history(spec.yf_symbol, start)
        node = state["tickers"].setdefault(spec.ticker, {})
        node.update({"frame": spec.frame, "yf_symbol": spec.yf_symbol,
                     "currency": spec.currency, "fx_pair": spec.fx_pair})
        node.setdefault("daily", {})
        node.setdefault("monthly", {})

        accepted, tk_flags = qc_series(spec.ticker, raw, node["daily"], MAX_DAILY_PCT,
                                       is_fx=False, force=spec.ticker in forced)
        flags += tk_flags

        fx_daily = state["fx"].get(spec.fx_pair, {}).get("daily", {})
        for d, rec in sorted(accepted.items()):
            fx = fx_daily.get(d)
            vol_usd = None
            if rec["volume"] is None:
                flags.append({"kind": "volume_missing", "series": spec.ticker, "date": d,
                              "detail": "provedor não retornou volume; dia fica sem barra"})
            elif fx is None:
                # Sem câmbio do dia não há volume financeiro. O gerador antigo
                # usava 0,65 fixo aqui (mcap_dashboard.py:564), o que mascara
                # falha de dado — preferimos o buraco visível.
                flags.append({"kind": "fx_missing", "series": spec.ticker, "date": d,
                              "detail": f"sem {spec.fx_pair} em {d}; volume não calculado"})
            else:
                vol_usd = round(rec["volume"] * rec["close"] * fx, 2)
            node["daily"][d] = {"close": rec["close"], "volume": rec["volume"],
                                "vol_usd": vol_usd}

        closed = {mk for mk, i in node["monthly"].items() if i.get("closed")}
        closes = {d: v["close"] for d, v in node["daily"].items()}
        node["monthly"].update(monthly_mean(closes, closed))
        fetched_summary[spec.ticker] = {
            "dias_buscados": len(raw), "dias_aceitos": len(accepted),
            "ultimo": max(accepted) if accepted else None,
            "ultimo_fechamento": accepted[max(accepted)]["close"] if accepted else None,
        }
        log.info("  → %s: %d dias aceitos de %d", spec.ticker, len(accepted), len(raw))

    state["flags"] = flags
    state["updated_utc"] = started.strftime("%Y-%m-%dT%H:%M:%SZ")

    entry = {
        "run_id": run_id,
        "step": "fetch",
        "timestamp_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": SOURCE,
        "symbols": [s.yf_symbol for s in specs] + sorted(pairs.values()),
        "fetched": fetched_summary,
        "flags": flags,
        "dry_run": bool(args.dry_run),
        "duration_s": round((dt.datetime.now(dt.timezone.utc) - started).total_seconds(), 2),
    }

    if args.dry_run:
        log.info("--dry-run: nada gravado")
        print(json.dumps(entry, ensure_ascii=False, indent=2))
    else:
        save_state(R.DATA_FILE, state)
        append_log(entry)
        log.info("Gravado %s (%d flags)", R.DATA_FILE, len(flags))

    for f in flags:
        log.warning("FLAG %s [%s %s] %s", f["kind"], f["series"], f["date"] or "-", f["detail"])
    return state


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Coleta de dados de mercado — Dashboard REE v6")
    p.add_argument("--days", type=int, default=45,
                   help="janela incremental em dias corridos (padrão: 45, cobre a virada do mês)")
    p.add_argument("--full", action="store_true", help="rebaixa o histórico completo")
    p.add_argument("--only", help="tickers separados por vírgula (ex.: ARA,BRE)")
    p.add_argument("--force-ticker", help="aplica mesmo com flag de outlier/revisão (use após conferir a fonte)")
    p.add_argument("--dry-run", action="store_true", help="não grava JSON nem log")
    p.add_argument("--calibrate", action="store_true",
                   help="compara a agregação mensal com os valores já no HTML e sai")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(message)s")

    if args.calibrate:
        calibrate(load_state(R.DATA_FILE))
        return 0

    run(args)
    # Flags não derrubam a execução: o que passou no QC foi gravado e pode ser
    # aplicado. O alerta é responsabilidade do notify.py, a partir do log.
    return 0


if __name__ == "__main__":
    sys.exit(main())
