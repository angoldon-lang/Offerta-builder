import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples")
TEMPLATES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")


@pytest.fixture
def csv_bom_path():
    return os.path.join(EXAMPLES, "bom_vvalley_solarwinds.csv")


@pytest.fixture
def template_path():
    return os.path.join(TEMPLATES, "offerta_ad_template.docx")


@pytest.fixture
def form_data():
    """Form valido minimo, senza servizi, per i test end-to-end."""
    return {
        "cliente": "BPER BANCA SPA",
        "piva": "03830780361",
        "referente": "Serena Piantoni",
        "oggetto": "Fornitura Soluzione SolarWinds",
        "autore": "Andrea Goldoni",
        "riferimento_offerta": "OFF_ADC_26/0313_R03",
        "data_offerta": "19/07/2026",
        "validita_offerta": "31/07/2026",
        "tipologia_pagamento": "Bonifico bancario",
        "condizioni_pagamento": "30 gg fine mese",
        "fatturazione": "Annuale anticipata",
        "durata_contratto_anni": 3,
        "iva_percento": 22,
        "margine_minimo_percento": 20,
        "rinnovo": "da concordare",
        "servizi_aggiuntivi": [],
        "pricing": {"mode": "markup", "markup_percent": 40, "rounding": "0.01"},
    }
