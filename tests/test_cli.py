import json
import os

from offerta_builder.cli import EXIT_BLOCKED, EXIT_OK, main


def test_form_init_crea_il_modello(tmp_path):
    target = tmp_path / "form.json"
    assert main(["form-init", "-o", str(target)]) == EXIT_OK
    data = json.loads(target.read_text(encoding="utf-8"))
    assert "cliente" in data and "pricing" in data


def test_form_init_precompila_dalla_bom(tmp_path, csv_bom_path):
    target = tmp_path / "form.json"
    main(["form-init", "-o", str(target), "--bom", csv_bom_path])
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["cliente"] == "BPER Banca S.p.A"


def test_comando_bom_scrive_il_json(tmp_path, csv_bom_path):
    target = tmp_path / "bom.json"
    assert main(["bom", csv_bom_path, "-o", str(target)]) == EXIT_OK
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["boms"][0]["distributor"] == "V-Valley"
    assert len(data["boms"][0]["items"]) == 4


def test_comando_bom_segnala_anomalie_bloccanti(tmp_path):
    bom = tmp_path / "bom.csv"
    bom.write_text("Codice;Descrizione;Q.ta\nAAA;Licenza;1\n", encoding="utf-8")
    assert main(["bom", str(bom), "-o", str(tmp_path / "out.json")]) == EXIT_BLOCKED


def test_build_da_cli(tmp_path, csv_bom_path, form_data):
    form_path = tmp_path / "form.json"
    form_path.write_text(json.dumps(form_data), encoding="utf-8")
    out_dir = tmp_path / "out"
    code = main([
        "build", "--bom", csv_bom_path, "--form", str(form_path),
        "-o", str(out_dir), "--modo", "markup", "--markup", "45",
    ])
    assert code == EXIT_OK
    assert os.path.exists(out_dir / "offerta.docx")
    assert os.path.exists(out_dir / "controlli_qa.json")


def test_build_senza_form_si_ferma(tmp_path, csv_bom_path):
    assert main(["build", "--bom", csv_bom_path, "-o", str(tmp_path)]) == EXIT_BLOCKED


def test_build_con_form_incompleto_si_ferma(tmp_path, csv_bom_path, form_data):
    form_data["riferimento_offerta"] = ""
    form_path = tmp_path / "form.json"
    form_path.write_text(json.dumps(form_data), encoding="utf-8")
    code = main(["build", "--bom", csv_bom_path, "--form", str(form_path), "-o", str(tmp_path)])
    assert code == EXIT_BLOCKED


def test_form_init_crea_le_cartelle_mancanti(tmp_path):
    target = tmp_path / "offerte" / "bper" / "form.json"
    assert main(["form-init", "-o", str(target)]) == EXIT_OK
    assert target.exists()


def test_bom_crea_le_cartelle_mancanti(tmp_path, csv_bom_path):
    target = tmp_path / "nuova" / "bom.json"
    assert main(["bom", csv_bom_path, "-o", str(target)]) == EXIT_OK
    assert target.exists()
