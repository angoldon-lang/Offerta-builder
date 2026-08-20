"""Schema dati unico dell'Offer Builder.

Il flusso è sempre: BOM del distributore -> ``NormalizedBom`` (costo di
acquisto) -> ``PricedOffer`` (prezzo cliente calcolato dal motore commerciale).
Nessun modulo a valle inventa numeri: legge solo quello che c'è qui dentro.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from decimal import Decimal
from typing import Any, Dict, List, Optional

SEVERITY_BLOCKING = "blocking"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


@dataclass
class Issue:
    """Anomalia rilevata durante import, pricing o QA."""

    code: str
    message: str
    severity: str = SEVERITY_WARNING
    where: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def blocking(self) -> bool:
        return self.severity == SEVERITY_BLOCKING

    def to_dict(self) -> Dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass
class BomItem:
    """Riga di BOM normalizzata: la parte 'costo' è quella del distributore."""

    line_no: int = 0
    sku: str = ""
    description: str = ""
    category: str = ""
    period: str = ""
    quantity: Decimal = Decimal("1")
    list_price_unit: Optional[Decimal] = None
    list_price_total: Optional[Decimal] = None
    discount_percent: Optional[Decimal] = None
    cost_net_unit: Optional[Decimal] = None
    cost_net_total: Optional[Decimal] = None
    currency: str = "EUR"
    notes: str = ""
    source_row: Dict[str, Any] = field(default_factory=dict)

    # Valorizzati dal motore commerciale (mai dall'import, mai dall'AI).
    sell_net_unit: Optional[Decimal] = None
    sell_net_total: Optional[Decimal] = None
    vat_percent: Optional[Decimal] = None
    vat_total: Optional[Decimal] = None
    sell_gross_total: Optional[Decimal] = None
    margin_value: Optional[Decimal] = None
    margin_percent: Optional[Decimal] = None
    pricing_mode: str = ""
    # Posizione nella lista completa delle righe importate: e' la chiave con cui
    # l'interfaccia identifica una riga da modificare.
    source_index: int = -1
    source_reference: str = ""
    edited: bool = False

    def key(self) -> str:
        return self.sku or self.description[:60]

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop("source_row", None)
        return _json_safe(data)


@dataclass
class NormalizedBom:
    """Una BOM distributore, qualunque fosse il formato di partenza."""

    distributor: str = ""
    vendor: str = ""
    quote_number: str = ""
    end_user: str = ""
    valid_until: str = ""
    currency: str = "EUR"
    source_file: str = ""
    source_format: str = ""
    items: List[BomItem] = field(default_factory=list)
    issues: List[Issue] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def blocking_issues(self) -> List[Issue]:
        return [i for i in self.issues if i.blocking]

    def total_cost(self) -> Decimal:
        return sum((i.cost_net_total or Decimal("0") for i in self.items), Decimal("0"))

    def total_list(self) -> Decimal:
        return sum((i.list_price_total or Decimal("0") for i in self.items), Decimal("0"))

    def to_dict(self) -> Dict[str, Any]:
        return _json_safe(
            {
                "distributor": self.distributor,
                "vendor": self.vendor,
                "quote_number": self.quote_number,
                "end_user": self.end_user,
                "valid_until": self.valid_until,
                "currency": self.currency,
                "source_file": self.source_file,
                "source_format": self.source_format,
                "meta": self.meta,
                "items": [i.to_dict() for i in self.items],
                "issues": [i.to_dict() for i in self.issues],
            }
        )


@dataclass
class ServiceLine:
    """Servizio aggiuntivo AD (installazione, PM, supporto, canone...)."""

    description: str
    quantity: Decimal = Decimal("1")
    unit_price: Decimal = Decimal("0")
    unit_cost: Decimal = Decimal("0")
    category: str = "Servizi"
    period: str = ""
    notes: str = ""


@dataclass
class OfferTotals:
    total_list: Decimal = Decimal("0")
    total_cost: Decimal = Decimal("0")
    total_net: Decimal = Decimal("0")
    total_vat: Decimal = Decimal("0")
    total_gross: Decimal = Decimal("0")
    margin_value: Decimal = Decimal("0")
    margin_percent: Decimal = Decimal("0")
    average_discount_percent: Decimal = Decimal("0")

    def to_dict(self) -> Dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass
class AnnualBreakdown:
    label: str
    total_net: Decimal
    total_cost: Decimal
    total_vat: Decimal
    total_gross: Decimal

    def to_dict(self) -> Dict[str, Any]:
        return _json_safe(asdict(self))


@dataclass
class PricedOffer:
    """Risultato del motore commerciale: è l'unica fonte di verità numerica."""

    offer: Dict[str, Any] = field(default_factory=dict)
    items: List[BomItem] = field(default_factory=list)
    totals: OfferTotals = field(default_factory=OfferTotals)
    annual: List[AnnualBreakdown] = field(default_factory=list)
    boms: List[NormalizedBom] = field(default_factory=list)
    excluded: List[BomItem] = field(default_factory=list)
    issues: List[Issue] = field(default_factory=list)
    content: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return _json_safe(
            {
                "offer": self.offer,
                "totals": self.totals.to_dict(),
                "annual": [a.to_dict() for a in self.annual],
                "items": [i.to_dict() for i in self.items],
                "excluded": [i.to_dict() for i in self.excluded],
                "boms": [b.to_dict() for b in self.boms],
                "issues": [i.to_dict() for i in self.issues],
                "content": self.content,
            }
        )
