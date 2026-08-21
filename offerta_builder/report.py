"""Riepilogo interno: costi, ricarichi, margini e anomalie.

Documento a uso interno AD, da non inviare al cliente: mostra il costo di
acquisto riga per riga accanto al prezzo proposto.
"""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any, Dict, List

from .dates import to_it
from .models import PricedOffer
from .money import format_eur, format_number, format_percent
from .qa import LEVEL_FAIL, LEVEL_OK, LEVEL_WARN, QaReport

_CSS = """
:root { color-scheme: light dark; }
body { font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; margin: 2rem auto;
       max-width: 1100px; padding: 0 1rem; line-height: 1.45; }
h1 { margin-bottom: 0.2rem; }
.sub { color: #666; margin-top: 0; }
.badge { display: inline-block; padding: 0.15rem 0.6rem; border-radius: 999px; font-size: 0.85rem;
         font-weight: 600; }
.badge.ok { background: #d8f3dc; color: #14532d; }
.badge.warn { background: #fff3cd; color: #7c4a03; }
.badge.fail { background: #ffd6d6; color: #7f1d1d; }
.riservato { background: #fff3cd; border-left: 4px solid #d97706; padding: 0.6rem 0.9rem;
             margin: 1rem 0; font-weight: 600; }
table { border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: 0.92rem; }
th, td { border: 1px solid #ccc; padding: 0.4rem 0.5rem; text-align: left; vertical-align: top; }
th { background: #f2f2f2; }
td.num, th.num { text-align: right; white-space: nowrap; }
tr.sotto-soglia td { background: #fff1f1; }
tfoot td { font-weight: 700; background: #fafafa; }
.grid { display: flex; flex-wrap: wrap; gap: 1rem; }
.card { border: 1px solid #ddd; border-radius: 8px; padding: 0.8rem 1rem; min-width: 190px; }
.card .label { color: #666; font-size: 0.82rem; }
.card .value { font-size: 1.25rem; font-weight: 700; }
ul.checks li { margin-bottom: 0.25rem; }
@media (prefers-color-scheme: dark) {
  body { background: #14161a; color: #e7e7e7; }
  th { background: #23262c; } th, td { border-color: #3a3f47; }
  .card, tfoot td { border-color: #3a3f47; background: #1b1e23; }
  tr.sotto-soglia td { background: #3a1f1f; }
  .sub, .card .label { color: #a9adb5; }
}
"""


def build_internal_report(
    offer: PricedOffer,
    form: Dict[str, Any],
    qa: QaReport,
    output_path: str,
) -> str:
    """Scrive il riepilogo interno in HTML e ne restituisce il percorso."""
    totals = offer.totals
    threshold = form.get("margine_minimo_percento")

    rows: List[str] = []
    for index, item in enumerate(offer.items, start=1):
        below = (
            threshold is not None
            and item.margin_percent is not None
            and item.sell_net_total
            and item.margin_percent < _dec(threshold)
        )
        rows.append(
            "<tr{cls}>".format(cls=' class="sotto-soglia"' if below else "")
            + f"<td class='num'>{index}</td>"
            + f"<td>{html.escape(item.sku)}</td>"
            + f"<td>{html.escape(item.description)}</td>"
            + f"<td>{html.escape(item.period)}</td>"
            + f"<td class='num'>{format_number(item.quantity)}</td>"
            + f"<td class='num'>{format_eur(item.list_price_total)}</td>"
            + f"<td class='num'>{format_percent(item.discount_percent) if item.discount_percent is not None else '-'}</td>"
            + f"<td class='num'>{format_eur(item.cost_net_total)}</td>"
            + f"<td class='num'>{format_eur(item.sell_net_total)}</td>"
            + f"<td class='num'>{format_eur(item.margin_value)}</td>"
            + f"<td class='num'>{format_percent(item.margin_percent)}</td>"
            + f"<td>{html.escape(item.pricing_mode)}</td></tr>"
        )

    annual_rows = "".join(
        f"<tr><td>{html.escape(entry.label)}</td>"
        f"<td class='num'>{format_eur(entry.total_cost)}</td>"
        f"<td class='num'>{format_eur(entry.total_net)}</td>"
        f"<td class='num'>{format_eur(entry.total_vat)}</td>"
        f"<td class='num'>{format_eur(entry.total_gross)}</td></tr>"
        for entry in offer.annual
    )

    check_items = "".join(
        f"<li><span class='badge {check.level}'>{_label(check.level)}</span> "
        f"<strong>{html.escape(check.title)}</strong>: {html.escape(check.message)}</li>"
        for check in qa.checks
        if check.level != LEVEL_OK
    ) or "<li><span class='badge ok'>OK</span> Nessuna anomalia rilevata.</li>"

    boms_info = "".join(
        f"<li>{html.escape(bom.distributor or 'n/d')} - quote {html.escape(bom.quote_number or 'n/d')}, "
        f"validità {html.escape(to_it(bom.valid_until) or 'n/d')}, "
        f"{len(bom.items)} righe, costo {format_eur(bom.total_cost())} "
        f"({html.escape(bom.source_format)})</li>"
        for bom in offer.boms
    )

    document = f"""<!doctype html>
<html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Riepilogo interno - {html.escape(str(form.get('riferimento_offerta', '')))}</title>
<style>{_CSS}</style></head><body>
<h1>Riepilogo interno offerta</h1>
<p class="sub">{html.escape(str(form.get('riferimento_offerta', '')))} &middot;
{html.escape(str(form.get('cliente', '')))} &middot;
generato il {datetime.now().strftime('%d/%m/%Y %H:%M')}</p>
<div class="riservato">Documento riservato a uso interno: contiene costi di acquisto e margini. Non inviare al cliente.</div>

<div class="grid">
  <div class="card"><div class="label">Totale listino</div><div class="value">{format_eur(totals.total_list)}</div></div>
  <div class="card"><div class="label">Costo acquisto</div><div class="value">{format_eur(totals.total_cost)}</div></div>
  <div class="card"><div class="label">Imponibile vendita</div><div class="value">{format_eur(totals.total_net)}</div></div>
  <div class="card"><div class="label">IVA</div><div class="value">{format_eur(totals.total_vat)}</div></div>
  <div class="card"><div class="label">Totale con IVA</div><div class="value">{format_eur(totals.total_gross)}</div></div>
  <div class="card"><div class="label">Margine</div><div class="value">{
      (format_eur(totals.margin_value) + " (" + format_percent(totals.margin_percent) + ")")
      if totals.margin_known else
      "non calcolabile: " + str(totals.rows_without_cost) + " righe senza costo"
  }</div></div>
  <div class="card"><div class="label">Esito QA</div><div class="value"><span class="badge {qa.status}">{_label(qa.status)}</span></div></div>
</div>

<h2>Dettaglio righe</h2>
<table><thead><tr>
<th class="num">#</th><th>Codice</th><th>Descrizione</th><th>Periodo</th><th class="num">Q.ta</th>
<th class="num">Listino</th><th class="num">Sconto</th><th class="num">Costo</th><th class="num">Vendita</th>
<th class="num">Margine</th><th class="num">Margine %</th><th>Modalità</th>
</tr></thead><tbody>{''.join(rows)}</tbody>
<tfoot><tr><td colspan="5">Totali</td>
<td class="num">{format_eur(totals.total_list)}</td>
<td class="num">{format_percent(totals.average_discount_percent)}</td>
<td class="num">{format_eur(totals.total_cost)}</td>
<td class="num">{format_eur(totals.total_net)}</td>
<td class="num">{format_eur(totals.margin_value)}</td>
<td class="num">{format_percent(totals.margin_percent)}</td><td></td></tr></tfoot></table>

<h2>Riepilogo per annualità</h2>
<table><thead><tr><th>Periodo</th><th class="num">Costo</th><th class="num">Imponibile</th>
<th class="num">IVA</th><th class="num">Totale</th></tr></thead><tbody>{annual_rows}</tbody></table>

<h2>BOM di origine</h2>
<ul>{boms_info or '<li>Nessuna BOM importata.</li>'}</ul>

<h2>Controlli QA da valutare</h2>
<ul class="checks">{check_items}</ul>

<h2>Condizioni</h2>
<ul>
<li>Validità offerta: {html.escape(to_it(form.get('validita_offerta')) or 'n/d')}</li>
<li>Pagamento: {html.escape(str(form.get('tipologia_pagamento', '')))} - {html.escape(str(form.get('condizioni_pagamento', '')))}</li>
<li>Fatturazione: {html.escape(str(form.get('fatturazione', '')))}</li>
<li>Durata contratto: {html.escape(str(form.get('durata_contratto_anni', '')))} anni - rinnovo: {html.escape(str(form.get('rinnovo', '')))}</li>
<li>Soglia margine minimo: {format_percent(threshold) if threshold is not None else 'n/d'}</li>
</ul>
</body></html>
"""
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write(document)
    return output_path


def _label(level: str) -> str:
    return {LEVEL_OK: "OK", LEVEL_WARN: "AVVISO", LEVEL_FAIL: "ERRORE"}.get(level, level.upper())


def _dec(value: Any):
    from decimal import Decimal

    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")
