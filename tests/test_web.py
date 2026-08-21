import io
import os

import pytest

from offerta_builder.web.app import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(work_root=str(tmp_path / "sessioni"))
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client


def carica_bom(client, csv_bom_path, session=""):
    with open(csv_bom_path, "rb") as handle:
        contenuto = handle.read()
    return client.post(
        "/api/upload",
        data={
            "session": session,
            "bom": (io.BytesIO(contenuto), os.path.basename(csv_bom_path)),
        },
        content_type="multipart/form-data",
    )


def test_pagina_iniziale(client):
    risposta = client.get("/")
    assert risposta.status_code == 200
    assert b"Offerta Builder" in risposta.data


def test_schema_espone_i_campi_del_form(client):
    dati = client.get("/api/schema").get_json()
    nomi = {campo["nome"] for campo in dati["campi"]}
    assert {"cliente", "piva", "riferimento_offerta", "margine_minimo_percento"} <= nomi
    assert "target_margin" in dati["modalita_prezzo"]
    assert ".pdf" in dati["estensioni_bom"]


def test_upload_bom_restituisce_righe_e_prefill(client, csv_bom_path):
    dati = carica_bom(client, csv_bom_path).get_json()
    assert dati["session"]
    assert len(dati["boms"]) == 1
    bom = dati["boms"][0]
    assert bom["distributore"] == "V-Valley"
    assert bom["righe"] == 4
    assert bom["costo"] == "18.924,56 €"
    assert len(bom["articoli"]) == 4
    assert dati["prefill"]["cliente"] == "BPER Banca S.p.A"
    assert dati["errori"] == []


def test_upload_rifiuta_estensioni_non_ammesse(client):
    risposta = client.post(
        "/api/upload",
        data={"bom": (io.BytesIO(b"contenuto"), "malware.exe")},
        content_type="multipart/form-data",
    )
    dati = risposta.get_json()
    assert dati["boms"] == []
    assert any("estensione non ammessa" in errore for errore in dati["errori"])


def test_anteprima_calcola_lato_server(client, csv_bom_path, form_data):
    session = carica_bom(client, csv_bom_path).get_json()["session"]
    dati = client.post("/api/anteprima", json={"session": session, "form": form_data}).get_json()
    assert dati["stato"] == "ok"
    assert dati["totali"]["costo"] == "18.924,56 €"
    assert len(dati["righe"]) == 4
    assert dati["righe"][0]["prezzo_unitario"].endswith("€")


def test_anteprima_con_deroga_manuale(client, csv_bom_path, form_data):
    session = carica_bom(client, csv_bom_path).get_json()["session"]
    form_data["pricing"] = {
        "mode": "markup",
        "markup_percent": "40",
        "rounding": "0.01",
        "overrides": [{"match": "2078005", "sell_net_unit": "12.500,00"}],
    }
    dati = client.post("/api/anteprima", json={"session": session, "form": form_data}).get_json()
    riga = next(r for r in dati["righe"] if r["sku"] == "2078005")
    assert riga["prezzo_unitario"] == "12.500,00 €"
    assert riga["modalita"] == "manual"


def test_anteprima_segnala_il_form_incompleto(client, csv_bom_path):
    session = carica_bom(client, csv_bom_path).get_json()["session"]
    dati = client.post(
        "/api/anteprima", json={"session": session, "form": {"cliente": "X"}, "force": False}
    ).get_json()
    assert dati["stato"] == "bloccato"
    assert any(a["code"] == "form.missing_required" for a in dati["anomalie"])


def test_genera_produce_i_file_e_il_qa(client, csv_bom_path, form_data):
    session = carica_bom(client, csv_bom_path).get_json()["session"]
    dati = client.post("/api/genera", json={"session": session, "form": form_data}).get_json()
    assert dati["stato"] == "ok"
    assert dati["qa"]["status"] in {"ok", "warn"}
    chiavi = {file["chiave"] for file in dati["file"]}
    assert {"docx", "bom", "qa", "data", "report"} <= chiavi
    assert "pdf" not in chiavi  # niente PDF se non richiesto

    docx = next(file for file in dati["file"] if file["chiave"] == "docx")
    scaricato = client.get(docx["url"])
    assert scaricato.status_code == 200
    assert scaricato.data[:2] == b"PK"  # è un vero .docx


def test_genera_si_ferma_su_form_incompleto(client, csv_bom_path, form_data):
    session = carica_bom(client, csv_bom_path).get_json()["session"]
    form_data["condizioni_pagamento"] = ""
    dati = client.post("/api/genera", json={"session": session, "form": form_data}).get_json()
    assert dati["stato"] == "bloccato"
    assert any(a["code"] == "form.missing_required" for a in dati["anomalie"])


def test_download_zip(client, csv_bom_path, form_data):
    session = carica_bom(client, csv_bom_path).get_json()["session"]
    client.post("/api/genera", json={"session": session, "form": form_data})
    risposta = client.get(f"/download/{session}/tutto")
    assert risposta.status_code == 200
    assert risposta.data[:2] == b"PK"


def test_download_chiave_sconosciuta(client, csv_bom_path, form_data):
    session = carica_bom(client, csv_bom_path).get_json()["session"]
    client.post("/api/genera", json={"session": session, "form": form_data})
    assert client.get(f"/download/{session}/inesistente").status_code == 404


def test_sessione_scaduta(client):
    risposta = client.post("/api/anteprima", json={"session": "non-esiste", "form": {}})
    assert risposta.status_code == 410


def test_rimozione_bom(client, csv_bom_path):
    session = carica_bom(client, csv_bom_path).get_json()["session"]
    dati = client.post("/api/rimuovi-bom", json={"session": session, "indice": 0}).get_json()
    assert dati["boms"] == []


def test_nuova_offerta_azzera_la_sessione(client, csv_bom_path):
    session = carica_bom(client, csv_bom_path).get_json()["session"]
    nuova = client.post("/api/nuova", json={"session": session}).get_json()["session"]
    assert nuova != session
    assert client.post("/api/anteprima", json={"session": session, "form": {}}).status_code == 410


def test_static_serviti(client):
    for percorso, atteso in [("/static/app.js", b"raccogliForm"), ("/static/style.css", b"--accent")]:
        risposta = client.get(percorso)
        assert risposta.status_code == 200
        assert atteso in risposta.data


def test_javascript_sintatticamente_valido():
    """Guardia contro modifiche di massa che rompono le stringhe del frontend."""
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node non disponibile")
    percorso = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "offerta_builder", "web", "static", "app.js",
    )
    esito = subprocess.run([node, "--check", percorso], capture_output=True)
    assert esito.returncode == 0, esito.stderr.decode("utf-8", "replace")


def test_schema_espone_i_valori_proposti_per_le_condizioni(client):
    campi = {campo["nome"]: campo for campo in client.get("/api/schema").get_json()["campi"]}
    assert "30 gg fine mese" in campi["condizioni_pagamento"]["suggerimenti"]
    assert "Bonifico bancario" in campi["tipologia_pagamento"]["suggerimenti"]
    assert "Annuale anticipata" in campi["fatturazione"]["suggerimenti"]
    assert campi["durata_contratto_anni"]["suggerimenti"] == ["1", "2", "3", "4", "5"]
    # restano proposte, non un elenco chiuso
    assert campi["condizioni_pagamento"]["scelte"] == []


def test_anteprima_con_righe_modificate(client, csv_bom_path, form_data):
    session = carica_bom(client, csv_bom_path).get_json()["session"]
    form_data["righe"] = [
        {"indice": 0, "riferimento": "2078005", "quantita": "3",
         "descrizione": "SolarWinds NPM SLX (rinnovo)"},
        {"indice": 1, "riferimento": "2078012", "escludi": True},
    ]
    dati = client.post("/api/anteprima", json={"session": session, "form": form_data}).get_json()

    righe = {riga["indice"]: riga for riga in dati["righe"]}
    assert righe[0]["descrizione"] == "SolarWinds NPM SLX (rinnovo)"
    assert righe[0]["quantita"] == "3"
    assert righe[0]["costo"] == "29.247,90 €"   # il costo segue la quantità
    assert righe[0]["modificata"] is True
    assert righe[1]["esclusa"] is True            # resta visibile, per poterla rimettere
    assert righe[2]["numero"] == 2                # la numerazione salta la riga esclusa


def test_riga_esclusa_non_finisce_nel_documento(client, csv_bom_path, form_data):
    from offerta_builder.docx_builder import extract_text

    session = carica_bom(client, csv_bom_path).get_json()["session"]
    form_data["righe"] = [{"indice": 1, "riferimento": "2078012", "escludi": True}]
    client.post("/api/genera", json={"session": session, "form": form_data})
    store = client.application.extensions["offerta_sessions"]
    docx = os.path.join(store.get(session).output_dir, "offerta.docx")
    testo = extract_text(docx)
    assert "2078005" in testo
    assert "2078012" not in testo


def test_modifica_di_riga_non_tocca_le_altre(client, csv_bom_path, form_data):
    """Stesso codice ripetuto su piu' righe: la modifica vale solo sulla sua."""
    session = carica_bom(client, csv_bom_path).get_json()["session"]
    form_data["righe"] = [{"indice": 0, "riferimento": "2078005", "prezzo_unitario": "12.500,00"}]
    dati = client.post("/api/anteprima", json={"session": session, "form": form_data}).get_json()
    righe = {riga["indice"]: riga for riga in dati["righe"]}
    assert righe[0]["prezzo_unitario"] == "12.500,00 €"
    assert righe[1]["prezzo_unitario"] != "12.500,00 €"


def test_margine_sotto_soglia_non_blocca_la_generazione(client, csv_bom_path, form_data):
    form_data["margine_minimo_percento"] = 80          # irraggiungibile
    form_data["pricing"] = {"mode": "markup", "markup_percent": "10", "rounding": "0.01"}
    session = carica_bom(client, csv_bom_path).get_json()["session"]
    dati = client.post("/api/genera", json={"session": session, "form": form_data}).get_json()
    assert dati["stato"] == "ok"
    assert dati["qa"]["status"] == "warn"
    assert any(file["chiave"] == "docx" for file in dati["file"])


def test_versione_esposta_e_allineata(client):
    """La versione mostrata deve essere quella del pacchetto installato."""
    import tomllib

    from offerta_builder import __version__

    assert client.get("/api/schema").get_json()["versione"] == __version__
    assert f"v{__version__}".encode() in client.get("/").data

    percorso = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pyproject.toml"
    )
    with open(percorso, "rb") as handle:
        assert tomllib.load(handle)["project"]["version"] == __version__
