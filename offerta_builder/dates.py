"""Gestione delle date dell'offerta.

Le date sono uno dei punti in cui le offerte sbagliano piu' spesso (``31-9-2026``
non esiste), quindi il parsing distingue sempre fra *formato non riconosciuto* e
*data impossibile*: il QA deve poter dire quale dei due problemi ha davanti.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime
from typing import Optional, Tuple

MONTHS = {
    "gen": 1, "gennaio": 1, "jan": 1, "january": 1,
    "feb": 2, "febbraio": 2, "february": 2,
    "mar": 3, "marzo": 3, "march": 3,
    "apr": 4, "aprile": 4, "april": 4,
    "mag": 5, "maggio": 5, "may": 5,
    "giu": 6, "giugno": 6, "jun": 6, "june": 6,
    "lug": 7, "luglio": 7, "jul": 7, "july": 7,
    "ago": 8, "agosto": 8, "aug": 8, "august": 8,
    "set": 9, "settembre": 9, "sep": 9, "sept": 9, "september": 9,
    "ott": 10, "ottobre": 10, "oct": 10, "october": 10,
    "nov": 11, "novembre": 11, "november": 11,
    "dic": 12, "dicembre": 12, "dec": 12, "december": 12,
}

_NUMERIC_RE = re.compile(r"^(\d{1,4})[\s./-](\d{1,2})[\s./-](\d{1,4})$")
_TEXTUAL_RE = re.compile(r"^(\d{1,2})[\s./-]*([A-Za-zàèéìòù]{3,12})[\s./-]*(\d{2,4})$")
_ISO_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_date_strict(value) -> Tuple[Optional[date], Optional[str]]:
    """Converte un testo in data.

    Ritorna ``(data, None)`` se valida, ``(None, motivo)`` altrimenti. I motivi
    possibili sono ``"vuota"``, ``"formato"`` e ``"inesistente"``.
    """
    if value is None:
        return None, "vuota"
    if isinstance(value, datetime):
        return value.date(), None
    if isinstance(value, date):
        return value, None

    text = str(value).strip()
    if not text:
        return None, "vuota"
    text = re.sub(r"\s+", " ", text)

    match = _ISO_RE.match(text)
    if match:
        return _build(int(match.group(1)), int(match.group(2)), int(match.group(3)))

    match = _NUMERIC_RE.match(text)
    if match:
        a, b, c = (int(match.group(i)) for i in (1, 2, 3))
        if a > 31:  # yyyy-mm-dd
            return _build(a, b, c)
        year = c if c > 99 else 2000 + c
        return _build(year, b, a)

    match = _TEXTUAL_RE.match(text)
    if match:
        day = int(match.group(1))
        month = MONTHS.get(match.group(2).lower()[:9]) or MONTHS.get(match.group(2).lower()[:3])
        year = int(match.group(3))
        if month is None:
            return None, "formato"
        if year < 100:
            year += 2000
        return _build(year, month, day)

    return None, "formato"


def _build(year: int, month: int, day: int) -> Tuple[Optional[date], Optional[str]]:
    if not 1 <= month <= 12:
        return None, "inesistente"
    last_day = calendar.monthrange(year, month)[1] if 1 <= month <= 12 else 31
    if not 1 <= day <= last_day:
        return None, "inesistente"
    try:
        return date(year, month, day), None
    except ValueError:
        return None, "inesistente"


def parse_date(value) -> Optional[date]:
    return parse_date_strict(value)[0]


def to_iso(value) -> str:
    parsed = parse_date(value)
    return parsed.isoformat() if parsed else ""


def to_it(value) -> str:
    """Formato italiano ``gg/mm/aaaa`` (stringa vuota se non interpretabile)."""
    parsed = parse_date(value)
    return parsed.strftime("%d/%m/%Y") if parsed else ""


def parse_period(value) -> Tuple[Optional[date], Optional[date]]:
    """Interpreta un periodo tipo ``31 Dec 2026 - 30 Dec 2027``."""
    if not value:
        return None, None
    text = re.sub(r"\s+", " ", str(value)).strip()
    parts = re.split(r"\s*(?:-|–|—|>|a\b|to\b|al\b)\s*", text, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) == 2:
        start = parse_date(parts[0])
        end = parse_date(parts[1])
        if start or end:
            return start, end
    single = parse_date(text)
    return single, None


def add_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:  # 29 febbraio
        return value.replace(year=value.year + years, day=28)
