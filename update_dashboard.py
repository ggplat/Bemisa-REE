#!/usr/bin/env python3
"""Aplica os dados de mercado validados ao Dashboard REE v6.

Lê `data/market_data.json` (produzido por `fetch_market_data.py`) e edita
**apenas** as séries de mercado dentro de cada `srcdoc`:

    stockCAD / stockAUD   preço mensal na moeda local
    cadusd   / audusd     câmbio mensal
    volData               volume financeiro diário em USD

`qBarK`, `issuances` e `projEvents` nunca são tocados. `sharesMap` e `cumInvK`
recebem forward-fill **sinalizado** quando um mês novo abre — sem isso o JS do
frame produz `mcap = NaN` e derruba a área de investimento a zero (ver README).

Uso:
    python update_dashboard.py                 # aplica, com backup datado
    python update_dashboard.py --dry-run       # mostra o que mudaria
    python update_dashboard.py --frames 0,1    # só alguns frames
    python update_dashboard.py --no-render-check
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import uuid

import ree_v6 as R
from fetch_market_data import append_log

log = logging.getLogger("ree.update")

PRICE_DECIMALS = 4
FX_DECIMALS = 4
FILL_NOTE_SHARES = "forward-fill automático — confirmar (Appendix 2A/3B/5B)"
FILL_NOTE_CUM = "forward-fill automático — confirmar (Nota 10 / segment note)"


class UpdateAborted(RuntimeError):
    """Erro que impede a gravação. Nada é escrito quando isto sobe."""


# ── VALIDAÇÕES ───────────────────────────────────────────────────────────────

def check_node_syntax(js_block: str, label: str) -> None:
    """Roda `node --check` no script do frame. Falha aqui aborta tudo."""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(js_block)
        path = fh.name
    try:
        proc = subprocess.run(["node", "--check", path],
                              capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            raise UpdateAborted(f"node --check reprovou o frame {label}:\n{proc.stderr.strip()}")
    except FileNotFoundError:
        log.warning("node não encontrado — checagem de sintaxe pulada")
    finally:
        os.unlink(path)


def extract_inline_script(frame_html: str) -> str:
    """Maior bloco <script> sem src — é o que carrega os dados e desenha."""
    import re
    blocks = re.findall(r"<script(?![^>]*\ssrc=)[^>]*>(.*?)</script>",
                        frame_html, re.DOTALL)
    if not blocks:
        raise UpdateAborted("nenhum <script> inline encontrado no frame")
    return max(blocks, key=len)


def check_frame_invariants(frame_html: str, spec: R.FrameSpec) -> None:
    """O contrato que mantém os gráficos inteiros.

    `monthOrder` é `Object.keys(<preço>)`, e o JS lê `sharesMap[m]` direto e
    `cumInvK[m] || 0`. Um mês no preço sem correspondente nesses dois dicts
    vira `NaN` no market cap e zero no investimento.
    """
    months = set(R.read_js_dict(frame_html, spec.price_var))
    for var in ("sharesMap", "cumInvK"):
        missing = months - set(R.read_js_dict(frame_html, var))
        if missing:
            raise UpdateAborted(
                f"{spec.ticker}: meses em {spec.price_var} sem entrada em {var}: "
                f"{sorted(missing)} — isso quebraria o gráfico")

    # volData tem de continuar sendo um array JSON válido e ordenado.
    dates = R.read_vol_dates(frame_html)
    if dates != sorted(dates):
        raise UpdateAborted(f"{spec.ticker}: volData fora de ordem cronológica")
    if len(dates) != len(set(dates)):
        raise UpdateAborted(f"{spec.ticker}: volData tem datas duplicadas")
    import re
    body = R.VOL_RE.search(frame_html).group(2)
    try:
        json.loads("[" + body + "]")
    except json.JSONDecodeError as exc:
        raise UpdateAborted(f"{spec.ticker}: volData não é JSON válido: {exc}") from None


def check_brand(before: str, after: str) -> None:
    """A identidade visual não pode mudar por efeito colateral."""
    for token in R.BRAND_TOKENS:
        if before.count(token) != after.count(token):
            raise UpdateAborted(
                f"identidade visual alterada: ocorrências de '{token}' passaram de "
                f"{before.count(token)} para {after.count(token)}")
    n_before = len(R.FRAME_RE.findall(before))
    n_after = len(R.FRAME_RE.findall(after))
    if n_before != n_after or n_after != 5:
        raise UpdateAborted(f"contagem de iframes mudou: {n_before} → {n_after}")
    for marker in ("data:image/png;base64,", "chart-frame", "master-toggle"):
        if before.count(marker) != after.count(marker):
            raise UpdateAborted(f"estrutura alterada: marcador '{marker}' mudou de contagem")


def run_render_check(path: str) -> None:
    """jsdom + D3: garante que os 5 frames desenham sem NaN."""
    script = os.path.join(R.ROOT, "tools", "render_check.js")
    if not os.path.exists(script):
        log.warning("tools/render_check.js ausente — checagem de renderização pulada")
        return
    proc = subprocess.run(["node", script, path], capture_output=True, text=True, timeout=300)
    sys.stdout.write(proc.stdout)
    if proc.returncode != 0:
        raise UpdateAborted(f"checagem de renderização falhou:\n{proc.stderr.strip()}")


# ── APLICAÇÃO ────────────────────────────────────────────────────────────────

def _fmt(value: float, decimals: int) -> str:
    return f"{value:.{decimals}f}"


def _is_writable(js: str, var: str, month: str) -> bool:
    """Um mês só pode ser escrito se for **novo** (ainda não existe no
    dashboard) ou se for o **mês corrente** (ainda em aberto, esperado se
    mover conforme mais pregões do mês entram). Qualquer outro mês que já
    exista no dashboard é permanentemente protegido — nunca é recalculado.

    Sem essa regra, a primeira execução do pipeline (sem histórico próprio
    ainda) recalculava meses já fechados e manualmente curados a partir de
    poucos pregões disponíveis na janela de busca, sobrescrevendo o valor
    original com uma média não representativa do mês inteiro.
    """
    existing = R.read_js_dict(js, var)
    return month not in existing or month == R.today_month_key()


def apply_frame(frame_html: str, spec: R.FrameSpec, state: dict) -> tuple[str, dict]:
    """Aplica preço, câmbio e volume de um ticker. Devolve (html, resumo)."""
    node = state["tickers"].get(spec.ticker)
    if not node:
        return frame_html, {"skipped": "sem dados no market_data.json"}

    changes = {"price": {}, "fx": {}, "vol_days": 0, "forward_filled": {}, "protected": []}
    js = frame_html

    # ── preço mensal ──
    for mk, info in sorted(node.get("monthly", {}).items(), key=lambda kv: R.month_to_int(kv[0])):
        if not _is_writable(js, spec.price_var, mk):
            changes["protected"].append(mk)
            continue
        value = _fmt(info["mean"], PRICE_DECIMALS)
        js, action = R.upsert_dict_entry(js, spec.price_var, mk, value)
        if action != "unchanged":
            changes["price"][mk] = {"valor": value, "acao": action, "pregoes": info["n_days"]}

    # ── câmbio mensal ──
    fx_monthly = state["fx"].get(spec.fx_pair, {}).get("monthly", {})
    for mk, info in sorted(fx_monthly.items(), key=lambda kv: R.month_to_int(kv[0])):
        if not _is_writable(js, spec.fx_var, mk):
            if mk not in changes["protected"]:
                changes["protected"].append(mk)
            continue
        value = _fmt(info["mean"], FX_DECIMALS)
        js, action = R.upsert_dict_entry(js, spec.fx_var, mk, value)
        if action != "unchanged":
            changes["fx"][mk] = {"valor": value, "acao": action}

    # ── forward-fill sinalizado das séries manuais ──
    # Só para meses que o preço acabou de abrir. Repete o último valor conhecido
    # (a mesma convenção que o arquivo já usa à mão) e deixa marca no código.
    months = sorted(R.read_js_dict(js, spec.price_var), key=R.month_to_int)
    for var, note in (("sharesMap", FILL_NOTE_SHARES), ("cumInvK", FILL_NOTE_CUM)):
        current = R.read_js_dict(js, var)
        if not current:
            raise UpdateAborted(f"{spec.ticker}: dict {var} vazio")
        ordered = sorted(current, key=R.month_to_int)
        last_value = current[ordered[-1]]
        for mk in months:
            if mk in current:
                continue
            value = f"{last_value:.0f}" if var == "sharesMap" else f"{last_value:g}"
            js, action = R.upsert_dict_entry(js, var, mk, value, comment=note)
            if action == "inserted":
                changes["forward_filled"].setdefault(var, {})[mk] = value
                log.warning("%s: %s[%s] preenchido com o último valor conhecido (%s) "
                            "— confirme na fonte primária", spec.ticker, var, mk, value)

    # ── volume financeiro diário ──
    existing = set(R.read_vol_dates(js))
    last_date = max(existing) if existing else ""
    points = [(d, rec["vol_usd"])
              for d, rec in sorted(node.get("daily", {}).items())
              if d > last_date and rec.get("vol_usd") is not None]
    if points:
        js = R.append_vol_points(js, points)
        changes["vol_days"] = len(points)
        changes["vol_range"] = [points[0][0], points[-1][0]]

    return js, changes


def run(args) -> int:
    started = dt.datetime.now(dt.timezone.utc)
    run_id = uuid.uuid4().hex[:12]

    if not os.path.exists(R.DATA_FILE):
        raise UpdateAborted(f"{R.DATA_FILE} não existe — rode fetch_market_data.py antes")
    with open(R.DATA_FILE, encoding="utf-8") as fh:
        state = json.load(fh)

    with open(R.DASHBOARD, encoding="utf-8") as fh:
        original = fh.read()
    frames = R.extract_frames(original)
    if sorted(frames) != [0, 1, 2, 3, 4]:
        raise UpdateAborted(f"esperados 5 frames, encontrados: {sorted(frames)}")

    wanted = ({int(x) for x in args.frames.split(",")} if args.frames
              else {s.frame for s in R.FRAMES})

    updated: dict[int, str] = {}
    summary: dict[str, dict] = {}
    for spec in R.FRAMES:
        if spec.frame not in wanted:
            continue
        new_js, changes = apply_frame(frames[spec.frame], spec, state)
        summary[spec.ticker] = changes
        if new_js != frames[spec.frame]:
            check_frame_invariants(new_js, spec)
            check_node_syntax(extract_inline_script(new_js), spec.ticker)
            updated[spec.frame] = new_js

    if not updated:
        log.info("Nenhuma mudança a aplicar.")
        if not args.dry_run:
            append_log({"run_id": run_id, "step": "update",
                        "timestamp_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "applied": {}, "changed": False,
                        "duration_s": round((dt.datetime.now(dt.timezone.utc) - started).total_seconds(), 2)})
        return 0

    new_doc = R.replace_frames(original, updated)
    check_brand(original, new_doc)

    for ticker, ch in summary.items():
        if ch.get("skipped"):
            log.info("%s: %s", ticker, ch["skipped"])
            continue
        log.info("%s: preço %s | câmbio %s | volume +%d dia(s)%s%s",
                 ticker, ch["price"] or "—", ch["fx"] or "—", ch["vol_days"],
                 f" | forward-fill {ch['forward_filled']}" if ch["forward_filled"] else "",
                 f" | {len(ch['protected'])} mês(es) protegido(s) (já fechado no dashboard)"
                 if ch["protected"] else "")

    if args.dry_run:
        log.info("--dry-run: nada gravado (%d frames mudariam, %d bytes de diferença)",
                 len(updated), abs(len(new_doc) - len(original)))
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    # Renderização é checada no arquivo candidato, antes de tocar no de produção.
    if not args.no_render_check:
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(new_doc)
            candidate = fh.name
        try:
            run_render_check(candidate)
        finally:
            os.unlink(candidate)

    stem = os.path.splitext(os.path.basename(R.DASHBOARD))[0]
    backup = os.path.join(os.path.dirname(R.DASHBOARD),
                          f"{stem}_backup_{dt.date.today():%Y%m%d}.html")
    shutil.copy2(R.DASHBOARD, backup)
    with open(R.DASHBOARD, "w", encoding="utf-8") as fh:
        fh.write(new_doc)
    os.makedirs(os.path.dirname(R.DOCS_COPY), exist_ok=True)
    shutil.copy2(R.DASHBOARD, R.DOCS_COPY)

    append_log({
        "run_id": run_id, "step": "update",
        "timestamp_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "applied": summary, "changed": True,
        "frames": sorted(updated),
        "backup_file": os.path.basename(backup),
        "duration_s": round((dt.datetime.now(dt.timezone.utc) - started).total_seconds(), 2),
    })
    log.info("Dashboard atualizado. Backup: %s", os.path.basename(backup))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Aplica dados de mercado ao Dashboard REE v6")
    p.add_argument("--dry-run", action="store_true", help="mostra as mudanças sem gravar")
    p.add_argument("--frames", help="índices de frame separados por vírgula (ex.: 0,1)")
    p.add_argument("--no-render-check", action="store_true",
                   help="pula a checagem jsdom (use só em ambiente sem node)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(message)s")
    try:
        return run(args)
    except UpdateAborted as exc:
        log.error("ABORTADO: %s", exc)
        log.error("O dashboard de produção NÃO foi modificado.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
