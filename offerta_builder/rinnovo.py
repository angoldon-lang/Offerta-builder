"""Rinnovo di un'offerta esistente.

Un'offerta scaduta contiene già tutto: cliente, referente, oggetto, righe e
condizioni. Invece di ricompilare il form da zero, il documento viene riletto e
i dati tornano dentro il flusso normale, pronti per essere aggiornati (date,
riferimento, eventuale adeguamento dei prezzi) e rigenerati sul template
corrente.

Il documento di partenza può essere un'offerta prodotta da questo programma o
scritta a mano in Word: si riconoscono le stesse etichette che il generatore usa
per compilare (vedi ``template_word``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from .dates import parse_date, to_it
from .models import SEVERITY_WARNING, BomItem, Issue, NormalizedBom
from .money import parse_decimal, q2
from .template_word import (
    ETICHETTE_CONDIZIONI,
    RIGA_TOTALE_OFFERTA,
    _celle_distinte,
    _paragrafi_caselle,
)

# Etichette di copertina: prefisso da togliere -> campo del form.
COPERTINA = [
    ("spett.le", "cliente"),
    ("p.iva", "piva"),
    ("alla c.a. di", "referente"),
    ("autore:", "autore"),
    ("rif:", "riferimento_offerta"),
]
VALIDITA_COPERTINA = "la presente offerta è valida fino al"
SOLO_DATA = re.compile(r"^\s*(\d{1,2}/\d{1,2}/\d{2,4})\s*$")
RIGA_DA_SALTARE = re.compile(
    r"^(totale|subtotale|netto a voi riservato|descrizione)\b", re.IGNORECASE
)
REVISIONE = re.compile(r"(_R)(\d{1,2})$", re.IGNORECASE)

# Copertina scritta come tabella etichetta/valore (template con segnaposto).
COPERTINA_TABELLA = [
    ("cliente", "cliente"),
    ("p.iva", "piva"),
    ("partita iva", "piva"),
    ("indirizzo", "indirizzo_cliente"),
    ("referente", "referente"),
    ("riferimento offerta", "riferimento_offerta"),
    ("data offerta", "data_offerta"),
    ("validita offerta", "validita_offerta"),
    ("autore", "autore"),
    ("oggetto", "oggetto"),
]
CONDIZIONI_EXTRA = [("durata contratto", "durata_contratto")]


def _norm(testo: str) -> str:
    """Etichetta confrontabile: minuscola, senza accenti né apostrofi."""
    testo = (testo or "").strip().lower()
    for accentata, piana in (("à", "a"), ("è", "e"), ("é", "e"), ("ì", "i"), ("ò", "o"), ("ù", "u")):
        testo = testo.replace(accentata, piana)
    return testo.replace("'", "").replace("’", "")


@dataclass
class OffertaImportata:
    """Dati recuperati da un'offerta precedente."""

    form: Dict[str, Any] = field(default_factory=dict)
    righe: List[Dict[str, Any]] = field(default_factory=list)
    totale: Optional[Decimal] = None
    issues: List[Issue] = field(default_factory=list)
    source_file: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "form": self.form,
            "righe": self.righe,
            "totale": str(self.totale) if self.totale is not None else "",
            "anomalie": [i.to_dict() for i in self.issues],
            "file": self.source_file,
        }


def read_offer(docx_path: str) -> OffertaImportata:
    """Rilegge un'offerta Word e ne recupera dati, righe e condizioni."""
    import os

    from docx import Document

    risultato = OffertaImportata(source_file=os.path.basename(docx_path))
    documento = Document(docx_path)

    _leggi_copertina(documento, risultato)
    _leggi_oggetto(documento, risultato)
    _leggi_condizioni(documento, risultato)
    _leggi_righe(documento, risultato)

    if not risultato.righe:
        risultato.issues.append(
            Issue(
                code="rinnovo.nessuna_riga",
                severity=SEVERITY_WARNING,
                message=(
                    "Nessuna riga riconosciuta nella tabella economica: verifica il documento "
                    "oppure inserisci le voci a mano."
                ),
                where=risultato.source_file,
            )
        )
    return risultato


# ---------------------------------------------------------------------------
# Lettura delle singole parti
# ---------------------------------------------------------------------------

def _pulisci(valore: str) -> str:
    return re.sub(r"[\s_]+$", "", (valore or "").strip()).strip(" :")


def _leggi_copertina(documento, risultato: OffertaImportata) -> None:
    visti: set[str] = set()
    for paragrafo in _paragrafi_caselle(documento):
        testo = paragrafo.text.strip()
        spoglio = testo.lower()
        if not testo:
            continue

        if spoglio.startswith(VALIDITA_COPERTINA):
            valore = _pulisci(testo[len(VALIDITA_COPERTINA):])
            if parse_date(valore):
                risultato.form.setdefault("validita_offerta", to_it(valore))
            continue

        for etichetta, campo in COPERTINA:
            if campo in visti or not spoglio.startswith(etichetta):
                continue
            valore = _pulisci(testo[len(etichetta):])
            if valore:
                risultato.form[campo] = valore
                visti.add(campo)
            break

        match = SOLO_DATA.match(testo)
        if match and "data_offerta" not in risultato.form:
            risultato.form["data_offerta"] = to_it(match.group(1))


def _leggi_oggetto(documento, risultato: OffertaImportata) -> None:
    paragrafi = list(documento.paragraphs)
    for indice, paragrafo in enumerate(paragrafi):
        stile = (paragrafo.style.name if paragrafo.style is not None else "").lower()
        if not stile.startswith(("heading", "titolo")) or paragrafo.text.strip().lower() != "oggetto":
            continue
        for successivo in paragrafi[indice + 1: indice + 6]:
            testo = successivo.text.strip()
            stile_succ = (successivo.style.name if successivo.style is not None else "").lower()
            if stile_succ.startswith(("heading", "titolo")):
                break
            if testo and len(testo) < 200 and not testo.startswith("["):
                risultato.form.setdefault("oggetto", testo)
                return


def _leggi_condizioni(documento, risultato: OffertaImportata) -> None:
    for tabella in documento.tables:
        for riga in tabella.rows:
            celle = _celle_distinte(riga)
            if len(celle) < 2:
                continue
            etichetta = _norm(celle[0].text)
            valore = celle[1].text.strip()
            if not valore:
                continue
            for chiave, campo in list(ETICHETTE_CONDIZIONI) + CONDIZIONI_EXTRA + COPERTINA_TABELLA:
                if not etichetta.startswith(_norm(chiave)):
                    continue
                if campo == "data_offerta":
                    if parse_date(valore):
                        risultato.form["data_offerta"] = to_it(valore)
                    break
                if campo == "durata_contratto":
                    anni = parse_decimal(re.sub(r"[^0-9,.]", " ", valore).strip().split(" ")[0])
                    if anni and anni > 0:
                        risultato.form.setdefault("durata_contratto_anni", int(anni))
                elif campo == "validita_offerta":
                    if parse_date(valore):
                        risultato.form["validita_offerta"] = to_it(valore)
                else:
                    risultato.form.setdefault(campo, valore)
                break


def _colonne(intestazione: List[str]) -> Dict[str, int]:
    """Individua le colonne utili dall'intestazione della tabella economica."""
    colonne: Dict[str, int] = {}
    for indice, testo in enumerate(intestazione):
        etichetta = _norm(testo)
        if "descrizione" in etichetta and "descrizione" not in colonne:
            colonne["descrizione"] = indice
        elif etichetta.startswith(("codice", "sku", "part")) and "codice" not in colonne:
            colonne["codice"] = indice
        elif etichetta.startswith(("q.ta", "qta", "quantita", "q,ta", "q ta")) and "quantita" not in colonne:
            colonne["quantita"] = indice
        elif "totale" in etichetta and "prezzo" not in colonne:
            colonne["prezzo"] = indice
    if "prezzo" not in colonne:
        for indice, testo in enumerate(intestazione):
            if "prezzo" in _norm(testo):
                colonne["prezzo"] = indice
    colonne.setdefault("descrizione", 0)
    colonne.setdefault("prezzo", len(intestazione) - 1)
    return colonne


def _leggi_righe(documento, risultato: OffertaImportata) -> None:
    for tabella in documento.tables:
        if not tabella.rows:
            continue
        intestazione = [cella.text.strip() for cella in _celle_distinte(tabella.rows[0])]
        unito = _norm(" ".join(intestazione))
        if "descrizione" not in unito or ("prezzo" not in unito and "totale" not in unito):
            continue
        colonne = _colonne(intestazione)

        for riga in tabella.rows[1:]:
            celle = _celle_distinte(riga)
            testi = [cella.text.strip() for cella in celle]
            if not any(testi):
                continue

            descrizione = testi[colonne["descrizione"]] if colonne["descrizione"] < len(testi) else ""
            prima = testi[0]
            if RIGA_DA_SALTARE.match(prima) or RIGA_DA_SALTARE.match(descrizione):
                if _norm(prima).startswith(RIGA_TOTALE_OFFERTA) or _norm(prima).startswith("totale offerta"):
                    risultato.totale = parse_decimal(testi[-1])
                continue
            if len(celle) < 3 or not descrizione:
                continue  # riga di raggruppamento a tutta larghezza

            quantita = parse_decimal(_valore(testi, colonne.get("quantita"))) or Decimal("1")
            prezzo_testo = _valore(testi, colonne.get("prezzo")) or testi[-1]
            prezzo = parse_decimal(prezzo_testo)
            risultato.righe.append(
                {
                    "codice": _valore(testi, colonne.get("codice")),
                    "descrizione": descrizione,
                    "quantita": str(quantita),
                    "prezzo_totale": str(q2(prezzo)) if prezzo is not None else "",
                    # "Incluso" e simili si conservano come sono.
                    "prezzo_testo": "" if prezzo is not None else prezzo_testo,
                }
            )
        if risultato.righe:
            return


def _valore(testi: List[str], indice: Optional[int]) -> str:
    if indice is None or indice >= len(testi):
        return ""
    return testi[indice]


# ---------------------------------------------------------------------------
# Aggiornamento per il rinnovo
# ---------------------------------------------------------------------------

def prossima_revisione(riferimento: str) -> str:
    """``OFF_ADC_26/0441_R00`` -> ``OFF_ADC_26/0441_R01``."""
    match = REVISIONE.search(riferimento or "")
    if not match:
        return riferimento
    numero = int(match.group(2)) + 1
    return REVISIONE.sub(f"{match.group(1)}{numero:0{len(match.group(2))}d}", riferimento)


def aggiorna_per_rinnovo(
    importata: OffertaImportata,
    giorni_validita: int = 30,
    oggi: Optional[date] = None,
    nuova_revisione: bool = True,
) -> Dict[str, Any]:
    """Prepara il form del rinnovo: date di oggi e riferimento incrementato."""
    oggi = oggi or date.today()
    form = dict(importata.form)
    form["data_offerta"] = to_it(oggi)
    form["validita_offerta"] = to_it(oggi + timedelta(days=max(1, giorni_validita)))
    if nuova_revisione and form.get("riferimento_offerta"):
        form["riferimento_offerta"] = prossima_revisione(form["riferimento_offerta"])
    return form


def bom_da_offerta(importata: OffertaImportata) -> NormalizedBom:
    """Trasforma le righe rilette in una "BOM" con i prezzi della vecchia offerta.

    Il costo di acquisto non è scritto in offerta: resta ignoto, e il margine non
    viene calcolato finché non si carica una BOM aggiornata. L'eventuale
    adeguamento dei prezzi si applica al momento del calcolo, così si può
    cambiare senza rileggere il documento.
    """
    bom = NormalizedBom(
        distributor="Offerta precedente",
        source_file=importata.source_file,
        source_format="docx",
    )
    for numero, riga in enumerate(importata.righe, start=1):
        quantita = parse_decimal(riga.get("quantita")) or Decimal("1")
        prezzo = parse_decimal(riga.get("prezzo_totale"))
        item = BomItem(
            line_no=numero,
            sku=str(riga.get("codice", "")),
            description=str(riga.get("descrizione", "")),
            quantity=quantita,
            notes="da offerta precedente",
        )
        if prezzo is not None:
            item.previous_price_total = q2(prezzo)
        item.display_price = str(riga.get("prezzo_testo") or "")
        bom.items.append(item)

    return bom
