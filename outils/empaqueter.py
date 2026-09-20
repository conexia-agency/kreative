#!/usr/bin/env python3
"""empaqueter.py : assemble le dossier skill livrable depuis le dépôt.

Le dépôt de développement reste la source de vérité ; le paquet est
régénérable à l'identique par cette seule commande :

    python3 outils/empaqueter.py                    # vers ~/Desktop/kreative-production
    python3 outils/empaqueter.py --vers <dossier>   # ailleurs
    python3 outils/empaqueter.py --zip              # plus une archive à côté

Ce qui part, et rien d'autre :

    SKILL.md, CHANGELOG.md, evals/        depuis paquet/
    references/installation.md, architecture.md
    references/strategie-creative.md      depuis skill/SKILL.md, INTACT
    CREAS INSPI DELIVERY/                 depuis skill/, la banque telle quelle
    scripts/kreative.py, orchestrateur.py, pipeline/, outils/

Ce qui ne part JAMAIS : les commandes clientes, un fichier .env, une valeur
de clé, les copies de conflit iCloud (« nom 2.ext »), les caches. L'assemblage
se termine par des contrôles qui font échouer l'empaquetage plutôt que de
livrer sale : tiret cadratin, emoji, motif de clé, fichier de données.
"""
from __future__ import annotations

import argparse
import re
import shutil
import unicodedata
import zipfile
from pathlib import Path

DEPOT = Path(__file__).resolve().parent.parent

# Le caractère interdit s'écrit par son code : ce fichier doit passer son
# propre contrôle, et le hook du poste de développement bloque le littéral.
TIRET_CADRATIN = chr(0x2014)

# Les copies de conflit iCloud se nomment « nom 2.ext », « nom 3.ext »...
# 193 traînaient dans le workspace le 17/09, dont un scraper périmé.
COPIE_ICLOUD = re.compile(r" \d+\.(py|md|json|html)$")

EXCLUS_NOMS = {"__pycache__", ".DS_Store", ".pytest_cache", "demo_peupler.py"}

# Un emoji dans un livrable est interdit ; on tolère le triangle
# d'avertissement U+26A0 et son sélecteur, assumés par le skill de stratégie,
# et la coche typographique U+2713 de ses checklists : ce sont des signes,
# pas des pictogrammes.
PLAGES_EMOJI = ((0x1F000, 0x1FAFF), (0x2600, 0x27BF))
EMOJI_TOLERES = {0x26A0, 0xFE0F, 0x2713, 0x2717}

MOTIFS_SECRET = [
    re.compile(r"(?i)(api[_-]?key|secret|token)\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{16,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
]


def _garde(chemin: Path) -> bool:
    if chemin.name in EXCLUS_NOMS or chemin.suffix == ".pyc":
        return False
    if chemin.name.startswith("."):
        return False
    if COPIE_ICLOUD.search(chemin.name):
        print(f"  écarté (copie iCloud) : {chemin.name}")
        return False
    return True


def _doublon_icloud(chemin: Path) -> bool:
    """« fichier 2.py », « dossier 2 » : les copies de conflit iCloud.

    Elles apparaissent toutes seules sur ce poste et sont toujours périmées :
    en embarquer une dans un paquet, c'est risquer qu'une session lise un
    vieux SKILL. On les écarte à la copie, quel que soit leur emplacement.
    """
    import re
    return any(re.search(r" \d+$", Path(part).stem) for part in chemin.parts)


def purger_doublons_icloud(dossier: Path) -> int:
    """Supprime les copies de conflit iCloud DANS un paquet assemblé.

    Le rmtree d'ouverture ne suffit pas : le Bureau est synchronisé iCloud,
    qui redépose ses vieilles versions en conflit APRÈS l'assemblage
    (« skill 3.md », « scripts 3 », mesuré le 19/09 : des arbres entiers
    dupliqués, datés d'un build précédent). Deux fichiers skill dans un
    paquet, c'est une session qui peut charger le vieux. À appeler en fin
    d'assemblage, et à recommander avant tout envoi.
    """
    import re
    n = 0
    for element in sorted(dossier.rglob("*"), key=lambda p: -len(p.parts)):
        if re.search(r" \d+$", element.stem):
            shutil.rmtree(element, ignore_errors=True) if element.is_dir() else element.unlink(missing_ok=True)
            n += 1
    if n:
        print(f"  {n} copie(s) de conflit iCloud purgée(s) de {dossier.name}")
    return n


def _copier_arbre(source: Path, cible: Path) -> int:
    n = 0
    for element in sorted(source.rglob("*")):
        if not element.is_file():
            continue
        if any(part in EXCLUS_NOMS for part in element.parts):
            continue
        if _doublon_icloud(element.relative_to(source)):
            continue
        if not _garde(element):
            continue
        destination = cible / element.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(element, destination)
        n += 1
    return n


def _emoji(texte: str) -> str:
    for caractere in texte:
        code = ord(caractere)
        if code in EMOJI_TOLERES:
            continue
        if any(a <= code <= b for a, b in PLAGES_EMOJI):
            return caractere
    return ""


# Les fichiers qui appartiennent au CLIENT et partent tels quels. Les règles
# d'écriture de Conexia (pas de tiret cadratin, pas d'emoji) s'appliquent à ce
# que Conexia écrit, pas au texte du client. Les avoir appliquées au skill de
# Kreative revenait à le réécrire : 98 lignes de son fichier avaient disparu,
# dont toute la section qui décrit son usage du navigateur. Constaté le 18/09,
# par lui : « ça vient dénaturer le skill de base ».
#
# Le contrôle des SECRETS, lui, ne connaît aucune exemption.
FICHIERS_DU_CLIENT = {
    "references/strategie-creative.md",
    "resources/strategie-creative.md",
}


def _controler(racine: Path) -> list:
    fautes = []
    for fichier in racine.rglob("*"):
        if not fichier.is_file():
            continue
        if fichier.suffix not in (".md", ".py", ".json", ".html"):
            continue
        texte = fichier.read_text(encoding="utf-8", errors="replace")
        relatif = fichier.relative_to(racine)
        du_client = str(relatif).replace("\\", "/") in FICHIERS_DU_CLIENT
        if TIRET_CADRATIN in texte and not du_client:
            fautes.append(f"tiret cadratin dans {relatif}")
        e = _emoji(texte)
        if e and not du_client:
            fautes.append(f"emoji {unicodedata.name(e, hex(ord(e)))} dans {relatif}")
        for motif in MOTIFS_SECRET:
            m = motif.search(texte)
            if m:
                fautes.append(f"motif de clé dans {relatif} : {m.group(0)[:24]}...")
    if not (racine / "scripts" / "pipeline" / "etat.py").exists():
        fautes.append("scripts/pipeline/etat.py absent, le paquet est incomplet")
    for interdit in ("commandes", ".env"):
        if (racine / interdit).exists():
            fautes.append(f"{interdit} ne doit jamais partir dans le paquet")
    return fautes


def empaqueter(vers: Path, faire_zip: bool) -> int:
    if vers.exists():
        shutil.rmtree(vers)
    vers.mkdir(parents=True)

    total = 0
    # 1. La coquille rédactionnelle.
    total += _copier_arbre(DEPOT / "paquet", vers)
    # 2. Le métier créatif.
    (vers / "references").mkdir(exist_ok=True)
    shutil.copy2(DEPOT / "skill" / "SKILL.md",
                 vers / "references" / "strategie-creative.md")
    total += 1
    # Le skill du client part intact ; ce qu'il demande d'aller chercher est déjà
    # sur le disque quand la chaîne tourne, et c'est ce fichier qui le dit. Sans
    # lui, la session relirait le site au navigateur alors que le scraper l'a fait.
    chaine = DEPOT / "paquet-cowork" / "chaine-kreative.md"
    if chaine.exists():
        shutil.copy2(chaine, vers / "references" / "chaine-kreative.md")
        total += 1
    # 3. La banque, telle quelle.
    total += _copier_arbre(DEPOT / "skill" / "CREAS INSPI DELIVERY",
                           vers / "CREAS INSPI DELIVERY")
    # 4. Le code.
    scripts = vers / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    for fichier in ("kreative.py", "orchestrateur.py"):
        shutil.copy2(DEPOT / fichier, scripts / fichier)
        total += 1
    # Le compositeur ne part plus : il fabriquait les créas en HTML, avec notre
    # répertoire d'archétypes et nos gabarits. La création vient du skill de
    # Kreative depuis le 18/09, et le texte est peint par le modèle.
    for dossier in ("pipeline", "outils"):
        total += _copier_arbre(DEPOT / dossier, scripts / dossier)

    purger_doublons_icloud(vers)
    fautes = _controler(vers)
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
    p = argparse.ArgumentParser(description="Assemble le dossier skill livrable")
    p.add_argument("--vers", type=Path,
                   default=Path.home() / "Desktop" / "kreative-production")
    p.add_argument("--zip", action="store_true")
    a = p.parse_args()
    return empaqueter(a.vers.expanduser(), a.zip)


if __name__ == "__main__":
    raise SystemExit(main())
