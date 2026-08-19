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


if __name__ == "__main__":
    target_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
    os.makedirs(target_dir, exist_ok=True)
    print(make_xlsx(os.path.join(target_dir, "bom_computergross_multivendor.xlsx")))
    print(make_pdf(os.path.join(target_dir, "bom_computergross_multivendor.pdf")))
