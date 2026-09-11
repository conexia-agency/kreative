#!/usr/bin/env python3
"""generation.py : produit les masters des créas briefées.

Le cahier des charges prévoit un appel direct à l'API Gemini vers Nano Banana
Pro. Cet endpoint est géobloqué depuis la Polynésie, et le pipeline tourne en
local à Tahiti. On passe donc par la CLI Higgsfield, qui expose le même modèle
sous le job type `nano_banana_2`. C'est aussi la seule voie utilisable sans
personne devant l'écran : le MCP Higgsfield réclame une authentification par
navigateur.

Un seul master par créa, toujours en 9:16. Les trois formats en sont ensuite
tirés par recadrage, sans nouvel appel au modèle. Générer trois fois donnerait
trois images différentes et violerait la règle du 4.2.

Usage :
    python3 generation.py --marque "Kreative" --estimer
    python3 generation.py --marque "Kreative"
    python3 generation.py --marque "Kreative" --creas c01 c02

Cible Python 3.9+.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import List, Optional

from etat import Commande, Crea

RACINE = Path(__file__).resolve().parent.parent
CHEMIN_ALOA = (
    RACINE.parent / "conexia" / "PRODUIT" / "caravage" / "skills" / "aloa-pack"
    / "aloa-design" / "scripts"
)
sys.path.insert(0, str(CHEMIN_ALOA))

import aloa_higgsfield as moteur  # noqa: E402

FORMAT_MASTER = "9:16"
RESOLUTION = "2k"


def construire_prompt(crea: Crea) -> str:
    """Le prompt envoyé au modèle, sans un caractère de plus.

    Rien n'est ajouté ici, et c'est délibéré. La consigne de cadrage est écrite
    par `strategie.py` DANS le champ `prompt.scene` au moment de la
    planification. Conséquence : ce que la commande `prompts` affiche est
    exactement ce qui part au modèle, à l'octet près, et un prompt corrigé à la
    main part tel qu'il a été corrigé.

    Un prompt assemblé au dernier moment serait invisible et non modifiable,
    ce qui est précisément le défaut qu'on cherche à supprimer.
    """
    return crea.prompt.rendu()


def a_generer(commande: Commande, filtre: Optional[List[str]]) -> List[Crea]:
    creas = [c for c in commande.creas() if c.etat == "briefee" and c.prompt.scene]
    if filtre:
        voulus = set(filtre)
        creas = [c for c in creas if c.identifiant in voulus]
    return creas


def estimer(commande: Commande, filtre: Optional[List[str]]) -> None:
    creas = a_generer(commande, filtre)
    if not creas:
        print("Aucune créa briefée en attente de génération.")
        return

    total = 0.0
    for crea in creas:
        bilan = moteur.cost(
            construire_prompt(crea),
            model=crea.prompt.modele,
            params={"aspect_ratio": FORMAT_MASTER, "resolution": RESOLUTION},
        )
        cout = bilan.get("credits") if isinstance(bilan, dict) else None
        if cout:
            total += float(cout)
        print(f"  {crea.identifiant} : {cout if cout is not None else 'inconnu'} crédits")

    solde = moteur.balance().get("credits")
    print(f"\nTotal estimé : {total:.2f} crédits pour {len(creas)} master(s).")
    if solde is not None:
        print(f"Solde : {solde} crédits.")


def generer(commande: Commande, filtre: Optional[List[str]]) -> int:
    creas = a_generer(commande, filtre)
    if not creas:
        print("Aucune créa briefée en attente de génération.")
        return 0

    dossier_masters = commande.dossier / "masters"
    dossier_masters.mkdir(parents=True, exist_ok=True)
    commande.passer_a("generation")

    produits = 0
    for crea in creas:
        print(f"  {crea.identifiant} ... ", end="", flush=True)
        resultat = moteur.generate(
            construire_prompt(crea),
            model=crea.prompt.modele,
            aspect_ratio=FORMAT_MASTER,
            resolution=RESOLUTION,
            out_dir=str(dossier_masters),
            campaign=commande.donnees["ardoise"],
        )

        if not resultat.ok or not resultat.path:
            print(f"échec : {resultat.error or 'sans détail'}")
            # L'échec est tracé et la créa reste briefée : elle sera reprise au
            # prochain passage. Une commande ne s'arrête pas sur une créa ratée.
            commande.tracer("generation_echec", crea=crea.identifiant,
                            erreur=(resultat.error or "")[:300], job=resultat.job_id)
            continue

        destination = dossier_masters / f"{crea.identifiant}.png"
        source = Path(resultat.path)
        if source.resolve() != destination.resolve():
            shutil.move(str(source), str(destination))

        crea.master = str(destination.relative_to(commande.dossier))
        crea.job_generation = resultat.job_id
        crea.etat = "master_ok"
        commande.ecrire_crea(crea)
        commande.tracer("master_genere", crea=crea.identifiant, job=resultat.job_id,
                        modele=crea.prompt.modele, credits=resultat.est_credits)
        produits += 1
        print(f"ok ({resultat.est_credits or '?'} crédits)")

    print(f"\n{produits} master(s) générés sur {len(creas)} demandés.")
    return produits


def main() -> int:
    parseur = argparse.ArgumentParser(description="Génère les masters des créas briefées")
    parseur.add_argument("--marque", required=True)
    parseur.add_argument("--creas", nargs="+", help="Limiter à ces identifiants")
    parseur.add_argument("--estimer", action="store_true",
                         help="Estimer le coût sans rien générer")
    arguments = parseur.parse_args()

    try:
        commande = Commande.charger(arguments.marque)
    except FileNotFoundError as erreur:
        print(f"Erreur : {erreur}", file=sys.stderr)
        return 1

    if arguments.estimer:
        estimer(commande, arguments.creas)
    else:
        generer(commande, arguments.creas)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
