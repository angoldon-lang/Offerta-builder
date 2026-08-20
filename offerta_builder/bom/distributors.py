"""Riconoscimento del distributore e piccoli aggiustamenti per profilo.

Serve solo a etichettare la BOM e ad applicare default noti (valuta, colonna
di costo preferita). Nessun profilo modifica gli importi letti dal file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class DistributorProfile:
    name: str
    patterns: List[str] = field(default_factory=list)
    currency: str = "EUR"
    # Se il file espone sia netto unitario sia netto totale, quale considerare
    # autorevole in caso di incoerenza.
    cost_priority: str = "total"
    notes: str = ""


PROFILES: List[DistributorProfile] = [
    DistributorProfile("V-Valley", [r"v\s*-?\s*valley", r"vvalley"], notes="Esprinet group"),
    DistributorProfile("Computer Gross", [r"computer\s*gross", r"\bcgross\b", r"\bcg\s*spa\b"]),
    DistributorProfile("Esprinet", [r"esprinet"]),
    DistributorProfile("Ingram Micro", [r"ingram"]),
    DistributorProfile("TD SYNNEX", [r"td\s*synnex", r"tech\s*data", r"synnex"]),
    DistributorProfile("ALSO", [r"\balso\b"]),
    DistributorProfile("Attiva", [r"attiva\s*(spa|evolution)?"]),
    DistributorProfile("Icos", [r"\bicos\b"]),
]

GENERIC = DistributorProfile("Distributore non identificato", [])

VENDOR_HINTS = [
    "SolarWinds", "VMware", "Veeam", "Fortinet", "Cisco", "Microsoft", "Dell",
    "HPE", "Lenovo", "NetApp", "Citrix", "Nutanix", "Sophos", "Palo Alto",
    "Check Point", "Acronis", "Trend Micro", "Red Hat", "Commvault", "Rubrik",
    "Zerto", "Aruba", "Juniper", "Barracuda", "WatchGuard", "Kaspersky",
    "Arcserve", "Datto", "N-able", "Bitdefender", "ESET", "Ivanti", "SentinelOne",
    "Synology", "QNAP", "Wasabi", "Proofpoint", "Qualys", "Tenable", "Splunk",
    "Zscaler", "Crowdstrike", "Hornetsecurity", "Vertiv", "APC", "Eaton",
]


def detect_distributor(*texts: str) -> Optional[DistributorProfile]:
    haystack = " ".join(t for t in texts if t).lower()
    if not haystack:
        return None
    for profile in PROFILES:
        for pattern in profile.patterns:
            if re.search(pattern, haystack, re.IGNORECASE):
                return profile
    return None


def detect_vendor(*texts: str) -> str:
    """Riconosce il vendor citato nel documento.

    Il confronto e' su parola intera: senza, "Dell" verrebbe trovato dentro
    "dell'offerta" in qualunque quotazione italiana.
    """
    haystack = " ".join(t for t in texts if t)
    if not haystack:
        return ""
    conteggi = []
    for vendor in VENDOR_HINTS:
        pattern = r"(?<![\w'])" + re.escape(vendor) + r"(?![\w'])"
        occorrenze = len(re.findall(pattern, haystack, re.IGNORECASE))
        if occorrenze:
            conteggi.append((occorrenze, -VENDOR_HINTS.index(vendor), vendor))
    if not conteggi:
        return ""
    return max(conteggi)[2]


def profile_for(name: str) -> DistributorProfile:
    for profile in PROFILES:
        if profile.name.lower() == (name or "").lower():
            return profile
    return GENERIC
