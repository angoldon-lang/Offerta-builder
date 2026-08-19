"""Motore commerciale: dal costo di acquisto al prezzo cliente.

Tutti i numeri dell'offerta nascono qui e solo qui. L'AI non entra in questo
modulo: puo' scrivere testi, non prezzi. Le modalita' supportate sono tre e si
possono combinare per riga:

* ``markup``        - ricarico sul costo (``prezzo = costo * (1 + markup%)``)
* ``target_margin`` - margine obiettivo sul venduto (``prezzo = costo / (1 - margine%)``)
* ``manual``        - prezzo deciso a mano, per riga
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
from .money import q2, q4

MODE_MARKUP = "markup"
MODE_TARGET_MARGIN = "target_margin"
MODE_MANUAL = "manual"
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
class PricingPolicy:
    mode: str = MODE_MARKUP
    markup_percent: Decimal = Decimal("0")
    target_margin_percent: Decimal = Decimal("0")
    vat_percent: Decimal = Decimal("22")
    min_margin_percent: Decimal = Decimal("30")
    rounding: str = "0.01"
    contract_years: int = 1
    overrides: List[LineOverride] = field(default_factory=list)
    services: List[ServiceLine] = field(default_factory=list)

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
                message=f"Modalita' di prezzo sconosciuta: '{policy.mode}'. Ammesse: {sorted(MODES)}.",
            )
        )
        return result

    for bom in boms:
        for item in bom.items:
            priced = _price_line(item, policy, result)
            result.items.append(priced)

    for service in policy.services:
        result.items.append(_price_service(service, policy, result))

    result.totals = _totals(result.items)
    result.annual = _annual_breakdown(result.items, policy)
    _check_thresholds(result, policy)
    return result


def _price_line(item: BomItem, policy: PricingPolicy, result: PricedOffer) -> BomItem:
    override = policy.override_for(item)
    mode = (override.mode if override and override.mode else policy.mode)
    qty = item.quantity or Decimal("1")
    cost_total = item.cost_net_total if item.cost_net_total is not None else Decimal("0")
    vat_percent = (
        override.vat_percent if override and override.vat_percent is not None else policy.vat_percent
    )

    sell_unit: Optional[Decimal] = None
    if override and override.sell_net_unit is not None:
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
                    f"Modalita' manuale senza prezzo per '{item.key()}': indica sell_net_unit "
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
    item.pricing_mode = "servizio"
    item.sell_net_unit = q2(service.unit_price)
    item.sell_net_total = q2(item.sell_net_unit * qty)
    item.vat_percent = q2(policy.vat_percent)
    item.vat_total = q2(item.sell_net_total * policy.vat_percent / Decimal("100"))
    item.sell_gross_total = q2(item.sell_net_total + item.vat_total)
    item.margin_value = q2(item.sell_net_total - (item.cost_net_total or Decimal("0")))
    item.margin_percent = (
        q4(item.margin_value / item.sell_net_total * Decimal("100")) if item.sell_net_total else Decimal("0")
    )
    if item.sell_net_total == 0:
        result.issues.append(
            Issue(
                code="pricing.service_zero",
                severity=SEVERITY_WARNING,
                message=f"Servizio '{service.description}' valorizzato a zero: confermare se e' incluso.",
            )
        )
    return item


def _totals(items: List[BomItem]) -> OfferTotals:
    totals = OfferTotals()
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
    """Riepilogo per annualita': per periodo se presente, altrimenti per durata."""
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
        else:  # l'ultima annualita' assorbe gli arrotondamenti
            net, cost, vat = net_left, cost_left, vat_left
        net_left, cost_left, vat_left = q2(net_left - net), q2(cost_left - cost), q2(vat_left - vat)
        breakdown.append(
            AnnualBreakdown(
                label=f"Annualita' {year} di {years}",
                total_net=net,
                total_cost=cost,
                total_vat=vat,
                total_gross=q2(net + vat),
            )
        )
    return breakdown


def _check_thresholds(result: PricedOffer, policy: PricingPolicy) -> None:
    threshold = policy.min_margin_percent
    if threshold <= 0:
        return
    for item in result.items:
        if item.sell_net_total and item.margin_percent is not None and item.margin_percent < threshold:
            result.issues.append(
                Issue(
                    code="pricing.margin_below_threshold",
                    severity=SEVERITY_WARNING,
                    message=(
                        f"Margine riga '{item.key()}' al {item.margin_percent}%, "
                        f"sotto la soglia minima del {threshold}%."
                    ),
                    where=f"riga {item.line_no or '-'} - {item.key()}",
                    details={"margine": item.margin_percent, "soglia": threshold},
                )
            )
    if result.totals.margin_percent < threshold:
        result.issues.append(
            Issue(
                code="pricing.total_margin_below_threshold",
                severity=SEVERITY_BLOCKING,
                message=(
                    f"Margine totale offerta al {result.totals.margin_percent}%, "
                    f"sotto la soglia minima del {threshold}%: serve approvazione esplicita."
                ),
                details={"margine": result.totals.margin_percent, "soglia": threshold},
            )
        )
