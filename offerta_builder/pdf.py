"""Conversione DOCX -> PDF tramite LibreOffice headless."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import Optional


class PdfConversionError(RuntimeError):
    pass


def find_soffice() -> Optional[str]:
    for candidate in ("soffice", "libreoffice"):
        path = shutil.which(candidate)
        if path:
            return path
    return None


def docx_to_pdf(docx_path: str, output_path: str, timeout: int = 180) -> str:
    """Converte il DOCX in PDF. Solleva ``PdfConversionError`` se non riesce."""
    soffice = find_soffice()
    if not soffice:
        raise PdfConversionError(
            "LibreOffice non trovato: installa 'libreoffice' oppure genera il PDF manualmente dal DOCX."
        )
    output_dir = os.path.dirname(os.path.abspath(output_path)) or "."
    os.makedirs(output_dir, exist_ok=True)
    with tempfile.TemporaryDirectory() as workdir:
        command = [
            soffice, "--headless", "--norestore",
            f"-env:UserInstallation=file://{workdir}/profile",
            "--convert-to", "pdf", "--outdir", workdir, os.path.abspath(docx_path),
        ]
        try:
            completed = subprocess.run(command, capture_output=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise PdfConversionError(f"Conversione PDF oltre il timeout di {timeout}s.") from exc
        produced = os.path.join(
            workdir, os.path.splitext(os.path.basename(docx_path))[0] + ".pdf"
        )
        if not os.path.exists(produced):
            raise PdfConversionError(
                "Conversione PDF non riuscita: "
                + (completed.stderr.decode("utf-8", "replace").strip() or "nessun output da LibreOffice")
            )
        shutil.copyfile(produced, output_path)
    return output_path
