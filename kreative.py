#!/usr/bin/env python3
"""kreative.py : la chaîne de production, en une commande.

**La création n'est pas ici.** Elle est dans le skill de Kreative : la
stratégie, les angles, la copy, le choix des assets et les prompts sont son
travail, et aucun fichier de cette chaîne n'en reprend une règle. Ce que la
chaîne fait tient en trois blocs : rassembler les entrées du client, passer le
lot au modèle, ranger et livrer ce qui en sort.

    python3 kreative.py entrees podmax                    # ce que le skill trouvera
    python3 kreative.py plan podmax --fichier plan.json   # ranger sa sortie
    python3 kreative.py prompts podmax                    # voir tous les prompts
    python3 kreative.py generer podmax                    # préparer le lot
    python3 kreative.py generer podmax --crea c07         # relancer une seule créa
    python3 kreative.py prompt podmax c07 --editer        # corriger un prompt
    python3 kreative.py formats podmax                    # les deux déclinaisons
    python3 kreative.py audit podmax                      # les contrôles mécaniques
    python3 kreative.py livrer podmax                     # le dossier de remise
    python3 kreative.py page podmax                       # la page de suivi
    python3 kreative.py etat podmax

Le fil directeur : le prompt est un champ de fichier, pas une chaîne assemblée
au vol. Il est donc visible, corrigeable, et rejouable à l'identique. Corriger
puis relancer une créa ne touche à aucune autre.

Cible Python 3.9+. Aucune dépendance externe hors génération et déclinaison.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

RACINE = Path(__file__).resolve().parent
sys.path.insert(0, str(RACINE / "pipeline"))

from etat import Commande, Crea  # noqa: E402

VERT, ORANGE, GRIS, ROUGE, RAZ = "\033[32m", "\033[33m", "\033[90m", "\033[31m", "\033[0m"


def _sans_couleur() -> bool:
    return not sys.stdout.isatty() or os.environ.get("NO_COLOR")


def c(texte: str, couleur: str) -> str:
    return texte if _sans_couleur() else f"{couleur}{texte}{RAZ}"


# ---------------------------------------------------------------------------
# entrees et plan : le passage de main avec le skill de Kreative
# ---------------------------------------------------------------------------

def commande_entrees(marque: str) -> int:
    """Montre ce que le skill trouvera sur le disque, et l'écrit à côté.

    C'est le seul endroit où la chaîne parle au skill, et elle ne lui dit que
    des chemins : le brief rédigé, les pièces jointes du formulaire, la charte
    mesurée, le contenu des pages, les images du site, les candidats logo et
    les captures. Ce qu'il en fait est son affaire.
    """
    import plan as module_plan

    commande = Commande.charger(marque)
    chemin = module_plan.ecrire_dossier(commande)
    print(module_plan.rapport_dossier(module_plan.dossier_entrees(commande)))
    print(f"\nInventaire écrit : {chemin}")
    print("\nÉtape suivante : appliquer le skill de Kreative sur ces entrées, "
          "puis ranger sa sortie avec :")
    print(f"  python3 kreative.py plan {commande.donnees['ardoise']} "
          f"--fichier <son-plan.json>")
    return 0


def commande_plan(marque: str, fichier: Path) -> int:
    """Range le plan produit par le skill. Ne le corrige jamais."""
    import plan as module_plan

    if not fichier.exists():
        print(f"Plan introuvable : {fichier}", file=sys.stderr)
        return 1
    try:
        bilan = module_plan.importer(marque, fichier)
    except (ValueError, json.JSONDecodeError) as erreur:
        print(f"Erreur : {erreur}", file=sys.stderr)
        return 1

    if bilan.get("plan_entier_refuse"):
        print(c("PLAN REFUSÉ EN ENTIER, rien n'a été rangé.", ROUGE))
        for refus in bilan["refus"]:
            print(f"  {refus}")
        print("\nLe process du skill n'a pas été suivi jusqu'au bout. Reprendre à :")
        print(f"  python3 pipeline/banque.py ouvrir {marque}")
        return 1

    print(f"{len(bilan['importees'])} créa(s) rangée(s)"
          + (f" : {', '.join(bilan['importees'])}" if bilan["importees"] else "."))
    for refus in bilan["refus"]:
        print(f"  {c('REFUS ', ROUGE)} {refus}")
    for alerte in bilan["alertes"]:
        print(f"  {c('ALERTE', ORANGE)} {alerte}")
    for ligne in bilan["ce_qui_a_manque"]:
        print(f"  {c('manqué', GRIS)} {ligne}")
    if bilan["refus"]:
        print("\nLes créas refusées ne sont pas rangées. Elles repartent au skill, "
              "avec le motif ci-dessus : rien n'est corrigé à sa place.")
        return 1
    print(f"\nVoir les prompts : python3 kreative.py prompts {marque}")
    print(f"Préparer le lot  : python3 kreative.py generer {marque}")
    return 0


# ---------------------------------------------------------------------------
# prompts : tout voir d'un coup
# ---------------------------------------------------------------------------

def _etiquette_fabrication(crea: Crea) -> str:
    if crea.prompt.scene:
        return c("génération", ORANGE)
    return c("sans prompt", GRIS)


def commande_prompts(marque: str, brut: bool) -> int:
    commande = Commande.charger(marque)
    creas = commande.creas()

    if brut:
        # Sortie machine : un objet par créa, pour rediriger dans un fichier.
        print(json.dumps([
            {"crea": x.identifiant, "angle": x.angle, "prompt": x.prompt.rendu(),
             "accroche": x.copy.accroche}
            for x in creas
        ], ensure_ascii=False, indent=1))
        return 0

    import couts

    a_generer = [x for x in creas if x.prompt.scene]
    bilan = couts.devis([{"modele": x.prompt.modele,
                          "references": len(x.prompt.references or [])}
                         for x in a_generer])
    chiffre = (f"{bilan['total']} crédits" if bilan["complet"]
               else f"au moins {bilan['total']} crédits, certains modèles non mesurés")
    print(f"{commande.donnees['marque']} : {len(creas)} créas, "
          f"{len(creas) - len(a_generer)} sans prompt, {len(a_generer)} à générer "
          f"({chiffre}).\n")

    for crea in creas:
        print(f"{c(crea.identifiant, ORANGE)}  {_etiquette_fabrication(crea)}  "
              f"{c(crea.etat, GRIS)}")
        print(f"  angle      {crea.angle}")
        print(f"  accroche   {crea.copy.accroche}")
        if crea.prompt.scene:
            for ligne in crea.prompt.rendu().splitlines():
                print(f"  {c('|', GRIS)} {ligne}")
        else:
            print(f"  {c('| aucun prompt : le plan du skill ne couvre pas cette créa', GRIS)}")
        print()
    return 0


# ---------------------------------------------------------------------------
# prompt : corriger une créa
# ---------------------------------------------------------------------------

def commande_prompt(marque: str, identifiant: str, editer: bool,
                    remplacer: Optional[str]) -> int:
    commande = Commande.charger(marque)
    creas = {x.identifiant: x for x in commande.creas()}
    if identifiant not in creas:
        print(f"Créa inconnue : {identifiant}. Connues : {', '.join(sorted(creas))}",
              file=sys.stderr)
        return 1
    crea = creas[identifiant]

    if remplacer is None and not editer:
        print(crea.prompt.rendu()
              or "(aucun prompt : le plan du skill ne couvre pas cette créa)")
        return 0

    if remplacer is not None:
        nouveau = remplacer
    else:
        editeur = os.environ.get("EDITOR", "nano")
        with tempfile.NamedTemporaryFile("w+", suffix=".txt", delete=False,
                                         encoding="utf-8") as fichier:
            fichier.write(crea.prompt.scene)
            temporaire = fichier.name
        subprocess.call([editeur, temporaire])
        nouveau = Path(temporaire).read_text(encoding="utf-8").strip()
        os.unlink(temporaire)

    if nouveau == crea.prompt.scene:
        print("Prompt inchangé.")
        return 0

    crea.prompt.scene = nouveau
    if not crea.prompt.modele:
        crea.prompt.modele = "nano_banana_2"
    # Le master existant devient caduc : la créa repasse en attente de
    # génération, et seule celle ci. C'est la reprise du 7.2 cas A, appliquée
    # à une correction de prompt.
    crea.master = None
    crea.job_generation = None
    crea.rendus = {}
    crea.etat = "briefee"
    crea.tours += 1
    commande.ecrire_crea(crea)
    commande.tracer("prompt_corrige", crea=identifiant, tours=crea.tours)
    print(f"Prompt de {identifiant} mis à jour, créa remise en attente.")
    print(f"Relancer : python3 kreative.py generer {marque} --crea {identifiant}")
    return 0


# ---------------------------------------------------------------------------
# generer : tout, ou une seule
# ---------------------------------------------------------------------------

def commande_generer(marque: str, creas: Optional[List[str]], estimer: bool) -> int:
    """Chiffre, puis prépare le lot que la session de génération consommera.

    Cette commande ne génère pas. Le connecteur MCP Higgsfield n'existe que dans
    une session Claude : elle écrit donc le lot, et la session l'exécute après
    un GO. Le découpage vit dans `pipeline/moteur.py`.
    """
    import couts
    import moteur

    commande = Commande.charger(marque)
    attendus = moteur.a_generer(commande, creas)

    if not attendus:
        composees = [x for x in commande.creas() if not x.prompt.scene]
        print("Aucune créa en attente de génération.")
        if composees:
            print(f"{len(composees)} créas sont composées et ne passent pas par le modèle.")
        return 0

    if estimer:
        # Le chiffrage vient de la table mesurée, plus d'un « fois deux » posé en
        # dur : tous les modèles ne coûtent pas le même prix, et un devis faux
        # autorise une dépense sur une base fausse.
        bilan = couts.devis([{"modele": x.prompt.modele,
                              "references": len(x.prompt.references or [])}
                             for x in attendus])
        for x in attendus:
            print(f"  {x.identifiant}  {x.prompt.modele:<18} {x.copy.accroche[:52]}")
        print()
        print(couts.rapport(bilan, plafond=moteur.PLAFOND_CREDITS_DEFAUT))
        return 0

    lot = moteur.preparer(commande, creas)
    print(moteur.rapport_lot(lot))
    print(f"\nLot écrit : {lot['_fichier']}")
    print("Pour générer : ouvrir une session Claude Code, lire ce lot, "
          "confirmer le devis, puis appeler le MCP Higgsfield.")
    return 2 if lot["au_dessus_du_plafond"] or not lot["devis"]["complet"] else 0


# ---------------------------------------------------------------------------
# etat
# ---------------------------------------------------------------------------

def commande_etat(marque: str) -> int:
    commande = Commande.charger(marque)
    creas = commande.creas()
    par_etat: dict = {}
    for x in creas:
        par_etat[x.etat] = par_etat.get(x.etat, 0) + 1

    d = commande.donnees
    print(f"{d['marque']}  pack {d['pack']}  "
          f"{d['quantite_vendue']} vendues, {d['quantite_generee']} produites")
    print(f"état de la commande : {d['etat']}")
    print(f"verticale : {d.get('verticale', 'non définie')}")
    print()
    for etat, nombre in sorted(par_etat.items()):
        print(f"  {nombre:>3}  {etat}")
    manquants = [x.identifiant for x in creas
                 if "[A COMPLETER:" in (x.copy.accroche + x.copy.sous_accroche)]
    if manquants:
        print(f"\n{c('Brief incomplet', ROUGE)} sur {len(manquants)} créas : "
              f"{', '.join(manquants[:8])}{' ...' if len(manquants) > 8 else ''}")
    return 0


# ---------------------------------------------------------------------------
# page
# ---------------------------------------------------------------------------

def commande_formats(marque: str, creas: Optional[List[str]]) -> int:
    """Tire le 4:5 et le 9:16 du master carré, sans le régénérer."""
    import formats as module_formats

    commande = Commande.charger(marque)
    en_attente = [c for c in commande.creas() if c.prompt.scene and not c.master]
    if en_attente and not creas:
        print(f"{len(en_attente)} créa(s) attendent leur génération : "
              f"{', '.join(c.identifiant for c in en_attente)}")
        print(f"  python3 kreative.py generer {marque}\n")

    bilan = module_formats.decliner(commande, creas)
    if not bilan["traitees"]:
        print("Aucun master à décliner.")
        return 0

    print(f"{bilan['traitees']} créa(s) traitée(s), "
          f"{bilan['completes']} aux trois formats.")
    for identifiant, motifs in bilan["a_etendre"].items():
        for nom, motif in motifs.items():
            print(f"  {c('à étendre', ORANGE)} {identifiant} {nom} : {motif}")
    if bilan["a_etendre"]:
        print(f"\nCes formats se produisent par le connecteur. La liste est dans "
              f"{commande.dossier}/formats/a-etendre.json")

    ecarts = module_formats.verifier(Commande.charger(marque))
    if ecarts:
        print(f"\n{len(ecarts)} écart(s) au contrôle des formats :")
        for ecart in ecarts:
            print(f"  {ecart}")
    return 0


def commande_audit(marque: str, format_json: bool, bloquant: bool) -> int:
    """Les contrôles mécaniques. Aucun ne porte de règle de création.

    Par défaut le code de sortie reste 0 même sur échec : le point ouvert 9.3
    du cahier des charges n'a pas été tranché par Kreative. `--bloquant` rend 1,
    pour enchaîner dans un script le jour où la réponse sera oui.
    """
    import audit
    commande = Commande.charger(marque)
    constats = audit.auditer(commande)
    if format_json:
        import dataclasses
        print(json.dumps([dataclasses.asdict(x) for x in constats],
                         ensure_ascii=False, indent=1))
    else:
        print(audit.rapport(constats, bloquant=bloquant))
    return 1 if bloquant and any(x.bloquant for x in constats) else 0


def commande_livrer(marque: str, vers: Optional[Path], sans_notification: bool) -> int:
    """Le dossier de remise et la notification de l'article 6."""
    import livrer as module_livrer

    try:
        bilan = module_livrer.livrer(marque, vers, not sans_notification)
    except RuntimeError as erreur:
        print(f"Erreur : {erreur}", file=sys.stderr)
        return 1

    print(f"{bilan['creas']} créa(s), {bilan['fichiers']} fichier(s) : "
          f"{bilan['dossier']}")
    notification = bilan.get("notification")
    if notification:
        for voie in notification["voies"]:
            etat = c("envoyée", VERT) if voie.get("ok") else c("non envoyée", GRIS)
            detail = voie.get("erreur") or voie.get("chemin") or ""
            print(f"  notification {voie['voie']:<9} {etat}  {detail}")
    else:
        print("  notification désactivée par --sans-notification")
    return 0


def commande_page(marque: str) -> int:
    import vue
    commande = Commande.charger(marque)
    chemin = vue.ecrire(commande)
    print(f"Page écrite : {chemin}")
    return 0


def commande_verifier() -> int:
    """Contrôle chaque prérequis du poste et dit ce qui manque.

    C'est la première commande à lancer sur une machine neuve, et la seule qui
    ne suppose rien : chaque contrôle nomme ce qu'il vérifie, ce qu'il a
    trouvé, et quoi faire quand ça manque. Zéro contrôle silencieux.
    """
    from etat import RACINE_DEFAUT

    RACINE_CODE = Path(__file__).resolve().parent
    constats: List[tuple] = []          # (ok, sujet, détail)

    def controle(ok: bool, sujet: str, present: str, remede: str) -> None:
        constats.append((ok, sujet, present if ok else remede))

    # 1. Python.
    v = sys.version_info
    controle(v >= (3, 9), "python", f"{v.major}.{v.minor}.{v.micro}",
             "installer Python 3.9 ou plus récent")

    # 2. Playwright et son Chromium.
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        try:
            with sync_playwright() as pw:
                chemin = Path(pw.chromium.executable_path)
            controle(chemin.exists(), "playwright + chromium", str(chemin),
                     "lancer : python3 -m playwright install chromium")
        except Exception as erreur:
            controle(False, "playwright + chromium", "",
                     f"chromium indisponible ({erreur}) : "
                     "python3 -m playwright install chromium")
    except ImportError:
        controle(False, "playwright + chromium", "",
                 "pip3 install playwright && python3 -m playwright install chromium")

    # 3. Tesseract, avec le français et l'anglais.
    tess = shutil.which("tesseract")
    if tess:
        langues = subprocess.run([tess, "--list-langs"], capture_output=True,
                                 text=True).stdout
        manque = [l for l in ("fra", "eng") if l not in langues.split()]
        controle(not manque, "tesseract fra+eng", tess,
                 f"langues manquantes {manque} : brew install tesseract-lang")
    else:
        controle(False, "tesseract fra+eng", "", "brew install tesseract tesseract-lang")

    # 4. Le MCP Higgsfield dans la configuration Claude Code.
    config = Path.home() / ".claude.json"
    try:
        serveurs = json.loads(config.read_text()).get("mcpServers", {})
    except (OSError, json.JSONDecodeError):
        serveurs = {}
    controle("higgsfield" in serveurs, "MCP higgsfield", "configuré dans ~/.claude.json",
             "l'ajouter dans ~/.claude.json puis REDÉMARRER Claude Code : un "
             "connecteur autorisé en cours de session ne publie pas ses outils")

    # 5. La CLI claude, que la rédaction du brief lance en sous-processus.
    cli = shutil.which("claude")
    controle(bool(cli), "CLI claude", cli or "",
             "installer Claude Code : https://claude.com/claude-code")

    # 6. Le skill de stratégie et la banque de références.
    try:
        import redaction
        controle(True, "skill de stratégie", str(redaction.SKILL.name), "")
    except FileNotFoundError as erreur:
        controle(False, "skill de stratégie", "", str(erreur))
    # Dépôt de développement : la banque vit dans skill/. Paquet installé : le
    # code est dans scripts/ et la banque à la racine du skill, un niveau
    # au-dessus.
    banques = [RACINE_CODE / "skill" / "CREAS INSPI DELIVERY",
               RACINE_CODE / "CREAS INSPI DELIVERY",
               RACINE_CODE.parent / "CREAS INSPI DELIVERY"]
    banque = next((b for b in banques if b.is_dir()), None)
    planches = len(list(banque.glob("_PLANCHES/*.jpg"))) if banque else 0
    controle(bool(banque) and planches >= 10, "banque de références",
             f"{banque}, {planches} planches" if banque else "",
             "le dossier CREAS INSPI DELIVERY doit être livré avec le skill, "
             "à côté du SKILL.md")

    # 7. La clé Zite, dans l'environnement du shell.
    controle(bool(os.environ.get("ZITE_API_KEY")), "ZITE_API_KEY",
             "présente dans l'environnement",
             "la poser dans le .env de l'espace de travail puis : "
             "set -a && source .env && set +a")

    # 8. L'espace de travail, inscriptible.
    try:
        RACINE_DEFAUT.mkdir(parents=True, exist_ok=True)
        temoin = RACINE_DEFAUT / ".temoin-ecriture"
        temoin.write_text("ok")
        temoin.unlink()
        controle(True, "espace de travail", str(RACINE_DEFAUT), "")
    except OSError as erreur:
        controle(False, "espace de travail", "",
                 f"{RACINE_DEFAUT} non inscriptible ({erreur}) : poser "
                 "KREATIVE_TRAVAIL vers un dossier à soi")

    # Le bilan, un contrôle par ligne.
    for ok, sujet, detail in constats:
        marque_ligne = "OK    " if ok else "MANQUE"
        print(f"  [{marque_ligne}] {sujet:<22} {detail}")
    rates = [c for c in constats if not c[0]]
    print()
    if rates:
        print(f"{len(rates)} prérequis manquant(s) sur {len(constats)} : "
              "la chaîne ne tournera pas entière.")
        return 1
    print(f"{len(constats)} contrôles, tout est en place.")
    return 0


def main() -> int:
    parseur = argparse.ArgumentParser(
        description="Chaîne de production Kreative",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Le fil directeur")[0].split("\n\n", 1)[1],
    )
    sous = parseur.add_subparsers(dest="action", required=True)

    p = sous.add_parser("entrees", help="Inventorier ce que le skill trouvera sur le disque")
    p.add_argument("marque")

    p = sous.add_parser("plan", help="Ranger le plan produit par le skill de Kreative")
    p.add_argument("marque")
    p.add_argument("--fichier", required=True, type=Path)

    p = sous.add_parser("prompts", help="Afficher tous les prompts du plan")
    p.add_argument("marque")
    p.add_argument("--brut", action="store_true", help="Sortie JSON")

    p = sous.add_parser("prompt", help="Voir ou corriger le prompt d'une créa")
    p.add_argument("marque")
    p.add_argument("crea")
    p.add_argument("--editer", action="store_true", help="Ouvrir dans $EDITOR")
    p.add_argument("--remplacer", help="Remplacer par ce texte")

    p = sous.add_parser("generer", help="Lancer les générations manquantes")
    p.add_argument("marque")
    p.add_argument("--crea", nargs="+", help="Limiter à ces créas")
    p.add_argument("--estimer", action="store_true", help="Coût sans générer")

    p = sous.add_parser("formats", help="Tirer le 4:5 et le 9:16 du master carré")
    p.add_argument("marque")
    p.add_argument("--crea", nargs="+", help="Limiter à ces créas")

    p = sous.add_parser("audit", help="Passer les contrôles mécaniques")
    p.add_argument("marque")
    p.add_argument("--json", action="store_true")
    p.add_argument("--bloquant", action="store_true",
                   help="Rendre 1 en cas d'échec, pour enchaîner dans un script")

    p = sous.add_parser("livrer", help="Construire le dossier de remise et notifier")
    p.add_argument("marque")
    p.add_argument("--vers", type=Path, help="Dossier de remise")
    p.add_argument("--sans-notification", action="store_true")

    p = sous.add_parser("etat", help="Où en est la commande")
    p.add_argument("marque")

    p = sous.add_parser("page", help="Produire la page de suivi")
    p.add_argument("marque")

    sous.add_parser("verifier", help="Contrôler les prérequis du poste, un par un")

    a = parseur.parse_args()
    try:
        if a.action == "entrees":
            return commande_entrees(a.marque)
        if a.action == "plan":
            return commande_plan(a.marque, a.fichier)
        if a.action == "prompts":
            return commande_prompts(a.marque, a.brut)
        if a.action == "prompt":
            return commande_prompt(a.marque, a.crea, a.editer, a.remplacer)
        if a.action == "generer":
            return commande_generer(a.marque, a.crea, a.estimer)
        if a.action == "formats":
            return commande_formats(a.marque, a.crea)
        if a.action == "audit":
            return commande_audit(a.marque, a.json, a.bloquant)
        if a.action == "livrer":
            return commande_livrer(a.marque, a.vers, a.sans_notification)
        if a.action == "etat":
            return commande_etat(a.marque)
        if a.action == "page":
            return commande_page(a.marque)
        if a.action == "verifier":
            return commande_verifier()
    except FileNotFoundError as erreur:
        print(f"Erreur : {erreur}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
