"""Dizionario degli alias di colonna usati dalle BOM dei distributori.

Sia il lettore (per capire quale riga e' l'intestazione) sia il normalizzatore
(per mappare le colonne sullo schema unico) partono da qui.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from .base import normalize_header

# campo canonico -> alias (gia' normalizzati con normalize_header)
COLUMN_ALIASES: Dict[str, List[str]] = {
    "sku": [
        "sku", "codice", "cod", "cod art", "codice articolo", "codice prodotto",
        "part number", "part no", "partnumber", "p n", "pn", "mpn", "item",
        "item number", "articolo", "material", "vendor part", "vendor sku",
        "codice fornitore", "product code", "manufacturer part number",
    ],
    "description": [
        "descrizione", "description", "desc", "descrizione articolo",
        "descrizione prodotto", "product description", "product", "denominazione",
        "item description", "nome prodotto", "prodotto",
    ],
    "quantity": [
        "qty", "q ty", "qta", "q ta", "quantita", "quantity", "pz", "pezzi",
        "n pezzi", "num", "units", "unita",
    ],
    "list_price_unit": [
        "listino unitario", "prezzo listino", "prezzo di listino", "prezzo listino unitario",
        "list price", "unit list price", "list unit price", "msrp", "srp",
        "prezzo unitario listino", "listino", "list", "unit price list",
    ],
    "list_price_total": [
        "totale listino", "listino totale", "list total", "extended list",
        "extended list price", "total list price", "importo listino",
        "totale prezzo listino",
    ],
    "discount_percent": [
        "sconto", "sconto %", "sconto perc", "sconto percentuale", "discount",
        "discount %", "disc", "disc %", "discount percent", "percentuale sconto",
        "% sconto", "% discount",
    ],
    "cost_net_unit": [
        "netto unitario", "prezzo netto unitario", "prezzo netto", "net price",
        "net unit price", "unit net price", "unit net", "costo unitario",
        "prezzo acquisto", "acquisto unitario", "dealer price", "reseller price",
        "unit cost", "buy price",
    ],
    "cost_net_total": [
        "totale netto", "netto totale", "net total", "extended net",
        "extended net price", "total net price", "importo netto", "costo totale",
        "totale acquisto", "total cost", "net amount", "importo", "totale",
        "total", "amount",
    ],
    "period": [
        "periodo", "period", "durata", "term", "coverage", "coverage term",
        "coverage period", "subscription term", "validity period", "date range",
        "service period", "da a",
    ],
    "category": [
        "categoria", "category", "tipo", "tipologia", "type", "line type",
        "product type", "famiglia", "family",
    ],
    "currency": ["valuta", "currency", "divisa", "cur", "ccy"],
    "vendor": ["vendor", "produttore", "brand", "marca", "manufacturer", "costruttore"],
    "notes": ["note", "notes", "commenti", "comment", "remarks", "osservazioni"],
}

_LOOKUP: Dict[str, str] = {}
for _canonical, _aliases in COLUMN_ALIASES.items():
    for _alias in _aliases:
        _LOOKUP.setdefault(normalize_header(_alias), _canonical)

# Alias che, da soli, non bastano a dire "questa e' la riga di intestazione".
_WEAK = {"totale", "total", "importo", "amount", "listino", "list", "num", "type", "tipo"}

# Campi che rendono credibile un'intestazione di BOM.
_STRONG_FIELDS = {"sku", "description", "quantity", "list_price_unit",
                  "cost_net_unit", "cost_net_total", "discount_percent"}


def map_header(cells: List[str]) -> Tuple[Dict[int, str], int]:
    """Mappa le celle di una possibile riga di intestazione sui campi canonici.

    Restituisce ``(indice colonna -> campo, punteggio)``. Il punteggio serve a
    scegliere fra piu' righe/tabelle candidate: piu' alto = intestazione piu'
    credibile.
    """
    mapping: Dict[int, str] = {}
    score = 0
    used: set[str] = set()
    for idx, cell in enumerate(cells):
        key = normalize_header(cell)
        if not key:
            continue
        canonical = _LOOKUP.get(key)
        if canonical is None:
            # match parziale: "prezzo di listino unitario (EUR)" -> list_price_unit
            candidates = [
                (alias, field_name)
                for alias, field_name in _LOOKUP.items()
                if len(alias) >= 4 and (alias in key or key in alias)
            ]
            if len(candidates) == 1:
                canonical = candidates[0][1]
            elif candidates:
                alias, canonical = max(candidates, key=lambda c: len(c[0]))
        if canonical is None or canonical in used:
            continue
        mapping[idx] = canonical
        used.add(canonical)
        if key in _WEAK:
            score += 1
        elif canonical in _STRONG_FIELDS:
            score += 3
        else:
            score += 2
    if not _STRONG_FIELDS & used:
        score = 0
    return mapping, score
