import os
from decimal import Decimal

import pytest

from offerta_builder.bom import normalize
from offerta_builder.models import SEVERITY_BLOCKING


def test_import_csv_vvalley(csv_bom_path):
    bom = normalize(csv_bom_path)
    assert bom.distributor == "V-Valley"
    assert bom.quote_number == "Q-883436"
    assert bom.valid_until == "2026-07-31"
    assert bom.vendor == "SolarWinds"
    assert bom.currency == "EUR"
    assert len(bom.items) == 4  # la riga "Totale" non e' un articolo
    assert bom.total_cost() == Decimal("18924.56")
    assert not bom.blocking_issues


def test_derivazione_unitario_da_totale(csv_bom_path):
    bom = normalize(csv_bom_path)
    riga = next(i for i in bom.items if i.sku == "2078033")
    assert riga.quantity == Decimal("2")
    assert riga.cost_net_total == Decimal("3825.60")
    assert riga.cost_net_unit == Decimal("1912.80")  # ricavato dal totale
    assert riga.list_price_total == Decimal("9564.00")


def test_costo_ricavato_da_listino_e_sconto(tmp_path):
    path = tmp_path / "bom.csv"
    path.write_text(
        "Codice;Descrizione;Q.ta;Prezzo di listino;Sconto %\n"
        "AAA-1;Licenza base;2;1.000,00;40\n",
        encoding="utf-8",
    )
    bom = normalize(str(path))
    riga = bom.items[0]
    assert riga.list_price_total == Decimal("2000.00")
    assert riga.cost_net_total == Decimal("1200.00")
    assert riga.cost_net_unit == Decimal("600.00")


def test_sconto_ricavato_da_listino_e_netto(tmp_path):
    path = tmp_path / "bom.csv"
    path.write_text(
        "Codice;Descrizione;Q.ta;Prezzo di listino;Netto unitario\n"
        "AAA-1;Licenza base;1;1.000,00;650,00\n",
        encoding="utf-8",
    )
    riga = normalize(str(path)).items[0]
    assert riga.discount_percent == Decimal("35.0000")


def test_costo_mancante_e_bloccante(tmp_path):
    path = tmp_path / "bom.csv"
    path.write_text(
        "Codice;Descrizione;Q.ta\nAAA-1;Licenza senza prezzo;1\n", encoding="utf-8"
    )
    bom = normalize(str(path))
    codici = [i.code for i in bom.blocking_issues]
    assert "bom.cost_missing" in codici


def test_incoerenza_netto_segnalata(tmp_path):
    path = tmp_path / "bom.csv"
    path.write_text(
        "Codice;Descrizione;Q.ta;Netto unitario;Totale netto\n"
        "AAA-1;Licenza;2;100,00;250,00\n",
        encoding="utf-8",
    )
    bom = normalize(str(path))
    assert any(i.code == "bom.cost_mismatch" for i in bom.issues)
    # Per default vince il totale riportato dal distributore.
    assert bom.items[0].cost_net_total == Decimal("250.00")
    assert bom.items[0].cost_net_unit == Decimal("125.00")


def test_file_senza_tabella_riconoscibile(tmp_path):
    path = tmp_path / "vuoto.csv"
    path.write_text("questa;non;e;una;bom\n", encoding="utf-8")
    bom = normalize(str(path))
    assert any(i.severity == SEVERITY_BLOCKING for i in bom.issues)


def test_formato_non_supportato(tmp_path):
    path = tmp_path / "bom.docx"
    path.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        normalize(str(path))


@pytest.mark.parametrize("nome", ["bom_computergross_multivendor.xlsx", "bom_computergross_multivendor.pdf"])
def test_import_xlsx_e_pdf(nome):
    from tests.conftest import EXAMPLES

    path = os.path.join(EXAMPLES, nome)
    if not os.path.exists(path):
        pytest.skip("esempi non generati: esegui python examples/make_samples.py")
    bom = normalize(path)
    assert bom.distributor == "Computer Gross"
    assert bom.quote_number == "CG-2027-44120"
    assert len(bom.items) == 3
    assert bom.total_cost() == Decimal("7104.00")
    assert not bom.blocking_issues
