"""Strutture comuni ai lettori di BOM (CSV, XLSX, PDF)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class RawTable:
    """Tabella grezza estratta da un file, prima della normalizzazione."""

    source: str
    fmt: str
    header: List[str] = field(default_factory=list)
    rows: List[List[str]] = field(default_factory=list)
    meta_text: str = ""
    sheet: str = ""
    score: int = 0

    def as_dicts(self) -> List[Dict[str, str]]:
        out: List[Dict[str, str]] = []
        for row in self.rows:
            record: Dict[str, str] = {}
            for idx, name in enumerate(self.header):
                if not name:
                    continue
                record[name] = row[idx] if idx < len(row) else ""
            out.append(record)
        return out


def clean_cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    text = text.replace(" ", " ").replace("\r", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_header(value: Any) -> str:
    """Chiave di confronto per gli header: minuscolo, senza punteggiatura."""
    text = clean_cell(value).lower()
    text = text.replace("à", "a").replace("è", "e").replace("é", "e")
    text = text.replace("ì", "i").replace("ò", "o").replace("ù", "u")
    text = re.sub(r"[^a-z0-9%]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_empty_row(row: List[str]) -> bool:
    return all(not clean_cell(c) for c in row)


META_PATTERNS = {
    "quote_number": [
        r"(?:quote|offerta|preventivo|quotation)\s*(?:number|no\.?|n\.?|#|id)?\s*[:#]\s*([A-Za-z0-9._/-]+)",
        r"\b(Q-\d{4,})\b",
    ],
    "end_user": [
        r"(?:end\s*user|end-user|cliente finale|utente finale|customer)\s*[:]\s*(.+)",
    ],
    "valid_until": [
        r"(?:valid(?:ity|o|a)?\s*(?:until|to|fino al|fino a)|scadenza|validit\w*)\s*[:]?\s*"
        r"([0-9]{1,2}[\s./-][A-Za-z0-9]{2,9}[\s./-][0-9]{2,4})",
    ],
    "distributor": [
        r"\b(V-?Valley|Computer\s*Gross|Esprinet|Ingram\s*Micro|TD\s*SYNNEX|Also|Attiva|Icos)\b",
    ],
    "vendor": [
        r"(?:vendor|produttore|brand|manufacturer)\s*[:]\s*(.+)",
    ],
    "currency": [
        r"(?:currency|valuta|divisa)\s*[:]\s*([A-Z]{3})",
    ],
    "offer_reference": [
        r"\b(OFF[_A-Z0-9]*[_/][0-9]{2}[/_][0-9]{3,4}(?:_R[0-9]{2})?)\b",
    ],
}


def extract_meta(text: str) -> Dict[str, str]:
    """Estrae dai testi di intestazione i dati di testata della BOM.

    Restituisce solo cio' che trova davvero: i campi assenti restano fuori dal
    dizionario, così il normalizzatore sa che deve chiederli.
    """
    meta: Dict[str, str] = {}
    if not text:
        return meta
    for key, patterns in META_PATTERNS.items():
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if not match:
                continue
            value = clean_cell(match.group(1))
            value = value.split("  ")[0].strip(" ;,")
            if value:
                meta[key] = value
                break
    return meta


def best_table(tables: List[RawTable]) -> Optional[RawTable]:
    """Sceglie la tabella più plausibile fra quelle estratte da un file."""
    scored = [t for t in tables if t.rows and t.header]
    if not scored:
        return None
    return max(scored, key=lambda t: (t.score, len(t.rows)))
