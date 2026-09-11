#!/usr/bin/env python3
"""exporter.py : instantané de l'état, pour le back-office.

Le back-office ne lit jamais les fichiers d'état directement : il lit ce que ce
module produit. La séparation a une raison précise. Aujourd'hui l'instantané est
un fichier JSON écrit sur disque et la page s'ouvre en local. Demain le serveur
FastAPI servira exactement la même structure sur `/api/etat`, et la page n'aura
pas une ligne à changer.

Les vignettes sont embarquées en data URI plutôt que référencées par chemin :
l'instantané reste lisible depuis n'importe où, y compris si on veut le montrer
à quelqu'un qui n'a pas les fichiers.

Usage :
    python3 exporter.py
    python3 exporter.py --sortie ../backoffice/donnees.json --largeur-vignette 380

Cible Python 3.9+. Dépendances : Pillow.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from PIL import Image

from etat import ETATS_CREA, RACINE_DEFAUT, Commande, ardoise

SORTIE_DEFAUT = Path(__file__).resolve().parent.parent / "backoffice" / "donnees.json"
LARGEUR_VIGNETTE = 380
QUALITE_VIGNETTE = 76
JOURNAL_MAX = 200


def vignette(chemin: Path, largeur: int = LARGEUR_VIGNETTE) -> Optional[str]:
    """Réduit une image et l'encode en data URI JPEG."""
    if not chemin.exists():
        return None
    image = Image.open(chemin).convert("RGB")
    ratio = largeur / image.size[0]
    image = image.resize((largeur, max(1, round(image.size[1] * ratio))), Image.LANCZOS)
    tampon = io.BytesIO()
    image.save(tampon, "JPEG", quality=QUALITE_VIGNETTE, optimize=True)
    donnees = base64.b64encode(tampon.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{donnees}"


def lire_journal(dossier: Path) -> List[dict]:
    fichier = dossier / "journal.jsonl"
    if not fichier.exists():
        return []
    lignes = []
    for ligne in fichier.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne:
            continue
        try:
            lignes.append(json.loads(ligne))
        except json.JSONDecodeError:
            # Une ligne corrompue ne doit pas faire tomber tout le back-office :
            # c'est justement quand ça casse qu'on a besoin de le regarder.
            lignes.append({"horodatage": "", "evenement": "ligne_illisible", "brut": ligne[:200]})
    return lignes[-JOURNAL_MAX:][::-1]


def exporter_commande(commande: Commande, largeur: int) -> dict:
    creas = commande.creas()

    compteurs: Dict[str, int] = {etat: 0 for etat in ETATS_CREA}
    for crea in creas:
        compteurs[crea.etat] = compteurs.get(crea.etat, 0) + 1

    creas_exportees = []
    for crea in creas:
        vignettes = {}
        for format_cible, chemin_relatif in crea.rendus.items():
            image = vignette(commande.dossier / chemin_relatif, largeur)
            if image:
                vignettes[format_cible] = image
        creas_exportees.append({
            "identifiant": crea.identifiant,
            "angle": crea.angle,
            "etat": crea.etat,
            "copy": {
                "accroche": crea.copy.accroche,
                "sous_accroche": crea.copy.sous_accroche,
                "cta": crea.copy.cta,
                "badge": crea.copy.badge,
            },
            "prompt": {"scene": crea.prompt.scene, "negatif": crea.prompt.negatif},
            "master": crea.master,
            "audit": crea.audit,
            "tours": crea.tours,
            "vignettes": vignettes,
        })

    donnees = commande.donnees
    retenues = compteurs.get("retenue", 0)
    a_livrer = donnees["quantite_vendue"]

    return {
        "marque": donnees["marque"],
        "ardoise": donnees["ardoise"],
        "url_site": donnees["url_site"],
        "pack": donnees["pack"],
        "quantite_vendue": a_livrer,
        "quantite_generee": donnees["quantite_generee"],
        "etat": donnees["etat"],
        "demonstration": donnees.get("demonstration", False),
        "strategie_source": donnees.get("strategie_source"),
        "tours_revision_restants": donnees.get("tours_revision_restants", 0),
        "cree_le": donnees["cree_le"],
        "modifie_le": donnees["modifie_le"],
        "compteurs": compteurs,
        "selection": {
            "retenues": retenues,
            "a_livrer": a_livrer,
            "suffisante": retenues >= a_livrer,
            "manquantes": max(0, a_livrer - retenues),
        },
        "creas": creas_exportees,
        "journal": lire_journal(commande.dossier),
    }


def exporter(racine: Path = RACINE_DEFAUT, largeur: int = LARGEUR_VIGNETTE) -> dict:
    commandes = []
    if racine.exists():
        for dossier in sorted(racine.iterdir()):
            if not (dossier / "commande.json").exists():
                continue
            commande = Commande.charger(dossier.name, racine=racine)
            commandes.append(exporter_commande(commande, largeur))

    return {
        "genere_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "commandes": commandes,
    }


def main() -> int:
    parseur = argparse.ArgumentParser(description="Exporte l'état pour le back-office")
    parseur.add_argument("--sortie", default=str(SORTIE_DEFAUT))
    parseur.add_argument("--largeur-vignette", type=int, default=LARGEUR_VIGNETTE)
    arguments = parseur.parse_args()

    instantane = exporter(largeur=arguments.largeur_vignette)
    sortie = Path(arguments.sortie)
    sortie.parent.mkdir(parents=True, exist_ok=True)
    serialise = json.dumps(instantane, ensure_ascii=False)
    sortie.write_text(serialise, encoding="utf-8")

    # Doublon en JavaScript : ouverte en double-clic, la page est en file://, où
    # fetch est refusé par la politique d'origine. Une balise script, elle,
    # passe. Le serveur FastAPI servira le JSON, la page sait lire les deux.
    jumeau = sortie.with_suffix(".js")
    jumeau.write_text(f"window.DONNEES = {serialise};\n", encoding="utf-8")

    poids = sortie.stat().st_size / 1024
    total_creas = sum(len(c["creas"]) for c in instantane["commandes"])
    print(f"{len(instantane['commandes'])} commande(s), {total_creas} créa(s) "
          f"-> {sortie} ({poids:.0f} Ko)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
