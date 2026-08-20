"""Genera BOM di esempio in XLSX e PDF, per provare tutti i lettori.

Uso: ``python examples/make_samples.py [cartella]``
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

ROWS = [
    ["Periodo", "Q.ta", "Codice articolo", "Descrizione", "Categoria",
     "Prezzo di listino", "Sconto %", "Netto unitario", "Totale netto"],
    ["01/01/2027 - 31/12/2027", 3, "VEEAM-BR-ENT", "Veeam Backup & Replication Enterprise Plus - 1 anno",
     "Subscription", "1.450,00", "38,00", "899,00", "2.697,00"],
    ["01/01/2027 - 31/12/2027", 1, "VEEAM-ONE-ENT", "Veeam ONE Enterprise Plus - 1 anno",
     "Subscription", "980,00", "35,00", "637,00", "637,00"],
    ["01/01/2027 - 31/12/2027", 2, "FG-100F-BDL", "FortiGate 100F UTP Bundle 12 mesi",
     "Hardware + Servizi", "3.250,00", "42,00", "1.885,00", "3.770,00"],
]

HEADER_LINES = [
    "Computer Gross S.p.A. - Quotazione riservata al rivenditore",
    "Quote Number: CG-2027-44120",
    "End User: Acme Manifatturiera S.r.l.",
    "Valid until: 15/01/2027",
    "Currency: EUR",
]


def make_xlsx(path: str) -> str:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "BOM"
    for line in HEADER_LINES:
        sheet.append([line])
    sheet.append([])
    for row in ROWS:
        sheet.append(row)
    workbook.save(path)
    return path


def make_pdf(path: str) -> str:
    """Converte una copia HTML della BOM in PDF con LibreOffice."""
    table_rows = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in ROWS
    )
    html = (
        "<html><body><p>"
        + "<br>".join(HEADER_LINES)
        + "</p><table border='1' cellspacing='0' cellpadding='4'>"
        + table_rows
        + "</table></body></html>"
    )
    with tempfile.TemporaryDirectory() as workdir:
        html_path = os.path.join(workdir, "bom.html")
        with open(html_path, "w", encoding="utf-8") as handle:
            handle.write(html)
        subprocess.run(
            ["soffice", "--headless", "--norestore", "--convert-to", "pdf", "--outdir", workdir, html_path],
            capture_output=True,
            check=False,
            timeout=180,
        )
        produced = os.path.join(workdir, "bom.pdf")
        if not os.path.exists(produced):
            raise RuntimeError("LibreOffice non ha prodotto il PDF di esempio.")
        os.replace(produced, path)
    return path


# ---------------------------------------------------------------------------
# Quotazione "a gruppi" in stile Computer Gross: intestazione fuori dal
# riquadro della tabella, righe di raggruppamento, totali intermedi e sconti
# a cascata. I dati sono inventati.
# ---------------------------------------------------------------------------

CG_TESTATA = [
    "Spett.le RIVENDITORE S.P.A. Utente finaleFarmacia Bianchi S.r.l.",
    "Cod Cliente 90210 IndirizzoVia Emilia 44",
    "CittàMODENA",
    "c.a. Ufficio Acquisti ContattoLaura Bianchi laura.bianchi@example.it",
    "SPECIAL BID:Q-11223",
    "Empoli 12-dicembre-2026",
    "OGGETTO: Preventivo numero 9988776",
    "Di seguito nostra migliore offerta :",
]

CG_INTESTAZIONE = ["", "Codice", "Descrizione", "Q.ta'", "Listino/Esp", "Sc 1", "Sc 2", "Sc 3",
                   "Prezzo Netto", "Prezzo Totale"]

CG_ARTICOLI = [
    ["ARC-BKP-PREM-36", "Arcserve Backup Suite Premium - Socket - 3 Year Subscription",
     "4", "€ 500,00", "30,00%", "10,00%", "0,00%", "€ 315,00", "€ 1.260,00"],
    ["ARC-STG-01T-36", "Arcserve Cyber Storage 1 TB - 3 Year Subscription",
     "2", "€ 200,00", "20,00%", "5,00%", "0,00%", "€ 152,00", "€ 304,00"],
]

CG_GRUPPI = ["Prima fatturazione all'ordine", "Seconda fatturazione a 12 mesi dall'ordine"]

CG_CODA = [
    "Termini e condizioni di vendita",
    "Validità dell'offerta Ordini evasi e fatturati entro il 31-gennaio-2027",
    "Modalità di pagamento RIMESSA DIRETTA 60 GG. F.M.",
]


def make_pdf_a_gruppi(path: str) -> str:
    """PDF con intestazione fuori tabella, gruppi e sconti a cascata."""
    larghezze = ["2%", "16%", "31%", "5%", "9%", "6%", "6%", "6%", "9%", "10%"]

    def celle(valori, stile=""):
        return "".join(
            f'<td width="{larghezze[i]}" style="{stile}">{v}</td>' for i, v in enumerate(valori)
        )

    bordo = "border:1px solid #000;padding:2px;font-size:8pt;"
    senza = "border:0;padding:2px;font-size:8pt;"

    righe = []
    righe.append(f"<tr>{celle(CG_INTESTAZIONE, senza)}</tr>")
    righe.append(f'<tr>{celle([""] + ["Decorrenza dal 01-01-2027 al 31-12-2029"] + [""] * 8, bordo)}</tr>')
    for indice, gruppo in enumerate(CG_GRUPPI, start=1):
        righe.append(f'<tr>{celle([""] + [gruppo] + [""] * 8, bordo)}</tr>')
        for articolo in CG_ARTICOLI:
            righe.append(f'<tr>{celle([""] + articolo, bordo)}</tr>')
        righe.append(
            f'<tr>{celle([""] * 6 + [f"Totale Gruppo {indice}"] + ["", "", "€ 1.564,00"], bordo)}</tr>'
        )

    html = (
        "<html><body style=\"font-family:Arial;font-size:9pt\"><p>"
        + "<br>".join(CG_TESTATA)
        + "</p><table width='100%' cellspacing='0' style='border-collapse:collapse'>"
        + "".join(righe)
        + "</table><p>"
        + "<br>".join(CG_CODA)
        + "</p></body></html>"
    )
    return _html_to_pdf(html, path)


def _html_to_pdf(html: str, path: str) -> str:
    with tempfile.TemporaryDirectory() as workdir:
        html_path = os.path.join(workdir, "doc.html")
        with open(html_path, "w", encoding="utf-8") as handle:
            handle.write(html)
        subprocess.run(
            ["soffice", "--headless", "--norestore", "--convert-to", "pdf", "--outdir", workdir, html_path],
            capture_output=True, check=False, timeout=180,
        )
        prodotto = os.path.join(workdir, "doc.pdf")
        if not os.path.exists(prodotto):
            raise RuntimeError("LibreOffice non ha prodotto il PDF di esempio.")
        os.replace(prodotto, path)
    return path


if __name__ == "__main__":
    target_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
    os.makedirs(target_dir, exist_ok=True)
    print(make_xlsx(os.path.join(target_dir, "bom_computergross_multivendor.xlsx")))
    print(make_pdf(os.path.join(target_dir, "bom_computergross_multivendor.pdf")))
    print(make_pdf_a_gruppi(os.path.join(target_dir, "bom_a_gruppi.pdf")))
