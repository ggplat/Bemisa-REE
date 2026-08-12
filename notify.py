#!/usr/bin/env python3
"""Alerta por e-mail do pipeline do Dashboard REE v6.

Lê a última execução em `logs/pipeline.jsonl` e manda um dos três avisos:

    OK        dados aplicados no dashboard
    ATENÇÃO   o QC pegou anomalia; o dado suspeito NÃO entrou
    FALHA     o pipeline abortou; o HTML de produção não mudou

Execução silenciosa é o caso comum: sem mudança e sem anomalia, nenhum e-mail
é enviado. Alerta que chega todo dia vira ruído e deixa de ser lido.

Configuração (variáveis de ambiente / GitHub Secrets):
    GMAIL_USER           conta remetente
    GMAIL_APP_PASSWORD   App Password do Gmail (não é a senha da conta)
    ALERT_TO             destinatário (padrão: gisrael@bemisa.com.br)

Uso:
    python notify.py                     # decide o tipo pelo último log
    python notify.py --failure "motivo"  # falha explícita (usado pelo workflow)
    python notify.py --dry-run           # imprime o e-mail em vez de enviar
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import smtplib
import sys
from email.message import EmailMessage

import ree_v6 as R

log = logging.getLogger("ree.notify")

DEFAULT_TO = "gisrael@bemisa.com.br"
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

# O que cada flag do QC significa e o que fazer a respeito.
FLAG_HELP = {
    "outlier_pct": "Salto de preço acima do limite diário. Confira o comunicado na ASX/SEDAR: "
                   "se o movimento for real, rode `python fetch_market_data.py --force-ticker <TICKER>`.",
    "outlier_fx": "Salto de câmbio acima do limite. Câmbio não se mexe tanto num dia — "
                  "quase sempre é dado ruim do provedor. Confira antes de forçar.",
    "revision": "O provedor mudou um valor já gravado. O valor antigo foi mantido. "
                "Decida se a revisão procede antes de forçar.",
    "gap": "O provedor parou de retornar dados. Nada foi preenchido — o buraco fica visível "
           "no gráfico, como deve ser.",
    "no_data": "Nenhum dado retornado para a série. Verifique se o ticker mudou de código.",
    "invalid_price": "Fechamento nulo, zero ou negativo. Dia descartado.",
    "invalid_volume": "Volume negativo. O preço foi aceito; o volume do dia, não.",
    "volume_missing": "O provedor não retornou volume. O dia fica sem barra no gráfico de volume.",
    "fx_missing": "Sem câmbio do dia, o volume financeiro não pode ser calculado. "
                  "Nenhuma taxa foi estimada.",
}


def read_last_runs(path: str) -> dict[str, dict]:
    """Última entrada de cada etapa (fetch/update) do log."""
    if not os.path.exists(path):
        return {}
    steps: dict[str, dict] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            steps[entry.get("step", "?")] = entry
    return steps


def build_body(fetch: dict, update: dict) -> tuple[str, str]:
    """Monta (assunto, corpo) a partir das últimas execuções."""
    flags = fetch.get("flags", []) if fetch else []
    changed = bool(update.get("changed")) if update else False
    when = (update or fetch or {}).get("timestamp_utc", "?")

    lines = [f"Execução: {when}",
             f"Fonte: {(fetch or {}).get('source', '—')}", ""]

    if changed:
        lines.append("APLICADO AO DASHBOARD")
        for ticker, ch in sorted(update.get("applied", {}).items()):
            if ch.get("skipped"):
                continue
            by_month = lambda kv: R.month_to_int(kv[0])  # noqa: E731 - ordem cronológica
            price = ", ".join(f"{m}={i['valor']}" for m, i in sorted(ch.get("price", {}).items(), key=by_month))
            fx = ", ".join(f"{m}={i['valor']}" for m, i in sorted(ch.get("fx", {}).items(), key=by_month))
            lines.append(f"  {ticker}:")
            if price:
                lines.append(f"    preço   {price}")
            if fx:
                lines.append(f"    câmbio  {fx}")
            if ch.get("vol_days"):
                rng = ch.get("vol_range", ["?", "?"])
                lines.append(f"    volume  +{ch['vol_days']} pregão(ões) ({rng[0]} a {rng[1]})")
            for var, months in (ch.get("forward_filled") or {}).items():
                ordered = ", ".join(sorted(months, key=R.month_to_int))
                lines.append(f"    ATENÇÃO {var}: {ordered} preenchido(s) com o "
                             f"último valor conhecido — confirme na fonte primária")
        if update.get("backup_file"):
            lines += ["", f"Backup da versão anterior: {update['backup_file']}"]
    else:
        lines.append("Nenhuma mudança aplicada ao dashboard.")

    if flags:
        lines += ["", f"ANOMALIAS DETECTADAS ({len(flags)}) — nenhum desses valores foi aplicado", ""]
        for f in flags:
            lines.append(f"  [{f['kind']}] {f['series']} {f.get('date') or ''}")
            lines.append(f"      {f['detail']}")
        kinds = sorted({f["kind"] for f in flags})
        lines += ["", "O QUE FAZER:"]
        for kind in kinds:
            lines.append(f"  {kind}: {FLAG_HELP.get(kind, 'ver logs/pipeline.jsonl')}")

    lines += ["", "-" * 62,
              "Séries sob curadoria manual (o pipeline não mexe nelas): cumInvK,",
              "qBarK, sharesMap, issuances, projEvents. Atualize-as a partir das",
              "fontes primárias (Nota 10, segment notes, Appendix 2A/3B/5B).",
              "", f"Log completo: {os.path.relpath(R.LOG_FILE, R.ROOT)}"]

    n = len(flags)
    if n:
        subject = f"[REE v6] ATENÇÃO — {n} anomalia{'s' if n > 1 else ''} detectada{'s' if n > 1 else ''}"
    elif changed:
        subject = f"[REE v6] OK — dados aplicados ({when[:10]})"
    else:
        subject = f"[REE v6] Sem mudanças ({when[:10]})"
    return subject, "\n".join(lines)


def send(subject: str, body: str, *, dry_run: bool) -> bool:
    to = os.environ.get("ALERT_TO", DEFAULT_TO)
    user = os.environ.get("GMAIL_USER")
    password = os.environ.get("GMAIL_APP_PASSWORD")

    if dry_run:
        print(f"To: {to}\nSubject: {subject}\n\n{body}")
        return True

    if not user or not password:
        # Falta de credencial não pode derrubar o pipeline: os dados já foram
        # validados e aplicados. Fica o aviso no log da execução.
        log.warning("GMAIL_USER/GMAIL_APP_PASSWORD ausentes — e-mail não enviado")
        log.warning("Assunto que seria enviado: %s", subject)
        return False

    msg = EmailMessage()
    msg["From"] = user
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=60) as smtp:
            smtp.starttls()
            smtp.login(user, password)
            smtp.send_message(msg)
    except Exception as exc:  # noqa: BLE001 - alerta falho não invalida os dados
        log.error("Envio de e-mail falhou: %s", exc)
        return False

    log.info("Alerta enviado para %s: %s", to, subject)
    return True


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Alerta por e-mail do pipeline REE v6")
    p.add_argument("--failure", help="mensagem de falha (o pipeline abortou)")
    p.add_argument("--dry-run", action="store_true", help="imprime em vez de enviar")
    p.add_argument("--force", action="store_true",
                   help="envia mesmo sem mudança e sem anomalia")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    steps = read_last_runs(R.LOG_FILE)

    if args.failure:
        subject = "[REE v6] FALHA — pipeline abortado"
        body = ("O pipeline falhou e foi interrompido.\n\n"
                f"{args.failure}\n\n"
                "O dashboard de produção NÃO foi modificado — as validações rodam\n"
                "antes da gravação, e a última versão boa segue publicada.\n\n"
                f"Última coleta registrada: {steps.get('fetch', {}).get('timestamp_utc', '—')}\n"
                f"Log: {os.path.relpath(R.LOG_FILE, R.ROOT)}")
        send(subject, body, dry_run=args.dry_run)
        return 0

    fetch, update = steps.get("fetch", {}), steps.get("update", {})
    if not fetch and not update:
        log.info("Sem execuções no log — nada a notificar.")
        return 0

    has_flags = bool(fetch.get("flags"))
    changed = bool(update.get("changed"))
    if not has_flags and not changed and not args.force:
        log.info("Sem mudanças e sem anomalias — nenhum e-mail enviado.")
        return 0

    subject, body = build_body(fetch, update)
    send(subject, body, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
