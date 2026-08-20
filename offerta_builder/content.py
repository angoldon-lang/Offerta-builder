"""Content Generator: i testi dell'offerta.

Di default i testi sono deterministici (template + dati del form): stessi input,
stesso documento. Se si attiva l'assistenza AI (``--ai``), il modello può
riscrivere *solo* prosa già delimitata, e l'output passa dal guard numerico:
ogni numero non presente nei dati calcolati fa scartare la riscrittura.
"""

from __future__ import annotations

import os
import re
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Set

from .dates import to_it
from .models import SEVERITY_WARNING, Issue, PricedOffer
from .money import format_eur

REQUISITI_STANDARD = [
    "Disponibilità di un referente tecnico del Cliente per tutta la durata delle attività.",
    "Accessi fisici e logici agli ambienti oggetto di fornitura, concordati preventivamente.",
    "Prerequisiti hardware, software e di rete conformi alle specifiche del produttore.",
    "Finestre di manutenzione concordate con almeno 5 giorni lavorativi di preavviso.",
]

ESCLUSIONI_STANDARD = [
    "Attività non esplicitamente indicate nella presente offerta.",
    "Trasferte, vitto e alloggio, se non diversamente specificato.",
    "Materiale elettrico, cablaggi e opere murarie.",
    "Licenze, sottoscrizioni e servizi di terze parti non elencati nell'offerta economica.",
]

ALLEGATI_STANDARD = [
    "Condizioni generali di fornitura",
    "Informativa privacy",
]


def build_content(offer: PricedOffer, form: Dict[str, Any]) -> Dict[str, Any]:
    """Costruisce tutti i testi dell'offerta a partire dai dati validati."""
    cliente = str(form.get("cliente", "")).strip()
    oggetto = str(form.get("oggetto", "")).strip()
    vendor = _first_vendor(offer)
    durata = form.get("durata_contratto_anni") or 1

    content: Dict[str, Any] = {
        "oggetto": oggetto,
        "premessa": str(form.get("premessa", "")).strip() or _premessa(cliente, oggetto, vendor, durata, form),
        "descrizione_fornitura": _descrizione_fornitura(offer, vendor),
        "descrizione_servizi": _descrizione_servizi(offer, form),
        "nota_servizi": _nota_servizi(offer),
        "requisiti": _as_list(form.get("requisiti_cliente")) or list(REQUISITI_STANDARD),
        "esclusioni": _as_list(form.get("esclusioni")) or list(ESCLUSIONI_STANDARD),
        "note_commerciali": _as_list(form.get("note_commerciali")),
        "allegati": _as_list(form.get("allegati")) or list(ALLEGATI_STANDARD),
        "condizioni": _condizioni(form),
    }
    return content


def _first_vendor(offer: PricedOffer) -> str:
    for bom in offer.boms:
        if bom.vendor:
            return bom.vendor
    return ""


def _as_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [line.strip() for line in value.splitlines() if line.strip()]
    return [str(v).strip() for v in value if str(v).strip()]


def _premessa(cliente: str, oggetto: str, vendor: str, durata: Any, form: Dict[str, Any]) -> str:
    referente = str(form.get("referente", "")).strip()
    apertura = f"Gentile {referente}," if referente else "Gentile Cliente,"
    soggetto = f"{cliente}" if cliente else "la Vostra Societa'"
    tecnologia = f" basata su tecnologia {vendor}" if vendor else ""
    anni = f" per una durata contrattuale di {durata} anni" if int(durata or 1) > 1 else ""
    return (
        f"{apertura}\n"
        f"facendo seguito alla Vostra cortese richiesta, siamo lieti di sottoporre a {soggetto} "
        f"la presente offerta relativa a: {oggetto}{tecnologia}{anni}.\n"
        "La soluzione proposta è stata dimensionata sulla base delle informazioni ricevute e "
        "delle configurazioni concordate; le condizioni economiche e contrattuali di riferimento "
        "sono riportate nelle sezioni seguenti."
    )


def _descrizione_fornitura(offer: PricedOffer, vendor: str) -> str:
    categorie: List[str] = []
    for item in offer.items:
        etichetta = (item.category or "").strip()
        if etichetta and etichetta not in categorie:
            categorie.append(etichetta)
    if not categorie:
        return "La fornitura comprende i componenti elencati nell'offerta economica."
    elenco = ", ".join(categorie[:-1]) + (" e " + categorie[-1] if len(categorie) > 1 else categorie[0])
    marchio = f" a marchio {vendor}" if vendor else ""
    return (
        f"La fornitura{marchio} comprende le seguenti tipologie di componenti: {elenco}. "
        "Il dettaglio completo, con codici, quantità e prezzi, è riportato nell'offerta economica."
    )


def _descrizione_servizi(offer: PricedOffer, form: Dict[str, Any]) -> List[str]:
    servizi = [item for item in offer.items if item.pricing_mode == "servizio"]
    righe = []
    for servizio in servizi:
        prezzo = format_eur(servizio.sell_net_total, "EUR")
        righe.append(f"{servizio.description} - {prezzo} (IVA esclusa)")
    return righe


def _nota_servizi(offer: PricedOffer) -> str:
    """Riga descrittiva dei servizi, per i template che hanno una sezione dedicata."""
    servizi = [item for item in offer.items if item.pricing_mode == "servizio"]
    if not servizi:
        return ""
    voci = ", ".join(servizio.description for servizio in servizi[:4])
    return f"Servizi professionali inclusi nella fornitura: {voci}."


def _condizioni(form: Dict[str, Any]) -> Dict[str, str]:
    validita = form.get("validita_offerta")
    return {
        "tipologia_pagamento": str(form.get("tipologia_pagamento", "")).strip(),
        "condizioni_pagamento": str(form.get("condizioni_pagamento", "")).strip(),
        "fatturazione": str(form.get("fatturazione", "")).strip(),
        "durata_contratto": f"{form.get('durata_contratto_anni', '')} anni".strip(),
        "rinnovo": str(form.get("rinnovo", "")).strip(),
        "validita_offerta": to_it(validita) if validita else "",
    }


# ---------------------------------------------------------------------------
# Guard numerico: l'AI non deve introdurre cifre che non esistono nei dati.
# ---------------------------------------------------------------------------

_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")


def allowed_numbers(offer: PricedOffer, form: Dict[str, Any]) -> Set[str]:
    """Insieme dei numeri legittimi: totali, importi di riga, dati del form."""
    values: Set[str] = set()

    def add(value: Any) -> None:
        if value is None or isinstance(value, bool):
            return
        if isinstance(value, (int, Decimal, float)):
            dec = Decimal(str(value))
            values.add(_canonical(dec))
            values.add(_canonical(dec.quantize(Decimal("1"))))
            return
        for match in _NUMBER_RE.findall(str(value)):
            values.add(_canonical_text(match))

    totals = offer.totals
    for value in (
        totals.total_list, totals.total_cost, totals.total_net, totals.total_vat,
        totals.total_gross, totals.margin_value, totals.margin_percent,
        totals.average_discount_percent,
    ):
        add(value)
    for item in offer.items:
        for value in (
            item.quantity, item.list_price_unit, item.list_price_total, item.discount_percent,
            item.cost_net_unit, item.cost_net_total, item.sell_net_unit, item.sell_net_total,
            item.vat_percent, item.vat_total, item.sell_gross_total, item.line_no,
        ):
            add(value)
        add(item.sku)
        add(item.period)
        add(item.description)
    for entry in offer.annual:
        for value in (entry.total_net, entry.total_cost, entry.total_vat, entry.total_gross):
            add(value)
        add(entry.label)
    for value in form.values():
        add(value if not isinstance(value, (list, dict)) else str(value))
    return values


def _canonical(value: Decimal) -> str:
    text = f"{value.normalize():f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _canonical_text(text: str) -> str:
    cleaned = text.replace(".", "").replace(",", ".") if text.count(",") == 1 else text.replace(",", "")
    try:
        return _canonical(Decimal(cleaned))
    except Exception:
        return text


def check_numbers(text: str, allowed: Set[str]) -> List[str]:
    """Numeri presenti nel testo ma non riconducibili ai dati calcolati."""
    unknown: List[str] = []
    for match in _NUMBER_RE.findall(text or ""):
        canonical = _canonical_text(match)
        if canonical in allowed or match in allowed:
            continue
        if len(canonical.replace(".", "")) <= 2:
            continue  # numeri piccoli (elenchi, "24x7", articoli di legge)
        unknown.append(match)
    return unknown


AI_SYSTEM_PROMPT = (
    "Sei l'assistente di redazione di offerte commerciali di un system integrator italiano. "
    "Riscrivi il testo fornito in italiano professionale, chiaro e sintetico. "
    "REGOLE INDEROGABILI: non introdurre, modificare o dedurre cifre, prezzi, percentuali, "
    "date, quantità o condizioni contrattuali; non aggiungere impegni, garanzie o SLA non "
    "presenti nel testo originale. Restituisci solo il testo riscritto, senza commenti."
)


def refine_with_ai(
    content: Dict[str, Any],
    offer: PricedOffer,
    form: Dict[str, Any],
    sections: Iterable[str] = ("premessa", "descrizione_fornitura"),
    model: str = "claude-sonnet-5",
) -> List[Issue]:
    """Riscrittura assistita dei soli testi discorsivi (opt-in).

    Ogni riscrittura viene accettata solo se non contiene numeri estranei ai
    dati calcolati; in caso contrario si tiene il testo deterministico e si
    registra un warning.
    """
    issues: List[Issue] = []
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        issues.append(
            Issue(
                code="content.ai_no_key",
                severity=SEVERITY_WARNING,
                message="Assistenza AI richiesta ma ANTHROPIC_API_KEY non è impostata: testi deterministici.",
            )
        )
        return issues
    try:
        import anthropic  # type: ignore
    except ImportError:
        issues.append(
            Issue(
                code="content.ai_no_sdk",
                severity=SEVERITY_WARNING,
                message="Pacchetto 'anthropic' non installato (pip install offerta-builder[ai]): testi deterministici.",
            )
        )
        return issues

    client = anthropic.Anthropic(api_key=api_key)
    allowed = allowed_numbers(offer, form)
    for section in sections:
        original = content.get(section)
        if not isinstance(original, str) or not original.strip():
            continue
        try:
            response = client.messages.create(
                model=model,
                max_tokens=1200,
                system=AI_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": original}],
            )
            rewritten = "".join(
                block.text for block in response.content if getattr(block, "type", "") == "text"
            ).strip()
        except Exception as exc:  # pragma: no cover - dipende dalla rete
            issues.append(
                Issue(
                    code="content.ai_error",
                    severity=SEVERITY_WARNING,
                    message=f"Riscrittura AI non riuscita per '{section}': {exc}. Testo deterministico mantenuto.",
                )
            )
            continue
        if not rewritten:
            continue
        unknown = check_numbers(rewritten, allowed)
        if unknown:
            issues.append(
                Issue(
                    code="content.ai_numbers_rejected",
                    severity=SEVERITY_WARNING,
                    message=(
                        f"Riscrittura AI di '{section}' scartata: numeri non presenti nei dati "
                        f"({', '.join(unknown[:5])})."
                    ),
                    where=section,
                    details={"numeri": unknown},
                )
            )
            continue
        content[section] = rewritten
    return issues
