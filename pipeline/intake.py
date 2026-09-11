#!/usr/bin/env python3
"""intake.py : analyse du site client, avec garde-fou.

Enveloppe `brand_intake.py` (aloa-pack) au lieu de le modifier : ce script est
la source de vérité partagée de Conexia, il n'a pas à porter les règles propres
à cette chaîne.

Raison d'être du garde-fou. Sur un site protégé par mot de passe, brand_intake
analyse la page de garde et rend une charte parfaitement plausible : la couleur
du bouton du mur en primaire, la police du gabarit en typographie de marque.
Aucune erreur n'est levée. Le pipeline produirait alors un pack entier hors
charte, et personne ne s'en apercevrait avant la livraison.

C'est le point ouvert #4 du cahier des charges : que se passe-t-il si l'analyse
du site échoue, ou si le site n'expose pas d'assets exploitables. Réponse tenue
ici : on échoue bruyamment et on n'entre pas en production sur une charte
douteuse.

Usage :
    python3 intake.py --url https://exemple.com --marque "Exemple"
    python3 intake.py --url https://exemple.com --marque "Exemple" --verifier-seulement

Cible Python 3.9+. Dépendances : playwright (sonde), brand_intake (aloa-pack).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

RACINE = Path(__file__).resolve().parent.parent
BRAND_INTAKE = (
    RACINE.parent / "conexia" / "PRODUIT" / "caravage" / "skills" / "aloa-pack"
    / "aloa-design" / "scripts" / "brand_intake.py"
)

# Signaux d'une page de garde : mur de mot de passe, page en construction,
# redirection de parking de domaine. La liste vise les gabarits les plus
# répandus (Framer, Webflow, Shopify, Wordpress), pas l'exhaustivité.
MOTIFS_TITRE = [
    r"enter password", r"password protected", r"mot de passe",
    r"coming soon", r"bient[oô]t disponible", r"under construction",
    r"site en maintenance", r"maintenance mode", r"restricted",
    r"connexion requise", r"log ?in required",
]

NOEUDS_MINIMUM = 60      # une page réelle en compte largement plus
TEXTE_MINIMUM = 400      # caractères de texte visible


class SiteInexploitable(Exception):
    """Levée quand le site ne peut pas servir de source de charte."""


def sonder(url: str, delai: int = 45000) -> Dict[str, object]:
    """Charge la page et rapporte de quoi juger si elle est exploitable."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        navigateur = p.chromium.launch()
        page = navigateur.new_page(viewport={"width": 1440, "height": 1000})
        try:
            reponse = page.goto(url, wait_until="domcontentloaded", timeout=delai)
            page.wait_for_timeout(1500)
            mesures = page.evaluate("""() => ({
                titre: document.title || '',
                noeuds: document.querySelectorAll('*').length,
                texte: (document.body ? document.body.innerText : '').trim().length,
                champsMotDePasse: document.querySelectorAll('input[type=password]').length,
                liens: document.querySelectorAll('a[href]').length,
                images: document.querySelectorAll('img').length,
            })""")
            mesures["statut"] = reponse.status if reponse else 0
            mesures["url_finale"] = page.url
            return mesures
        finally:
            navigateur.close()


def juger(mesures: Dict[str, object]) -> List[str]:
    """Retourne la liste des raisons rendant le site inexploitable."""
    raisons: List[str] = []

    statut = int(mesures.get("statut") or 0)
    if statut in (401, 403):
        raisons.append(f"accès refusé (HTTP {statut})")
    elif statut >= 400 or statut == 0:
        raisons.append(f"page non servie (HTTP {statut})")

    titre = str(mesures.get("titre", "")).lower()
    for motif in MOTIFS_TITRE:
        if re.search(motif, titre):
            raisons.append(f"titre de page de garde : « {mesures['titre']} »")
            break

    if int(mesures.get("champsMotDePasse") or 0) > 0:
        raisons.append("la page présente un champ de mot de passe")

    if int(mesures.get("noeuds") or 0) < NOEUDS_MINIMUM:
        raisons.append(f"page quasi vide ({mesures.get('noeuds')} éléments)")

    if int(mesures.get("texte") or 0) < TEXTE_MINIMUM:
        raisons.append(f"trop peu de texte ({mesures.get('texte')} caractères)")

    return raisons


def verifier(url: str) -> Dict[str, object]:
    mesures = sonder(url)
    raisons = juger(mesures)
    return {"mesures": mesures, "raisons": raisons, "exploitable": not raisons}


def analyser(url: str, marque: str, sortie: Path) -> Path:
    """Vérifie le site puis lance brand_intake. Échoue avant, jamais après."""
    bilan = verifier(url)
    mesures = bilan["mesures"]

    print(f"Sonde : HTTP {mesures['statut']}, {mesures['noeuds']} éléments, "
          f"{mesures['texte']} caractères, titre « {mesures['titre']} »")

    if not bilan["exploitable"]:
        raise SiteInexploitable(
            "Le site ne peut pas servir de source de charte :\n  - "
            + "\n  - ".join(bilan["raisons"])
            + "\n\nUne charte extraite d'une page de garde est plausible mais fausse, "
              "et contaminerait tout le pack. Fournir un accès, ou une autre source "
              "de charte."
        )

    if not BRAND_INTAKE.exists():
        raise SiteInexploitable(f"brand_intake introuvable : {BRAND_INTAKE}")

    sortie.mkdir(parents=True, exist_ok=True)
    resultat = subprocess.run(
        [sys.executable, str(BRAND_INTAKE), "--url", url, "--name", marque,
         "--out", str(sortie)],
        capture_output=True, text=True,
    )
    print(resultat.stdout[-1500:] if resultat.stdout else "")
    if resultat.returncode != 0:
        raise SiteInexploitable(
            f"brand_intake a échoué (code {resultat.returncode}) :\n{resultat.stderr[-800:]}"
        )

    charte = sortie / "charte.json"
    if not charte.exists():
        raise SiteInexploitable("brand_intake n'a pas produit de charte.json")

    return charte


def main() -> int:
    parseur = argparse.ArgumentParser(description="Analyse du site client, avec garde-fou")
    parseur.add_argument("--url", required=True)
    parseur.add_argument("--marque")
    parseur.add_argument("--sortie")
    parseur.add_argument("--verifier-seulement", action="store_true",
                         help="Sonder le site sans lancer l'extraction")
    arguments = parseur.parse_args()

    if arguments.verifier_seulement:
        bilan = verifier(arguments.url)
        print(json.dumps(bilan, ensure_ascii=False, indent=2))
        return 0 if bilan["exploitable"] else 2

    if not arguments.marque:
        print("--marque est requis hors mode vérification.", file=sys.stderr)
        return 1

    sortie = Path(arguments.sortie) if arguments.sortie else (
        RACINE / "commandes" / arguments.marque.lower().replace(" ", "-") / "marque"
    )
    try:
        charte = analyser(arguments.url, arguments.marque, sortie)
    except SiteInexploitable as erreur:
        print(f"\nAnalyse refusée.\n{erreur}", file=sys.stderr)
        return 2

    print(f"\nCharte extraite : {charte}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
