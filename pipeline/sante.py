#!/usr/bin/env python3
"""sante.py : le contrôle de branchement de la chaîne, dans n'importe quel environnement.

Le skill de Kreative ouvre son process par une étape 0, « vérifier
l'outillage » : sans navigateur ni banque lisible, on ne produit pas. Ce
module est la même étape 0 pour la chaîne. Le code tourne dans trois
environnements différents (le dépôt de développement, le paquet Claude Code
assemblé, le paquet Cowork), et chaque environnement range le skill, la
banque et l'espace de travail à un endroit différent. Deviner, c'est produire
un pack raté sans le savoir : ce module VÉRIFIE, et quand quelque chose n'est
pas branché, il le dit, avec le remède.

    python3 pipeline/sante.py            # depuis le dépôt
    python3 scripts/pipeline/sante.py    # depuis un paquet assemblé

Sortie : une ligne par contrôle, `ok` / `MANQUE` / `option`, puis un verdict.
Code retour 1 si un contrôle bloquant échoue : un orchestrateur peut donc
refuser de lancer un run sur un poste mal branché.

Deux choses ne se vérifient pas d'ici, et le dire fait partie du contrôle :
le connecteur Higgsfield et le navigateur n'existent que dans une session
Claude. Le rapport les liste comme « à vérifier en session », avec l'appel
qui les prouve.
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))

OK, MANQUE, OPTION, SESSION = "ok     ", "MANQUE ", "option ", "session"


def _environnement() -> tuple[str, Path]:
    """Quel environnement, et où vit le fichier du skill créatif."""
    racine = ICI.parent
    if (racine / "outils" / "empaqueter.py").exists() and (racine / "skill" / "strategie-creative.md").exists():
        return "dépôt de développement", racine / "skill" / "strategie-creative.md"
    # Dans un paquet assemblé, le code vit sous scripts/ : le skill se cherche
    # au niveau du script ET au niveau du paquet.
    for base in (racine, racine.parent):
        if (base / "references" / "strategie-creative.md").exists():
            return "paquet Claude Code", base / "references" / "strategie-creative.md"
        if (base / "resources" / "strategie-creative.md").exists():
            return "paquet Cowork", base / "resources" / "strategie-creative.md"
    return "inconnu", racine / "SKILL.md"


def controler() -> int:
    lignes: list[tuple[str, str, str]] = []
    bloquants = 0

    def note(etat: str, quoi: str, detail: str = "") -> None:
        nonlocal bloquants
        if etat == MANQUE:
            bloquants += 1
        lignes.append((etat, quoi, detail))

    env, chemin_skill = _environnement()

    # 1. Le skill créatif, la seule source de la création.
    if chemin_skill.exists() and chemin_skill.stat().st_size > 20_000:
        note(OK, "skill créatif", f"{chemin_skill}")
    elif chemin_skill.exists():
        note(MANQUE, "skill créatif", f"{chemin_skill} fait {chemin_skill.stat().st_size} octets : tronqué. Réassembler le paquet.")
    else:
        note(MANQUE, "skill créatif", f"introuvable ({chemin_skill}). Dans le dépôt : skill/strategie-creative.md. Dans un paquet : references/ ou resources/strategie-creative.md, injecté par outils/empaqueter.py.")

    # 2. La banque de références, par le même résolveur que la chaîne.
    try:
        import banque as _banque
        racine_banque = _banque._racine_banque()
    except Exception as erreur:
        racine_banque = None
        note(MANQUE, "banque de références", f"résolveur en échec : {erreur}")
    if racine_banque is not None:
        planches = sorted((racine_banque / "_PLANCHES").glob("PLANCHE_*.jpg"))
        familles = [d.name for d in racine_banque.iterdir() if d.is_dir() and d.name != "_PLANCHES"]
        if len(planches) >= 20 and len(familles) >= 3:
            note(OK, "banque de références", f"{racine_banque} : {len(planches)} planches, familles {', '.join(sorted(familles))}")
        else:
            note(MANQUE, "banque de références", f"{racine_banque} : {len(planches)} planches et {len(familles)} familles, il en faut 20 et 3. Banque incomplète.")
        # Le skill dit « à côté du SKILL.md ». Quand l'installation la range
        # ailleurs, la session doit le savoir AVANT de suivre le skill à la
        # lettre : c'est banque.py ouvrir qui donne les chemins réels.
        if racine_banque.parent != chemin_skill.parent:
            note(OPTION, "banque, emplacement", f"pas à côté du fichier du skill dans cet environnement : passer par « banque.py ouvrir », qui liste les chemins exacts.")

    # 3. Chaque module de la chaîne s'importe. `audit` est à part : le paquet
    # Cowork ne l'embarque pas (la relecture s'y fait à l'œil, c'est
    # documenté), donc son absence est une option, sa casse un manque.
    modules = ["etat", "zite", "banque", "plan", "moteur", "couts", "formats", "livrer", "publier", "retours"]
    casse = []
    for nom in modules:
        try:
            importlib.import_module(nom)
        except Exception as erreur:
            casse.append(f"{nom} ({type(erreur).__name__}: {erreur})")
    if casse:
        note(MANQUE, "modules de la chaîne", "ne s'importent pas : " + " · ".join(casse))
    else:
        note(OK, "modules de la chaîne", f"{len(modules)} modules s'importent")
    try:
        importlib.import_module("audit")
        note(OK, "audit OCR", "présent, les contrôles mécaniques tourneront")
    except ModuleNotFoundError:
        note(OPTION, "audit OCR", "absent de ce paquet : la relecture des visuels se fait à l'œil par la session, comme la doc du paquet le prévoit.")
    except Exception as erreur:
        note(MANQUE, "audit OCR", f"présent mais cassé : {type(erreur).__name__}: {erreur}")

    # 4. L'espace de travail, écriture prouvée.
    try:
        from etat import RACINE_DEFAUT
        RACINE_DEFAUT.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=RACINE_DEFAUT, prefix=".sante-", delete=True):
            pass
        source = "KREATIVE_TRAVAIL" if os.environ.get("KREATIVE_TRAVAIL", "").strip() else "défaut"
        note(OK, "espace de travail", f"{RACINE_DEFAUT} ({source}), écriture vérifiée")
    except Exception as erreur:
        note(MANQUE, "espace de travail", f"pas d'écriture possible : {erreur}. Poser KREATIVE_TRAVAIL vers un dossier accessible.")

    # 5. La clé du formulaire. Présence seulement, jamais la valeur.
    if os.environ.get("ZITE_API_KEY", "").strip():
        note(OK, "ZITE_API_KEY", "présente dans l'environnement")
    else:
        note(MANQUE, "ZITE_API_KEY", "absente : le relevé des formulaires échouera. Charger le .env (set -a && source .env && set +a) avant zite.py.")

    # 6. Pillow, nécessaire aux formats et à l'audit.
    try:
        importlib.import_module("PIL.Image")
        note(OK, "Pillow", "disponible")
    except Exception:
        note(MANQUE, "Pillow", "absent : pip install Pillow. Sans lui, ni déclinaison de formats ni audit.")

    # 7. Les moteurs de lecture, tous deux optionnels : sans eux, la relecture
    # des visuels se fait à l'œil par la session, ce que la doc du paquet
    # prévoit. On dit ce qui est là, pas ce qui devrait.
    import shutil as _shutil
    if _shutil.which("tesseract"):
        note(OK, "tesseract", "présent, l'audit lira les textes peints")
    else:
        note(OPTION, "tesseract", "absent : l'audit passera en relecture à l'œil. brew/apt install tesseract pour l'activer.")
    vision = Path.home() / ".cache" / "kreative" / "ocr-vision"
    if sys.platform == "darwin":
        note(OK if vision.exists() else OPTION, "Apple Vision", "binaire compilé" if vision.exists() else "sera compilé au premier audit (macOS seulement)")

    # 8. Le connecteur Higgsfield. La génération passe par lui et par rien
    # d'autre. Sa CONFIGURATION se vérifie d'ici ; son APPEL, seulement en
    # session. Sur Cowork, le connecteur se gère dans l'application, il n'y a
    # rien à lire sur le disque.
    if env == "paquet Cowork":
        note(SESSION, "connecteur Higgsfield", "à activer dans les connecteurs de Cowork (voir INSTALLATION.md) ; l'appel de solde en session fait foi.")
    else:
        declare = False
        try:
            import json as _json
            config = _json.loads((Path.home() / ".claude.json").read_text(encoding="utf-8"))
            serveurs = dict(config.get("mcpServers") or {})
            for projet in (config.get("projects") or {}).values():
                serveurs.update(projet.get("mcpServers") or {})
            declare = "higgsfield" in serveurs
        except Exception:
            pass
        if declare:
            note(OK, "connecteur Higgsfield", "déclaré dans ~/.claude.json ; l'OAuth s'ouvre dans le navigateur au premier appel, un navigateur doit être disponible sur ce poste, une fois. L'appel de solde en session fait foi.")
        else:
            note(MANQUE, "connecteur Higgsfield", "non déclaré : la génération est impossible. L'ajouter (installation.md, section 2) : claude mcp add --transport http --scope user higgsfield https://mcp.higgsfield.ai/mcp, puis redémarrer Claude Code et laisser l'OAuth s'ouvrir dans le navigateur au premier appel. Jamais la CLI higgsfield : le MCP seul.")

    # 9. Les copies de conflit iCloud. Un dossier synchronisé (le Bureau, les
    # Documents) redépose de vieilles versions sous « nom 2.md », « scripts 3 »,
    # y compris APRÈS un assemblage propre : mesuré le 19/09, des arbres
    # entiers dupliqués dans les deux paquets. Deux fichiers skill côte à
    # côte, c'est une session qui peut charger le vieux : bloquant.
    import re as _re
    racine_env = chemin_skill.parent if env != "dépôt de développement" else ICI.parent
    # Seuls comptent les dossiers que la chaîne LIT : un doublon dans un
    # dossier ignoré ou de données ne trompe personne.
    IGNORES = {".git", ".codegraph", "commandes", "inspirations-sources",
               "inspirations", "corpus", "sources", "_ecarte-de-leur-skill"}
    doublons = [str(p.relative_to(racine_env)) for p in racine_env.rglob("*")
                if _re.search(r" \d+$", p.stem) and not IGNORES & set(p.parts)]
    if doublons:
        note(MANQUE, "copies de conflit iCloud", f"{len(doublons)} élément(s) en double, "
             f"vieilles versions redéposées par la synchronisation : "
             f"{', '.join(doublons[:5])}{'…' if len(doublons) > 5 else ''}. "
             f"Les supprimer (ce sont des copies périmées), ou réassembler le paquet : "
             f"l'empaquetage les purge désormais.")
    else:
        note(OK, "copies de conflit iCloud", "aucune")

    # 10. Ce qui ne se prouve qu'en session.
    note(SESSION, "génération", "un appel de solde (balance) en session prouve le connecteur autorisé et le compte crédité, avant toute dépense.")
    note(SESSION, "navigateur", "exigé par le skill pour l'analyse du site ; en chaîne, scraper.py ou le navigateur de la session s'en charge. C'est aussi lui qui porte l'OAuth du connecteur au premier appel.")

    print(f"Environnement : {env}\n")
    for etat, quoi, detail in lignes:
        print(f"  [{etat}] {quoi}" + (f" : {detail}" if detail else ""))
    print()
    if bloquants:
        print(f"{bloquants} branchement(s) manquant(s) : la chaîne ne doit pas tourner en l'état.")
        return 1
    print("Tout est branché. Les deux contrôles « session » restent à prouver au premier appel.")
    return 0


if __name__ == "__main__":
    raise SystemExit(controler())
