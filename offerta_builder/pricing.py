"""Motore commerciale: dal costo di acquisto al prezzo cliente.

Tutti i numeri dell'offerta nascono qui e solo qui. L'AI non entra in questo
modulo: può scrivere testi, non prezzi. Le modalità supportate sono tre e si
possono combinare per riga:

* ``markup``        - ricarico sul costo (``prezzo = costo * (1 + markup%)``)
* ``target_margin`` - margine obiettivo sul venduto (``prezzo = costo / (1 - margine%)``)
* ``manual``        - prezzo deciso a mano, per riga
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from .dates import parse_period, to_it
from .models import (
    SEVERITY_BLOCKING,
    SEVERITY_WARNING,
    AnnualBreakdown,
    BomItem,
    Issue,
    NormalizedBom,
    OfferTotals,
    PricedOffer,
    ServiceLine,
)
from .money import format_percent, q2, q4

MODE_MARKUP = "markup"
MODE_TARGET_MARGIN = "target_margin"
MODE_MANUAL = "manual"
MODE_RINNOVO = "rinnovo"
MODES = {MODE_MARKUP, MODE_TARGET_MARGIN, MODE_MANUAL}

ROUNDING_STEPS = {
    "none": None,
    "0.01": Decimal("0.01"),
    "0.05": Decimal("0.05"),
    "1": Decimal("1"),
    "5": Decimal("5"),
    "10": Decimal("10"),
    "100": Decimal("100"),
}


@dataclass
class LineOverride:
    """Deroga puntuale su una riga, individuata per SKU o testo descrizione."""

    match: str
    mode: str = ""
    markup_percent: Optional[Decimal] = None
    target_margin_percent: Optional[Decimal] = None
    sell_net_unit: Optional[Decimal] = None
    sell_net_total: Optional[Decimal] = None
    vat_percent: Optional[Decimal] = None


@dataclass
class LineEdit:
    """Modifica manuale su una riga dell'offerta, individuata per posizione.

    Le righe si possono correggere una per una (descrizione, quantità, prezzo)
    o togliere dall'offerta. Il riferimento serve da controllo: se la riga in
    quella posizione non è più quella, la modifica viene ignorata invece di
    finire sulla riga sbagliata.
    """

    index: int
    reference: str = ""
    sku: str = ""
    description: str = ""
    quantity: Optional[Decimal] = None
    sell_net_unit: Optional[Decimal] = None
    exclude: bool = False

    def matches(self, item: BomItem) -> bool:
        if not self.reference:
            return True
        atteso = self.reference.strip().lower()
        return atteso in (item.sku or "").lower() or atteso in (item.description or "").lower()


@dataclass
class PricingPolicy:
    mode: str = MODE_MARKUP
    markup_percent: Decimal = Decimal("0")
    target_margin_percent: Decimal = Decimal("0")
    vat_percent: Decimal = Decimal("22")
    min_margin_percent: Decimal = Decimal("30")
    rounding: str = "0.01"
    contract_years: int = 1
    # Ritocco dei prezzi ripresi da un'offerta precedente (rinnovo).
    renewal_adjustment_percent: Decimal = Decimal("0")
    overrides: List[LineOverride] = field(default_factory=list)
    line_edits: List[LineEdit] = field(default_factory=list)
    services: List[ServiceLine] = field(default_factory=list)

    def edit_for(self, index: int, item: BomItem) -> Optional[LineEdit]:
        for edit in self.line_edits:
            if edit.index == index and edit.matches(item):
                return edit
        return None

    def override_for(self, item: BomItem) -> Optional[LineOverride]:
        for override in self.overrides:
            needle = (override.match or "").strip().lower()
            if not needle:
                continue
            if needle == item.sku.lower() or needle in item.description.lower():
                return override
        return None


def _round_step(value: Decimal, rounding: str) -> Decimal:
    step = ROUNDING_STEPS.get(rounding, Decimal("0.01"))
    if step is None:
        return q2(value)
    if step == Decimal("0.01"):
        return q2(value)
    return (value / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * step


def price_offer(
    boms: List[NormalizedBom],
    policy: PricingPolicy,
    offer: Optional[Dict[str, Any]] = None,
) -> PricedOffer:
    """Applica la politica commerciale a tutte le righe e calcola i totali."""
    result = PricedOffer(offer=dict(offer or {}), boms=list(boms))

    if policy.mode not in MODES:
        result.issues.append(
            Issue(
                code="pricing.mode_unknown",
                severity=SEVERITY_BLOCKING,
                message=f"Modalità di prezzo sconosciuta: '{policy.mode}'. Ammesse: {sorted(MODES)}.",
            )
        )
        return result

    indice = 0
    for bom in boms:
        for original in bom.items:
            # Si lavora su una copia: le righe normalizzate restano quelle lette
            # dal file, cosi' le modifiche manuali non si accumulano fra un
            # ricalcolo e l'altro.
            item = replace(original)
            item.source_index = indice
            item.source_reference = (original.sku or original.description or "")[:40]
            edit = policy.edit_for(indice, item)
            indice += 1
            if edit is not None:
                _apply_edit(item, edit)
                if edit.exclude:
                    result.excluded.append(item)
                    continue
            result.items.append(_price_line(item, policy, result, edit))

    for service in policy.services:
        servizio = _price_service(service, policy, result)
        servizio.source_index = indice
        indice += 1
        result.items.append(servizio)

    result.totals = _totals(result.items)
    result.annual = _annual_breakdown(result.items, policy)
    _check_thresholds(result, policy)
    return result


def _apply_edit(item: BomItem, edit: LineEdit) -> None:
    """Riporta sulla riga le correzioni fatte a mano prima del calcolo."""
    if edit.sku:
        item.sku = edit.sku
    if edit.description:
        item.description = edit.description
    if edit.quantity is not None and edit.quantity > 0 and edit.quantity != item.quantity:
        item.quantity = edit.quantity
        # Cambiando la quantità cambia anche il costo di acquisto della riga.
        if item.cost_net_unit is not None:
            item.cost_net_total = q2(item.cost_net_unit * edit.quantity)
        if item.list_price_unit is not None:
            item.list_price_total = q2(item.list_price_unit * edit.quantity)
    item.edited = bool(edit.sku or edit.description or edit.quantity is not None or edit.sell_net_unit is not None)


def _price_line(
    item: BomItem,
    policy: PricingPolicy,
    result: PricedOffer,
    edit: Optional[LineEdit] = None,
) -> BomItem:
    override = policy.override_for(item)
    mode = (override.mode if override and override.mode else policy.mode)
    qty = item.quantity or Decimal("1")
    cost_total = item.cost_net_total if item.cost_net_total is not None else Decimal("0")
    vat_percent = (
        override.vat_percent if override and override.vat_percent is not None else policy.vat_percent
    )

    sell_unit: Optional[Decimal] = None
    if item.previous_price_total is not None and (edit is None or edit.sell_net_unit is None):
        # Rinnovo: si parte dal prezzo dell'offerta precedente, con l'eventuale
        # adeguamento deciso dall'operatore.
        prezzo = item.previous_price_total * (
            Decimal("100") + policy.renewal_adjustment_percent
        ) / Decimal("100")
        sell_unit = prezzo / qty if qty else prezzo
        mode = MODE_RINNOVO
    elif edit is not None and edit.sell_net_unit is not None:
        # Il prezzo scritto a mano sulla riga vince su qualunque politica.
        sell_unit = edit.sell_net_unit
        mode = MODE_MANUAL
    elif override and override.sell_net_unit is not None:
        sell_unit = override.sell_net_unit
        mode = MODE_MANUAL
    elif override and override.sell_net_total is not None and qty:
        sell_unit = override.sell_net_total / qty
        mode = MODE_MANUAL
    elif mode == MODE_MARKUP:
        markup = override.markup_percent if override and override.markup_percent is not None else policy.markup_percent
        cost_unit = item.cost_net_unit if item.cost_net_unit is not None else (cost_total / qty if qty else Decimal("0"))
        sell_unit = cost_unit * (Decimal("1") + markup / Decimal("100"))
    elif mode == MODE_TARGET_MARGIN:
        margin = (
            override.target_margin_percent
            if override and override.target_margin_percent is not None
            else policy.target_margin_percent
        )
        if margin >= Decimal("100"):
            result.issues.append(
                Issue(
                    code="pricing.margin_invalid",
                    severity=SEVERITY_BLOCKING,
                    message=f"Margine obiettivo {margin}% non applicabile (deve essere < 100%).",
                    where=f"riga {item.line_no} - {item.key()}",
                )
            )
            margin = Decimal("0")
        cost_unit = item.cost_net_unit if item.cost_net_unit is not None else (cost_total / qty if qty else Decimal("0"))
        sell_unit = cost_unit / (Decimal("1") - margin / Decimal("100"))
    elif mode == MODE_MANUAL:
        result.issues.append(
            Issue(
                code="pricing.manual_missing",
                severity=SEVERITY_BLOCKING,
                message=(
                    f"Modalità manuale senza prezzo per '{item.key()}': indica sell_net_unit "
                    "o sell_net_total nelle deroghe di riga."
                ),
                where=f"riga {item.line_no} - {item.key()}",
            )
        )
        sell_unit = Decimal("0")

    item.pricing_mode = mode
    item.sell_net_unit = _round_step(sell_unit or Decimal("0"), policy.rounding)
    item.sell_net_total = q2(item.sell_net_unit * qty)
    item.vat_percent = q2(vat_percent)
    item.vat_total = q2(item.sell_net_total * vat_percent / Decimal("100"))
    item.sell_gross_total = q2(item.sell_net_total + item.vat_total)
    if item.cost_net_total is None:
        # Senza costo il margine non si può calcolare: meglio lasciarlo vuoto
        # che scrivere 100%.
        item.margin_value = None
        item.margin_percent = None
    else:
        item.margin_value = q2(item.sell_net_total - cost_total)
        item.margin_percent = (
            q4(item.margin_value / item.sell_net_total * Decimal("100"))
            if item.sell_net_total
            else Decimal("0")
        )
    return item


def _price_service(service: ServiceLine, policy: PricingPolicy, result: PricedOffer) -> BomItem:
    qty = service.quantity or Decimal("1")
    item = BomItem(
        line_no=0,
        sku="",
        description=service.description,
        category=service.category or "Servizi",
        period=service.period,
        quantity=qty,
        cost_net_unit=q2(service.unit_cost),
        cost_net_total=q2(service.unit_cost * qty),
        notes=service.notes,
    )
    item.pricing_mode = "servizio" if service.block != "prodotti" else "riga_libera"
    item.display_price = service.display_price
    item.sell_net_unit = q2(service.unit_price)
    item.sell_net_total = q2(item.sell_net_unit * qty)
    item.vat_percent = q2(policy.vat_percent)
    item.vat_total = q2(item.sell_net_total * policy.vat_percent / Decimal("100"))
    item.sell_gross_total = q2(item.sell_net_total + item.vat_total)
    item.margin_value = q2(item.sell_net_total - (item.cost_net_total or Decimal("0")))
    item.margin_percent = (
        q4(item.margin_value / item.sell_net_total * Decimal("100")) if item.sell_net_total else Decimal("0")
    )
    if item.sell_net_total == 0 and not service.display_price:
        # Una voce marcata "Incluso" e' voluta: l'avviso vale solo per lo zero
        # lasciato per distrazione.
        result.issues.append(
            Issue(
                code="pricing.service_zero",
                severity=SEVERITY_WARNING,
                message=f"Voce '{service.description}' valorizzata a zero: confermare se è inclusa.",
            )
        )
    return item


def _totals(items: List[BomItem]) -> OfferTotals:
    totals = OfferTotals()
    totals.rows_without_cost = sum(
        1 for item in items if item.cost_net_total is None and item.sell_net_total
    )
    for item in items:
        totals.total_list += item.list_price_total or Decimal("0")
        totals.total_cost += item.cost_net_total or Decimal("0")
        totals.total_net += item.sell_net_total or Decimal("0")
        totals.total_vat += item.vat_total or Decimal("0")
    totals.total_list = q2(totals.total_list)
    totals.total_cost = q2(totals.total_cost)
    totals.total_net = q2(totals.total_net)
    totals.total_vat = q2(totals.total_vat)
    totals.total_gross = q2(totals.total_net + totals.total_vat)
    if totals.rows_without_cost:
        # Costi ignoti (offerta rinnovata): un margine calcolato sui costi
        # mancanti direbbe 100%, che è peggio di non dirlo.
        totals.margin_value = Decimal("0")
        totals.margin_percent = Decimal("0")
    else:
        totals.margin_value = q2(totals.total_net - totals.total_cost)
        totals.margin_percent = (
            q4(totals.margin_value / totals.total_net * Decimal("100")) if totals.total_net else Decimal("0")
        )
    totals.average_discount_percent = (
        q4((Decimal("1") - totals.total_cost / totals.total_list) * Decimal("100"))
        if totals.total_list
        else Decimal("0")
    )
    return totals


def _annual_breakdown(items: List[BomItem], policy: PricingPolicy) -> List[AnnualBreakdown]:
    """Riepilogo per annualità: per periodo se presente, altrimenti per durata."""
    grouped: Dict[str, List[BomItem]] = {}
    for item in items:
        if item.period:
            start, end = parse_period(item.period)
            label = (
                f"{to_it(start)} - {to_it(end)}" if start and end else item.period
            )
        else:
            label = "Senza periodo indicato"
        grouped.setdefault(label, []).append(item)

    periodic = [label for label in grouped if label != "Senza periodo indicato"]
    if periodic:
        breakdown = []
        for label in sorted(grouped, key=lambda l: (l == "Senza periodo indicato", l)):
            group = grouped[label]
            net = q2(sum((i.sell_net_total or Decimal("0") for i in group), Decimal("0")))
            cost = q2(sum((i.cost_net_total or Decimal("0") for i in group), Decimal("0")))
            vat = q2(sum((i.vat_total or Decimal("0") for i in group), Decimal("0")))
            breakdown.append(
                AnnualBreakdown(label=label, total_net=net, total_cost=cost, total_vat=vat, total_gross=q2(net + vat))
            )
        return breakdown

    totals = _totals(items)
    years = max(1, int(policy.contract_years or 1))
    if years == 1:
        return [
            AnnualBreakdown(
                label="Totale contratto",
                total_net=totals.total_net,
                total_cost=totals.total_cost,
                total_vat=totals.total_vat,
                total_gross=totals.total_gross,
            )
        ]

    breakdown = []
    net_left, cost_left, vat_left = totals.total_net, totals.total_cost, totals.total_vat
    for year in range(1, years + 1):
        if year < years:
            net = q2(totals.total_net / years)
            cost = q2(totals.total_cost / years)
            vat = q2(totals.total_vat / years)
        else:  # l'ultima annualità assorbe gli arrotondamenti
            net, cost, vat = net_left, cost_left, vat_left
        net_left, cost_left, vat_left = q2(net_left - net), q2(cost_left - cost), q2(vat_left - vat)
        breakdown.append(
            AnnualBreakdown(
                label=f"Annualità {year} di {years}",
                total_net=net,
                total_cost=cost,
                total_vat=vat,
                total_gross=q2(net + vat),
            )
        )
    return breakdown


def _check_thresholds(result: PricedOffer, policy: PricingPolicy) -> None:
    threshold = policy.min_margin_percent
    if threshold <= 0 or not result.totals.margin_known:
        return  # senza costi il margine non è confrontabile con la soglia
    # Se e' l'intera offerta a stare sotto soglia basta dirlo una volta: elencare
    # anche tutte le righe seppellirebbe le altre segnalazioni.
    if result.totals.margin_percent < threshold:
        result.issues.append(
            Issue(
                code="pricing.total_margin_below_threshold",
                severity=SEVERITY_WARNING,
                message=(
                    f"Margine totale offerta al {format_percent(result.totals.margin_percent)}, "
                    f"sotto la soglia minima del {format_percent(threshold)}: da valutare."
                ),
                details={"margine": result.totals.margin_percent, "soglia": threshold},
            )
        )
        return
    for item in result.items:
        if item.sell_net_total and item.margin_percent is not None and item.margin_percent < threshold:
            result.issues.append(
                Issue(
                    code="pricing.margin_below_threshold",
                    severity=SEVERITY_WARNING,
                    message=(
                        f"Margine riga '{item.key()}' al {format_percent(item.margin_percent)}, "
                        f"sotto la soglia minima del {format_percent(threshold)}."
                    ),
                    where=f"riga {item.line_no or '-'} - {item.key()}",
                    details={"margine": item.margin_percent, "soglia": threshold},
                )
            )

