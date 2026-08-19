from decimal import Decimal

from offerta_builder.form import blank_form, missing_required, prefill_from_bom, validate
from offerta_builder.models import SEVERITY_BLOCKING, NormalizedBom


def blocking(issues):
    return [i.code for i in issues if i.severity == SEVERITY_BLOCKING]


def test_form_vuoto_elenca_i_campi_obbligatori():
    mancanti = missing_required(blank_form())
    nomi = {spec.name for spec in mancanti}
    assert "cliente" in nomi and "riferimento_offerta" in nomi
    assert "iva_percento" not in nomi  # ha un default


def test_form_valido_non_produce_blocchi(form_data):
    clean, issues = validate(form_data)
    assert blocking(issues) == []
    assert clean["data_offerta_it"] == "19/07/2026"
    assert clean["iva_percento"] == Decimal("22")


def test_data_inesistente_blocca(form_data):
    form_data["validita_offerta"] = "31-9-2026"
    assert "form.date_invalid" in blocking(validate(form_data)[1])


def test_validita_precedente_alla_data_offerta(form_data):
    form_data["validita_offerta"] = "01/07/2026"
    assert "form.validity_before_offer" in blocking(validate(form_data)[1])


def test_piva_lunghezza_errata(form_data):
    form_data["piva"] = "12345"
    assert "form.piva_length" in blocking(validate(form_data)[1])


def test_piva_checksum_errato_e_solo_avviso(form_data):
    form_data["piva"] = "03830780362"
    codici = [i.code for i in validate(form_data)[1]]
    assert "form.piva_checksum" in codici
    assert blocking(validate(form_data)[1]) == []


def test_servizio_senza_prezzo_blocca(form_data):
    form_data["servizi_aggiuntivi"] = [{"descrizione": "Installazione"}]
    assert "form.service_no_price" in blocking(validate(form_data)[1])


def test_percentuale_fuori_range(form_data):
    form_data["margine_minimo_percento"] = 150
    assert "form.percent_out_of_range" in blocking(validate(form_data)[1])


def test_durata_non_intera(form_data):
    form_data["durata_contratto_anni"] = "tre"
    assert "form.int_invalid" in blocking(validate(form_data)[1])


def test_precompilazione_da_bom():
    bom = NormalizedBom(end_user="Acme_S.p.A", vendor="Veeam")
    data = prefill_from_bom({"cliente": "", "oggetto": ""}, [bom])
    assert data["cliente"] == "Acme S.p.A"
    assert data["oggetto"] == "Fornitura soluzione Veeam"


def test_precompilazione_non_sovrascrive():
    bom = NormalizedBom(end_user="Acme_S.p.A", vendor="Veeam")
    data = prefill_from_bom({"cliente": "BPER BANCA SPA"}, [bom])
    assert data["cliente"] == "BPER BANCA SPA"
