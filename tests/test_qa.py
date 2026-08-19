from decimal import Decimal

import pytest

from offerta_builder.models import BomItem, NormalizedBom
from offerta_builder.pricing import PricingPolicy, price_offer
from offerta_builder.qa import LEVEL_FAIL, LEVEL_OK, LEVEL_WARN, run_qa


@pytest.fixture
def offerta():
    item = BomItem(
        line_no=1, sku="AAA", description="Licenza", quantity=Decimal("1"),
        cost_net_unit=Decimal("1000"), cost_net_total=Decimal("1000"),
    )
    bom = NormalizedBom(distributor="V-Valley", quote_number="Q-1", valid_until="2026-07-31", items=[item])
    return price_offer([bom], PricingPolicy(markup_percent=Decimal("50"), min_margin_percent=Decimal("20")))


def check(report, check_id):
    return next(c for c in report.checks if c.id == check_id)


def documento(offer, extra=""):
    from offerta_builder.money import format_eur

    return (
        f"Imponibile {format_eur(offer.totals.total_net)}\n"
        f"Totale {format_eur(offer.totals.total_gross)}\n{extra}"
    )


def test_offerta_pulita_supera_il_qa(offerta, form_data):
    report = run_qa(offerta, form_data, document_text=documento(offerta))
    assert check(report, "qa.placeholders").level == LEVEL_OK
    assert check(report, "qa.totali").level == LEVEL_OK
    assert check(report, "qa.iva").level == LEVEL_OK
    assert report.passed


def test_segnaposto_residui_bloccano(offerta, form_data):
    report = run_qa(offerta, form_data, document_text=documento(offerta, "Gentile {{ cliente }}, <<REFERENTE>>"))
    assert check(report, "qa.placeholders").level == LEVEL_FAIL
    assert not report.passed


def test_titoli_incollati(offerta, form_data):
    report = run_qa(offerta, form_data, document_text=documento(offerta, "PremessaPremessa"))
    assert check(report, "qa.titoli").level == LEVEL_FAIL


def test_titoli_duplicati_da_heading(offerta, form_data):
    report = run_qa(offerta, form_data, document_text=documento(offerta),
                    headings=["Premessa", "Offerta economica", "Premessa"])
    assert check(report, "qa.titoli").level == LEVEL_FAIL


def test_importi_ripetuti_non_sono_titoli_duplicati(offerta, form_data):
    """Prezzo unitario e totale coincidono con quantita' 1: e' legittimo."""
    report = run_qa(offerta, form_data, document_text=documento(offerta, "1.500,00 EUR\n1.500,00 EUR"))
    assert check(report, "qa.titoli").level == LEVEL_OK


def test_data_impossibile_nel_form(offerta, form_data):
    form_data["validita_offerta"] = "31-9-2026"
    report = run_qa(offerta, form_data, document_text=documento(offerta))
    assert check(report, "qa.date").level == LEVEL_FAIL


def test_validita_oltre_quella_del_distributore(offerta, form_data):
    form_data["validita_offerta"] = "30/09/2026"
    report = run_qa(offerta, form_data, document_text=documento(offerta))
    assert check(report, "qa.validita_bom").level == LEVEL_FAIL


def test_totali_non_quadrati(offerta, form_data):
    offerta.totals.total_net += Decimal("100")
    report = run_qa(offerta, form_data, document_text=documento(offerta))
    assert check(report, "qa.totali").level == LEVEL_FAIL


def test_iva_incoerente(offerta, form_data):
    offerta.items[0].vat_total = Decimal("1.00")
    report = run_qa(offerta, form_data, document_text=documento(offerta))
    assert check(report, "qa.iva").level == LEVEL_FAIL


def test_margine_sotto_soglia(offerta, form_data):
    form_data["margine_minimo_percento"] = 60
    report = run_qa(offerta, form_data, document_text=documento(offerta))
    assert check(report, "qa.margine").level == LEVEL_FAIL


def test_condizioni_di_pagamento_incomplete(offerta, form_data):
    form_data["condizioni_pagamento"] = ""
    report = run_qa(offerta, form_data, document_text=documento(offerta))
    assert check(report, "qa.condizioni").level == LEVEL_FAIL


def test_totale_non_presente_nel_documento(offerta, form_data):
    report = run_qa(offerta, form_data, document_text="Offerta senza importi")
    assert check(report, "qa.totale_documento").level == LEVEL_FAIL


def test_report_serializzabile(offerta, form_data):
    payload = run_qa(offerta, form_data, document_text=documento(offerta)).to_dict()
    assert payload["status"] in {LEVEL_OK, LEVEL_WARN, LEVEL_FAIL}
    assert payload["totale_controlli"] == len(payload["controlli"])
