"""QA Agent: l'ultimo cancello prima dell'invio.

Ricontrolla il documento generato e i dati che lo hanno prodotto. Ogni controllo
ha un esito (``ok``/``warn``/``fail``); un solo ``fail`` blocca l'export PDF e
l'approvazione, salvo forzatura esplicita dell'operatore.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from .dates import parse_date_strict, to_it
from .models import SEVERITY_BLOCKING, SEVERITY_WARNING, Issue, PricedOffer, _json_safe
from .money import close_enough, format_eur, format_percent, q2

LEVEL_OK = "ok"
LEVEL_WARN = "warn"
LEVEL_FAIL = "fail"

PLACEHOLDER_PATTERNS = [
    r"\{\{[^}]*\}\}",
    r"\{%[^%]*%\}",
    r"<<[^>]{1,60}>>",
    r"\[\[[^\]]{1,60}\]\]",
    r"\bTBD\b",
    r"\bPLACEHOLDER\b",
    r"\bXXXX+\b",
    r"\bLOREM IPSUM\b",
    r"\bNOME CLIENTE\b",
]

# "PremessaPremessa", "OggettoOggetto": tipico di un merge di segnaposto.
_DUPLICATED_WORD_RE = re.compile(r"\b([A-Z][a-zàèéìòù]{3,20})\1\b")


@dataclass
class Check:
    id: str
    title: str
    level: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.level == LEVEL_OK

    def to_dict(self) -> Dict[str, Any]:
        return _json_safe(
            {
                "id": self.id,
                "titolo": self.title,
                "esito": self.level,
                "messaggio": self.message,
                "dettagli": self.details,
            }
        )


@dataclass
class QaReport:
    checks: List[Check] = field(default_factory=list)
    generated_at: str = ""

    @property
    def status(self) -> str:
        if any(c.level == LEVEL_FAIL for c in self.checks):
            return LEVEL_FAIL
        if any(c.level == LEVEL_WARN for c in self.checks):
            return LEVEL_WARN
        return LEVEL_OK

    @property
    def passed(self) -> bool:
        return self.status != LEVEL_FAIL

    def failures(self) -> List[Check]:
        return [c for c in self.checks if c.level == LEVEL_FAIL]

    def warnings(self) -> List[Check]:
        return [c for c in self.checks if c.level == LEVEL_WARN]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "generato_il": self.generated_at or datetime.now().isoformat(timespec="seconds"),
            "totale_controlli": len(self.checks),
            "errori": len(self.failures()),
            "avvisi": len(self.warnings()),
            "controlli": [c.to_dict() for c in self.checks],
        }


def run_qa(
    offer: PricedOffer,
    form: Dict[str, Any],
    document_text: str = "",
    min_margin_percent: Optional[Decimal] = None,
    headings: Optional[List[str]] = None,
) -> QaReport:
    """Esegue tutti i controlli previsti prima dell'approvazione."""
    report = QaReport(generated_at=datetime.now().isoformat(timespec="seconds"))
    threshold = (
        min_margin_percent
        if min_margin_percent is not None
        else Decimal(str(form.get("margine_minimo_percento") or 0))
    )

    report.checks.append(_check_placeholders(document_text))
    report.checks.append(_check_duplicated_titles(document_text, headings))
    report.checks.append(_check_dates(form))
    report.checks.append(_check_validity_vs_bom(offer, form))
    report.checks.append(_check_line_totals(offer))
    report.checks.append(_check_vat(offer, form))
    report.checks.append(_check_margin(offer, threshold))
    report.checks.append(_check_payment_terms(form))
    report.checks.append(_check_required_fields(form))
    report.checks.append(_check_document_totals(offer, document_text))
    report.checks.extend(_checks_from_issues(offer))
    return report


def _check_placeholders(text: str) -> Check:
    if not text:
        return Check("qa.placeholders", "Segnaposto residui", LEVEL_WARN,
                     "Documento non analizzato: testo non disponibile.")
    found: List[str] = []
    for pattern in PLACEHOLDER_PATTERNS:
        found.extend(match.group(0) for match in re.finditer(pattern, text, re.IGNORECASE))
    if found:
        return Check(
            "qa.placeholders",
            "Segnaposto residui",
            LEVEL_FAIL,
            f"Nel documento restano {len(found)} segnaposto non compilati.",
            {"trovati": sorted(set(found))[:20]},
        )
    return Check("qa.placeholders", "Segnaposto residui", LEVEL_OK, "Nessun segnaposto residuo.")


def _check_duplicated_titles(text: str, headings: Optional[List[str]] = None) -> Check:
    """Cerca titoli incollati (``PremessaPremessa``) e sezioni ripetute.

    Le ripetizioni di importi in celle adiacenti (prezzo unitario = totale con
    quantità 1) sono legittime: il confronto fra righe consecutive ignora
    quindi tutto cio' che contiene cifre.
    """
    if not text:
        return Check("qa.titoli", "Titoli duplicati", LEVEL_WARN, "Documento non analizzato.")
    duplicated = {m.group(0) for m in _DUPLICATED_WORD_RE.finditer(text)}

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    repeated_lines = {
        current
        for previous, current in zip(lines, lines[1:])
        if previous == current and len(current) < 60 and not any(ch.isdigit() for ch in current)
    }

    repeated_headings = set()
    if headings:
        seen: Dict[str, int] = {}
        for heading in headings:
            key = heading.strip().lower()
            seen[key] = seen.get(key, 0) + 1
        repeated_headings = {h for h in headings if seen[h.strip().lower()] > 1}

    problems = sorted(duplicated | repeated_lines | repeated_headings)
    if problems:
        return Check(
            "qa.titoli",
            "Titoli duplicati",
            LEVEL_FAIL,
            "Titoli o intestazioni duplicati nel documento.",
            {"occorrenze": problems[:20]},
        )
    return Check("qa.titoli", "Titoli duplicati", LEVEL_OK, "Nessuna duplicazione rilevata.")


def _check_dates(form: Dict[str, Any]) -> Check:
    problems: List[str] = []
    values: Dict[str, Optional[date]] = {}
    for field_name, label in [("data_offerta", "Data offerta"), ("validita_offerta", "Validità offerta")]:
        parsed, error = parse_date_strict(form.get(field_name))
        values[field_name] = parsed
        if parsed is None:
            problems.append(f"{label}: '{form.get(field_name)}' non valida ({error}).")
    data_offerta, validita = values.get("data_offerta"), values.get("validita_offerta")
    if data_offerta and validita and validita < data_offerta:
        problems.append(
            f"Validità ({to_it(validita)}) precedente alla data offerta ({to_it(data_offerta)})."
        )
    if problems:
        return Check("qa.date", "Date offerta", LEVEL_FAIL, " ".join(problems), {"problemi": problems})
    return Check(
        "qa.date",
        "Date offerta",
        LEVEL_OK,
        f"Date coerenti: offerta {to_it(data_offerta)}, validità {to_it(validita)}.",
    )


def _check_validity_vs_bom(offer: PricedOffer, form: Dict[str, Any]) -> Check:
    validita, _ = parse_date_strict(form.get("validita_offerta"))
    if validita is None:
        return Check("qa.validita_bom", "Validità vs BOM", LEVEL_WARN,
                     "Validità offerta non interpretabile: confronto con la BOM non eseguito.")
    problems: List[str] = []
    checked = 0
    for bom in offer.boms:
        bom_validity, _ = parse_date_strict(bom.valid_until)
        if bom_validity is None:
            continue
        checked += 1
        if validita > bom_validity:
            problems.append(
                f"{bom.distributor} (quote {bom.quote_number or 'n/d'}): quotazione valida fino al "
                f"{to_it(bom_validity)}, offerta valida fino al {to_it(validita)}."
            )
    if problems:
        return Check(
            "qa.validita_bom",
            "Validità vs BOM",
            LEVEL_FAIL,
            "La validità dell'offerta supera quella della quotazione distributore.",
            {"problemi": problems},
        )
    if checked == 0:
        return Check("qa.validita_bom", "Validità vs BOM", LEVEL_WARN,
                     "Nessuna BOM riporta una validità: va confermata con il distributore.")
    return Check("qa.validita_bom", "Validità vs BOM", LEVEL_OK,
                 "Validità offerta compatibile con le quotazioni distributore.")


def _check_line_totals(offer: PricedOffer) -> Check:
    sum_net = q2(sum((i.sell_net_total or Decimal("0") for i in offer.items), Decimal("0")))
    sum_vat = q2(sum((i.vat_total or Decimal("0") for i in offer.items), Decimal("0")))
    sum_gross = q2(sum((i.sell_gross_total or Decimal("0") for i in offer.items), Decimal("0")))
    totals = offer.totals
    problems = []
    if not close_enough(sum_net, totals.total_net):
        problems.append(f"imponibile righe {format_eur(sum_net)} != totale offerta {format_eur(totals.total_net)}")
    if not close_enough(sum_vat, totals.total_vat):
        problems.append(f"IVA righe {format_eur(sum_vat)} != IVA offerta {format_eur(totals.total_vat)}")
    if not close_enough(sum_gross, totals.total_gross):
        problems.append(f"totale lordo righe {format_eur(sum_gross)} != totale offerta {format_eur(totals.total_gross)}")
    annual_net = q2(sum((a.total_net for a in offer.annual), Decimal("0")))
    if offer.annual and not close_enough(annual_net, totals.total_net):
        problems.append(
            f"riepilogo annualità {format_eur(annual_net)} != imponibile offerta {format_eur(totals.total_net)}"
        )
    if problems:
        return Check("qa.totali", "Quadratura totali", LEVEL_FAIL,
                     "Totali non quadrati: " + "; ".join(problems), {"problemi": problems})
    return Check("qa.totali", "Quadratura totali", LEVEL_OK,
                 f"Somma righe = totale offerta ({format_eur(totals.total_gross)}).")


def _check_vat(offer: PricedOffer, form: Dict[str, Any]) -> Check:
    expected_rate = Decimal(str(form.get("iva_percento") or 0))
    problems = []
    for item in offer.items:
        if item.sell_net_total is None or item.vat_total is None:
            continue
        rate = item.vat_percent if item.vat_percent is not None else expected_rate
        expected = q2(item.sell_net_total * rate / Decimal("100"))
        if not close_enough(expected, item.vat_total):
            problems.append(
                f"riga '{item.key()}': IVA {format_eur(item.vat_total)}, attesa {format_eur(expected)}"
            )
    if problems:
        return Check("qa.iva", "Calcolo IVA", LEVEL_FAIL,
                     "IVA non coerente su alcune righe.", {"problemi": problems[:10]})
    return Check("qa.iva", "Calcolo IVA", LEVEL_OK,
                 f"IVA calcolata correttamente ({format_percent(expected_rate, 0)}).")


def _check_margin(offer: PricedOffer, threshold: Decimal) -> Check:
    margin = offer.totals.margin_percent
    if threshold <= 0:
        return Check("qa.margine", "Margine minimo", LEVEL_WARN,
                     f"Soglia di margine non impostata (margine offerta {format_percent(margin)}).")
    below = [
        f"{i.key()} ({format_percent(i.margin_percent)})"
        for i in offer.items
        if i.sell_net_total and i.margin_percent is not None and i.margin_percent < threshold
    ]
    if margin < threshold:
        # Segnalato, mai bloccante: accettare un margine basso e' una decisione
        # commerciale che spetta a chi firma l'offerta.
        return Check(
            "qa.margine",
            "Margine minimo",
            LEVEL_WARN,
            f"Margine offerta {format_percent(margin)}, sotto la soglia minima {format_percent(threshold)}.",
            {"margine": margin, "soglia": threshold, "righe_sotto_soglia": below[:20]},
        )
    if below:
        quante = f"{len(below)} righe sono" if len(below) > 1 else "1 riga è"
        return Check(
            "qa.margine",
            "Margine minimo",
            LEVEL_WARN,
            f"Margine totale {format_percent(margin)} sopra soglia, ma {quante} sotto il {format_percent(threshold)}.",
            {"righe_sotto_soglia": below[:20]},
        )
    return Check("qa.margine", "Margine minimo", LEVEL_OK,
                 f"Margine offerta {format_percent(margin)}, sopra la soglia {format_percent(threshold)}.")


def _check_payment_terms(form: Dict[str, Any]) -> Check:
    missing = [
        label
        for key, label in [
            ("tipologia_pagamento", "Tipologia pagamento"),
            ("condizioni_pagamento", "Condizioni pagamento"),
            ("fatturazione", "Fatturazione"),
        ]
        if not str(form.get(key, "")).strip()
    ]
    if missing:
        return Check("qa.condizioni", "Condizioni di pagamento", LEVEL_FAIL,
                     "Condizioni incomplete: " + ", ".join(missing), {"mancanti": missing})
    return Check("qa.condizioni", "Condizioni di pagamento", LEVEL_OK, "Condizioni di pagamento complete.")


def _check_required_fields(form: Dict[str, Any]) -> Check:
    from .form import missing_required

    missing = missing_required(form)
    if missing:
        return Check(
            "qa.campi_obbligatori",
            "Campi obbligatori",
            LEVEL_FAIL,
            "Campi obbligatori mancanti: " + ", ".join(spec.label for spec in missing),
            {"mancanti": [spec.name for spec in missing]},
        )
    return Check("qa.campi_obbligatori", "Campi obbligatori", LEVEL_OK, "Tutti i campi obbligatori valorizzati.")


def _check_document_totals(offer: PricedOffer, text: str) -> Check:
    """Il totale stampato nel documento deve essere quello calcolato."""
    if not text:
        return Check("qa.totale_documento", "Totale a documento", LEVEL_WARN, "Documento non analizzato.")
    from .money import format_eur

    expected = format_eur(offer.totals.total_gross, "EUR")
    expected_net = format_eur(offer.totals.total_net, "EUR")
    normalized = re.sub(r"\s+", " ", text)
    if expected.split(" ")[0] in normalized and expected_net.split(" ")[0] in normalized:
        return Check("qa.totale_documento", "Totale a documento", LEVEL_OK,
                     f"Imponibile e totale ({expected}) presenti nel documento.")
    return Check(
        "qa.totale_documento",
        "Totale a documento",
        LEVEL_FAIL,
        f"Totale calcolato ({expected}) non trovato nel documento generato.",
        {"atteso_imponibile": expected_net, "atteso_totale": expected},
    )


def _checks_from_issues(offer: PricedOffer) -> List[Check]:
    """Riporta nel QA le anomalie di import/pricing già raccolte a monte."""
    issues: List[Issue] = list(offer.issues)
    for bom in offer.boms:
        issues.extend(bom.issues)
    checks: List[Check] = []
    for issue in issues:
        level = LEVEL_FAIL if issue.severity == SEVERITY_BLOCKING else (
            LEVEL_WARN if issue.severity == SEVERITY_WARNING else LEVEL_OK
        )
        checks.append(
            Check(
                id=issue.code,
                title=f"Anomalia a monte ({issue.code})",
                level=level,
                message=issue.message + (f" [{issue.where}]" if issue.where else ""),
                details=issue.details,
            )
        )
    return checks
