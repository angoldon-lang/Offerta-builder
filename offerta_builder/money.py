"""Parsing e formattazione di importi/percentuali.

Tutti i calcoli monetari del progetto usano ``Decimal``: nessun float entra mai
nel motore commerciale, così i totali sono riproducibili al centesimo.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Optional, Union

Number = Union[str, int, float, Decimal, None]

CENT = Decimal("0.01")
RATE = Decimal("0.0001")

NBSP = " "
THIN_SPACE = " "
_CLEAN_RE = re.compile(r"[^0-9,.\-+]")


def parse_decimal(value: Number) -> Optional[Decimal]:
    """Converte un valore in ``Decimal`` accettando formati IT ed EN.

    Gestisce ``"1.234,56"``, ``"1,234.56"``, ``"9.749,30 EUR"``, ``"66,02%"``,
    ``"(1.200,00)"`` (negativo contabile). Restituisce ``None`` se il valore è
    vuoto o non interpretabile: il chiamante decide se è un dato mancante.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return Decimal(str(value))

    text = str(value).strip()
    if not text:
        return None

    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]

    text = text.replace(NBSP, "").replace(THIN_SPACE, "").replace(" ", "")
    text = _CLEAN_RE.sub("", text)
    if not text or text in {"-", "+", ".", ","}:
        return None

    if text.startswith("-"):
        negative = not negative
    text = text.lstrip("+-")

    last_dot = text.rfind(".")
    last_comma = text.rfind(",")

    if last_dot >= 0 and last_comma >= 0:
        # L'ultimo separatore presente è quello decimale.
        if last_comma > last_dot:
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif last_comma >= 0:
        groups = text.split(",")
        if len(groups) > 2 and all(len(g) == 3 for g in groups[1:]):
            text = text.replace(",", "")  # 1,234,567 -> separatore di migliaia
        else:
            text = text.replace(",", ".")
    elif last_dot >= 0:
        groups = text.split(".")
        if len(groups) > 2 and all(len(g) == 3 for g in groups[1:]):
            text = text.replace(".", "")  # 1.234.567 -> separatore di migliaia
        elif len(groups) == 2 and len(groups[1]) == 3 and 0 < len(groups[0]) <= 3:
            # Ambiguo (es. "1.234"): in un contesto IT sono migliaia.
            text = text.replace(".", "")

    try:
        result = Decimal(text)
    except InvalidOperation:
        return None
    return -result if negative else result


def q2(value: Number) -> Decimal:
    """Arrotonda a due decimali (half-up, come la prassi contabile)."""
    dec = parse_decimal(value)
    if dec is None:
        dec = Decimal("0")
    return dec.quantize(CENT, rounding=ROUND_HALF_UP)


def q4(value: Number) -> Decimal:
    """Arrotonda a quattro decimali: usato per percentuali e tassi."""
    dec = parse_decimal(value)
    if dec is None:
        dec = Decimal("0")
    return dec.quantize(RATE, rounding=ROUND_HALF_UP)


def close_enough(a: Optional[Decimal], b: Optional[Decimal], tolerance: Decimal = CENT) -> bool:
    """Confronto tollerante fra due importi (default: un centesimo)."""
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= tolerance


def relative_gap(a: Optional[Decimal], b: Optional[Decimal]) -> Decimal:
    """Scostamento relativo fra due importi, 0 se coincidono."""
    if a is None or b is None:
        return Decimal("0")
    if a == b:
        return Decimal("0")
    base = max(abs(a), abs(b))
    if base == 0:
        return Decimal("0")
    return abs(a - b) / base


def format_eur(value: Number, symbol: str = "EUR") -> str:
    """Formatta un importo in stile italiano: ``12.186,93 EUR``."""
    amount = q2(value)
    negative = amount < 0
    digits = f"{abs(amount):,.2f}"
    digits = digits.replace(",", "|").replace(".", ",").replace("|", ".")
    sign = "-" if negative else ""
    return f"{sign}{digits} {symbol}".strip()


def format_percent(value: Number, decimals: int = 2) -> str:
    """Formatta una percentuale in stile italiano: ``66,02%``."""
    dec = parse_decimal(value)
    if dec is None:
        return ""
    text = f"{dec:.{decimals}f}".replace(".", ",")
    return f"{text}%"


def format_number(value: Number, decimals: int = 0) -> str:
    dec = parse_decimal(value)
    if dec is None:
        return ""
    text = f"{dec:,.{decimals}f}"
    return text.replace(",", "|").replace(".", ",").replace("|", ".")
