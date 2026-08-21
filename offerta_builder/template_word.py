"""Compilazione di un template Word **senza segnaposto**.

Il modello AD è un documento normale, scritto a mano in Word: la tabella
dell'offerta economica ha le sue etichette (``[descrizione di dettaglio]``,
``TOTALE MATERIALI``, ``Netto a Voi Riservato``), le condizioni di vendita sono
una tabella etichetta/valore, la copertina sta in caselle di testo.

Questo modulo riconosce quelle etichette e ci scrive dentro i dati dell'offerta,
conservando stili, colori e formattazione del modello. Nessun segnaposto da
inserire: si carica il Word così com'è.

Chi preferisce i segnaposto Jinja continua a usarli: il generatore sceglie da
solo la strada in base al template (vedi ``docx_builder.render``).
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# --- copertina: etichetta nel testo -> campo del contesto -------------------
ETICHETTE_COPERTINA = [
    ("offerta per", "cliente"),
    ("spett.le", "cliente"),
    ("p.iva", "piva"),
    ("alla c.a. di", "referente"),
    ("autore:", "autore"),
    ("rif:", "riferimento_offerta"),
    ("la presente offerta è valida fino al", "validita_offerta"),
]
TESTO_DATA_VUOTA = "fare clic o toccare qui per immettere una data"
SOLO_DATA = re.compile(r"^\s*\d{1,2}/\d{1,2}/\d{2,4}\s*$")
RIEMPITIVO = re.compile(r"[_\s]{3,}$")

# --- condizioni di vendita: etichetta di riga -> campo ----------------------
ETICHETTE_CONDIZIONI = [
    ("tipologia di pagamento", "tipologia_pagamento"),
    ("condizioni di pagamento", "condizioni_pagamento"),
    ("fatturazione", "fatturazione"),
    ("validità contratto", "durata_contratto"),
    ("validità offerta", "validita_offerta"),
    ("rinnovo", "rinnovo"),
]

# --- tabella economica ------------------------------------------------------
RIGA_DETTAGLIO = "descrizione di dettaglio"
RIGA_GENERICA_PRODOTTI = "descrizione generica prodotti"
RIGA_GENERICA_SERVIZI = "descrizione generica servizi"
RIGA_TOTALE_PRODOTTI = "totale materiali"
RIGA_TOTALE_SERVIZI = "totale servizi"
RIGA_TOTALE_OFFERTA = ("netto a voi riservato", "totale offerta", "totale generale")

SEGNAPOSTO_OGGETTO = ("[descrizione]", "[oggetto]")
PUNTO_ELENCO_VUOTO = ("…", "...")


def recognized_sections(template_path: str) -> List[str]:
    """Sezioni che il compilatore sa riconoscere in questo template.

    Serve a dirlo prima di generare: un modello riconosciuto si carica com'è,
    uno sconosciuto va corredato di segnaposto.
    """
    from docx import Document

    try:
        documento = Document(template_path)
    except Exception:  # pragma: no cover - file non leggibile
        return []

    sezioni: List[str] = []
    etichette = [etichetta for etichetta, _ in ETICHETTE_COPERTINA]
    for paragrafo in _paragrafi_caselle(documento):
        testo = paragrafo.text.strip().lower()
        if any(testo.startswith(etichetta) for etichetta in etichette):
            sezioni.append("copertina")
            break

    if _trova_tabella_economica(documento) is not None:
        sezioni.append("offerta economica")

    for tabella in documento.tables:
        for riga in tabella.rows:
            celle = _celle_distinte(riga)
            if len(celle) >= 2 and any(
                celle[0].text.strip().lower().startswith(chiave)
                for chiave, _ in ETICHETTE_CONDIZIONI
            ):
                sezioni.append("condizioni di vendita")
                break
        if "condizioni di vendita" in sezioni:
            break

    for paragrafo in documento.paragraphs:
        testo = paragrafo.text.strip()
        if testo.lower() in SEGNAPOSTO_OGGETTO or testo in PUNTO_ELENCO_VUOTO:
            sezioni.append("oggetto, requisiti ed esclusioni")
            break
    return sezioni


def fill_document(template_path: str, context: Dict[str, Any], output_path: str) -> List[str]:
    """Compila il template riconoscendo le etichette. Ritorna cosa ha riempito."""
    from docx import Document

    documento = Document(template_path)
    fatti: List[str] = []

    if _compila_copertina(documento, context):
        fatti.append("copertina")
    if _compila_tabella_economica(documento, context):
        fatti.append("offerta economica")
    if _compila_condizioni(documento, context):
        fatti.append("condizioni di vendita")
    if _compila_paragrafi(documento, context):
        fatti.append("oggetto, premessa, requisiti ed esclusioni")

    documento.save(output_path)
    return fatti


# ---------------------------------------------------------------------------
# Testo: si scrive nel primo run, così la formattazione del modello resta.
# ---------------------------------------------------------------------------

def _scrivi(paragrafo, testo: str) -> None:
    if paragrafo.runs:
        paragrafo.runs[0].text = testo
        for run in paragrafo.runs[1:]:
            run.text = ""
    else:
        paragrafo.add_run(testo)


def _scrivi_cella(cella, testo: str) -> None:
    _scrivi(cella.paragraphs[0], testo)
    for extra in cella.paragraphs[1:]:
        _scrivi(extra, "")


def _celle_distinte(riga) -> List[Any]:
    viste = set()
    distinte = []
    for cella in riga.cells:
        if id(cella._tc) in viste:
            continue
        viste.add(id(cella._tc))
        distinte.append(cella)
    return distinte


def _testo_riga(riga) -> str:
    return " ".join(cella.text for cella in _celle_distinte(riga)).strip().lower()


def _clona_riga(tabella, modello, valori: List[str], prima: bool = True):
    from docx.table import _Row

    nuovo = copy.deepcopy(modello._tr)
    if prima:
        modello._tr.addprevious(nuovo)
    else:
        modello._tr.addnext(nuovo)
    riga = _Row(nuovo, tabella)
    celle = _celle_distinte(riga)
    for indice, cella in enumerate(celle):
        _scrivi_cella(cella, valori[indice] if indice < len(valori) else "")
    return riga


def _elimina_riga(riga) -> None:
    riga._tr.getparent().remove(riga._tr)


# ---------------------------------------------------------------------------
# Copertina (caselle di testo)
# ---------------------------------------------------------------------------

def _paragrafi_caselle(documento):
    from docx.text.paragraph import Paragraph

    for casella in documento.element.body.iter(f"{W_NS}txbxContent"):
        for elemento in casella.iter(f"{W_NS}p"):
            yield Paragraph(elemento, documento)


def _compila_copertina(documento, context: Dict[str, Any]) -> bool:
    scritto = False
    data_fatta = False
    for paragrafo in _paragrafi_caselle(documento):
        for run in paragrafo.runs:
            testo = run.text
            spoglio = testo.strip().lower()
            if not spoglio:
                continue

            if spoglio.startswith(TESTO_DATA_VUOTA):
                run.text = str(context.get("validita_offerta", ""))
                scritto = True
                continue
            if SOLO_DATA.match(testo) and not data_fatta:
                run.text = str(context.get("data_offerta", "")) or testo
                data_fatta = scritto = True
                continue

            for etichetta, campo in ETICHETTE_COPERTINA:
                valore = str(context.get(campo, "")).strip()
                if not valore or not spoglio.startswith(etichetta):
                    continue
                coda = testo.strip()[len(etichetta):]
                if coda.strip() and not RIEMPITIVO.match(coda):
                    break  # la riga contiene già un valore: non si tocca
                run.text = f"{testo.strip()[:len(etichetta)]} {valore}"
                scritto = True
                break
    return scritto


# ---------------------------------------------------------------------------
# Tabella dell'offerta economica
# ---------------------------------------------------------------------------

def _indice_riga(tabella, *etichette: str) -> Optional[int]:
    for indice, riga in enumerate(tabella.rows):
        testo = _testo_riga(riga)
        if any(etichetta in testo for etichetta in etichette):
            return indice
    return None


def _trova_tabella_economica(documento):
    for tabella in documento.tables:
        testo = " ".join(_testo_riga(riga) for riga in tabella.rows)
        if RIGA_DETTAGLIO in testo or RIGA_TOTALE_OFFERTA[0] in testo:
            return tabella
    return None


def _compila_tabella_economica(documento, context: Dict[str, Any]) -> bool:
    tabella = _trova_tabella_economica(documento)
    if tabella is None:
        return False

    prodotti = context.get("prodotti") or []
    servizi = context.get("servizi") or []

    # I due blocchi hanno la stessa forma: riga generica, righe di dettaglio,
    # totale. Si compilano dal fondo, così gli indici a monte restano validi.
    blocchi = [
        (RIGA_GENERICA_SERVIZI, RIGA_TOTALE_SERVIZI, servizi, context.get("nota_servizi", ""),
         context.get("totale_servizi", "")),
        (RIGA_GENERICA_PRODOTTI, RIGA_TOTALE_PRODOTTI, prodotti, context.get("oggetto", ""),
         context.get("totale_prodotti", "")),
    ]

    dettagli = [
        indice for indice, riga in enumerate(tabella.rows)
        if RIGA_DETTAGLIO in _testo_riga(riga)
    ]

    for posizione, (etichetta_generica, etichetta_totale, righe, testo_generico, totale) in enumerate(blocchi):
        modello_indice = dettagli[-1 - posizione] if len(dettagli) > posizione else None
        if modello_indice is None:
            continue
        modello = tabella.rows[modello_indice]

        if righe:
            for riga in righe:
                _clona_riga(tabella, modello, [
                    riga.get("descrizione_completa") or riga.get("descrizione", ""),
                    riga.get("quantita", ""),
                    riga.get("totale", ""),
                ])
        _elimina_riga(modello)

        indice_generica = _indice_riga(tabella, etichetta_generica)
        if indice_generica is not None:
            if righe:
                _scrivi_cella(_celle_distinte(tabella.rows[indice_generica])[0], str(testo_generico))
            else:
                _elimina_riga(tabella.rows[indice_generica])

        indice_totale = _indice_riga(tabella, etichetta_totale)
        if indice_totale is not None:
            if righe:
                _scrivi_cella(_celle_distinte(tabella.rows[indice_totale])[-1], str(totale))
            else:
                _elimina_riga(tabella.rows[indice_totale])

    indice_offerta = _indice_riga(tabella, *RIGA_TOTALE_OFFERTA)
    if indice_offerta is not None:
        _scrivi_cella(
            _celle_distinte(tabella.rows[indice_offerta])[-1],
            str(context.get("totale_imponibile", "")),
        )
    return True


# ---------------------------------------------------------------------------
# Condizioni di vendita
# ---------------------------------------------------------------------------

def _compila_condizioni(documento, context: Dict[str, Any]) -> bool:
    scritto = False
    for tabella in documento.tables:
        for riga in tabella.rows:
            celle = _celle_distinte(riga)
            if len(celle) < 2:
                continue
            etichetta = celle[0].text.strip().lower()
            for chiave, campo in ETICHETTE_CONDIZIONI:
                if not etichetta.startswith(chiave):
                    continue
                valore = str(context.get(campo, "")).strip()
                if valore:
                    _scrivi_cella(celle[1], valore)
                    scritto = True
                break
    return scritto


# ---------------------------------------------------------------------------
# Oggetto, premessa, requisiti, esclusioni
# ---------------------------------------------------------------------------

def _sezione_corrente(paragrafi, indice: int) -> str:
    for precedente in reversed(paragrafi[:indice]):
        stile = (precedente.style.name if precedente.style is not None else "").lower()
        if stile.startswith("heading") and precedente.text.strip():
            return precedente.text.strip().lower()
    return ""


def _espandi_elenco(paragrafo, voci: List[str]) -> None:
    """Sostituisce un punto elenco segnaposto con una voce per riga."""
    from docx.text.paragraph import Paragraph

    if not voci:
        _scrivi(paragrafo, "")
        return
    _scrivi(paragrafo, str(voci[0]))
    riferimento = paragrafo
    for voce in voci[1:]:
        nuovo = copy.deepcopy(paragrafo._p)
        riferimento._p.addnext(nuovo)
        riferimento = Paragraph(nuovo, paragrafo._parent)
        _scrivi(riferimento, str(voce))


def _compila_paragrafi(documento, context: Dict[str, Any]) -> bool:
    paragrafi = list(documento.paragraphs)
    scritto = False

    for indice, paragrafo in enumerate(paragrafi):
        testo = paragrafo.text.strip()
        spoglio = testo.lower()
        stile = (paragrafo.style.name if paragrafo.style is not None else "").lower()

        if spoglio in SEGNAPOSTO_OGGETTO:
            _scrivi(paragrafo, str(context.get("oggetto", "")))
            scritto = True
        elif testo in PUNTO_ELENCO_VUOTO:
            sezione = _sezione_corrente(paragrafi, indice)
            if sezione.startswith("requisiti") and "esclusioni" not in sezione:
                _espandi_elenco(paragrafo, context.get("requisiti") or [])
            elif sezione.startswith("esclusioni"):
                _espandi_elenco(paragrafo, context.get("esclusioni") or [])
            else:
                _scrivi(paragrafo, str(context.get("descrizione_fornitura", "")))
            scritto = True
        elif stile.startswith("heading") and spoglio == "premessa":
            successivo = paragrafi[indice + 1] if indice + 1 < len(paragrafi) else None
            if successivo is not None and not successivo.text.strip():
                _scrivi(successivo, str(context.get("premessa", "")))
                scritto = True
    return scritto
