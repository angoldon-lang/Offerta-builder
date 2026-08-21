"""Rinnovo di un'offerta scaduta: rilettura, aggiornamento, riprezzatura."""

import io
from datetime import date
from decimal import Decimal

import pytest

from offerta_builder.pipeline import build_offer, prepare_offer
from offerta_builder.rinnovo import (
    aggiorna_per_rinnovo,
    bom_da_offerta,
    prossima_revisione,
    read_offer,
)


@pytest.fixture
def offerta_vecchia(tmp_path, csv_bom_path, form_data, template_path):
    """Un'offerta generata dal programma, da usare come 'offerta scaduta'."""
    form_data["servizi_aggiuntivi"] = [
        {"descrizione": "Installazione", "quantita": 1, "prezzo_unitario": 2000, "costo_unitario": 800}
    ]
    result = build_offer(
        bom_paths=[csv_bom_path], form=form_data, output_dir=str(tmp_path / "vecchia"),
        template_path=template_path,
    )
    return result.outputs["docx"], result


def test_rilettura_di_una_offerta_generata(offerta_vecchia):
    percorso, originale = offerta_vecchia
    letta = read_offer(percorso)

    assert letta.form["cliente"] == "BPER BANCA SPA"
    assert letta.form["riferimento_offerta"] == "OFF_ADC_26/0313_R03"
    assert letta.form["condizioni_pagamento"] == "30 gg fine mese"
    assert len(letta.righe) == len(originale.offer.items)
    assert letta.righe[0]["descrizione"].startswith("SolarWinds")


def test_rilettura_conserva_i_prezzi(offerta_vecchia):
    percorso, originale = offerta_vecchia
    letta = read_offer(percorso)
    primo = originale.offer.items[0]
    assert Decimal(letta.righe[0]["prezzo_totale"]) == primo.sell_net_total


def test_nuova_revisione_del_riferimento():
    assert prossima_revisione("OFF_ADC_26/0441_R00") == "OFF_ADC_26/0441_R01"
    assert prossima_revisione("OFF_ADC_26/0313_R09") == "OFF_ADC_26/0313_R10"
    assert prossima_revisione("OFF_SENZA_REVISIONE") == "OFF_SENZA_REVISIONE"


def test_date_aggiornate_al_rinnovo(offerta_vecchia):
    percorso, _ = offerta_vecchia
    letta = read_offer(percorso)
    form = aggiorna_per_rinnovo(letta, giorni_validita=45, oggi=date(2026, 9, 1))
    assert form["data_offerta"] == "01/09/2026"
    assert form["validita_offerta"] == "16/10/2026"
    assert form["riferimento_offerta"].endswith("_R04")
    assert form["cliente"] == letta.form["cliente"]


def test_prezzi_ripresi_senza_ricalcolo(offerta_vecchia, form_data):
    percorso, originale = offerta_vecchia
    letta = read_offer(percorso)
    prep = prepare_offer([bom_da_offerta(letta)], dict(form_data, servizi_aggiuntivi=[]))

    assert prep.offer.totals.total_net == originale.offer.totals.total_net
    assert all(i.pricing_mode == "rinnovo" for i in prep.offer.items if i.sell_net_total)


def test_adeguamento_percentuale(offerta_vecchia, form_data):
    percorso, originale = offerta_vecchia
    letta = read_offer(percorso)
    prep = prepare_offer(
        [bom_da_offerta(letta)],
        dict(form_data, servizi_aggiuntivi=[], adeguamento_percent="10"),
    )
    atteso = (originale.offer.totals.total_net * Decimal("1.10")).quantize(Decimal("0.01"))
    assert abs(prep.offer.totals.total_net - atteso) <= Decimal("0.10")


def test_margine_non_calcolabile_senza_costi(offerta_vecchia, form_data):
    """L'offerta non riporta i costi: meglio dirlo che scrivere 100%."""
    percorso, _ = offerta_vecchia
    letta = read_offer(percorso)
    prep = prepare_offer([bom_da_offerta(letta)], dict(form_data, servizi_aggiuntivi=[]))

    totali = prep.offer.totals
    assert not totali.margin_known
    assert totali.rows_without_cost == len(prep.offer.items)
    assert totali.margin_percent == Decimal("0")
    assert all(i.margin_percent is None for i in prep.offer.items)


def test_qa_spiega_il_margine_mancante(offerta_vecchia, form_data):
    from offerta_builder.qa import LEVEL_WARN, run_qa

    percorso, _ = offerta_vecchia
    letta = read_offer(percorso)
    prep = prepare_offer([bom_da_offerta(letta)], dict(form_data, servizi_aggiuntivi=[]))
    report = run_qa(prep.offer, prep.form, document_text="")
    check = next(c for c in report.checks if c.id == "qa.margine")
    assert check.level == LEVEL_WARN
    assert "non calcolabile" in check.message


def test_rinnovo_completo_sul_template_corrente(tmp_path, offerta_vecchia, template_path, form_data):
    percorso, _ = offerta_vecchia
    letta = read_offer(percorso)
    form = aggiorna_per_rinnovo(letta, giorni_validita=30, oggi=date(2026, 9, 1))
    form.update({"iva_percento": 22, "margine_minimo_percento": 30, "servizi_aggiuntivi": []})

    result = build_offer(
        boms=[bom_da_offerta(letta)], form=form, output_dir=str(tmp_path / "nuova"),
        template_path=template_path,
    )
    from offerta_builder.docx_builder import extract_text

    testo = extract_text(result.outputs["docx"])
    assert "01/09/2026" in testo          # data aggiornata
    assert "OFF_ADC_26/0313_R04" in testo  # revisione incrementata
    assert result.qa.status != "fail"


# ---------------------------------------------------------------- interfaccia

def test_endpoint_offerta_precedente(tmp_path, offerta_vecchia):
    from offerta_builder.web.app import create_app

    percorso, _ = offerta_vecchia
    app = create_app(work_root=str(tmp_path / "sessioni"))
    app.config.update(TESTING=True)
    with app.test_client() as client:
        with open(percorso, "rb") as handle:
            risposta = client.post(
                "/api/offerta-precedente",
                data={"offerta": (io.BytesIO(handle.read()), "vecchia.docx"), "giorni_validita": "60"},
                content_type="multipart/form-data",
            ).get_json()

        assert risposta["stato"] == "ok"
        assert risposta["righe"] >= 4
        assert risposta["form"]["cliente"] == "BPER BANCA SPA"
        assert risposta["form"]["riferimento_offerta"].endswith("_R04")

        anteprima = client.post(
            "/api/anteprima",
            json={"session": risposta["session"], "form": dict(risposta["form"], iva_percento=22,
                                                               margine_minimo_percento=30)},
        ).get_json()
        assert anteprima["stato"] == "ok"
        assert anteprima["totali"]["margine"] == "non calcolabile"


def test_endpoint_rifiuta_file_non_docx(tmp_path):
    from offerta_builder.web.app import create_app

    app = create_app(work_root=str(tmp_path / "sessioni"))
    app.config.update(TESTING=True)
    with app.test_client() as client:
        risposta = client.post(
            "/api/offerta-precedente",
            data={"offerta": (io.BytesIO(b"non e' un docx"), "vecchia.pdf")},
            content_type="multipart/form-data",
        )
        assert risposta.status_code == 400


def test_qa_avvisa_che_i_prezzi_non_sono_riverificati(offerta_vecchia, form_data):
    """Nel rinnovo non c'è una quotazione distributore con cui confrontarsi."""
    from offerta_builder.qa import LEVEL_WARN, run_qa

    percorso, _ = offerta_vecchia
    letta = read_offer(percorso)
    prep = prepare_offer([bom_da_offerta(letta)], dict(form_data, servizi_aggiuntivi=[]))
    report = run_qa(prep.offer, prep.form, document_text="")
    check = next(c for c in report.checks if c.id == "qa.validita_bom")
    assert check.level == LEVEL_WARN
    assert "distributore" in check.message


def test_riga_inclusa_conservata_nel_rinnovo(tmp_path, csv_bom_path, form_data, template_path):
    """Una voce "Incluso" resta "Incluso" anche dopo il rinnovo."""
    form_data["righe_aggiuntive"] = [
        {"descrizione": "ADCare - Backup", "quantita": 1, "prezzo_unitario": "Incluso"}
    ]
    prima = build_offer(
        bom_paths=[csv_bom_path], form=form_data, output_dir=str(tmp_path / "prima"),
        template_path=template_path,
    )
    letta = read_offer(prima.outputs["docx"])
    riga = next(r for r in letta.righe if "ADCare" in r["descrizione"])
    assert riga["prezzo_testo"] == "Incluso"

    prep = prepare_offer([bom_da_offerta(letta)], dict(form_data, righe_aggiuntive=[], servizi_aggiuntivi=[]))
    rinnovata = next(i for i in prep.offer.items if "ADCare" in i.description)
    assert rinnovata.display_price == "Incluso"
    assert rinnovata.sell_net_total == 0
