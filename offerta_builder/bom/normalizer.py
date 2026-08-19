"""Da tabella grezza a ``NormalizedBom``.

Regola guida: la BOM del distributore è **costo di acquisto**, mai offerta al
cliente. Qui si ricostruiscono solo i dati mancanti che sono deducibili in modo
aritmetico (netto = listino - sconto, totale = unitario x quantità); tutto cio'
che resta ambiguo diventa una ``Issue`` e ferma il flusso.
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Dict, List, Optional

from ..dates import to_iso
from ..models import (
    SEVERITY_BLOCKING,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    BomItem,
    Issue,
    NormalizedBom,
)
from ..money import format_eur, parse_decimal, q2, q4, relative_gap
from .base import best_table, clean_cell, extract_meta
from .columns import COLUMN_ALIASES
from .distributors import GENERIC, detect_distributor, detect_vendor, profile_for
from .reader import read_tables

CANONICAL_FIELDS = set(COLUMN_ALIASES.keys())
TOLERANCE = Decimal("0.02")  # 2% di scostamento fra valore letto e ricalcolato

_TOTAL_ROW_HINTS = {
    "totale", "totale generale", "total", "grand total", "subtotal", "subtotale",
    "totale offerta", "totale complessivo", "sum",
}


def normalize(
    path: str,
    distributor_hint: str = "",
    vendor_hint: str = "",
    currency_hint: str = "",
) -> NormalizedBom:
    """Legge un file BOM e lo riporta allo schema unico."""
    tables = read_tables(path)
    table = best_table(tables)
    bom = NormalizedBom(source_file=os.path.abspath(path))

    if table is None:
        bom.source_format = os.path.splitext(path)[1].lstrip(".").lower()
        bom.issues.append(
            Issue(
                code="bom.no_table",
                severity=SEVERITY_BLOCKING,
                message=(
                    "Nessuna tabella riconoscibile nel file: intestazioni non trovate. "
                    "Serve conferma manuale delle colonne (codice, quantità, netto)."
                ),
                where=path,
            )
        )
        return bom

    bom.source_format = table.fmt
    meta = extract_meta(table.meta_text)
    bom.meta = dict(meta)

    profile = (
        profile_for(distributor_hint)
        if distributor_hint
        else detect_distributor(meta.get("distributor", ""), table.meta_text, os.path.basename(path))
        or GENERIC
    )
    bom.distributor = profile.name
    bom.quote_number = meta.get("quote_number", "")
    bom.end_user = meta.get("end_user", "")
    bom.valid_until = to_iso(meta.get("valid_until", ""))
    bom.currency = (currency_hint or meta.get("currency") or profile.currency or "EUR").upper()

    records = table.as_dicts()
    body_text = " ".join(
        " ".join(str(v) for v in record.values()) for record in records[:40]
    )
    bom.vendor = vendor_hint or meta.get("vendor", "") or detect_vendor(table.meta_text, body_text)

    missing_columns = _missing_columns(table.header)
    if missing_columns:
        bom.issues.append(
            Issue(
                code="bom.missing_columns",
                severity=SEVERITY_WARNING,
                message="Colonne non riconosciute nel file: " + ", ".join(missing_columns),
                where=path,
                details={"colonne": missing_columns},
            )
        )

    line_no = 0
    for record in records:
        if _looks_like_total_row(record):
            continue
        item = _build_item(record, bom, profile.cost_priority)
        if item is None:
            continue
        line_no += 1
        item.line_no = line_no
        bom.items.append(item)

    if not bom.items:
        bom.issues.append(
            Issue(
                code="bom.no_items",
                severity=SEVERITY_BLOCKING,
                message="Nessuna riga articolo estratta dalla BOM: verifica il file o le colonne.",
                where=path,
            )
        )

    if not bom.valid_until:
        bom.issues.append(
            Issue(
                code="bom.no_validity",
                severity=SEVERITY_WARNING,
                message=(
                    "Validità della quotazione distributore non trovata: va confermata "
                    "manualmente prima di fissare la validità dell'offerta."
                ),
                where=path,
            )
        )
    if not bom.quote_number:
        bom.issues.append(
            Issue(
                code="bom.no_quote_number",
                severity=SEVERITY_INFO,
                message="Numero quotazione distributore non trovato nel file.",
                where=path,
            )
        )
    return bom


def _missing_columns(header: List[str]) -> List[str]:
    """Intestazioni presenti nel file ma non mappate su un campo canonico."""
    return [h for h in header if h and h not in CANONICAL_FIELDS]


def _looks_like_total_row(record: Dict[str, str]) -> bool:
    description = clean_cell(record.get("description", "")).lower()
    sku = clean_cell(record.get("sku", ""))
    if description in _TOTAL_ROW_HINTS and not sku:
        return True
    joined = " ".join(clean_cell(v).lower() for k, v in record.items() if k in {"sku", "description", "category"})
    return joined.strip() in _TOTAL_ROW_HINTS


def _build_item(record: Dict[str, str], bom: NormalizedBom, cost_priority: str) -> Optional[BomItem]:
    sku = clean_cell(record.get("sku", ""))
    description = clean_cell(record.get("description", ""))
    if not sku and not description:
        return None

    item = BomItem(
        sku=sku,
        description=description,
        category=clean_cell(record.get("category", "")),
        period=clean_cell(record.get("period", "")),
        notes=clean_cell(record.get("notes", "")),
        currency=(clean_cell(record.get("currency", "")) or bom.currency).upper(),
        source_row=dict(record),
    )

    quantity = parse_decimal(record.get("quantity"))
    if quantity is None:
        item.quantity = Decimal("1")
        bom.issues.append(
            Issue(
                code="bom.quantity_missing",
                severity=SEVERITY_WARNING,
                message=f"Quantità assente per '{item.key()}': assunta 1, da confermare.",
                where=f"riga {item.key()}",
            )
        )
    elif quantity <= 0:
        item.quantity = Decimal("1")
        bom.issues.append(
            Issue(
                code="bom.quantity_invalid",
                severity=SEVERITY_BLOCKING,
                message=f"Quantità non valida ({quantity}) per '{item.key()}'.",
                where=f"riga {item.key()}",
            )
        )
    else:
        item.quantity = quantity

    item.list_price_unit = parse_decimal(record.get("list_price_unit"))
    item.list_price_total = parse_decimal(record.get("list_price_total"))
    item.discount_percent = parse_decimal(record.get("discount_percent"))
    item.cost_net_unit = parse_decimal(record.get("cost_net_unit"))
    item.cost_net_total = parse_decimal(record.get("cost_net_total"))

    _derive_amounts(item, bom, cost_priority)
    return item


def _derive_amounts(item: BomItem, bom: NormalizedBom, cost_priority: str) -> None:
    """Completa gli importi mancanti e segnala le incoerenze."""
    qty = item.quantity or Decimal("1")
    where = f"riga {item.line_no or item.key()}"

    # Listino: unitario <-> totale.
    if item.list_price_unit is not None and item.list_price_total is None:
        item.list_price_total = q2(item.list_price_unit * qty)
    elif item.list_price_total is not None and item.list_price_unit is None and qty:
        item.list_price_unit = q2(item.list_price_total / qty)
    elif item.list_price_unit is not None and item.list_price_total is not None:
        expected = q2(item.list_price_unit * qty)
        if relative_gap(expected, item.list_price_total) > TOLERANCE:
            bom.issues.append(
                Issue(
                    code="bom.list_mismatch",
                    severity=SEVERITY_WARNING,
                    message=(
                        f"Totale listino incoerente per '{item.key()}': "
                        f"letto {format_eur(item.list_price_total)}, atteso {format_eur(expected)}."
                    ),
                    where=where,
                    details={"letto": item.list_price_total, "atteso": expected},
                )
            )

    # Costo: unitario <-> totale, con priorità da profilo distributore.
    if item.cost_net_unit is not None and item.cost_net_total is None:
        item.cost_net_total = q2(item.cost_net_unit * qty)
    elif item.cost_net_total is not None and item.cost_net_unit is None and qty:
        item.cost_net_unit = q2(item.cost_net_total / qty)
    elif item.cost_net_unit is not None and item.cost_net_total is not None:
        expected = q2(item.cost_net_unit * qty)
        if relative_gap(expected, item.cost_net_total) > TOLERANCE:
            authoritative = "totale" if cost_priority == "total" else "unitario"
            bom.issues.append(
                Issue(
                    code="bom.cost_mismatch",
                    severity=SEVERITY_WARNING,
                    message=(
                        f"Netto incoerente per '{item.key()}': unitario x quantità = {format_eur(expected)}, "
                        f"totale in BOM = {format_eur(item.cost_net_total)}. "
                        f"Considerato autorevole il {authoritative}."
                    ),
                    where=where,
                    details={"unitario_per_qta": expected, "totale_bom": item.cost_net_total},
                )
            )
            if cost_priority == "total":
                item.cost_net_unit = q2(item.cost_net_total / qty)
            else:
                item.cost_net_total = expected

    # Costo ricavabile da listino + sconto.
    if item.cost_net_total is None and item.list_price_total is not None and item.discount_percent is not None:
        item.cost_net_total = q2(item.list_price_total * (Decimal("100") - item.discount_percent) / Decimal("100"))
        item.cost_net_unit = q2(item.cost_net_total / qty) if qty else None

    # Sconto ricavabile da listino + netto.
    if item.discount_percent is None and item.list_price_total and item.cost_net_total is not None:
        item.discount_percent = q4(
            (Decimal("1") - item.cost_net_total / item.list_price_total) * Decimal("100")
        )
    elif (
        item.discount_percent is not None
        and item.list_price_total
        and item.cost_net_total is not None
    ):
        expected = q2(item.list_price_total * (Decimal("100") - item.discount_percent) / Decimal("100"))
        if relative_gap(expected, item.cost_net_total) > TOLERANCE:
            bom.issues.append(
                Issue(
                    code="bom.discount_mismatch",
                    severity=SEVERITY_WARNING,
                    message=(
                        f"Sconto incoerente per '{item.key()}': con {item.discount_percent}% il netto "
                        f"sarebbe {format_eur(expected)}, in BOM è {format_eur(item.cost_net_total)}."
                    ),
                    where=where,
                    details={"netto_atteso": expected, "netto_bom": item.cost_net_total},
                )
            )

    if item.cost_net_total is None:
        bom.issues.append(
            Issue(
                code="bom.cost_missing",
                severity=SEVERITY_BLOCKING,
                message=(
                    f"Costo di acquisto assente per '{item.key()}': servono netto unitario, "
                    "netto totale oppure listino + sconto."
                ),
                where=where,
            )
        )
    elif item.cost_net_total < 0:
        bom.issues.append(
            Issue(
                code="bom.cost_negative",
                severity=SEVERITY_BLOCKING,
                message=f"Costo negativo per '{item.key()}': {format_eur(item.cost_net_total)}.",
                where=where,
            )
        )
