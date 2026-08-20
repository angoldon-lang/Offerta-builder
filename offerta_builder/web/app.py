"""Applicazione web locale: upload BOM e template, form, anteprima, generazione.

È un guscio sottile attorno alla stessa pipeline usata dalla CLI: la UI raccoglie
i dati e mostra i risultati, ma **tutti i calcoli restano nel backend**
(``pricing``, ``qa``), esattamente come da riga di comando.

Pensata per girare in locale (``offerta web``): ascolta su 127.0.0.1 e tiene i
file di lavoro in una cartella temporanea per sessione.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence

from flask import Flask, jsonify, render_template, request, send_file

from ..bom import normalize
from ..bom.reader import SUPPORTED_EXTENSIONS
from ..form import FIELDS, blank_form, prefill_from_bom
from ..models import NormalizedBom
from ..money import format_eur, format_number, format_percent
from ..pipeline import BlockingError, build_offer, prepare_offer
from ..pricing import MODES, ROUNDING_STEPS

TEMPLATE_EXTENSIONS = {".docx"}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
SESSION_TTL_SECONDS = 12 * 3600


@dataclass
class Session:
    """Stato di lavorazione di una singola offerta."""

    id: str
    directory: str
    boms: List[NormalizedBom] = field(default_factory=list)
    bom_files: List[Dict[str, Any]] = field(default_factory=list)
    template_path: str = ""
    template_name: str = ""
    outputs: Dict[str, str] = field(default_factory=dict)
    touched_at: float = field(default_factory=time.time)

    @property
    def input_dir(self) -> str:
        return os.path.join(self.directory, "input")

    @property
    def output_dir(self) -> str:
        return os.path.join(self.directory, "out")


class SessionStore:
    """Sessioni in memoria: l'app è locale e monoutente."""

    def __init__(self, root: Optional[str] = None):
        self.root = root or tempfile.mkdtemp(prefix="offerta-web-")
        self._sessions: Dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(self) -> Session:
        import secrets

        session_id = secrets.token_urlsafe(12)
        directory = os.path.join(self.root, session_id)
        os.makedirs(os.path.join(directory, "input"), exist_ok=True)
        os.makedirs(os.path.join(directory, "out"), exist_ok=True)
        session = Session(id=session_id, directory=directory)
        with self._lock:
            self._sessions[session_id] = session
            self._evict_expired()
        return session

    def get(self, session_id: str) -> Optional[Session]:
        with self._lock:
            session = self._sessions.get(session_id or "")
            if session is not None:
                session.touched_at = time.time()
            return session

    def require(self, session_id: str) -> Session:
        session = self.get(session_id)
        if session is None:
            raise LookupError("Sessione non trovata o scaduta: ricarica la pagina.")
        return session

    def drop(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.pop(session_id or "", None)
        if session is not None:
            shutil.rmtree(session.directory, ignore_errors=True)

    def _evict_expired(self) -> None:
        limit = time.time() - SESSION_TTL_SECONDS
        for session_id, session in list(self._sessions.items()):
            if session.touched_at < limit:
                self._sessions.pop(session_id, None)
                shutil.rmtree(session.directory, ignore_errors=True)


def create_app(work_root: Optional[str] = None) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
    app.config["JSON_SORT_KEYS"] = False
    store = SessionStore(work_root)
    app.extensions["offerta_sessions"] = store

    # ---------------------------------------------------------------- pagina
    @app.get("/")
    def index():
        return render_template("index.html")

    # ---------------------------------------------------------------- schema
    @app.get("/api/schema")
    def schema():
        return jsonify(
            {
                "campi": [
                    {
                        "nome": spec.name,
                        "etichetta": spec.label,
                        "tipo": spec.kind,
                        "obbligatorio": spec.required,
                        "esempio": spec.example,
                        "scelte": list(spec.choices),
                        "suggerimenti": list(spec.suggestions),
                        "aiuto": spec.help,
                        "default": str(spec.default) if spec.default is not None else "",
                    }
                    for spec in FIELDS
                ],
                "modalita_prezzo": sorted(MODES),
                "arrotondamenti": list(ROUNDING_STEPS.keys()),
                "form_vuoto": blank_form(),
                "estensioni_bom": sorted(SUPPORTED_EXTENSIONS),
                "estensioni_template": sorted(TEMPLATE_EXTENSIONS),
                "oggi": date.today().strftime("%d/%m/%Y"),
            }
        )

    # ---------------------------------------------------------------- upload
    @app.post("/api/upload")
    def upload():
        session_id = request.form.get("session", "")
        session = store.get(session_id) or store.create()

        errors: List[str] = []
        for uploaded in request.files.getlist("bom"):
            if not uploaded or not uploaded.filename:
                continue
            saved = _save_upload(uploaded, session.input_dir, SUPPORTED_EXTENSIONS, errors)
            if not saved:
                continue
            try:
                bom = normalize(saved)
            except Exception as exc:  # file illeggibile o corrotto
                errors.append(f"{os.path.basename(saved)}: {exc}")
                os.remove(saved)
                continue
            session.boms.append(bom)
            session.bom_files.append({"nome": os.path.basename(saved), "percorso": saved})

        template = request.files.get("template")
        if template and template.filename:
            saved = _save_upload(template, session.input_dir, TEMPLATE_EXTENSIONS, errors)
            if saved:
                session.template_path = saved
                session.template_name = os.path.basename(saved)

        return jsonify(
            {
                "session": session.id,
                "boms": [_bom_payload(bom) for bom in session.boms],
                "template": session.template_name,
                "prefill": _prefill(session.boms),
                "errori": errors,
            }
        )

    @app.post("/api/rimuovi-bom")
    def rimuovi_bom():
        payload = request.get_json(silent=True) or {}
        session = store.require(payload.get("session", ""))
        indice = int(payload.get("indice", -1))
        if 0 <= indice < len(session.boms):
            session.boms.pop(indice)
            rimosso = session.bom_files.pop(indice)
            try:
                os.remove(rimosso["percorso"])
            except OSError:
                pass
        return jsonify({"boms": [_bom_payload(bom) for bom in session.boms]})

    # ------------------------------------------------------------- anteprima
    @app.post("/api/anteprima")
    def anteprima():
        payload = request.get_json(silent=True) or {}
        session = store.require(payload.get("session", ""))
        if not session.boms:
            return jsonify({"stato": "vuoto", "messaggio": "Carica almeno una BOM."})
        try:
            prepared = prepare_offer(
                session.boms,
                payload.get("form") or {},
                pricing_overrides=None,
                force=bool(payload.get("force")),
            )
        except BlockingError as exc:
            return jsonify(
                {
                    "stato": "bloccato",
                    "messaggio": str(exc),
                    "anomalie": [i.to_dict() for i in exc.issues],
                }
            )
        return jsonify(
            {
                "stato": "ok",
                "totali": _totals_payload(prepared.offer),
                "righe": _lines_payload(prepared.offer),
                "annualita": [
                    {
                        "periodo": a.label,
                        "imponibile": format_eur(a.total_net),
                        "iva": format_eur(a.total_vat),
                        "totale": format_eur(a.total_gross),
                    }
                    for a in prepared.offer.annual
                ],
                "anomalie": [i.to_dict() for i in prepared.offer.issues + prepared.issues],
            }
        )

    # --------------------------------------------------------------- genera
    @app.post("/api/genera")
    def genera():
        payload = request.get_json(silent=True) or {}
        session = store.require(payload.get("session", ""))
        if not session.boms:
            return jsonify({"stato": "vuoto", "messaggio": "Carica almeno una BOM."})

        shutil.rmtree(session.output_dir, ignore_errors=True)
        os.makedirs(session.output_dir, exist_ok=True)
        try:
            result = build_offer(
                form=payload.get("form") or {},
                output_dir=session.output_dir,
                template_path=session.template_path or None,
                use_ai=bool(payload.get("ai")),
                force=bool(payload.get("force")),
                make_pdf=bool(payload.get("pdf")),
                boms=session.boms,
            )
        except BlockingError as exc:
            return jsonify(
                {
                    "stato": "bloccato",
                    "messaggio": str(exc),
                    "anomalie": [i.to_dict() for i in exc.issues],
                }
            )

        session.outputs = dict(result.outputs)
        return jsonify(
            {
                "stato": "ok",
                "qa": result.qa.to_dict(),
                "totali": _totals_payload(result.offer),
                "note": [i.to_dict() for i in result.issues],
                "file": [
                    {
                        "chiave": chiave,
                        "nome": os.path.basename(percorso),
                        "byte": os.path.getsize(percorso) if os.path.exists(percorso) else 0,
                        "url": f"/download/{session.id}/{chiave}",
                    }
                    for chiave, percorso in result.outputs.items()
                ],
                "zip": f"/download/{session.id}/tutto",
            }
        )

    # -------------------------------------------------------------- download
    @app.get("/download/<session_id>/<chiave>")
    def download(session_id: str, chiave: str):
        session = store.require(session_id)
        if chiave == "tutto":
            archivio = os.path.join(session.directory, "offerta.zip")
            with zipfile.ZipFile(archivio, "w", zipfile.ZIP_DEFLATED) as zf:
                for percorso in session.outputs.values():
                    if os.path.exists(percorso):
                        zf.write(percorso, os.path.basename(percorso))
            return send_file(archivio, as_attachment=True, download_name="offerta.zip")
        percorso = session.outputs.get(chiave)
        if not percorso or not os.path.exists(percorso):
            return jsonify({"errore": "File non disponibile: rigenera l'offerta."}), 404
        return send_file(percorso, as_attachment=True, download_name=os.path.basename(percorso))

    # ----------------------------------------------------------------- reset
    @app.post("/api/nuova")
    def nuova():
        payload = request.get_json(silent=True) or {}
        store.drop(payload.get("session", ""))
        return jsonify({"session": store.create().id})

    @app.errorhandler(LookupError)
    def sessione_mancante(exc: LookupError):
        return jsonify({"stato": "errore", "messaggio": str(exc)}), 410

    @app.errorhandler(413)
    def troppo_grande(_exc):
        limite = MAX_UPLOAD_BYTES // (1024 * 1024)
        return jsonify({"stato": "errore", "messaggio": f"File troppo grande (limite {limite} MB)."}), 413

    return app


# ---------------------------------------------------------------------------
# Helper di serializzazione: la UI riceve valori già formattati in italiano,
# così nessun calcolo o arrotondamento avviene nel browser.
# ---------------------------------------------------------------------------

def _save_upload(uploaded, destination: str, allowed: Sequence[str], errors: List[str]) -> str:
    from werkzeug.utils import secure_filename

    nome = secure_filename(uploaded.filename or "")
    if not nome:
        errors.append("Nome file non valido.")
        return ""
    estensione = os.path.splitext(nome)[1].lower()
    if estensione not in allowed:
        errors.append(f"{nome}: estensione non ammessa ({', '.join(sorted(allowed))}).")
        return ""
    os.makedirs(destination, exist_ok=True)
    percorso = os.path.join(destination, nome)
    base, ext = os.path.splitext(percorso)
    contatore = 2
    while os.path.exists(percorso):
        percorso = f"{base}_{contatore}{ext}"
        contatore += 1
    uploaded.save(percorso)
    return percorso


def _bom_payload(bom: NormalizedBom) -> Dict[str, Any]:
    return {
        "distributore": bom.distributor,
        "vendor": bom.vendor,
        "quote": bom.quote_number,
        "cliente_finale": bom.end_user,
        "validita": bom.valid_until,
        "formato": bom.source_format,
        "file": os.path.basename(bom.source_file),
        "special_bid": bom.meta.get("special_bid", ""),
        "periodo_contratto": bom.meta.get("periodo_contratto", ""),
        # Condizioni fra distributore e rivenditore: informative, non vengono
        # mai copiate nelle condizioni verso il cliente.
        "pagamento_distributore": bom.meta.get("payment_terms", ""),
        "righe": len(bom.items),
        "costo": format_eur(bom.total_cost()),
        "listino": format_eur(bom.total_list()),
        "anomalie": [i.to_dict() for i in bom.issues],
        "articoli": [
            {
                "n": item.line_no,
                "sku": item.sku,
                "descrizione": item.description,
                "periodo": item.period,
                "quantita": format_number(item.quantity),
                "listino": format_eur(item.list_price_total) if item.list_price_total is not None else "",
                "sconto": format_percent(item.discount_percent) if item.discount_percent is not None else "",
                "costo": format_eur(item.cost_net_total),
            }
            for item in bom.items
        ],
    }


def _prefill(boms: Sequence[NormalizedBom]) -> Dict[str, str]:
    """Campi proposti dalla BOM: stessa logica del flusso da riga di comando."""
    return {chiave: valore for chiave, valore in prefill_from_bom({}, boms).items() if valore}


def _totals_payload(offer) -> Dict[str, Any]:
    totals = offer.totals
    return {
        "listino": format_eur(totals.total_list),
        "costo": format_eur(totals.total_cost),
        "imponibile": format_eur(totals.total_net),
        "iva": format_eur(totals.total_vat),
        "totale": format_eur(totals.total_gross),
        "margine": format_eur(totals.margin_value),
        "margine_percento": format_percent(totals.margin_percent),
        "margine_valore": float(totals.margin_percent),
        "sconto_medio": format_percent(totals.average_discount_percent),
        "righe": len(offer.items),
    }


def _lines_payload(offer) -> List[Dict[str, Any]]:
    """Righe dell'offerta, comprese quelle escluse a mano (per poterle ripristinare)."""
    righe = [_line_payload(item) for item in offer.items]
    righe.extend(_line_payload(item, esclusa=True) for item in offer.excluded)
    righe.sort(key=lambda riga: riga["indice"])
    for posizione, riga in enumerate(r for r in righe if not r["esclusa"]):
        riga["numero"] = posizione + 1
    return righe


def _line_payload(item, esclusa: bool = False) -> Dict[str, Any]:
    return {
        "indice": item.source_index,
        "riferimento": item.source_reference,
        "esclusa": esclusa,
        "modificata": item.edited,
        "numero": 0,
        "sku": item.sku,
        "descrizione": item.description,
        "categoria": item.category,
        "periodo": item.period,
        "quantita": format_number(item.quantity),
        "quantita_valore": str(item.quantity),
        "costo": format_eur(item.cost_net_total),
        "costo_unitario": format_eur(item.cost_net_unit),
        "prezzo_unitario": format_eur(item.sell_net_unit),
        "prezzo_unitario_valore": float(item.sell_net_unit or Decimal("0")),
        "totale": format_eur(item.sell_net_total),
        "margine": format_eur(item.margin_value),
        "margine_percento": format_percent(item.margin_percent),
        "margine_valore": float(item.margin_percent or Decimal("0")),
        "modalita": item.pricing_mode,
    }


def run(host: str = "127.0.0.1", port: int = 8000, open_browser: bool = True, debug: bool = False) -> None:
    """Avvia il server locale (usato da ``offerta web``)."""
    app = create_app()
    url = f"http://{host}:{port}"
    print(f"Offerta Builder è in ascolto su {url}")
    print("Premi Ctrl+C per fermarlo.")
    if open_browser:
        import webbrowser

        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host=host, port=port, debug=debug, use_reloader=False)
