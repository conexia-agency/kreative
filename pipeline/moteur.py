#!/usr/bin/env python3
"""moteur.py : le passage de main entre la chaîne et la session qui génère.

**Ce module n'appelle jamais Higgsfield.** C'est sa raison d'être, pas une
limite qu'on subit. Le connecteur MCP n'existe que dans une session Claude : ni
`cron`, ni `orchestrateur.py`, ni une fonction serveur ne peuvent l'invoquer.
Une chaîne qui prétendrait générer toute seule par le MCP ne tournerait jamais
la nuit, et personne ne s'en apercevrait avant la première livraison manquée.

On coupe donc la génération en trois temps, dont deux sont automatiques :

1. `preparer` écrit `jobs/<horodatage>.json` : tout ce qu'il faut pour générer,
   prompts à l'octet près, modèle, références, et le devis en crédits. Aucun
   réseau. C'est la chaîne sans humain qui le fait.
2. une session Claude lit ce fichier, montre le devis, attend le GO, appelle le
   MCP, et télécharge les images.
3. `recolter` range les images produites, met les créas à jour et journalise le
   coût réel. Aucun réseau non plus.

Le fichier de lot est le contrat. Il se lit sans le code qui l'a écrit, et il
suffit à lui seul : c'est ce qui permet de reprendre un lot trois jours plus
tard, ou sur une autre machine, sans rejouer la stratégie.

Cible Python 3.9+. Aucune dépendance externe.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import couts
from etat import Commande, Crea

# Le format vient du skill de Kreative, qui l'impose noir sur blanc : « Le 1:1
# (carré) est le format par défaut, toujours, tu ne changes de ratio que si le
# brief l'exige explicitement », et sa propre liste de contrôle le vérifie.
# La chaîne ne choisit donc pas le ratio du master, elle recopie le sien. Les
# deux autres formats du 4.2 se tirent de ce carré après coup, dans
# `formats.py`, sans que le master soit régénéré.
FORMAT_MASTER = "1:1"
RESOLUTION = "2k"

# Au-delà, la chaîne s'arrête et demande. C'est l'un des trois seuls arrêts sur
# exception prévus : brief incomplet, site inexploitable, coût au-dessus du
# plafond. Un pack Scale de 48 créas à 2 crédits en coûte 96 ; le plafond laisse
# donc passer un pack entier et arrête une boucle emballée.
PLAFOND_CREDITS_DEFAUT = 120.0


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dossier_jobs(commande: Commande) -> Path:
    chemin = commande.dossier / "jobs"
    chemin.mkdir(parents=True, exist_ok=True)
    return chemin


def a_generer(commande: Commande, filtre: Optional[List[str]] = None) -> List[Crea]:
    """Les créas briefées qui attendent un master.

    Une créa sans `prompt.scene` n'est pas générable : le plan du skill ne l'a
    pas couverte. Elle est laissée de côté plutôt que d'être envoyée au modèle
    avec un prompt vide.
    """
    creas = [c for c in commande.creas() if c.etat == "briefee" and c.prompt.scene]
    if filtre:
        voulus = set(filtre)
        creas = [c for c in creas if c.identifiant in voulus]
    return creas


def construire_prompt(crea: Crea) -> str:
    """Le prompt envoyé au modèle, sans un caractère de plus.

    Rien n'est ajouté ici, et c'est le coeur du sujet. Le prompt entier a été
    écrit par le skill de Kreative et rangé tel quel par `plan.py`. Y ajouter
    une consigne au dernier moment reviendrait à corriger son travail sans que
    personne le voie, et c'est exactement ce qui lui a été reproché le 18/09.

    Conséquence utile : ce que la commande `prompts` affiche est exactement ce
    qui part au modèle, et un prompt corrigé à la main part tel qu'il a été
    corrigé.
    """
    return crea.prompt.rendu()


# ---------------------------------------------------------------------------
# 1. Préparer : de la commande au lot, sans réseau
# ---------------------------------------------------------------------------

def preparer(commande: Commande, filtre: Optional[List[str]] = None,
             plafond: float = PLAFOND_CREDITS_DEFAUT) -> Optional[dict]:
    """Écrit le lot à générer. Rend le lot, ou None s'il n'y a rien à faire."""
    creas = a_generer(commande, filtre)
    if not creas:
        return None

    jobs = []
    for crea in creas:
        references = [r for r in (crea.prompt.references or [])
                      if (commande.dossier / r).exists()]
        manquantes = [r for r in (crea.prompt.references or []) if r not in references]
        jobs.append({
            "crea": crea.identifiant,
            "modele": crea.prompt.modele,
            "prompt": construire_prompt(crea),
            "negatif": crea.prompt.negatif,
            "aspect_ratio": FORMAT_MASTER,
            "resolution": RESOLUTION,
            "references": references,
            "references_manquantes": manquantes,
            "sortie_attendue": f"masters/{crea.identifiant}.png",
        })

    # La forme longue, pas la liste de noms : une image vers image coûte le
    # double sur Nano Banana Pro, et la chaîne compose ses produits en
    # référence. Chiffrer sur le seul nom du modèle sous-estimerait de moitié.
    bilan = couts.devis(jobs)
    lot = {
        "schema": "kreative-lot/1",
        "ardoise": commande.donnees["ardoise"],
        "marque": commande.donnees.get("marque"),
        "prepare_le": _maintenant(),
        "format_master": FORMAT_MASTER,
        "resolution": RESOLUTION,
        "devis": bilan,
        "plafond_credits": plafond,
        "au_dessus_du_plafond": bilan["total"] > plafond,
        "recolte_le": None,
        "solde_avant": None,
        "solde_apres": None,
        "jobs": jobs,
        # Ce bloc est lu par la session qui génère. Il ne porte AUCUNE règle de
        # création : celles-ci sont dans le skill de Kreative, qui a écrit les
        # prompts, et les répéter ici les ferait diverger le jour où il change.
        # Ce qui reste est mécanique, et n'existe qu'ici.
        "consignes": [
            "Le prompt part au modèle sans qu'un caractère soit ajouté ni retiré. "
            "Ne rien compléter, ne rien reformuler, ne rien traduire : il a été "
            "écrit par le skill de Kreative et il fait foi.",
            "Joindre en référence les fichiers listés dans `references`, dans "
            "l'ordre où ils sont donnés : le prompt les appelle par leur rang.",
            "Générer par le connecteur Higgsfield, jamais par la ligne de commande.",
            "Télécharger chaque image produite sur le disque avant de la ranger : "
            "les rendus Higgsfield disparaissent au bout de sept jours.",
            "Relever le solde avant et après le lot, et le passer à `recolter` : "
            "c'est ce qui calibre la table de coûts.",
            "Afficher le devis et attendre un GO explicite avant le premier appel.",
        ],
    }

    fichier = _dossier_jobs(commande) / f"{_maintenant().replace(':', '')}.json"
    fichier.write_text(json.dumps(lot, ensure_ascii=False, indent=2), encoding="utf-8")
    (_dossier_jobs(commande) / "a-lancer.json").write_text(
        json.dumps({"lot": fichier.name, "prepare_le": lot["prepare_le"]},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    commande.tracer("lot_prepare", fichier=fichier.name, jobs=len(jobs),
                    credits_estimes=bilan["total"], devis_complet=bilan["complet"])
    lot["_fichier"] = str(fichier)
    return lot


def lot_en_attente(commande: Commande) -> Optional[dict]:
    """Le lot préparé et non encore récolté, s'il y en a un."""
    pointeur = _dossier_jobs(commande) / "a-lancer.json"
    if not pointeur.exists():
        return None
    try:
        nom = json.loads(pointeur.read_text(encoding="utf-8"))["lot"]
        lot = json.loads((_dossier_jobs(commande) / nom).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, KeyError, FileNotFoundError):
        return None
    if lot.get("recolte_le"):
        return None
    lot["_fichier"] = str(_dossier_jobs(commande) / nom)
    return lot


# ---------------------------------------------------------------------------
# 3. Récolter : des images produites à l'état de la commande
# ---------------------------------------------------------------------------

def recolter(commande: Commande, resultats: List[dict],
             solde_avant: Optional[float] = None,
             solde_apres: Optional[float] = None) -> dict:
    """Range les images générées et met les créas à jour.

    `resultats` est une liste de `{crea, fichier, job_id}`. `fichier` est un
    chemin sur le disque : la session a déjà téléchargé l'image. On ne se fie
    jamais à une URL, parce que les rendus Higgsfield disparaissent au bout de
    sept jours et qu'un master perdu rend la commande irreproductible.

    Une créa absente des résultats reste `briefee` : elle repassera au lot
    suivant. Une commande ne s'arrête pas sur une créa ratée.
    """
    lot = lot_en_attente(commande)
    dossier_masters = commande.dossier / "masters"
    dossier_masters.mkdir(parents=True, exist_ok=True)

    range_ok, refuses = 0, []
    for resultat in resultats:
        identifiant = resultat.get("crea")
        source = Path(resultat.get("fichier") or "")
        if not identifiant or not source.exists():
            refuses.append({"crea": identifiant, "raison": f"fichier introuvable : {source}"})
            continue
        if source.stat().st_size < 5000:
            refuses.append({"crea": identifiant,
                            "raison": f"image suspecte, {source.stat().st_size} octets"})
            continue

        crea = next((c for c in commande.creas() if c.identifiant == identifiant), None)
        if crea is None:
            refuses.append({"crea": identifiant, "raison": "cette créa n'existe pas"})
            continue

        destination = dossier_masters / f"{identifiant}.png"
        if source.resolve() != destination.resolve():
            shutil.move(str(source), str(destination))
        crea.master = str(destination.relative_to(commande.dossier))
        crea.job_generation = resultat.get("job_id")
        crea.etat = "master_ok"
        commande.ecrire_crea(crea)
        commande.tracer("master_genere", crea=identifiant, job=resultat.get("job_id"),
                        modele=crea.prompt.modele)
        range_ok += 1

    # Le coût réel, mesuré sur l'écart de solde. Une seule famille de modèle par
    # lot, sinon l'écart ne s'attribue à personne.
    observation = None
    if solde_avant is not None and solde_apres is not None and range_ok:
        modeles = {c.prompt.modele for c in commande.creas()
                   if c.identifiant in {r.get("crea") for r in resultats}}
        if len(modeles) == 1:
            observation = couts.enregistrer(
                modeles.pop(), range_ok, solde_avant, solde_apres,
                ardoise=commande.donnees["ardoise"])

    if lot:
        lot["recolte_le"] = _maintenant()
        lot["solde_avant"] = solde_avant
        lot["solde_apres"] = solde_apres
        lot["ranges"] = range_ok
        lot["refuses"] = refuses
        fichier = Path(lot.pop("_fichier"))
        fichier.write_text(json.dumps(lot, ensure_ascii=False, indent=2), encoding="utf-8")

    if range_ok and not a_generer(commande):
        commande.passer_a("composition")

    commande.tracer("lot_recolte", ranges=range_ok, refuses=len(refuses),
                    credits_reels=(round(solde_avant - solde_apres, 2)
                                   if solde_avant is not None and solde_apres is not None
                                   else None))
    return {"ranges": range_ok, "refuses": refuses, "observation": observation}


def rapport_lot(lot: dict) -> str:
    """Le lot en clair, pour la décision humaine qui précède la dépense."""
    lignes = [f"{lot['marque']} ({lot['ardoise']}) : {len(lot['jobs'])} master(s) à générer,",
              f"format {lot['format_master']} en {lot['resolution']}.", ""]
    for job in lot["jobs"]:
        refs = f"  [{len(job['references'])} réf.]" if job["references"] else ""
        lignes.append(f"  {job['crea']}  {job['modele']}{refs}")
        if job["references_manquantes"]:
            lignes.append(f"        RÉFÉRENCES ABSENTES : "
                          f"{', '.join(job['references_manquantes'])}")
    lignes.append("")
    lignes.append(couts.rapport(lot["devis"], plafond=lot.get("plafond_credits")))
    return "\n".join(lignes)


def main() -> int:
    import argparse
    analyseur = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sous = analyseur.add_subparsers(dest="action", required=True)
    p_pre = sous.add_parser("preparer", help="écrire le lot à générer")
    p_pre.add_argument("ardoise")
    p_pre.add_argument("--creas", nargs="+")
    p_pre.add_argument("--plafond", type=float, default=PLAFOND_CREDITS_DEFAUT)
    p_att = sous.add_parser("en-attente", help="montrer le lot non récolté")
    p_att.add_argument("ardoise")
    p_rec = sous.add_parser("recolter", help="ranger les images produites")
    p_rec.add_argument("ardoise")
    p_rec.add_argument("--resultats", required=True,
                       help="fichier JSON : [{crea, fichier, job_id}]")
    p_rec.add_argument("--solde-avant", type=float)
    p_rec.add_argument("--solde-apres", type=float)
    args = analyseur.parse_args()

    commande = Commande.charger(args.ardoise)

    if args.action == "preparer":
        lot = preparer(commande, args.creas, args.plafond)
        if not lot:
            print("Aucune créa briefée en attente de génération.")
            return 0
        print(rapport_lot(lot))
        print(f"\nLot écrit : {lot['_fichier']}")
        return 2 if lot["au_dessus_du_plafond"] or not lot["devis"]["complet"] else 0

    if args.action == "en-attente":
        lot = lot_en_attente(commande)
        if not lot:
            print("Aucun lot en attente.")
            return 0
        print(rapport_lot(lot))
        return 0

    resultats = json.loads(Path(args.resultats).read_text(encoding="utf-8"))
    bilan = recolter(commande, resultats, args.solde_avant, args.solde_apres)
    print(f"{bilan['ranges']} master(s) rangé(s).")
    for refus in bilan["refuses"]:
        print(f"  refusé {refus['crea']} : {refus['raison']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
