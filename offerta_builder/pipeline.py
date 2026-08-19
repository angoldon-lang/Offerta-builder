"""Orchestrazione del flusso: BOM -> form -> prezzi -> DOCX -> QA -> output.

Il flusso è volutamente a cancelli: ogni fase che trova un problema bloccante
si ferma e chiede conferma, invece di tirare a indovinare.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Sequence

from . import content as content_module
from .bom import normalize
from .docx_builder import build_context, extract_headings, extract_text, render
from .form import prefill_from_bom, validate
from .models import (
    SEVERITY_BLOCKING,
    Issue,
    NormalizedBom,
    PricedOffer,
    ServiceLine,
)
from .money import parse_decimal
from .pdf import PdfConversionError, docx_to_pdf
from .pricing import LineOverride, PricingPolicy, price_offer
from .qa import QaReport, run_qa
from .report import build_internal_report

OUTPUT_NAMES = {
    "docx": "offerta.docx",
    "pdf": "offerta.pdf",
    "bom": "bom_normalizzata.json",
    "qa": "controlli_qa.json",
    "report": "riepilogo_interno.html",
    "data": "dati_offerta.json",
}


class BlockingError(RuntimeError):
    """Il flusso si è fermato: servono conferme o correzioni dell'operatore."""

    def __init__(self, message: str, issues: Sequence[Issue] = ()):
        super().__init__(message)
        self.issues = list(issues)


@dataclass
class PreparedOffer:
    """Offerta calcolata ma non ancora scritta su disco."""

    form: Dict[str, Any]
    offer: PricedOffer
    issues: List[Issue] = field(default_factory=list)


@dataclass
class BuildResult:
    offer: PricedOffer
    qa: QaReport
    outputs: Dict[str, str] = field(default_factory=dict)
    issues: List[Issue] = field(default_factory=list)
    form: Dict[str, Any] = field(default_factory=dict)


def import_boms(paths: Sequence[str], distributor_hint: str = "", vendor_hint: str = "") -> List[NormalizedBom]:
    return [normalize(path, distributor_hint=distributor_hint, vendor_hint=vendor_hint) for path in paths]


def policy_from_form(form: Dict[str, Any], overrides: Optional[Dict[str, Any]] = None) -> PricingPolicy:
    """Costruisce la politica di prezzo dal form, con eventuali override da CLI."""
    pricing = dict(form.get("pricing") or {})
    pricing.update({k: v for k, v in (overrides or {}).items() if v is not None})

    policy = PricingPolicy(
        mode=str(pricing.get("mode") or "markup"),
        markup_percent=_dec(pricing.get("markup_percent"), Decimal("0")),
        target_margin_percent=_dec(pricing.get("target_margin_percent"), Decimal("0")),
        vat_percent=_dec(form.get("iva_percento"), Decimal("22")),
        min_margin_percent=_dec(form.get("margine_minimo_percento"), Decimal("0")),
        rounding=str(pricing.get("rounding") or "0.01"),
        contract_years=int(form.get("durata_contratto_anni") or 1),
    )
    for raw in pricing.get("overrides") or []:
        policy.overrides.append(
            LineOverride(
                match=str(raw.get("match", "")),
                mode=str(raw.get("mode", "")),
                markup_percent=parse_decimal(raw.get("markup_percent")),
                target_margin_percent=parse_decimal(raw.get("target_margin_percent")),
                sell_net_unit=parse_decimal(raw.get("sell_net_unit")),
                sell_net_total=parse_decimal(raw.get("sell_net_total")),
                vat_percent=parse_decimal(raw.get("vat_percent")),
            )
        )
    policy.services = _services_from_form(form)
    return policy


def _services_from_form(form: Dict[str, Any]) -> List[ServiceLine]:
    services: List[ServiceLine] = []
    for raw in form.get("servizi_aggiuntivi") or []:
        if isinstance(raw, str):
            continue  # senza prezzo non è una riga d'offerta: resta testo descrittivo
        if not isinstance(raw, dict) or not str(raw.get("descrizione", "")).strip():
            continue
        services.append(
            ServiceLine(
                description=str(raw["descrizione"]).strip(),
                quantity=_dec(raw.get("quantita"), Decimal("1")),
                unit_price=_dec(raw.get("prezzo_unitario"), Decimal("0")),
                unit_cost=_dec(raw.get("costo_unitario"), Decimal("0")),
                category=str(raw.get("categoria") or "Servizi"),
                period=str(raw.get("periodo") or ""),
                notes=str(raw.get("note") or ""),
            )
        )
    return services


def prepare_offer(
    boms: Sequence[NormalizedBom],
    form: Dict[str, Any],
    pricing_overrides: Optional[Dict[str, Any]] = None,
    force: bool = False,
) -> "PreparedOffer":
    """Valida il form e calcola i prezzi, senza scrivere nulla su disco.

    È la parte del flusso che si può rieseguire a ogni modifica dei dati:
    la usa l'anteprima della UI web, e la riusa ``build_offer``.
    """
    issues: List[Issue] = []

    bom_blocking = [i for bom in boms for i in bom.blocking_issues]
    if bom_blocking and not force:
        raise BlockingError(
            "Import BOM interrotto: dati mancanti o incoerenti da confermare.", bom_blocking
        )
    issues.extend(bom_blocking)

    form = prefill_from_bom(form, boms)
    clean_form, form_issues = validate(form)
    issues.extend(form_issues)
    form_blocking = [i for i in form_issues if i.severity == SEVERITY_BLOCKING]
    if form_blocking and not force:
        raise BlockingError("Form incompleto o non valido.", form_blocking)

    policy = policy_from_form(clean_form, pricing_overrides)
    offer = price_offer(boms, policy, offer=_offer_meta(clean_form))
    pricing_blocking = [i for i in offer.issues if i.severity == SEVERITY_BLOCKING]
    if pricing_blocking and not force:
        raise BlockingError("Motore commerciale bloccato.", pricing_blocking)

    return PreparedOffer(form=clean_form, offer=offer, issues=issues)


def build_offer(
    bom_paths: Sequence[str] = (),
    form: Optional[Dict[str, Any]] = None,
    output_dir: str = "out",
    template_path: Optional[str] = None,
    pricing_overrides: Optional[Dict[str, Any]] = None,
    use_ai: bool = False,
    force: bool = False,
    make_pdf: bool = False,
    approve: Optional[Callable[[BuildResult], bool]] = None,
    boms: Optional[Sequence[NormalizedBom]] = None,
) -> BuildResult:
    """Esegue l'intero flusso e scrive gli output nella cartella indicata.

    Le BOM si passano come percorsi (``bom_paths``) oppure già normalizzate
    (``boms``), per non rileggere i file a ogni rigenerazione.

    Il deliverable è il DOCX: resta modificabile a mano prima dell'invio. Il
    PDF si genera solo con ``make_pdf=True``, e comunque solo a QA superato.

    ``force=True`` prosegue anche in presenza di anomalie bloccanti (import,
    form o QA), registrandole comunque negli output.
    """
    os.makedirs(output_dir, exist_ok=True)

    # 1-3. Import BOM, form e prezzi ----------------------------------------
    if boms is None:
        boms = import_boms(bom_paths)
    prepared = prepare_offer(boms, form or {}, pricing_overrides, force=force)
    clean_form, offer, issues = prepared.form, prepared.offer, prepared.issues

    # 4. Testi --------------------------------------------------------------
    generated = content_module.build_content(offer, clean_form)
    if use_ai:
        offer.issues.extend(content_module.refine_with_ai(generated, offer, clean_form))
    offer.content = generated

    # 5. DOCX ---------------------------------------------------------------
    context = build_context(offer, clean_form, generated)
    docx_path = os.path.join(output_dir, OUTPUT_NAMES["docx"])
    render(context, docx_path, template_path=template_path)

    # 6. QA -----------------------------------------------------------------
    qa_report = run_qa(
        offer,
        clean_form,
        document_text=extract_text(docx_path),
        headings=extract_headings(docx_path),
    )

    result = BuildResult(offer=offer, qa=qa_report, form=clean_form, issues=issues)
    result.outputs["docx"] = docx_path

    # 7. Output di supporto -------------------------------------------------
    bom_path = os.path.join(output_dir, OUTPUT_NAMES["bom"])
    _write_json(bom_path, {"boms": [bom.to_dict() for bom in boms]})
    result.outputs["bom"] = bom_path

    qa_path = os.path.join(output_dir, OUTPUT_NAMES["qa"])
    _write_json(qa_path, qa_report.to_dict())
    result.outputs["qa"] = qa_path

    data_path = os.path.join(output_dir, OUTPUT_NAMES["data"])
    _write_json(data_path, offer.to_dict())
    result.outputs["data"] = data_path

    report_path = build_internal_report(
        offer, clean_form, qa_report, os.path.join(output_dir, OUTPUT_NAMES["report"])
    )
    result.outputs["report"] = report_path

    # 8. PDF (opzionale): solo dopo QA superato o forzatura esplicita --------
    if make_pdf:
        if not qa_report.passed and not force:
            result.issues.append(
                Issue(
                    code="pipeline.pdf_blocked",
                    severity=SEVERITY_BLOCKING,
                    message="PDF non generato: il QA ha rilevato errori bloccanti.",
                )
            )
        elif approve is not None and not approve(result):
            result.issues.append(
                Issue(
                    code="pipeline.pdf_not_approved",
                    severity=SEVERITY_BLOCKING,
                    message="PDF non generato: approvazione non concessa dall'operatore.",
                )
            )
        else:
            try:
                pdf_path = docx_to_pdf(docx_path, os.path.join(output_dir, OUTPUT_NAMES["pdf"]))
                result.outputs["pdf"] = pdf_path
            except PdfConversionError as exc:
                result.issues.append(
                    Issue(code="pipeline.pdf_error", severity=SEVERITY_BLOCKING, message=str(exc))
                )
    return result


def _offer_meta(form: Dict[str, Any]) -> Dict[str, Any]:
    from .dates import to_it

    return {
        "cliente": form.get("cliente", ""),
        "piva": form.get("piva", ""),
        "referente": form.get("referente", ""),
        "oggetto": form.get("oggetto", ""),
        "autore": form.get("autore", ""),
        "riferimento_offerta": form.get("riferimento_offerta", ""),
        "data_offerta": to_it(form.get("data_offerta")),
        "validita_offerta": to_it(form.get("validita_offerta")),
        "durata_contratto_anni": form.get("durata_contratto_anni", ""),
        "fatturazione": form.get("fatturazione", ""),
    }


def _write_json(path: str, payload: Any) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, default=str)
        handle.write("\n")


def _dec(value: Any, default: Decimal) -> Decimal:
    parsed = parse_decimal(value)
    return parsed if parsed is not None else default
