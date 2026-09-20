#!/usr/bin/env python3
"""ranger.py : crée, migre et vérifie les dossiers de commande.

Applique `CONVENTIONS.md`, qui fait autorité. Ce script en est la mise en oeuvre :
si les deux divergent, c'est un bug ici, pas une liberté prise là-bas.

Trois commandes.

    python3 outils/ranger.py creer --marque "Les Bains de Dax" \
        --url https://exemple.fr --pack starter
    python3 outils/ranger.py migrer <ardoise>
    python3 outils/ranger.py verifier            # tous les dossiers
    python3 outils/ranger.py verifier <ardoise>     # un seul

**La migration copie, elle ne déplace jamais.** L'ancien dossier reste intact
et l'ancienne forme n'est pas supprimée : effacer est une décision humaine, prise
après vérification. C'est la seule protection contre une migration qui se
trompe sur 314 Mo de rendus déjà livrés à des clients.

Cible Python 3.9+. Aucune dépendance externe.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "pipeline"))

from etat import (  # noqa: E402
    ETATS_COMMANDE,
    PACKS,
    RACINE_DEFAUT,
    VERSION_SCHEMA,
    Commande,
    ardoise,
    maintenant,
    volume_genere,
)

# L'arborescence complète d'une commande conforme. `etat.Commande.creer` en pose
# déjà quatre ; les autres sont les ajouts de CONVENTIONS.md.
SOUS_DOSSIERS = (
    "brief",
    "brief/pieces-jointes",
    "creas",
    "dist",
    "marque",
    "marque/assets-site",
    "marque/captures",
    "marque/logo",
    "marque/references",
    "masters",
    "reprises",
)

# Ce qu'un dossier doit contenir pour être jugé conforme.
ATTENDUS = ("commande.json", "journal.jsonl")

# Fichiers isolés que la migration sait replacer. Listés ici pour ne pas être
# annoncés comme non reconnus alors qu'ils sont traités.
FICHIERS_TRAITES = ("brief.md", "ETAT.md", "suivi.html", "journal.jsonl", "commande.json")


# ---------------------------------------------------------------------------
# Création
# ---------------------------------------------------------------------------

def creer(marque: str, url: str, pack: str, racine: Path = RACINE_DEFAUT) -> Path:
    """Ouvre une commande neuve, complète et conforme."""
    commande = Commande.creer(marque=marque, url_site=url, pack=pack, racine=racine)
    completer_arborescence(commande.dossier)
    commande.tracer("arborescence_posee", convention="CONVENTIONS.md")
    return commande.dossier


def completer_arborescence(dossier: Path) -> List[str]:
    """Crée les sous-dossiers manquants. Ne touche à rien d'existant."""
    poses = []
    for sous in SOUS_DOSSIERS:
        chemin = dossier / sous
        if not chemin.exists():
            chemin.mkdir(parents=True, exist_ok=True)
            poses.append(sous)
    return poses


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

# Correspondance entre l'ancienne forme libre et la convention. La clé est le
# nom rencontré dans les dossiers de 2026, la valeur sa destination.
#
# `out`, `out-v2` et `out-v3` sont le cas intéressant : c'étaient des reprises
# rangées à la main, en dupliquant tout le pack pour une image changée. La plus
# récente devient `dist/`, les précédentes descendent dans `reprises/`.
RENOMMAGES: Dict[str, str] = {
    "refs": "marque/references",
    "creas": "creas",
    "marque": "marque",
    "masters": "masters",
    "dist": "dist",
}

MOTIF_VERSION = re.compile(r"^(out|creas|dist)(?:-v(\d+))?$")


def analyser_ancien(dossier: Path) -> Tuple[List[str], Dict[str, List[str]]]:
    """Relève ce que contient un dossier avant migration.

    Retourne les entrées reconnues et les versions détectées, par famille.
    """
    versions: Dict[str, List[str]] = {}
    inconnus: List[str] = []
    for entree in sorted(dossier.iterdir()):
        if entree.name.startswith("."):
            continue
        correspondance = MOTIF_VERSION.match(entree.name)
        if correspondance and entree.is_dir():
            famille = correspondance.group(1)
            versions.setdefault(famille, []).append(entree.name)
        elif entree.name not in RENOMMAGES and entree.name not in ATTENDUS \
                and entree.name not in FICHIERS_TRAITES:
            inconnus.append(entree.name)
    return inconnus, versions


def _rang(nom: str) -> int:
    """`out` vaut 1, `out-v2` vaut 2 : l'ordre chronologique des reprises."""
    correspondance = MOTIF_VERSION.match(nom)
    if not correspondance or not correspondance.group(2):
        return 1
    return int(correspondance.group(2))


def migrer(nom: str, racine: Path = RACINE_DEFAUT, *, appliquer: bool = False) -> dict:
    """Copie un ancien dossier vers la convention. Ne supprime jamais l'ancien.

    Sans `--appliquer`, se contente d'annoncer ce qui serait fait.
    """
    source = racine / nom
    if not source.is_dir():
        raise FileNotFoundError(f"Dossier introuvable : {source}")

    # La cible est un dossier neuf, jamais la source. Migrer en place
    # demanderait de promouvoir `creas-v3` par dessus `creas`, donc d'ecraser
    # une version deja livree a un client pour reparer un rangement. On copie
    # a cote, Tom compare, puis il bascule lui-meme.
    cible = racine / "_migres" / ardoise(nom)
    inconnus, versions = analyser_ancien(source)

    actions: List[str] = []
    for famille, noms in sorted(versions.items()):
        ordonnes = sorted(noms, key=_rang)
        plus_recent = ordonnes[-1]
        destination = "dist" if famille in ("out", "dist") else famille
        actions.append(f"{plus_recent} -> {destination}/")
        for ancien in ordonnes[:-1]:
            actions.append(f"{ancien} -> reprises/_migration/{ancien}/")

    for entree, destination in sorted(RENOMMAGES.items()):
        if (source / entree).is_dir() and entree not in versions:
            suffixe = "" if entree != destination else " (a l'identique)"
            actions.append(f"{entree} -> {destination}/{suffixe}")

    if (source / "brief.md").exists():
        actions.append("brief.md -> brief/brief.md")
    if (source / "ETAT.md").exists():
        actions.append("ETAT.md -> brief/ETAT-historique.md")
    for fichier in ("commande.json", "journal.jsonl", "suivi.html"):
        if (source / fichier).exists():
            actions.append(f"{fichier} -> {fichier} (a l'identique)")

    rapport = {
        "source": str(source),
        "cible": str(cible),
        "actions": actions,
        "non_reconnus": inconnus,
        "applique": False,
    }
    if not appliquer:
        return rapport

    completer_arborescence(cible)
    for famille, noms in sorted(versions.items()):
        ordonnes = sorted(noms, key=_rang)
        destination = "dist" if famille in ("out", "dist") else famille
        _copier(source / ordonnes[-1], cible / destination)
        for ancien in ordonnes[:-1]:
            _copier(source / ancien, cible / "reprises" / "_migration" / ancien)
    for entree, destination in RENOMMAGES.items():
        if (source / entree).is_dir() and entree not in versions:
            _copier(source / entree, cible / destination)
    if (source / "brief.md").exists():
        shutil.copy2(source / "brief.md", cible / "brief" / "brief.md")
    if (source / "ETAT.md").exists():
        shutil.copy2(source / "ETAT.md", cible / "brief" / "ETAT-historique.md")
    for fichier in ("commande.json", "journal.jsonl", "suivi.html"):
        if (source / fichier).exists():
            shutil.copy2(source / fichier, cible / fichier)

    rapport["applique"] = True
    return rapport


def _copier(source: Path, cible: Path) -> None:
    cible.mkdir(parents=True, exist_ok=True)
    for element in source.iterdir():
        destination = cible / element.name
        if element.is_dir():
            shutil.copytree(element, destination, dirs_exist_ok=True)
        elif not destination.exists():
            shutil.copy2(element, destination)


# ---------------------------------------------------------------------------
# Vérification
# ---------------------------------------------------------------------------

def verifier(nom: Optional[str] = None, racine: Path = RACINE_DEFAUT) -> List[dict]:
    """Contrôle la conformité. Un écart est signalé, jamais corrigé en douce."""
    # Les dossiers techniques (`_migres`, et tout ce qui commence par un blanc
    # souligné) ne sont pas des commandes : les auditer produirait des écarts
    # qui n'en sont pas.
    if nom:
        dossiers = [racine / nom]
    else:
        dossiers = sorted(
            d for d in racine.iterdir() if d.is_dir() and not d.name.startswith("_")
        )
    rapports = []
    for dossier in dossiers:
        ecarts: List[str] = []
        for attendu in ATTENDUS:
            if not (dossier / attendu).exists():
                ecarts.append(f"manque {attendu}")
        manquants = [s for s in SOUS_DOSSIERS if not (dossier / s).exists()]
        if manquants:
            ecarts.append(f"sous-dossiers manquants : {', '.join(manquants)}")

        fichier = dossier / "commande.json"
        if fichier.exists():
            try:
                donnees = json.loads(fichier.read_text(encoding="utf-8"))
            except json.JSONDecodeError as erreur:
                ecarts.append(f"commande.json illisible : {erreur}")
                donnees = {}
            if donnees.get("version_schema") != VERSION_SCHEMA:
                ecarts.append(
                    f"version_schema {donnees.get('version_schema')} au lieu de {VERSION_SCHEMA}"
                )
            if donnees.get("etat") not in ETATS_COMMANDE:
                ecarts.append(f"etat inconnu : {donnees.get('etat')}")
            if donnees.get("pack") and donnees["pack"] not in PACKS:
                ecarts.append(f"pack inconnu : {donnees['pack']}")
            # Le volume se vérifie par la COHÉRENCE INTERNE de la commande, pas
            # par la règle en vigueur aujourd'hui. Le 17/09, l'abandon de la
            # surproduction a fait passer le facteur de 2 à 1, et les 22
            # commandes ouvertes se sont mises à signaler un écart d'un seul
            # coup, alors qu'aucune n'avait bougé : elles étaient justes sous la
            # règle de leur création, et le lot de test a bien ses 24 créas sur le
            # disque. Un contrôle qui condamne tout le passé à chaque changement
            # de règle apprend à ignorer les alertes.
            #
            # Est donc en écart une commande dont le volume déclaré ne
            # correspond NI à la règle du jour, NI au nombre de créas réellement
            # planifiées. Ce cas-là est une vraie incohérence.
            declaree = donnees.get("quantite_generee")
            attendue = volume_genere(donnees.get("quantite_vendue", 0))
            planifiees = len(list((dossier / "creas").glob("*.json")))
            if declaree is not None and declaree != attendue and declaree != planifiees:
                ecarts.append(
                    f"quantite_generee {declaree} : ni la règle du jour ({attendue}) "
                    f"ni le nombre de créas planifiées ({planifiees})"
                )
            ardoise_attendue = ardoise(donnees.get("marque", ""))
            if ardoise_attendue and dossier.name != ardoise_attendue:
                ecarts.append(f"nom de dossier {dossier.name} au lieu de {ardoise_attendue}")

        # Les suffixes de version rangés à la main sont le motif qui a justifié
        # cette convention : les signaler tant qu'ils traînent.
        for entree in dossier.iterdir():
            if entree.is_dir() and re.match(r".+-v\d+$", entree.name):
                ecarts.append(f"reprise rangee a la main : {entree.name}")

        rapports.append({"dossier": dossier.name, "conforme": not ecarts, "ecarts": ecarts})
    return rapports


# ---------------------------------------------------------------------------
# Ligne de commande
# ---------------------------------------------------------------------------

def main() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sous = analyseur.add_subparsers(dest="commande", required=True)

    p_creer = sous.add_parser("creer", help="ouvrir une commande neuve")
    p_creer.add_argument("--marque", required=True)
    p_creer.add_argument("--url", required=True)
    p_creer.add_argument("--pack", required=True, choices=sorted(PACKS))

    p_migrer = sous.add_parser("migrer", help="ranger un ancien dossier")
    p_migrer.add_argument("nom")
    p_migrer.add_argument(
        "--appliquer",
        action="store_true",
        help="copier reellement ; sans ce drapeau, annonce seulement",
    )

    p_verifier = sous.add_parser("verifier", help="controler la conformite")
    p_verifier.add_argument("nom", nargs="?")

    args = analyseur.parse_args()

    if args.commande == "creer":
        dossier = creer(args.marque, args.url, args.pack)
        print(f"Commande ouverte : {dossier}")
        return 0

    if args.commande == "migrer":
        rapport = migrer(args.nom, appliquer=args.appliquer)
        entete = "APPLIQUE" if rapport["applique"] else "SIMULATION, rien n'a bouge"
        print(f"{entete} : {rapport['source']} -> {rapport['cible']}")
        for action in rapport["actions"]:
            print(f"  {action}")
        if rapport["non_reconnus"]:
            print(f"  non reconnus, laisses en place : {', '.join(rapport['non_reconnus'])}")
        if not rapport["applique"]:
            print("\nRelancer avec --appliquer pour copier. L'ancien dossier reste intact.")
        return 0

    rapports = verifier(args.nom)
    fautifs = 0
    for rapport in rapports:
        if rapport["conforme"]:
            print(f"  ok      {rapport['dossier']}")
        else:
            fautifs += 1
            print(f"  ECART   {rapport['dossier']}")
            for ecart in rapport["ecarts"]:
                print(f"            {ecart}")
    print(f"\n{len(rapports) - fautifs} conformes, {fautifs} a reprendre.")
    return 1 if fautifs else 0


if __name__ == "__main__":
    raise SystemExit(main())
