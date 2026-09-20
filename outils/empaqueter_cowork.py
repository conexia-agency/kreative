#!/usr/bin/env python3
"""empaqueter_cowork.py : assemble la variante Cowork du skill, livrable au client.

    python3 outils/empaqueter_cowork.py                  # vers ~/Desktop/kreative-cowork
    python3 outils/empaqueter_cowork.py --vers <dossier>
    python3 outils/empaqueter_cowork.py --zip

**Pourquoi une variante et pas le même paquet.** Cowork exécute du Python et
des commandes, mais ne peut PAS installer de dépendance système à l'exécution :
la documentation des skills le dit, les paquets doivent être préinstallés. Deux
modules de la chaîne en dépendent et ne peuvent donc pas partir :

    pipeline/scraper.py   pilote un navigateur Chromium
    pipeline/audit.py     appelle un moteur de reconnaissance de caractères

Ils sont REMPLACÉS par des procédures écrites dans `skill.md`, que la session
exécute elle-même : l'aspiration du site passe par le navigateur intégré de
Cowork, et le contrôle du texte peint se fait à l'oeil. Le second échange est un
gain, pas une concession : mesuré le 18/09, la reconnaissance de caractères a
raté quatre textes pourtant nets (un texte incliné, des libellés peints en
couleur vive sur fond sombre) que la lecture de l'image retrouve.

Tout le reste du code part tel quel : onze modules en Python pur, qui n'ouvrent
que `urllib`, `json` et `pathlib`, plus Pillow qui est un paquet standard.

Ce qui ne part JAMAIS, comme pour l'autre paquet : les commandes clientes, un
fichier `.env`, une valeur de clé. Les contrôles de `empaqueter.py` sont
réutilisés tels quels et font échouer l'assemblage plutôt que de livrer sale.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path

DEPOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DEPOT / "outils"))

from empaqueter import _controler, _copier_arbre, purger_doublons_icloud  # noqa: E402

# Les modules qui tournent dans Cowork : Python pur, aucune dépendance système.
MODULES_PORTABLES = (
    "sante.py",         # le contrôle de branchement, à jouer en premier
    "loupe.py",         # les quadrants pleine résolution pour la relecture
    "etat.py",          # le modèle de commande, socle de tous les autres
    "zite.py",          # relevé des formulaires, urllib seul
    "banque.py",        # le registre de lecture de la banque de références
    "plan.py",          # lit la sortie du skill et la range en créas
    "moteur.py",        # préparation du lot et récolte
    "couts.py",         # la table des coûts mesurés
    "formats.py",       # les trois formats, prolongement et assemblage, Pillow
    "livrer.py",        # le dossier de remise et la notification
    "publier.py",       # la plateforme de revue, en option
    "retours.py",       # les retours clients
)

# Ceux qu'on laisse derrière, et la raison, écrite pour qui ouvrira le paquet.
ECARTES = {
    "strategie.py": "la stratégie est faite par le skill de Kreative, pas par un script",
    "redaction.py": "le skill cartographie lui-même le brief, c'est son étape 1",
    "generation.py": "doublon de moteur.py, retiré de la chaîne",
    "repertoire.py": "doctrine créative, sortie de la chaîne le 18/09",
    "scraper.py": "pilote un navigateur Chromium, impossible à installer dans Cowork",
    "audit.py": "appelle un moteur de reconnaissance de caractères, idem",
    "vue.py": "dépend de l'audit écarté",
    "exporter.py": "dépend de l'audit écarté",
    "photographie.py": "doctrine photo, absorbée par strategie-creative.md",
}


def empaqueter(vers: Path, faire_zip: bool) -> int:
    source = DEPOT / "paquet-cowork"
    if not (source / "skill.md").exists():
        print(f"skill.md introuvable dans {source}", file=sys.stderr)
        return 1

    if vers.exists():
        shutil.rmtree(vers)
    vers.mkdir(parents=True)

    total = 0
    # 1. Le skill lui-même, à la racine, comme Cowork l'attend.
    shutil.copy2(source / "skill.md", vers / "skill.md")
    total += 1
    # chaine-kreative.md part dans resources, à côté du skill du client, pas ici.
    for extra in source.glob("*.md"):
        if extra.name not in ("skill.md", "chaine-kreative.md"):
            shutil.copy2(extra, vers / extra.name)
            total += 1

    # 2. Les références métier.
    resources = vers / "resources"
    resources.mkdir()
    shutil.copy2(DEPOT / "skill" / "SKILL.md", resources / "strategie-creative.md")
    total += 1
    # Nos ajouts vivent DANS resources, à côté du skill du client, jamais dedans.
    chaine = DEPOT / "paquet-cowork" / "chaine-kreative.md"
    if chaine.exists():
        shutil.copy2(chaine, resources / "chaine-kreative.md")
        total += 1

    # 3. La banque de références, telle quelle.
    total += _copier_arbre(DEPOT / "skill" / "CREAS INSPI DELIVERY",
                           vers / "CREAS INSPI DELIVERY")

    # 4. Les modules portables, dans l'arborescence que leurs imports attendent.
    pipeline = vers / "scripts" / "pipeline"
    pipeline.mkdir(parents=True)
    manquants = []
    for nom in MODULES_PORTABLES:
        origine = DEPOT / "pipeline" / nom
        if not origine.exists():
            manquants.append(nom)
            continue
        shutil.copy2(origine, pipeline / nom)
        total += 1
    if manquants:
        print("modules introuvables : " + ", ".join(manquants), file=sys.stderr)
        return 1

    # 5. La note qui dit ce qui manque et pourquoi, à côté du code.
    lignes = ["# Ce qui n'est pas dans ce paquet, et pourquoi", "",
              "Cowork ne peut pas installer de dépendance système à l'exécution.",
              "Ces modules de la chaîne en demandent une, ils sont donc remplacés",
              "par des procédures écrites dans `skill.md`, que la session exécute",
              "elle-même.", ""]
    for nom, raison in sorted(ECARTES.items()):
        lignes.append(f"- **{nom}** : {raison}.")
    lignes += ["", "Les onze modules présents sont en Python pur : ils n'ouvrent que",
               "`urllib`, `json` et `pathlib`, plus Pillow pour la livraison, qui est",
               "un paquet standard."]
    (vers / "scripts" / "MODULES.md").write_text("\n".join(lignes) + "\n", encoding="utf-8")
    total += 1

    fautes = _controler(vers)
    purger_doublons_icloud(vers)
    if fautes:
        print("EMPAQUETAGE REFUSÉ :")
        for f in fautes:
            print("  -", f)
        return 1

    taille = sum(f.stat().st_size for f in vers.rglob("*") if f.is_file())
    print(f"{total} fichiers, {taille / 1e6:.1f} Mo : {vers}")

    if faire_zip:
        archive = vers.with_suffix(".zip")
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
            for fichier in sorted(vers.rglob("*")):
                if fichier.is_file():
                    z.write(fichier, fichier.relative_to(vers.parent))
        print(f"archive : {archive} ({archive.stat().st_size / 1e6:.1f} Mo)")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Assemble la variante Cowork du skill")
    p.add_argument("--vers", type=Path, default=Path.home() / "Desktop" / "kreative-cowork")
    p.add_argument("--zip", dest="faire_zip", action="store_true")
    a = p.parse_args()
    return empaqueter(a.vers.expanduser(), a.faire_zip)


if __name__ == "__main__":
    raise SystemExit(main())
