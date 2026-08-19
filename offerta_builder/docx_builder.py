"""Generazione del DOCX.

Due modalità:

* **template AD** (consigliata): il file Word aziendale con segnaposto Jinja
  (``{{ cliente }}``, ``{%tr for riga in righe %}``) viene compilato con
  ``docxtpl``, mantenendo stili, tabelle e allegati del template;
* **fallback**: se non viene passato un template, il documento viene costruito
  da zero con ``python-docx`` (copertina, oggetto, premessa, offerta economica,
  condizioni, accettazione, allegati) - utile per test e per partire subito.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from .dates import to_it
from .models import PricedOffer
from .money import format_eur, format_number, format_percent

CURRENCY_LABEL = "EUR"


def build_context(offer: PricedOffer, form: Dict[str, Any], content: Dict[str, Any]) -> Dict[str, Any]:
    """Prepara il contesto per il template: valori già formattati, niente calcoli."""
    righe: List[Dict[str, str]] = []
    for index, item in enumerate(offer.items, start=1):
        righe.append(
            {
                "n": str(index),
                "sku": item.sku,
                "codice": item.sku,
                "descrizione": item.description,
                "categoria": item.category,
                "periodo": item.period,
                "quantita": format_number(item.quantity, 0 if item.quantity == item.quantity.to_integral_value() else 2),
                "prezzo_unitario": format_eur(item.sell_net_unit, CURRENCY_LABEL),
                "totale": format_eur(item.sell_net_total, CURRENCY_LABEL),
                "iva_percento": format_percent(item.vat_percent, 0),
                "iva": format_eur(item.vat_total, CURRENCY_LABEL),
                "totale_ivato": format_eur(item.sell_gross_total, CURRENCY_LABEL),
            }
        )

    totals = offer.totals
    annualita = [
        {
            "periodo": entry.label,
            "imponibile": format_eur(entry.total_net, CURRENCY_LABEL),
            "iva": format_eur(entry.total_vat, CURRENCY_LABEL),
            "totale": format_eur(entry.total_gross, CURRENCY_LABEL),
        }
        for entry in offer.annual
    ]

    condizioni = content.get("condizioni", {})
    context: Dict[str, Any] = {
        # anagrafica e testata
        "cliente": form.get("cliente", ""),
        "piva": form.get("piva", ""),
        "indirizzo_cliente": form.get("indirizzo_cliente", ""),
        "referente": form.get("referente", ""),
        "email_referente": form.get("email_referente", ""),
        "autore": form.get("autore", ""),
        "riferimento_offerta": form.get("riferimento_offerta", ""),
        "data_offerta": to_it(form.get("data_offerta")),
        "validita_offerta": to_it(form.get("validita_offerta")),
        "oggetto": content.get("oggetto", form.get("oggetto", "")),
        # testi
        "premessa": content.get("premessa", ""),
        "descrizione_fornitura": content.get("descrizione_fornitura", ""),
        "descrizione_servizi": content.get("descrizione_servizi", []),
        "requisiti": content.get("requisiti", []),
        "esclusioni": content.get("esclusioni", []),
        "note_commerciali": content.get("note_commerciali", []),
        "allegati": content.get("allegati", []),
        # condizioni
        "tipologia_pagamento": condizioni.get("tipologia_pagamento", ""),
        "condizioni_pagamento": condizioni.get("condizioni_pagamento", ""),
        "fatturazione": condizioni.get("fatturazione", ""),
        "durata_contratto": condizioni.get("durata_contratto", ""),
        "rinnovo": condizioni.get("rinnovo", ""),
        "iva_percento": format_percent(form.get("iva_percento", 0), 0),
        # economics
        "righe": righe,
        "annualita": annualita,
        "totale_imponibile": format_eur(totals.total_net, CURRENCY_LABEL),
        "totale_iva": format_eur(totals.total_vat, CURRENCY_LABEL),
        "totale_offerta": format_eur(totals.total_gross, CURRENCY_LABEL),
        "totale_listino": format_eur(totals.total_list, CURRENCY_LABEL),
        "valuta": CURRENCY_LABEL,
    }
    return context


def render(context: Dict[str, Any], output_path: str, template_path: Optional[str] = None) -> str:
    """Scrive il DOCX. Con template usa docxtpl, altrimenti costruisce il documento."""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
    if template_path:
        from docxtpl import DocxTemplate

        document = DocxTemplate(template_path)
        document.render(context)
        document.save(output_path)
        return output_path
    return _render_fallback(context, output_path)


def template_placeholders(template_path: str) -> List[str]:
    """Elenca i segnaposto Jinja dichiarati dal template (utile per il QA)."""
    from docxtpl import DocxTemplate

    document = DocxTemplate(template_path)
    return sorted(document.get_undeclared_template_variables())


def _render_fallback(context: Dict[str, Any], output_path: str) -> str:
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    document = Document()

    # --- copertina ---------------------------------------------------------
    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("OFFERTA COMMERCIALE")
    run.bold = True
    run.font.size = Pt(22)

    subtitle = document.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle.add_run(context.get("oggetto", "")).bold = True

    cover = document.add_table(rows=0, cols=2)
    cover.alignment = WD_TABLE_ALIGNMENT.CENTER
    for label, key in [
        ("Cliente", "cliente"),
        ("P.IVA", "piva"),
        ("Indirizzo", "indirizzo_cliente"),
        ("Referente", "referente"),
        ("Riferimento offerta", "riferimento_offerta"),
        ("Data offerta", "data_offerta"),
        ("Validità offerta", "validita_offerta"),
        ("Autore", "autore"),
    ]:
        value = context.get(key, "")
        if not value:
            continue
        row = cover.add_row().cells
        row[0].paragraphs[0].add_run(label).bold = True
        row[1].text = str(value)

    document.add_page_break()

    # --- oggetto e premessa ------------------------------------------------
    document.add_heading("Oggetto", level=1)
    document.add_paragraph(context.get("oggetto", ""))

    document.add_heading("Premessa", level=1)
    for block in str(context.get("premessa", "")).split("\n"):
        if block.strip():
            document.add_paragraph(block.strip())

    if context.get("descrizione_fornitura"):
        document.add_heading("Descrizione della fornitura", level=1)
        document.add_paragraph(context["descrizione_fornitura"])

    if context.get("descrizione_servizi"):
        document.add_heading("Servizi professionali", level=1)
        for servizio in context["descrizione_servizi"]:
            document.add_paragraph(servizio, style="List Bullet")

    # --- offerta economica -------------------------------------------------
    document.add_heading("Offerta economica", level=1)
    headers = ["#", "Codice", "Descrizione", "Periodo", "Q.ta", "Prezzo unitario", "Totale"]
    table = document.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    for index, header in enumerate(headers):
        cell = table.rows[0].cells[index]
        cell.text = ""
        cell.paragraphs[0].add_run(header).bold = True
    for riga in context.get("righe", []):
        cells = table.add_row().cells
        cells[0].text = riga["n"]
        cells[1].text = riga["codice"]
        cells[2].text = riga["descrizione"]
        cells[3].text = riga["periodo"]
        cells[4].text = riga["quantita"]
        cells[5].text = riga["prezzo_unitario"]
        cells[6].text = riga["totale"]

    document.add_paragraph()
    totals_table = document.add_table(rows=0, cols=2)
    totals_table.style = "Table Grid"
    for label, key in [
        ("Totale imponibile", "totale_imponibile"),
        (f"IVA {context.get('iva_percento', '')}", "totale_iva"),
        ("Totale offerta", "totale_offerta"),
    ]:
        cells = totals_table.add_row().cells
        cells[0].paragraphs[0].add_run(label).bold = True
        cells[1].paragraphs[0].add_run(str(context.get(key, ""))).bold = True

    if context.get("annualita") and len(context["annualita"]) > 1:
        document.add_heading("Riepilogo per annualità", level=2)
        annual_table = document.add_table(rows=1, cols=4)
        annual_table.style = "Table Grid"
        for index, header in enumerate(["Periodo", "Imponibile", "IVA", "Totale"]):
            cell = annual_table.rows[0].cells[index]
            cell.text = ""
            cell.paragraphs[0].add_run(header).bold = True
        for entry in context["annualita"]:
            cells = annual_table.add_row().cells
            cells[0].text = entry["periodo"]
            cells[1].text = entry["imponibile"]
            cells[2].text = entry["iva"]
            cells[3].text = entry["totale"]

    # --- condizioni --------------------------------------------------------
    document.add_heading("Condizioni di vendita", level=1)
    conditions_table = document.add_table(rows=0, cols=2)
    conditions_table.style = "Table Grid"
    for label, key in [
        ("Validità offerta", "validita_offerta"),
        ("Tipologia di pagamento", "tipologia_pagamento"),
        ("Condizioni di pagamento", "condizioni_pagamento"),
        ("Fatturazione", "fatturazione"),
        ("Durata contratto", "durata_contratto"),
        ("Rinnovo", "rinnovo"),
    ]:
        value = context.get(key, "")
        if not value:
            continue
        cells = conditions_table.add_row().cells
        cells[0].paragraphs[0].add_run(label).bold = True
        cells[1].text = str(value)

    if context.get("requisiti"):
        document.add_heading("Requisiti a carico del Cliente", level=2)
        for requisito in context["requisiti"]:
            document.add_paragraph(requisito, style="List Bullet")

    if context.get("esclusioni"):
        document.add_heading("Esclusioni", level=2)
        for esclusione in context["esclusioni"]:
            document.add_paragraph(esclusione, style="List Bullet")

    if context.get("note_commerciali"):
        document.add_heading("Note commerciali", level=2)
        for nota in context["note_commerciali"]:
            document.add_paragraph(nota, style="List Bullet")

    # --- accettazione ------------------------------------------------------
    document.add_heading("Accettazione", level=1)
    document.add_paragraph(
        "Per accettazione della presente offerta, comprensiva delle condizioni di vendita e "
        "degli allegati richiamati, timbro e firma del Cliente:"
    )
    signature = document.add_table(rows=2, cols=2)
    signature.style = "Table Grid"
    signature.rows[0].cells[0].text = "Data"
    signature.rows[0].cells[1].text = "Timbro e firma"
    signature.rows[1].cells[0].text = ""
    signature.rows[1].cells[1].text = ""

    if context.get("allegati"):
        document.add_heading("Allegati", level=1)
        for allegato in context["allegati"]:
            document.add_paragraph(allegato, style="List Bullet")

    document.save(output_path)
    return output_path


def extract_text(docx_path: str) -> str:
    """Testo completo del documento generato (paragrafi + tabelle), per il QA."""
    from docx import Document

    document = Document(docx_path)
    parts: List[str] = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                parts.extend(p.text for p in cell.paragraphs)
    for section in document.sections:
        for container in (section.header, section.footer):
            parts.extend(p.text for p in container.paragraphs)
    return "\n".join(part for part in parts if part)


def extract_headings(docx_path: str) -> List[str]:
    """Titoli del documento (stili Heading), per il controllo sui duplicati."""
    from docx import Document

    document = Document(docx_path)
    headings: List[str] = []
    for paragraph in document.paragraphs:
        style = (paragraph.style.name or "") if paragraph.style is not None else ""
        if style.lower().startswith(("heading", "titolo")) and paragraph.text.strip():
            headings.append(paragraph.text.strip())
    return headings
