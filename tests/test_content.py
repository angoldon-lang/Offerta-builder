from decimal import Decimal

import pytest

from offerta_builder.content import allowed_numbers, build_content, check_numbers
from offerta_builder.models import BomItem, NormalizedBom
from offerta_builder.pricing import PricingPolicy, price_offer


@pytest.fixture
def offerta():
    item = BomItem(
        line_no=1, sku="2078005", description="SolarWinds NPM SLX", category="Subscription",
        quantity=Decimal("1"), cost_net_unit=Decimal("9749.30"), cost_net_total=Decimal("9749.30"),
    )
    bom = NormalizedBom(distributor="V-Valley", vendor="SolarWinds", items=[item])
    return price_offer([bom], PricingPolicy(markup_percent=Decimal("25")))


def test_testi_generati_dai_dati(offerta, form_data):
    content = build_content(offerta, form_data)
    assert "BPER BANCA SPA" in content["premessa"]
    assert "Serena Piantoni" in content["premessa"]
    assert "Subscription" in content["descrizione_fornitura"]
    assert content["requisiti"] and content["esclusioni"]
    assert content["condizioni"]["condizioni_pagamento"] == "30 gg fine mese"


def test_premessa_personalizzata_ha_la_precedenza(offerta, form_data):
    form_data["premessa"] = "Testo scritto a mano."
    assert build_content(offerta, form_data)["premessa"] == "Testo scritto a mano."


def test_guard_numerico_accetta_i_valori_calcolati(offerta, form_data):
    consentiti = allowed_numbers(offerta, form_data)
    testo = f"L'imponibile ammonta a {offerta.totals.total_net} euro."
    assert check_numbers(testo, consentiti) == []


def test_guard_numerico_rifiuta_numeri_inventati(offerta, form_data):
    consentiti = allowed_numbers(offerta, form_data)
    sospetti = check_numbers("Sconto aggiuntivo del 42,7% per 99.999,00 EUR", consentiti)
    assert sospetti == ["42,7", "99.999,00"]


def test_ai_senza_chiave_non_altera_i_testi(offerta, form_data, monkeypatch):
    from offerta_builder.content import refine_with_ai

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    content = build_content(offerta, form_data)
    originale = content["premessa"]
    issues = refine_with_ai(content, offerta, form_data)
    assert content["premessa"] == originale
    assert [i.code for i in issues] == ["content.ai_no_key"]
