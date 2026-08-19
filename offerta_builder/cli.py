"""Interfaccia a riga di comando dell'Offer Builder.

Comandi:

* ``offerta form-init``  - crea il modello del form rapido da compilare
* ``offerta bom``        - importa e normalizza una o piu' BOM (solo lettura)
* ``offerta build``      - flusso completo: BOM + form -> DOCX, QA, PDF, riepiloghi
* ``offerta qa``         - riesegue i controlli su output gia' generati
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Optional, Sequence

from . import __version__
from .form import blank_form, interactive_fill, load_form, save_form
from .money import format_eur, format_percent
from .pipeline import BlockingError, BuildResult, build_offer, import_boms
from .qa import LEVEL_FAIL, LEVEL_OK, LEVEL_WARN

EXIT_OK = 0
EXIT_BLOCKED = 2
EXIT_QA_FAILED = 3

_ICON = {LEVEL_OK: "[OK]  ", LEVEL_WARN: "[WARN]", LEVEL_FAIL: "[FAIL]"}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return EXIT_OK
    return args.handler(args)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="offerta",
        description="Offer Builder controllato: BOM distributori -> offerta DOCX/PDF su template.",
    )
    parser.add_argument("--version", action="version", version=f"offerta-builder {__version__}")
    sub = parser.add_subparsers(dest="command")

    form_init = sub.add_parser("form-init", help="crea il modello JSON del form rapido")
    form_init.add_argument("-o", "--output", default="form_offerta.json")
    form_init.add_argument("--bom", nargs="*", default=[], help="BOM da cui precompilare i campi deducibili")
    form_init.set_defaults(handler=_cmd_form_init)

    bom_cmd = sub.add_parser("bom", help="importa e normalizza le BOM")
    bom_cmd.add_argument("files", nargs="+")
    bom_cmd.add_argument("-o", "--output", default="", help="file JSON di destinazione")
    bom_cmd.add_argument("--distributore", default="", help="forza il profilo distributore")
    bom_cmd.add_argument("--vendor", default="", help="forza il vendor")
    bom_cmd.set_defaults(handler=_cmd_bom)

    build = sub.add_parser("build", help="genera l'offerta completa")
    build.add_argument("--bom", nargs="+", required=True, help="file BOM (CSV/XLSX/PDF)")
    build.add_argument("--form", default="", help="form rapido compilato (JSON/YAML)")
    build.add_argument("--template", default="", help="template Word AD con segnaposto")
    build.add_argument("-o", "--out", default="out", help="cartella di output")
    build.add_argument("--interattivo", action="store_true", help="chiede a video i campi mancanti")
    build.add_argument("--modo", choices=["markup", "target_margin", "manual"], default=None)
    build.add_argument("--markup", default=None, help="ricarico %% sul costo")
    build.add_argument("--margine", default=None, help="margine obiettivo %% sul venduto")
    build.add_argument("--arrotondamento", default=None, choices=["none", "0.01", "0.05", "1", "5", "10", "100"])
    build.add_argument("--pdf", action="store_true",
                       help="genera anche il PDF (solo a QA superato); di default esce solo il DOCX")
    build.add_argument("--ai", action="store_true", help="riscrittura assistita dei testi discorsivi")
    build.add_argument("--force", action="store_true", help="prosegue anche con anomalie bloccanti")
    build.add_argument("--json", action="store_true", help="output di riepilogo in JSON")
    build.set_defaults(handler=_cmd_build)

    qa_cmd = sub.add_parser("qa", help="mostra l'esito dei controlli gia' generati")
    qa_cmd.add_argument("file", help="percorso di controlli_qa.json")
    qa_cmd.set_defaults(handler=_cmd_qa)
    return parser


def _cmd_form_init(args: argparse.Namespace) -> int:
    data = blank_form()
    if args.bom:
        from .form import prefill_from_bom

        data = prefill_from_bom(data, import_boms(args.bom))
    save_form(args.output, data)
    print(f"Modello form scritto in {args.output}")
    print("Compila i campi obbligatori, poi lancia: offerta build --bom <file> --form " + args.output)
    return EXIT_OK


def _cmd_bom(args: argparse.Namespace) -> int:
    boms = import_boms(args.files, distributor_hint=args.distributore, vendor_hint=args.vendor)
    payload = {"boms": [bom.to_dict() for bom in boms]}
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        print(f"BOM normalizzata scritta in {args.output}")
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=False))

    blocking = 0
    for bom in boms:
        print(
            f"\n{bom.distributor} | quote {bom.quote_number or 'n/d'} | {len(bom.items)} righe | "
            f"costo {format_eur(bom.total_cost())} | validita' {bom.valid_until or 'n/d'}"
        )
        for issue in bom.issues:
            print(f"  - [{issue.severity}] {issue.message}")
            blocking += 1 if issue.blocking else 0
    return EXIT_BLOCKED if blocking else EXIT_OK


def _cmd_build(args: argparse.Namespace) -> int:
    form: Dict[str, Any] = load_form(args.form) if args.form else blank_form()
    if args.interattivo:
        from .form import prefill_from_bom

        form = prefill_from_bom(form, import_boms(args.bom))
        form = interactive_fill(form)
    elif not args.form:
        print("Nessun form indicato: usa --form <file.json> oppure --interattivo.", file=sys.stderr)
        return EXIT_BLOCKED

    pricing_overrides = {
        "mode": args.modo,
        "markup_percent": args.markup,
        "target_margin_percent": args.margine,
        "rounding": args.arrotondamento,
    }

    approve = _console_approval if args.interattivo else None
    try:
        result = build_offer(
            bom_paths=args.bom,
            form=form,
            output_dir=args.out,
            template_path=args.template or None,
            pricing_overrides=pricing_overrides,
            use_ai=args.ai,
            force=args.force,
            make_pdf=args.pdf,
            approve=approve,
        )
    except BlockingError as exc:
        print(f"\nFLUSSO INTERROTTO: {exc}", file=sys.stderr)
        for issue in exc.issues:
            location = f" [{issue.where}]" if issue.where else ""
            print(f"  - {issue.message}{location}", file=sys.stderr)
        print(
            "\nCorreggi i dati (o rilancia con --force per procedere assumendoti la responsabilita').",
            file=sys.stderr,
        )
        return EXIT_BLOCKED

    if args.json:
        print(json.dumps(_summary(result), indent=2, ensure_ascii=False, default=str))
    else:
        _print_summary(result)
    return EXIT_OK if result.qa.passed else EXIT_QA_FAILED


def _cmd_qa(args: argparse.Namespace) -> int:
    with open(args.file, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    print(f"Esito QA: {payload.get('status', 'n/d').upper()} "
          f"({payload.get('errori', 0)} errori, {payload.get('avvisi', 0)} avvisi)")
    for check in payload.get("controlli", []):
        icon = _ICON.get(check.get("esito", ""), "      ")
        print(f"{icon} {check.get('titolo')}: {check.get('messaggio')}")
    return EXIT_OK if payload.get("status") != LEVEL_FAIL else EXIT_QA_FAILED


def _console_approval(result: BuildResult) -> bool:
    _print_summary(result)
    try:
        answer = input("\nConfermi la generazione del PDF da inviare? [s/N] ").strip().lower()
    except EOFError:
        return False
    return answer in {"s", "si", "sì", "y", "yes"}


def _summary(result: BuildResult) -> Dict[str, Any]:
    totals = result.offer.totals
    return {
        "riferimento": result.form.get("riferimento_offerta", ""),
        "cliente": result.form.get("cliente", ""),
        "righe": len(result.offer.items),
        "totale_costo": str(totals.total_cost),
        "totale_imponibile": str(totals.total_net),
        "totale_iva": str(totals.total_vat),
        "totale_offerta": str(totals.total_gross),
        "margine": str(totals.margin_value),
        "margine_percento": str(totals.margin_percent),
        "qa": result.qa.status,
        "output": result.outputs,
        "anomalie": [issue.to_dict() for issue in result.issues],
    }


def _print_summary(result: BuildResult) -> None:
    totals = result.offer.totals
    print("\n=== Riepilogo offerta ===")
    print(f"Cliente        : {result.form.get('cliente', '')}")
    print(f"Riferimento    : {result.form.get('riferimento_offerta', '')}")
    print(f"Righe          : {len(result.offer.items)}")
    print(f"Costo acquisto : {format_eur(totals.total_cost)}")
    print(f"Imponibile     : {format_eur(totals.total_net)}")
    print(f"IVA            : {format_eur(totals.total_vat)}")
    print(f"Totale offerta : {format_eur(totals.total_gross)}")
    print(f"Margine        : {format_eur(totals.margin_value)} ({format_percent(totals.margin_percent)})")

    print("\n=== Controlli QA ===")
    for check in result.qa.checks:
        print(f"{_ICON.get(check.level, '      ')} {check.title}: {check.message}")
    print(f"\nEsito QA: {result.qa.status.upper()}")

    if result.issues:
        print("\n=== Note di flusso ===")
        for issue in result.issues:
            print(f"  - [{issue.severity}] {issue.message}")

    print("\n=== Output ===")
    for key, path in result.outputs.items():
        print(f"  {key:7s} {os.path.abspath(path)}")
    if "pdf" not in result.outputs:
        bloccato = any(issue.code.startswith("pipeline.pdf") for issue in result.issues)
        print(
            "  pdf     non generato: vedi le note di flusso qui sopra"
            if bloccato
            else "  pdf     non richiesto (usa --pdf a offerta chiusa)"
        )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
