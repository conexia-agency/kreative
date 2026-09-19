#!/usr/bin/env python3
"""loupe.py : découpe chaque master en zones pleine résolution pour la relecture.

Une créa de 2048 px lue en entier arrive à l'œil réduite : la composition se
juge très bien ainsi, mais un texte peint peut y cacher une faute qu'on ne
voit qu'agrandie. Toutes les fautes attrapées sur le pack Podmax du 19/09
l'ont été au zoom, aucune en vignette. Ce module rend le zoom systématique
au lieu d'artisanal : chaque master est découpé en quadrants qui se
recouvrent, chacun lu ensuite avec toute la résolution disponible pour lui.

    python3 pipeline/loupe.py <ardoise>                # tous les masters
    python3 pipeline/loupe.py <ardoise> --creas c03    # une créa

Les découpes s'écrivent dans `session/loupe/` de la commande, une image par
zone : <crea>-hg, -hd, -bg, -bd (haut/bas, gauche/droite). Le recouvrement
de 12 % évite qu'une ligne de texte tombée pile sur la coupe échappe aux
deux moitiés. La relecture reste un acte de la session : ouvrir chaque zone,
lire chaque texte, comparer au plan. Ce module fournit les pixels, pas le
jugement.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))

from etat import Commande  # noqa: E402

RECOUVREMENT = 0.12  # part du côté partagée entre deux zones voisines

ZONES = ("hg", "hd", "bg", "bd")


def decouper(commande: Commande, creas: List[str] | None = None) -> Dict[str, List[str]]:
    """Écrit les quadrants de chaque master demandé, et rend leurs chemins."""
    from PIL import Image

    dossier_masters = commande.dossier / "masters"
    sortie = commande.dossier / "session" / "loupe"
    sortie.mkdir(parents=True, exist_ok=True)

    masters = sorted(dossier_masters.glob("c*.png"))
    if creas:
        voulus = set(creas)
        masters = [m for m in masters if m.stem in voulus]
        absents = voulus - {m.stem for m in masters}
        if absents:
            raise RuntimeError(f"master(s) introuvable(s) : {', '.join(sorted(absents))}")
    if not masters:
        raise RuntimeError(f"aucun master dans {dossier_masters}")

    resultat: Dict[str, List[str]] = {}
    for master in masters:
        with Image.open(master) as image:
            largeur, hauteur = image.size
            marge_l = int(largeur * RECOUVREMENT / 2)
            marge_h = int(hauteur * RECOUVREMENT / 2)
            moitie_l, moitie_h = largeur // 2, hauteur // 2
            boites = {
                "hg": (0, 0, moitie_l + marge_l, moitie_h + marge_h),
                "hd": (moitie_l - marge_l, 0, largeur, moitie_h + marge_h),
                "bg": (0, moitie_h - marge_h, moitie_l + marge_l, hauteur),
                "bd": (moitie_l - marge_l, moitie_h - marge_h, largeur, hauteur),
            }
            chemins = []
            for zone in ZONES:
                destination = sortie / f"{master.stem}-{zone}.png"
                image.crop(boites[zone]).save(destination)
                chemins.append(str(destination))
        resultat[master.stem] = chemins
    return resultat


def main() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    analyseur.add_argument("ardoise")
    analyseur.add_argument("--creas", nargs="*", help="limiter à ces créas (défaut : toutes)")
    args = analyseur.parse_args()

    try:
        commande = Commande.charger(args.ardoise)
        resultat = decouper(commande, args.creas or None)
    except Exception as erreur:
        print(f"loupe : {erreur}", file=sys.stderr)
        return 1

    for crea, chemins in resultat.items():
        print(f"  {crea} : {len(chemins)} zones -> {Path(chemins[0]).parent}")
    print(f"{len(resultat)} master(s) découpé(s) : ouvrir chaque zone une par une, "
          f"et lire chaque texte contre le plan.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
