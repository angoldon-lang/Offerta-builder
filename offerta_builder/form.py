"""Form rapido: raccoglie e valida i dati che la BOM non contiene.

Il form è dichiarativo (vedi ``FIELDS``): la CLI lo usa sia per generare un
modello JSON da compilare, sia per chiedere in modo interattivo solo i campi
mancanti. Nessun campo obbligatorio viene inventato: se manca, il flusso si
ferma.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Sequence

from .dates import parse_date_strict, to_it, to_iso
from .models import SEVERITY_BLOCKING, SEVERITY_WARNING, Issue
from .money import parse_decimal

KIND_TEXT = "text"
KIND_DATE = "date"
KIND_DECIMAL = "decimal"
KIND_PERCENT = "percent"
KIND_INT = "int"
KIND_LIST = "list"
KIND_CHOICE = "choice"


@dataclass
class FieldSpec:
    name: str
    label: str
    kind: str = KIND_TEXT
    required: bool = False
    example: str = ""
    choices: Sequence[str] = ()
    # Valori proposti a tendina, ma non vincolanti: si può sempre scriverne
    # uno diverso (a differenza di ``choices``, che invece è un elenco chiuso).
    suggestions: Sequence[str] = ()
    default: Any = None
    help: str = ""


FIELDS: List[FieldSpec] = [
    # --- obbligatori -------------------------------------------------------
    FieldSpec("cliente", "Cliente", required=True, example="BPER BANCA SPA"),
    FieldSpec("piva", "P.IVA", required=True, example="03830780361"),
    FieldSpec("referente", "Referente", required=True, example="Serena Piantoni"),
    FieldSpec("oggetto", "Oggetto offerta", required=True, example="Fornitura Soluzione SolarWinds"),
    FieldSpec("autore", "Autore", required=True, example="Andrea Goldoni"),
    FieldSpec("riferimento_offerta", "Riferimento offerta", required=True, example="OFF_ADC_26/0313_R03"),
    FieldSpec("data_offerta", "Data offerta", kind=KIND_DATE, required=True, example="19/07/2026"),
    FieldSpec("validita_offerta", "Validità offerta", kind=KIND_DATE, required=True, example="31/07/2026"),
    FieldSpec(
        "tipologia_pagamento", "Tipologia pagamento", required=True, example="Bonifico bancario",
        suggestions=(
            "Bonifico bancario", "Bonifico bancario anticipato", "RiBa", "Rimessa diretta",
            "Addebito SEPA", "Carta di credito",
        ),
    ),
    FieldSpec(
        "condizioni_pagamento", "Condizioni pagamento", required=True, example="30 gg fine mese",
        suggestions=(
            "Pagamento anticipato", "30 gg data fattura", "30 gg fine mese", "60 gg data fattura",
            "60 gg fine mese", "90 gg fine mese", "50% all'ordine, 50% alla consegna",
        ),
    ),
    FieldSpec(
        "fatturazione", "Fatturazione", required=True, example="Annuale anticipata",
        suggestions=(
            "Unica soluzione all'ordine", "Annuale anticipata", "Annuale posticipata",
            "Alla consegna", "Trimestrale anticipata", "Mensile", "A stato avanzamento lavori",
        ),
    ),
    FieldSpec(
        "durata_contratto_anni", "Durata contratto (anni)", kind=KIND_INT, required=True, example="3",
        suggestions=("1", "2", "3", "4", "5"),
    ),
    FieldSpec("iva_percento", "IVA %", kind=KIND_PERCENT, required=True, default=Decimal("22"), example="22"),
    FieldSpec("margine_minimo_percento", "Margine minimo %", kind=KIND_PERCENT, required=True,
              default=Decimal("30"), example="30",
              help="Soglia di controllo: sotto viene segnalata, non blocca l'offerta"),
    # --- opzionali ---------------------------------------------------------
    FieldSpec("indirizzo_cliente", "Indirizzo cliente", example="Via San Carlo 8/20, 41121 Modena"),
    FieldSpec("email_referente", "Email referente", example="serena.piantoni@cliente.it"),
    FieldSpec("servizi_aggiuntivi", "Servizi aggiuntivi", kind=KIND_LIST,
              help="Elenco di oggetti {descrizione, quantita, prezzo_unitario, costo_unitario}"),
    FieldSpec("adeguamento_percent", "Adeguamento prezzi %", kind=KIND_DECIMAL,
              example="3", help="Ritocco sui prezzi ripresi da un'offerta precedente"),
    FieldSpec("righe_aggiuntive", "Righe libere in offerta", kind=KIND_LIST,
              help="Voci da aggiungere fra i materiali; il prezzo può essere un testo (es. Incluso)"),
    FieldSpec("requisiti_cliente", "Requisiti a carico del cliente", kind=KIND_LIST),
    FieldSpec("esclusioni", "Esclusioni", kind=KIND_LIST),
    FieldSpec("rinnovo", "Rinnovo", kind=KIND_CHOICE,
              choices=("automatico", "da concordare", "escluso"), default="da concordare"),
    FieldSpec("note_commerciali", "Note commerciali", kind=KIND_LIST,
              help="Vincoli distributore/vendor, scadenze, non svincolabilità"),
    FieldSpec("premessa", "Premessa (testo personalizzato)",
              help="Se vuota viene generata dal Content Generator"),
    FieldSpec("allegati", "Allegati", kind=KIND_LIST),
]

FIELDS_BY_NAME = {f.name: f for f in FIELDS}

DEFAULT_SERVICE_KEYS = {
    "descrizione": "",
    "quantita": 1,
    "prezzo_unitario": 0,
    "costo_unitario": 0,
    "categoria": "Servizi",
    "periodo": "",
}


def blank_form() -> Dict[str, Any]:
    """Modello di form da compilare, con esempi nei campi obbligatori."""
    data: Dict[str, Any] = {}
    for spec in FIELDS:
        if spec.kind == KIND_LIST:
            data[spec.name] = []
        elif spec.default is not None:
            data[spec.name] = str(spec.default) if isinstance(spec.default, Decimal) else spec.default
        else:
            data[spec.name] = ""
    data["servizi_aggiuntivi"] = [dict(DEFAULT_SERVICE_KEYS)]
    # Correzioni manuali riga per riga, valorizzate dall'interfaccia web.
    data["righe"] = []
    data["righe_aggiuntive"] = []
    data["pricing"] = {
        "mode": "target_margin",
        "markup_percent": 0,
        "target_margin_percent": 35,
        "rounding": "0.01",
        "overrides": [],
    }
    return data


def load_form(path: str) -> Dict[str, Any]:
    """Carica un form da JSON (o YAML, se PyYAML è installato)."""
    ext = os.path.splitext(path)[1].lower()
    with open(path, "r", encoding="utf-8") as handle:
        if ext in {".yaml", ".yml"}:
            try:
                import yaml  # type: ignore
            except ImportError as exc:  # pragma: no cover - dipende dall'ambiente
                raise RuntimeError(
                    "Form YAML richiesto ma PyYAML non è installato: usa un file .json"
                ) from exc
            return yaml.safe_load(handle) or {}
        return json.load(handle)


def save_form(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False, default=str)
        handle.write("\n")


def missing_required(data: Dict[str, Any]) -> List[FieldSpec]:
    return [spec for spec in FIELDS if spec.required and not _has_value(data.get(spec.name))]


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def prefill_from_bom(data: Dict[str, Any], boms: Sequence[Any]) -> Dict[str, Any]:
    """Propone i dati deducibili dalla BOM senza sovrascrivere quelli inseriti.

    Restano fuori le condizioni commerciali: quelle del distributore valgono fra
    distributore e rivenditore, non fra rivenditore e cliente finale.
    """
    data = dict(data)
    for bom in boms:
        if not _has_value(data.get("cliente")) and getattr(bom, "end_user", ""):
            data["cliente"] = str(bom.end_user).replace("_", " ").strip()
        if not _has_value(data.get("oggetto")) and getattr(bom, "vendor", ""):
            data["oggetto"] = f"Fornitura soluzione {bom.vendor}"
        if not _has_value(data.get("validita_offerta")) and getattr(bom, "valid_until", ""):
            data["validita_offerta"] = to_it(bom.valid_until)
    return data


def validate(data: Dict[str, Any]) -> tuple[Dict[str, Any], List[Issue]]:
    """Valida e converte i campi del form.

    Ritorna i dati puliti (date ISO + versione ``gg/mm/aaaa``, decimali come
    ``Decimal``) e l'elenco delle anomalie. Le anomalie bloccanti impediscono la
    generazione del documento.
    """
    clean: Dict[str, Any] = dict(data)
    issues: List[Issue] = []

    for spec in missing_required(data):
        issues.append(
            Issue(
                code="form.missing_required",
                severity=SEVERITY_BLOCKING,
                message=f"Campo obbligatorio mancante: {spec.label}"
                + (f" (es. {spec.example})" if spec.example else ""),
                where=spec.name,
            )
        )

    for spec in FIELDS:
        value = data.get(spec.name)
        if not _has_value(value):
            if spec.default is not None and spec.name not in data:
                clean[spec.name] = spec.default
            continue
        if spec.kind == KIND_DATE:
            parsed, error = parse_date_strict(value)
            if parsed is None:
                issues.append(
                    Issue(
                        code="form.date_invalid",
                        severity=SEVERITY_BLOCKING,
                        message=(
                            f"{spec.label}: data non valida ('{value}', motivo: {error}). "
                            "Usa il formato gg/mm/aaaa."
                        ),
                        where=spec.name,
                    )
                )
            else:
                clean[spec.name] = parsed
                clean[f"{spec.name}_iso"] = to_iso(parsed)
                clean[f"{spec.name}_it"] = to_it(parsed)
        elif spec.kind in {KIND_DECIMAL, KIND_PERCENT}:
            parsed_dec = parse_decimal(value)
            if parsed_dec is None:
                issues.append(
                    Issue(
                        code="form.number_invalid",
                        severity=SEVERITY_BLOCKING,
                        message=f"{spec.label}: valore numerico non valido ('{value}').",
                        where=spec.name,
                    )
                )
            else:
                clean[spec.name] = parsed_dec
                if spec.kind == KIND_PERCENT and not (Decimal("0") <= parsed_dec <= Decimal("100")):
                    issues.append(
                        Issue(
                            code="form.percent_out_of_range",
                            severity=SEVERITY_BLOCKING,
                            message=f"{spec.label}: percentuale fuori intervallo 0-100 ({parsed_dec}).",
                            where=spec.name,
                        )
                    )
        elif spec.kind == KIND_INT:
            parsed_dec = parse_decimal(value)
            if parsed_dec is None or parsed_dec != parsed_dec.to_integral_value() or parsed_dec <= 0:
                issues.append(
                    Issue(
                        code="form.int_invalid",
                        severity=SEVERITY_BLOCKING,
                        message=f"{spec.label}: serve un numero intero positivo (ricevuto '{value}').",
                        where=spec.name,
                    )
                )
            else:
                clean[spec.name] = int(parsed_dec)
        elif spec.kind == KIND_CHOICE and spec.choices:
            if str(value).strip().lower() not in {c.lower() for c in spec.choices}:
                issues.append(
                    Issue(
                        code="form.choice_invalid",
                        severity=SEVERITY_WARNING,
                        message=f"{spec.label}: valore '{value}' fuori dai valori previsti {list(spec.choices)}.",
                        where=spec.name,
                    )
                )

    issues.extend(_validate_piva(clean.get("piva")))
    issues.extend(_validate_dates(clean))
    issues.extend(_validate_services(clean))
    return clean, issues


def _validate_piva(value: Any) -> List[Issue]:
    if not _has_value(value):
        return []
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if len(digits) != 11:
        return [
            Issue(
                code="form.piva_length",
                severity=SEVERITY_BLOCKING,
                message=f"P.IVA non valida: attese 11 cifre, ricevute {len(digits)} ('{value}').",
                where="piva",
            )
        ]
    total = 0
    for index, char in enumerate(digits):
        digit = int(char)
        if index % 2:  # posizioni pari (1-based)
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    if total % 10 != 0:
        return [
            Issue(
                code="form.piva_checksum",
                severity=SEVERITY_WARNING,
                message=f"P.IVA {digits}: cifra di controllo non valida, verificare con il cliente.",
                where="piva",
            )
        ]
    return []


def _validate_dates(clean: Dict[str, Any]) -> List[Issue]:
    issues: List[Issue] = []
    data_offerta = clean.get("data_offerta")
    validita = clean.get("validita_offerta")
    if hasattr(data_offerta, "year") and hasattr(validita, "year"):
        if validita < data_offerta:
            issues.append(
                Issue(
                    code="form.validity_before_offer",
                    severity=SEVERITY_BLOCKING,
                    message=(
                        f"Validità offerta ({to_it(validita)}) precedente alla data offerta "
                        f"({to_it(data_offerta)})."
                    ),
                    where="validita_offerta",
                )
            )
        elif (validita - data_offerta).days > 180:
            issues.append(
                Issue(
                    code="form.validity_too_long",
                    severity=SEVERITY_WARNING,
                    message=(
                        f"Validità offerta a {(validita - data_offerta).days} giorni dalla data offerta: "
                        "verificare la coerenza con la quotazione del distributore."
                    ),
                    where="validita_offerta",
                )
            )
    return issues


def _validate_services(clean: Dict[str, Any]) -> List[Issue]:
    issues: List[Issue] = []
    services = clean.get("servizi_aggiuntivi") or []
    if not isinstance(services, list):
        return [
            Issue(
                code="form.services_format",
                severity=SEVERITY_BLOCKING,
                message="'servizi_aggiuntivi' deve essere una lista di voci.",
                where="servizi_aggiuntivi",
            )
        ]
    for index, service in enumerate(services, start=1):
        if isinstance(service, str):
            continue
        if not isinstance(service, dict):
            issues.append(
                Issue(
                    code="form.service_format",
                    severity=SEVERITY_BLOCKING,
                    message=f"Servizio #{index}: formato non valido.",
                    where="servizi_aggiuntivi",
                )
            )
            continue
        if not str(service.get("descrizione", "")).strip():
            issues.append(
                Issue(
                    code="form.service_no_description",
                    severity=SEVERITY_BLOCKING,
                    message=f"Servizio #{index}: descrizione mancante.",
                    where="servizi_aggiuntivi",
                )
            )
        if not str(service.get("prezzo_unitario", "")).strip():
            issues.append(
                Issue(
                    code="form.service_no_price",
                    severity=SEVERITY_BLOCKING,
                    message=(
                        f"Servizio '{service.get('descrizione', '#' + str(index))}': prezzo unitario "
                        "mancante. Scrivi l'importo, oppure un testo come 'Incluso' se non si fattura."
                    ),
                    where="servizi_aggiuntivi",
                )
            )
    return issues


def interactive_fill(data: Dict[str, Any], only_missing: bool = True) -> Dict[str, Any]:
    """Chiede a video i campi mancanti (usato dalla CLI in modalità guidata)."""
    filled = dict(data)
    for spec in FIELDS:
        if spec.kind == KIND_LIST:
            continue
        if only_missing and _has_value(filled.get(spec.name)):
            continue
        if only_missing and not spec.required:
            continue
        prompt = f"{spec.label}"
        if spec.example:
            prompt += f" (es. {spec.example})"
        if spec.choices:
            prompt += f" {list(spec.choices)}"
        prompt += ": "
        try:
            answer = input(prompt).strip()
        except EOFError:
            answer = ""
        if answer:
            filled[spec.name] = answer
        elif spec.default is not None:
            filled[spec.name] = spec.default
    return filled
