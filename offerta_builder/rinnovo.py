"""Rinnovo di un'offerta esistente.

Un'offerta scaduta contiene già tutto: cliente, referente, oggetto, righe e
condizioni. Invece di ricompilare il form da zero, il documento viene riletto e
i dati tornano dentro il flusso normale, pronti per essere aggiornati (date,
riferimento, eventuale adeguamento dei prezzi) e rigenerati sul template
corrente.

Si legge il **DOCX**, il **PDF** (l'offerta come è stata inviata al cliente) e i
formati vecchi di Word (``.doc``, ``.rtf``, ``.odt``), convertiti al volo se sul
computer c'è LibreOffice. Quello che conta non è il formato ma la struttura:
righe di testo per la copertina, tabelle per righe e condizioni.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .dates import parse_date, to_it
from .models import SEVERITY_BLOCKING, SEVERITY_WARNING, BomItem, Issue, NormalizedBom
from .money import parse_decimal, q2
from .template_word import ETICHETTE_CONDIZIONI, _celle_distinte, _paragrafi_caselle

FORMATI_DIRETTI = {".docx", ".pdf"}
FORMATI_DA_CONVERTIRE = {".doc", ".rtf", ".odt"}
FORMATI_SUPPORTATI = FORMATI_DIRETTI | FORMATI_DA_CONVERTIRE

# Copertina: prefisso della riga -> campo del form.
COPERTINA = [
    ("spett.le", "cliente"),
    ("p.iva", "piva"),
    ("partita iva", "piva"),
    ("alla c.a. di", "referente"),
    ("c.a. di", "referente"),
    ("autore:", "autore"),
    ("rif:", "riferimento_offerta"),
    ("riferimento:", "riferimento_offerta"),
]
VALIDITA_COPERTINA = ("la presente offerta e valida fino al", "offerta valida fino al")
DATA_COPERTINA = re.compile(r"^[A-Za-zàèéìòù' ]{0,20}[–-]\s*(\d{1,2}/\d{1,2}/\d{2,4})\s*$")
SOLO_DATA = re.compile(r"^\s*(\d{1,2}/\d{1,2}/\d{2,4})\s*$")
INTESTAZIONE_OFFERTA = "offerta per"

# Copertina scritta come tabella etichetta/valore.
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

RIGA_DA_SALTARE = re.compile(
    r"^(totale|subtotale|netto a voi riservato|descrizione|imponibile|iva\b)", re.IGNORECASE
)
RIGHE_TOTALE = ("netto a voi riservato", "totale offerta", "totale generale", "totale")
REVISIONE = re.compile(r"(_R)(\d{1,2})$", re.IGNORECASE)


def _norm(testo: str) -> str:
    """Etichetta confrontabile: minuscola, senza accenti né apostrofi."""
    testo = (testo or "").strip().lower()
    for accentata, piana in (("à", "a"), ("è", "e"), ("é", "e"), ("ì", "i"), ("ò", "o"), ("ù", "u")):
        testo = testo.replace(accentata, piana)
    return re.sub(r"\s+", " ", testo.replace("'", "").replace("’", ""))


@dataclass
class OffertaImportata:
    """Dati recuperati da un'offerta precedente."""

    form: Dict[str, Any] = field(default_factory=dict)
    righe: List[Dict[str, Any]] = field(default_factory=list)
    totale: Optional[Decimal] = None
    issues: List[Issue] = field(default_factory=list)
    source_file: str = ""
    source_format: str = ""
    # Percorso del DOCX utilizzabile come modello: il file stesso, oppure la
    # conversione dei formati Word vecchi.
    template_path: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "form": self.form,
            "righe": self.righe,
            "totale": str(self.totale) if self.totale is not None else "",
            "anomalie": [i.to_dict() for i in self.issues],
            "file": self.source_file,
            "formato": self.source_format,
        }


@dataclass
class _Contenuto:
    """Il documento ridotto a quello che serve: righe di testo e tabelle."""

    linee: List[str] = field(default_factory=list)
    tabelle: List[List[List[str]]] = field(default_factory=list)
    # (testo del titolo, testo del paragrafo seguente): solo per i DOCX.
    sezioni: List[Tuple[str, List[str]]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Ingresso
# ---------------------------------------------------------------------------

def read_offer(docx_path: str) -> OffertaImportata:
    """Rilegge un'offerta (DOCX, PDF o Word vecchio) e ne recupera i dati."""
    estensione = os.path.splitext(docx_path)[1].lower()
    risultato = OffertaImportata(
        source_file=os.path.basename(docx_path), source_format=estensione.lstrip(".")
    )

    if estensione not in FORMATI_SUPPORTATI:
        risultato.issues.append(
            Issue(
                code="rinnovo.formato",
                severity=SEVERITY_BLOCKING,
                message=(
                    f"Formato '{estensione or '?'}' non gestito: usa il DOCX o il PDF dell'offerta."
                ),
                where=risultato.source_file,
            )
        )
        return risultato

    percorso = docx_path
    if estensione == ".docx":
        risultato.template_path = docx_path
    if estensione in FORMATI_DA_CONVERTIRE:
        convertito = _converti_in_docx(docx_path)
        if not convertito:
            risultato.issues.append(
                Issue(
                    code="rinnovo.conversione",
                    severity=SEVERITY_BLOCKING,
                    message=(
                        f"Il formato '{estensione}' richiede LibreOffice per la conversione, "
                        "che non è installato. Salva l'offerta come .docx o .pdf e riprova."
                    ),
                    where=risultato.source_file,
                )
            )
            return risultato
        percorso = convertito
        risultato.template_path = convertito

    try:
        if os.path.splitext(percorso)[1].lower() == ".pdf":
            contenuto = _contenuto_da_pdf(percorso)
        else:
            contenuto = _contenuto_da_docx(percorso)
    except Exception as exc:
        risultato.issues.append(
            Issue(
                code="rinnovo.illeggibile",
                severity=SEVERITY_BLOCKING,
                message=(
                    f"Documento non apribile ({type(exc).__name__}: {exc}). "
                    "Se è un file Word vecchio, salvalo come .docx; se è protetto, togli la password."
                ),
                where=risultato.source_file,
            )
        )
        return risultato

    # Ogni parte è indipendente: se una non si legge, le altre restano valide.
    for nome, lettore in (
        ("copertina", _leggi_copertina),
        ("condizioni", _leggi_condizioni),
        ("oggetto", _leggi_oggetto),
        ("righe", _leggi_righe),
    ):
        try:
            lettore(contenuto, risultato)
        except Exception as exc:  # pragma: no cover - documenti fuori standard
            risultato.issues.append(
                Issue(
                    code=f"rinnovo.{nome}",
                    severity=SEVERITY_WARNING,
                    message=f"Non è stato possibile leggere {nome}: {exc}",
                    where=risultato.source_file,
                )
            )

    if not risultato.righe:
        risultato.issues.append(
            Issue(
                code="rinnovo.nessuna_riga",
                severity=SEVERITY_WARNING,
                message=(
                    "Nessuna riga riconosciuta nella tabella economica: i dati di testata sono "
                    "stati recuperati, le voci vanno aggiunte a mano."
                ),
                where=risultato.source_file,
            )
        )
    return risultato


def _converti_in_docx(percorso: str) -> str:
    """Converte i formati vecchi con LibreOffice, se disponibile."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return ""
    cartella = tempfile.mkdtemp(prefix="offerta-conv-")
    try:
        subprocess.run(
            [soffice, "--headless", "--norestore", "--convert-to", "docx",
             "--outdir", cartella, os.path.abspath(percorso)],
            capture_output=True, check=False, timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    atteso = os.path.join(cartella, os.path.splitext(os.path.basename(percorso))[0] + ".docx")
    return atteso if os.path.exists(atteso) else ""


# ---------------------------------------------------------------------------
# Estrazione del contenuto, per formato
# ---------------------------------------------------------------------------

def _contenuto_da_docx(percorso: str) -> _Contenuto:
    from docx import Document

    documento = Document(percorso)
    contenuto = _Contenuto()

    paragrafi = list(documento.paragraphs)
    for paragrafo in paragrafi:
        testo = paragrafo.text.strip()
        if testo:
            contenuto.linee.append(testo)
    for paragrafo in _paragrafi_caselle(documento):
        testo = paragrafo.text.strip()
        if testo and testo not in contenuto.linee:
            contenuto.linee.append(testo)

    for indice, paragrafo in enumerate(paragrafi):
        stile = (paragrafo.style.name if paragrafo.style is not None else "").lower()
        if not stile.startswith(("heading", "titolo")) or not paragrafo.text.strip():
            continue
        seguito: List[str] = []
        for successivo in paragrafi[indice + 1: indice + 8]:
            stile_succ = (successivo.style.name if successivo.style is not None else "").lower()
            if stile_succ.startswith(("heading", "titolo")):
                break
            if successivo.text.strip():
                seguito.append(successivo.text.strip())
        contenuto.sezioni.append((paragrafo.text.strip(), seguito))

    for tabella in documento.tables:
        matrice = [[cella.text.strip() for cella in _celle_distinte(riga)] for riga in tabella.rows]
        if matrice:
            contenuto.tabelle.append(matrice)
    return contenuto


def _contenuto_da_pdf(percorso: str) -> _Contenuto:
    import pdfplumber

    contenuto = _Contenuto()
    with pdfplumber.open(percorso) as pdf:
        for pagina in pdf.pages:
            testo = pagina.extract_text() or ""
            contenuto.linee.extend(riga.strip() for riga in testo.splitlines() if riga.strip())
            for tabella in pagina.extract_tables():
                matrice = [
                    [re.sub(r"\s+", " ", (cella or "").strip()) for cella in riga]
                    for riga in tabella
                    if riga
                ]
                if matrice:
                    contenuto.tabelle.append(matrice)
    return contenuto


# ---------------------------------------------------------------------------
# Lettura delle singole parti
# ---------------------------------------------------------------------------

def _pulisci(valore: str) -> str:
    return re.sub(r"[\s_]+$", "", (valore or "").strip()).strip(" :")


def _leggi_copertina(contenuto: _Contenuto, risultato: OffertaImportata) -> None:
    for indice, riga in enumerate(contenuto.linee):
        spoglio = _norm(riga)

        if any(spoglio.startswith(prefisso) for prefisso in VALIDITA_COPERTINA):
            for prefisso in VALIDITA_COPERTINA:
                if spoglio.startswith(prefisso):
                    valore = _pulisci(riga[len(prefisso):])
                    if parse_date(valore):
                        risultato.form["validita_offerta"] = to_it(valore)
                    break
            continue

        if spoglio == INTESTAZIONE_OFFERTA and indice + 1 < len(contenuto.linee):
            candidato = contenuto.linee[indice + 1].strip()
            if candidato and len(candidato) < 120:
                risultato.form.setdefault("oggetto", candidato)
            continue

        for etichetta, campo in COPERTINA:
            if campo in risultato.form or not spoglio.startswith(etichetta):
                continue
            valore = _pulisci(riga[len(etichetta):])
            if valore:
                risultato.form[campo] = valore
            break

        match = DATA_COPERTINA.match(riga) or SOLO_DATA.match(riga)
        if match and "data_offerta" not in risultato.form:
            risultato.form["data_offerta"] = to_it(match.group(1))


def _leggi_oggetto(contenuto: _Contenuto, risultato: OffertaImportata) -> None:
    if risultato.form.get("oggetto"):
        return
    for titolo, seguito in contenuto.sezioni:
        if _norm(titolo) != "oggetto":
            continue
        for testo in seguito:
            if testo and len(testo) < 200 and not testo.startswith("["):
                risultato.form["oggetto"] = testo
                return


def _leggi_condizioni(contenuto: _Contenuto, risultato: OffertaImportata) -> None:
    etichette = list(ETICHETTE_CONDIZIONI) + CONDIZIONI_EXTRA + COPERTINA_TABELLA
    for tabella in contenuto.tabelle:
        for riga in tabella:
            if len(riga) < 2:
                continue
            etichetta = _norm(riga[0])
            valore = (riga[1] or "").strip()
            if not etichetta or not valore:
                continue
            for chiave, campo in etichette:
                if not etichetta.startswith(_norm(chiave)):
                    continue
                if campo == "durata_contratto":
                    anni = parse_decimal(re.sub(r"[^0-9,.]", " ", valore).strip().split(" ")[0])
                    if anni and anni > 0:
                        risultato.form.setdefault("durata_contratto_anni", int(anni))
                elif campo in {"validita_offerta", "data_offerta"}:
                    if parse_date(valore):
                        risultato.form[campo] = to_it(valore)
                else:
                    risultato.form.setdefault(campo, valore)
                break


def _compatta(testo: str) -> str:
    """Etichetta senza spazi: nei PDF una parola può essere spezzata a metà."""
    return _norm(testo).replace(" ", "").replace(".", "")


def _colonne(intestazione: Sequence[str]) -> Dict[str, int]:
    """Individua le colonne utili dall'intestazione della tabella economica."""
    colonne: Dict[str, int] = {}
    for indice, testo in enumerate(intestazione):
        etichetta = _norm(testo)
        compatta = _compatta(testo)
        if "descrizione" in compatta and "descrizione" not in colonne:
            colonne["descrizione"] = indice
        elif compatta.startswith(("codice", "sku", "partnumber")) and "codice" not in colonne:
            colonne["codice"] = indice
        elif compatta.startswith(("qta", "quantita", "qty")) and "quantita" not in colonne:
            colonne["quantita"] = indice
        elif "totale" in etichetta and "prezzo" not in colonne:
            colonne["prezzo"] = indice
    if "prezzo" not in colonne:
        for indice, testo in enumerate(intestazione):
            if "prezzo" in _compatta(testo):
                colonne["prezzo"] = indice
    colonne.setdefault("descrizione", 0)
    colonne.setdefault("prezzo", max(0, len(intestazione) - 1))
    return colonne


def _valore(testi: Sequence[str], indice: Optional[int]) -> str:
    if indice is None or indice >= len(testi):
        return ""
    return testi[indice]


def _righe_con_seguito(tabelle: List[List[List[str]]], inizio: int) -> List[List[str]]:
    """Righe della tabella economica, comprese le continuazioni.

    Nei PDF il salto pagina spezza la tabella: la parte sotto arriva come una
    tabella a sé, senza intestazione. Se ha lo stesso numero di colonne è la
    continuazione della precedente.
    """
    intestazione = tabelle[inizio]
    righe = list(intestazione[1:])
    colonne = len(intestazione[0])
    for tabella in tabelle[inizio + 1: inizio + 4]:
        if not tabella or len(tabella[0]) != colonne:
            break
        testa = _compatta(" ".join(tabella[0]))
        if "descrizione" in testa and ("prezzo" in testa or "totale" in testa):
            break  # è un'altra tabella con la sua intestazione
        righe.extend(tabella)
    return righe


def _leggi_righe(contenuto: _Contenuto, risultato: OffertaImportata) -> None:
    for posizione, tabella in enumerate(contenuto.tabelle):
        if not tabella:
            continue
        intestazione = tabella[0]
        unito = _compatta(" ".join(intestazione))
        if "descrizione" not in unito or ("prezzo" not in unito and "totale" not in unito):
            continue
        colonne = _colonne(intestazione)

        for riga in _righe_con_seguito(contenuto.tabelle, posizione):
            if not any((cella or "").strip() for cella in riga):
                continue
            descrizione = _valore(riga, colonne["descrizione"]).strip()
            prima = (riga[0] or "").strip()

            if RIGA_DA_SALTARE.match(prima) or RIGA_DA_SALTARE.match(descrizione):
                if any(_norm(prima).startswith(t) for t in RIGHE_TOTALE):
                    importo = next(
                        (parse_decimal(c) for c in reversed(riga) if parse_decimal(c) is not None),
                        None,
                    )
                    if importo is not None and risultato.totale is None:
                        risultato.totale = importo
                continue

            valorizzate = [c for c in riga[1:] if (c or "").strip()]
            if not descrizione or not valorizzate:
                continue  # riga di raggruppamento a tutta larghezza

            quantita = parse_decimal(_valore(riga, colonne.get("quantita"))) or Decimal("1")
            prezzo_testo = (_valore(riga, colonne.get("prezzo")) or "").strip()
            if not prezzo_testo:
                # Riga senza prezzo: nei PDF è la coda di una descrizione andata
                # a capo fra due pagine, non una voce a sé.
                if risultato.righe:
                    precedente = risultato.righe[-1]
                    precedente["descrizione"] = f"{precedente['descrizione']} {descrizione}".strip()
                continue
            prezzo = parse_decimal(prezzo_testo)
            risultato.righe.append(
                {
                    "codice": _valore(riga, colonne.get("codice")),
                    "descrizione": descrizione,
                    "quantita": str(quantita),
                    "prezzo_totale": str(q2(prezzo)) if prezzo is not None else "",
                    # "Incluso" e simili si conservano come sono.
                    "prezzo_testo": "" if prezzo is not None else prezzo_testo.strip(),
                }
            )
        if risultato.righe:
            return


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
        source_format=importata.source_format or "docx",
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
