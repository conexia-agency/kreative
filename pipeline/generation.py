#!/usr/bin/env python3
"""generation.py : le devis et la préparation des masters.

Ce module ne génère plus rien lui-même, et c'est la correction d'une erreur
d'architecture. Il importait `aloa_higgsfield`, le moteur du pack aloa, ce que
la décision du 11/09 interdit : Kreative vend des créas Meta, donc concurrence
aloa, et livrer le moteur de Conexia à un concurrent est un problème commercial
avant d'être technique.

La génération passe désormais par le connecteur MCP Higgsfield, qui n'existe que
dans une session Claude. Le découpage vit dans `moteur.py` : préparer le lot
sans réseau, générer dans une session, récolter sans réseau. Ce fichier n'en
garde que la porte d'entrée en ligne de commande.

Le cahier des charges prévoyait un appel direct à l'API Gemini vers Nano Banana
Pro. Cet endpoint répond `400 User location is not supported` depuis la
Polynésie, et le pipeline tourne à Tahiti. Le MCP expose le même modèle sous
l'identifiant `nano_banana_pro`.

Usage :
    python3 generation.py --marque "Kreative" --estimer
    python3 generation.py --marque "Kreative" --preparer
    python3 generation.py --marque "Kreative" --preparer --creas c01 c02

Cible Python 3.9+. Aucune dépendance externe, aucune dépendance à aloa.
"""
from __future__ import annotations

import argparse
import sys
from typing import List, Optional

import couts
import moteur
from etat import Commande

# Réexportés : plusieurs modules et le back-office les importaient d'ici.
FORMAT_MASTER = moteur.FORMAT_MASTER
RESOLUTION = moteur.RESOLUTION
a_generer = moteur.a_generer
construire_prompt = moteur.construire_prompt


def estimer(commande: Commande, filtre: Optional[List[str]] = None,
            solde: Optional[float] = None) -> dict:
    """Chiffre ce que coûterait la génération, sans rien lancer ni interroger.

    Le solde n'est pas lu ici : il vient du MCP, donc d'une session. On l'accepte
    en paramètre pour que l'appelant qui l'a puisse le faire afficher.
    """
    creas = a_generer(commande, filtre)
    if not creas:
        print("Aucune créa briefée en attente de génération.")
        return {"total": 0.0, "complet": True, "mesures": [], "inconnus": [], "nombre": 0}

    bilan = couts.devis([{"modele": c.prompt.modele,
                          "references": len(c.prompt.references or [])}
                         for c in creas])
    print(couts.rapport(bilan, solde=solde, plafond=moteur.PLAFOND_CREDITS_DEFAUT))
    return bilan


def main() -> int:
    parseur = argparse.ArgumentParser(description="Devis et préparation des masters")
    parseur.add_argument("--marque", required=True)
    parseur.add_argument("--creas", nargs="+", help="Limiter à ces identifiants")
    parseur.add_argument("--estimer", action="store_true",
                         help="Chiffrer sans rien préparer")
    parseur.add_argument("--preparer", action="store_true",
                         help="Écrire le lot que la session de génération consommera")
    parseur.add_argument("--solde", type=float,
                         help="Solde de crédits, si on l'a déjà relevé")
    parseur.add_argument("--plafond", type=float, default=moteur.PLAFOND_CREDITS_DEFAUT)
    arguments = parseur.parse_args()

    try:
        commande = Commande.charger(arguments.marque)
    except FileNotFoundError as erreur:
        print(f"Erreur : {erreur}", file=sys.stderr)
        return 1

    if arguments.preparer:
        lot = moteur.preparer(commande, arguments.creas, arguments.plafond)
        if not lot:
            print("Aucune créa briefée en attente de génération.")
            return 0
        print(moteur.rapport_lot(lot))
        print(f"\nLot écrit : {lot['_fichier']}")
        print("La génération se lance depuis une session Claude Code, qui lit ce "
              "fichier, montre le devis, attend le GO et appelle le MCP Higgsfield.")
        return 2 if lot["au_dessus_du_plafond"] or not lot["devis"]["complet"] else 0

    estimer(commande, arguments.creas, arguments.solde)
    if not arguments.estimer:
        print("\nRien n'a été préparé. Ajouter --preparer pour écrire le lot.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
