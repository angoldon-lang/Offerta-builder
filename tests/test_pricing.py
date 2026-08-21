from decimal import Decimal

from offerta_builder.models import BomItem, NormalizedBom, ServiceLine
from offerta_builder.pricing import (
    MODE_MANUAL, MODE_MARKUP, MODE_TARGET_MARGIN, LineOverride, PricingPolicy, price_offer,
)


def bom_with(cost, qty=1, sku="AAA", period="", list_total=None):
    item = BomItem(
        line_no=1, sku=sku, description="Articolo", quantity=Decimal(str(qty)),
        cost_net_unit=Decimal(str(cost)), cost_net_total=Decimal(str(cost)) * Decimal(str(qty)),
        period=period, list_price_total=Decimal(str(list_total)) if list_total else None,
    )
    return NormalizedBom(distributor="Test", items=[item])


def test_markup_sul_costo():
    offer = price_offer([bom_with(100, qty=2)], PricingPolicy(mode=MODE_MARKUP, markup_percent=Decimal("30")))
    riga = offer.items[0]
    assert riga.sell_net_unit == Decimal("130.00")
    assert riga.sell_net_total == Decimal("260.00")
    assert riga.margin_value == Decimal("60.00")
    assert riga.margin_percent == Decimal("23.0769")


def test_margine_obiettivo_sul_venduto():
    offer = price_offer(
        [bom_with(750)], PricingPolicy(mode=MODE_TARGET_MARGIN, target_margin_percent=Decimal("25"))
    )
    riga = offer.items[0]
    assert riga.sell_net_total == Decimal("1000.00")
    assert riga.margin_percent == Decimal("25.0000")


def test_prezzo_manuale_per_riga():
    policy = PricingPolicy(
        mode=MODE_MARKUP,
        markup_percent=Decimal("30"),
        overrides=[LineOverride(match="AAA", sell_net_total=Decimal("500"))],
    )
    offer = price_offer([bom_with(100, qty=2)], policy)
    assert offer.items[0].sell_net_total == Decimal("500.00")
    assert offer.items[0].pricing_mode == MODE_MANUAL


def test_modalita_manuale_senza_prezzo_e_bloccante():
    offer = price_offer([bom_with(100)], PricingPolicy(mode=MODE_MANUAL))
    assert any(i.code == "pricing.manual_missing" for i in offer.issues)


def test_iva_e_totali_ricalcolati():
    offer = price_offer(
        [bom_with(1000, list_total=2000)],
        PricingPolicy(mode=MODE_MARKUP, markup_percent=Decimal("20"), vat_percent=Decimal("22")),
    )
    totals = offer.totals
    assert totals.total_net == Decimal("1200.00")
    assert totals.total_vat == Decimal("264.00")
    assert totals.total_gross == Decimal("1464.00")
    assert totals.total_cost == Decimal("1000.00")
    assert totals.average_discount_percent == Decimal("50.0000")


def test_arrotondamento_a_dieci_euro():
    offer = price_offer(
        [bom_with(1000)],
        PricingPolicy(mode=MODE_MARKUP, markup_percent=Decimal("23"), rounding="10"),
    )
    assert offer.items[0].sell_net_unit == Decimal("1230")


def test_servizi_aggiunti_come_righe():
    policy = PricingPolicy(
        mode=MODE_MARKUP,
        markup_percent=Decimal("0"),
        services=[ServiceLine(description="Installazione", unit_price=Decimal("1000"), unit_cost=Decimal("400"))],
    )
    offer = price_offer([bom_with(100)], policy)
    servizio = offer.items[-1]
    assert servizio.pricing_mode == "servizio"
    assert servizio.sell_net_total == Decimal("1000.00")
    assert servizio.margin_value == Decimal("600.00")
    assert offer.totals.total_net == Decimal("1100.00")


def test_riepilogo_per_periodo():
    bom = bom_with(100, period="01/01/2027 - 31/12/2027")
    bom.items.append(
        BomItem(line_no=2, sku="BBB", description="Secondo anno", quantity=Decimal("1"),
                cost_net_unit=Decimal("100"), cost_net_total=Decimal("100"),
                period="01/01/2028 - 31/12/2028")
    )
    offer = price_offer([bom], PricingPolicy(mode=MODE_MARKUP, markup_percent=Decimal("0")))
    assert [a.label for a in offer.annual] == ["01/01/2027 - 31/12/2027", "01/01/2028 - 31/12/2028"]
    assert sum(a.total_net for a in offer.annual) == offer.totals.total_net


def test_ripartizione_su_piu_annualita_senza_periodo():
    policy = PricingPolicy(mode=MODE_MARKUP, markup_percent=Decimal("0"), contract_years=3)
    offer = price_offer([bom_with(Decimal("1000"))], policy)
    assert len(offer.annual) == 3
    assert sum(a.total_net for a in offer.annual) == offer.totals.total_net


def test_margine_sotto_soglia_segnalato_una_volta_sola():
    """Offerta tutta sotto soglia: una segnalazione, non una per riga."""
    policy = PricingPolicy(mode=MODE_MARKUP, markup_percent=Decimal("5"), min_margin_percent=Decimal("30"))
    offer = price_offer([bom_with(1000), bom_with(500, sku="BBB")], policy)
    codici = [i.code for i in offer.issues]
    assert codici == ["pricing.total_margin_below_threshold"]
    assert not [i for i in offer.issues if i.blocking]


def test_riga_sotto_soglia_segnalata_se_il_totale_regge():
    """Se l'offerta nel complesso sta sopra soglia, si indicano le righe deboli."""
    from offerta_builder.pricing import LineEdit

    policy = PricingPolicy(
        mode=MODE_TARGET_MARGIN, target_margin_percent=Decimal("50"), min_margin_percent=Decimal("30"),
        line_edits=[LineEdit(index=1, reference="BBB", sell_net_unit=Decimal("55"))],
    )
    offer = price_offer([bom_due_righe()], policy)
    codici = [i.code for i in offer.issues]
    assert "pricing.margin_below_threshold" in codici
    assert "pricing.total_margin_below_threshold" not in codici


# ---------------------------------------------------------------------------
# Modifiche manuali di riga
# ---------------------------------------------------------------------------

def bom_due_righe():
    return NormalizedBom(
        distributor="Test",
        items=[
            BomItem(line_no=1, sku="AAA", description="Licenza A", quantity=Decimal("2"),
                    cost_net_unit=Decimal("100"), cost_net_total=Decimal("200"),
                    list_price_unit=Decimal("150"), list_price_total=Decimal("300")),
            BomItem(line_no=2, sku="BBB", description="Licenza B", quantity=Decimal("1"),
                    cost_net_unit=Decimal("50"), cost_net_total=Decimal("50")),
        ],
    )


def test_modifica_quantita_ricalcola_anche_il_costo():
    from offerta_builder.pricing import LineEdit

    policy = PricingPolicy(mode=MODE_MARKUP, markup_percent=Decimal("0"),
                           line_edits=[LineEdit(index=0, reference="AAA", quantity=Decimal("5"))])
    offer = price_offer([bom_due_righe()], policy)
    riga = offer.items[0]
    assert riga.quantity == Decimal("5")
    assert riga.cost_net_total == Decimal("500.00")
    assert riga.list_price_total == Decimal("750.00")
    assert riga.sell_net_total == Decimal("500.00")


def test_modifica_descrizione_e_codice():
    from offerta_builder.pricing import LineEdit

    policy = PricingPolicy(
        mode=MODE_MARKUP, markup_percent=Decimal("10"),
        line_edits=[LineEdit(index=1, reference="BBB", sku="BBB-NEW", description="Licenza B rinominata")],
    )
    offer = price_offer([bom_due_righe()], policy)
    assert offer.items[1].sku == "BBB-NEW"
    assert offer.items[1].description == "Licenza B rinominata"
    assert offer.items[1].edited


def test_riga_esclusa_non_entra_nei_totali():
    from offerta_builder.pricing import LineEdit

    policy = PricingPolicy(mode=MODE_MARKUP, markup_percent=Decimal("0"),
                           line_edits=[LineEdit(index=0, reference="AAA", exclude=True)])
    offer = price_offer([bom_due_righe()], policy)
    assert len(offer.items) == 1
    assert offer.items[0].sku == "BBB"
    assert offer.totals.total_net == Decimal("50.00")
    assert [i.sku for i in offer.excluded] == ["AAA"]


def test_prezzo_manuale_di_riga_vince_sulla_politica():
    from offerta_builder.pricing import LineEdit

    policy = PricingPolicy(mode=MODE_TARGET_MARGIN, target_margin_percent=Decimal("30"),
                           line_edits=[LineEdit(index=1, reference="BBB", sell_net_unit=Decimal("99"))])
    offer = price_offer([bom_due_righe()], policy)
    assert offer.items[1].sell_net_unit == Decimal("99.00")
    assert offer.items[1].pricing_mode == "manual"
    # l'altra riga resta sulla politica generale (a meno dell'arrotondamento)
    assert abs(offer.items[0].margin_percent - Decimal("30")) < Decimal("0.01")


def test_modifica_ignorata_se_la_riga_non_corrisponde():
    """Modifiche rimaste da una BOM precedente non devono colpire righe altrui."""
    from offerta_builder.pricing import LineEdit

    policy = PricingPolicy(mode=MODE_MARKUP, markup_percent=Decimal("0"),
                           line_edits=[LineEdit(index=0, reference="ZZZ", exclude=True)])
    offer = price_offer([bom_due_righe()], policy)
    assert len(offer.items) == 2
    assert not offer.excluded


def test_le_righe_normalizzate_non_vengono_modificate():
    from offerta_builder.pricing import LineEdit

    bom = bom_due_righe()
    policy = PricingPolicy(mode=MODE_MARKUP, markup_percent=Decimal("0"),
                           line_edits=[LineEdit(index=0, reference="AAA", quantity=Decimal("9"))])
    price_offer([bom], policy)
    assert bom.items[0].quantity == Decimal("2")  # la BOM resta quella letta dal file
