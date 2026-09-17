#!/usr/bin/env python3
"""kreative.py : la chaîne de production, en une commande.

Ce qui remplace le copier coller de prompts un par un :

    python3 kreative.py brief exemples/brief-aloa.json   # commande + plan complet
    python3 kreative.py prompts aloa-design               # voir tous les prompts
    python3 kreative.py generer aloa-design               # tout générer, en un appel
    python3 kreative.py generer aloa-design --crea c07    # relancer une seule créa
    python3 kreative.py prompt aloa-design c07 --editer   # corriger un prompt
    python3 kreative.py composer aloa-design              # les 3 formats
    python3 kreative.py audit aloa-design                 # le gate qualité
    python3 kreative.py page aloa-design                  # la page de suivi
    python3 kreative.py etat aloa-design

Le fil directeur : le prompt est un champ de fichier, pas une chaîne assemblée
au vol. Il est donc visible, corrigeable, et rejouable à l'identique. Corriger
puis relancer une créa ne touche à aucune autre.

Cible Python 3.9+. Aucune dépendance externe hors génération.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

RACINE = Path(__file__).resolve().parent
sys.path.insert(0, str(RACINE / "pipeline"))

import repertoire  # noqa: E402
import strategie  # noqa: E402
from etat import Commande, Crea  # noqa: E402

VERT, ORANGE, GRIS, ROUGE, RAZ = "\033[32m", "\033[33m", "\033[90m", "\033[31m", "\033[0m"


def _sans_couleur() -> bool:
    return not sys.stdout.isatty() or os.environ.get("NO_COLOR")


def c(texte: str, couleur: str) -> str:
    return texte if _sans_couleur() else f"{couleur}{texte}{RAZ}"


# ---------------------------------------------------------------------------
# brief : du fichier de brief au plan complet
# ---------------------------------------------------------------------------

def _purger_masters_orphelins(commande, creas) -> list:
    """Supprime les masters des créas repassées en fabrication composée.

    Un replan réassigne les archétypes, mais les masters sont nommés d'après le
    NUMERO de créa, pas d'après l'archétype. Une créa qui était « produit en
    scène » et devient « affiche typographique » gardait donc son image sur le
    disque, alors que son gabarit ne l'emploie plus.

    Ce n'est pas seulement du désordre. Le gate lit les masters pour y chercher
    du texte gravé : sur le pack Growth il a signalé le mot « otis » dans une
    image qu'aucune créa n'utilisait plus. Un contrôle qui échoue sur un
    fantôme est pire qu'un contrôle absent, il apprend à ignorer les alertes.

    Le master est supprimé, jamais archivé : le régénérer coûte deux crédits,
    et le garder coûte une créa fausse un jour où personne ne regardera.
    """
    from pipeline import repertoire

    supprimes = []
    for crea in creas:
        archetype = str(crea.angle or "").split("/")[-1]
        fiche = repertoire.ARCHETYPES_PAR_CLE.get(archetype)
        if not fiche or fiche.fabrication != repertoire.COMPOSE:
            continue
        identifiant = crea.identifiant
        chemins = [commande.dossier / "masters" / f"{identifiant}.png"]
        chemins += list((commande.dossier / "dist" / identifiant / "_travail")
                        .glob("master-*.png"))
        trouve = False
        for chemin in chemins:
            if chemin.exists():
                chemin.unlink()
                trouve = True
        if trouve:
            supprimes.append(identifiant)
    return supprimes


def commande_brief(chemin: Path, forcer: bool) -> int:
    if not chemin.exists():
        print(f"Brief introuvable : {chemin}", file=sys.stderr)
        return 1
    brief = json.loads(chemin.read_text(encoding="utf-8"))

    obligatoires = ("marque", "pack", "verticale")
    absents = [cle for cle in obligatoires if not brief.get(cle)]
    if absents:
        print(f"Brief incomplet, champs obligatoires absents : {', '.join(absents)}",
              file=sys.stderr)
        return 1

    try:
        commande = Commande.charger(brief["marque"])
        if not forcer:
            print(f"Une commande existe déjà pour « {brief['marque']} ». "
                  f"Relancer avec --forcer pour replanifier.", file=sys.stderr)
            return 1
        commande.donnees["brief"] = brief
        commande.sauver()
    except FileNotFoundError:
        commande = Commande.creer(
            marque=brief["marque"],
            url_site=brief.get("url_site", ""),
            pack=brief["pack"],
            brief=brief,
        )

    try:
        creas, diag = strategie.planifier(commande, forcer=forcer)
    except ValueError as erreur:
        print(f"Erreur : {erreur}", file=sys.stderr)
        return 1

    if not creas:
        print("Toutes les créas sont déjà planifiées. Relancer avec --forcer.")
        return 0

    orphelins = _purger_masters_orphelins(commande, creas)
    print(strategie.rapport(creas, diag))
    if orphelins:
        print(f"\n  {len(orphelins)} master(s) devenu(s) orphelin(s) et supprimé(s) : "
              f"{', '.join(orphelins)}")
        print("  Le replan a réassigné ces créas à un archétype composé, "
              "qui n'emploie aucune image générée.")
    print(f"\nPlan écrit dans {commande.dossier}/creas/")
    print(f"Voir les prompts : python3 kreative.py prompts {commande.donnees['ardoise']}")
    print(f"Tout générer     : python3 kreative.py generer {commande.donnees['ardoise']}")
    return 0


# ---------------------------------------------------------------------------
# prompts : tout voir d'un coup
# ---------------------------------------------------------------------------

def _etiquette_fabrication(crea: Crea) -> str:
    if crea.prompt.scene:
        return c("génération", ORANGE)
    return c("composé", VERT)


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
          f"{len(creas) - len(a_generer)} composées, {len(a_generer)} à générer "
          f"({chiffre}).\n")

    for crea in creas:
        ressort, arch = (crea.angle.split("/") + [""])[:2]
        nom_arch = repertoire.ARCHETYPES_PAR_CLE.get(arch)
        nom_res = repertoire.RESSORTS_PAR_CLE.get(ressort)
        print(f"{c(crea.identifiant, ORANGE)}  {_etiquette_fabrication(crea)}  "
              f"{c(crea.etat, GRIS)}")
        print(f"  archétype  {nom_arch.nom if nom_arch else arch}")
        print(f"  ressort    {nom_res.nom if nom_res else ressort}")
        print(f"  accroche   {crea.copy.accroche}")
        if crea.prompt.scene:
            for ligne in crea.prompt.rendu().splitlines():
                print(f"  {c('|', GRIS)} {ligne}")
        else:
            print(f"  {c('| aucun prompt : cet archétype se compose en HTML', GRIS)}")
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
        print(crea.prompt.rendu() or "(aucun prompt, archétype composé)")
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

def commande_composer(marque: str, creas: Optional[List[str]],
                      formats: Optional[List[str]]) -> int:
    """Fabrique les trois formats. La majorite des creas ne passe pas par un
    modele : elles se composent ici, en HTML, a partir des assets reels."""
    sys.path.insert(0, str(RACINE / "compositeur"))
    import rendu

    commande = Commande.charger(marque)
    a_faire = [c for c in commande.creas()
               if c.etat in ("briefee", "master_ok", "composee")
               and not (c.prompt.scene and not c.master)]
    en_attente = [c for c in commande.creas() if c.prompt.scene and not c.master]
    if creas:
        a_faire = [c for c in a_faire if c.identifiant in set(creas)]

    if en_attente and not creas:
        print(f"{len(en_attente)} créa(s) attendent leur génération : "
              f"{', '.join(c.identifiant for c in en_attente)}")
        print(f"  python3 kreative.py generer {marque}\n")
    if not a_faire:
        print("Aucune créa à composer.")
        return 0

    print(f"{len(a_faire)} créa(s) à composer.")
    rendu.rendre(commande, a_faire, formats)
    apres = {c.identifiant: c for c in Commande.charger(marque).creas()}
    problemes = 0
    for c in a_faire:
        ecarts = rendu.verifier_coherence(commande, apres[c.identifiant])
        if ecarts:
            problemes += 1
            print(f"  [!] {c.identifiant} : {'; '.join(ecarts)}", file=sys.stderr)
    print(f"\n{len(a_faire) - problemes}/{len(a_faire)} conformes à la règle 4.2.")
    return 0


def commande_audit(marque: str, format_json: bool) -> int:
    """Le gate qualite. Sept controles mecaniques, aucun jugement.

    Code de sortie 1 en cas d'echec : la commande peut donc etre enchainee
    dans un script sans que personne lise la sortie.
    """
    import audit
    commande = Commande.charger(marque)
    constats = audit.auditer(commande)
    if format_json:
        import dataclasses
        print(json.dumps([dataclasses.asdict(x) for x in constats],
                         ensure_ascii=False, indent=1))
    else:
        print(audit.rapport(constats))
    return 1 if any(x.bloquant for x in constats) else 0


def commande_page(marque: str) -> int:
    import vue
    commande = Commande.charger(marque)
    chemin = vue.ecrire(commande)
    print(f"Page écrite : {chemin}")
    return 0


def main() -> int:
    parseur = argparse.ArgumentParser(
        description="Chaîne de production Kreative",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Le fil directeur")[0].split("\n\n", 1)[1],
    )
    sous = parseur.add_subparsers(dest="action", required=True)

    p = sous.add_parser("brief", help="Créer la commande et le plan depuis un brief")
    p.add_argument("fichier", type=Path)
    p.add_argument("--forcer", action="store_true", help="Replanifier une commande existante")

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

    p = sous.add_parser("composer", help="Fabriquer les trois formats")
    p.add_argument("marque")
    p.add_argument("--crea", nargs="+", help="Limiter à ces créas")
    p.add_argument("--formats", nargs="+", choices=["1x1", "4x5", "9x16"])

    p = sous.add_parser("audit", help="Passer le gate qualité")
    p.add_argument("marque")
    p.add_argument("--json", action="store_true")

    p = sous.add_parser("etat", help="Où en est la commande")
    p.add_argument("marque")

    p = sous.add_parser("page", help="Produire la page de suivi")
    p.add_argument("marque")

    a = parseur.parse_args()
    try:
        if a.action == "brief":
            return commande_brief(a.fichier, a.forcer)
        if a.action == "prompts":
            return commande_prompts(a.marque, a.brut)
        if a.action == "prompt":
            return commande_prompt(a.marque, a.crea, a.editer, a.remplacer)
        if a.action == "generer":
            return commande_generer(a.marque, a.crea, a.estimer)
        if a.action == "composer":
            return commande_composer(a.marque, a.crea, a.formats)
        if a.action == "audit":
            return commande_audit(a.marque, a.json)
        if a.action == "etat":
            return commande_etat(a.marque)
        if a.action == "page":
            return commande_page(a.marque)
    except FileNotFoundError as erreur:
        print(f"Erreur : {erreur}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
