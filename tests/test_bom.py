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
    assert len(bom.items) == 4  # la riga "Totale" non è un articolo
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


# ---------------------------------------------------------------------------
# Quotazioni "a gruppi" (stile Computer Gross): intestazione fuori dal riquadro
# della tabella, righe di raggruppamento, totali intermedi, sconti a cascata.
# ---------------------------------------------------------------------------

def test_import_pdf_a_gruppi():
    from tests.conftest import EXAMPLES

    path = os.path.join(EXAMPLES, "bom_a_gruppi.pdf")
    if not os.path.exists(path):
        pytest.skip("esempi non generati: esegui python examples/make_samples.py")
    bom = normalize(path)

    assert len(bom.items) == 4          # 2 articoli x 2 tranche di fatturazione
    assert bom.total_cost() == Decimal("3128.00")
    assert bom.total_list() == Decimal("4800.00")
    assert not bom.blocking_issues

    # le righe di raggruppamento diventano il periodo delle righe che seguono
    assert bom.items[0].period == "Prima fatturazione all'ordine"
    assert bom.items[2].period.startswith("Seconda fatturazione")

    # testata riconosciuta anche senza i due punti dopo l'etichetta
    assert bom.quote_number == "9988776"
    assert bom.end_user == "Farmacia Bianchi S.r.l."
    assert bom.valid_until == "2027-01-31"
    assert bom.vendor == "Arcserve"
    assert "RIMESSA DIRETTA" in bom.meta.get("payment_terms", "")


def test_sconti_a_cascata_composti(tmp_path):
    """30% + 10% non fa 40%: si applicano uno sull'altro."""
    path = tmp_path / "bom.csv"
    path.write_text(
        "Codice;Descrizione;Q.ta;Listino;Sc 1;Sc 2;Sc 3;Prezzo Netto\n"
        "AAA-1;Licenza;1;500,00;30,00%;10,00%;0,00%;315,00\n",
        encoding="utf-8",
    )
    riga = normalize(str(path)).items[0]
    assert riga.discount_percent == Decimal("37.0000")
    assert riga.cost_net_total == Decimal("315.00")


def test_righe_di_raggruppamento_e_totale_ignorate(tmp_path):
    path = tmp_path / "bom.csv"
    path.write_text(
        "Codice;Descrizione;Q.ta;Prezzo Netto\n"
        ";Prima fatturazione all'ordine;;\n"
        "AAA-1;Licenza base;2;100,00\n"
        ";Totale Gruppo 1;;200,00\n"
        ";Seconda fatturazione a 12 mesi;;\n"
        "AAA-1;Licenza base;2;100,00\n",
        encoding="utf-8",
    )
    bom = normalize(str(path))
    assert len(bom.items) == 2
    assert bom.total_cost() == Decimal("400.00")
    assert bom.items[0].period == "Prima fatturazione all'ordine"
    assert bom.items[1].period == "Seconda fatturazione a 12 mesi"
    assert not bom.blocking_issues


def test_periodo_di_decorrenza_finisce_nei_metadati(tmp_path):
    path = tmp_path / "bom.csv"
    path.write_text(
        "Codice;Descrizione;Q.ta;Prezzo Netto\n"
        ";Decorrenza dal 01-01-2027 al 31-12-2029;;\n"
        "AAA-1;Licenza base;1;100,00\n",
        encoding="utf-8",
    )
    bom = normalize(str(path))
    assert bom.meta["periodo_contratto"] == "Decorrenza dal 01-01-2027 al 31-12-2029"
    assert bom.items[0].period == "Decorrenza dal 01-01-2027 al 31-12-2029"


def test_intestazione_richiede_almeno_due_colonne():
    """Una riga con il solo 'Totale' non e' un'intestazione."""
    from offerta_builder.bom.columns import map_header

    assert map_header(["", "", "Totale Gruppo 1", "", "€ 3.502,54"])[1] == 0
    assert map_header(["Codice", "Descrizione"])[1] > 0


def test_vendor_riconosciuto_a_parola_intera():
    from offerta_builder.bom.distributors import detect_vendor

    assert detect_vendor("valida fino alla scadenza dell'offerta") == ""
    assert detect_vendor("Arcserve UDP 11.x Premium Edition") == "Arcserve"
    assert detect_vendor("Server Dell PowerEdge R760") == "Dell"
