#!/usr/bin/env python3
"""orchestrateur.py : fait tourner la chaîne sans personne devant l'écran.

    python3 orchestrateur.py tourner --une-fois
    python3 orchestrateur.py tourner --intervalle 300
    python3 orchestrateur.py etat

Un cycle enchaîne les maillons dans l'ordre, sur toutes les commandes concernées :

1. **relevé** : les nouvelles soumissions Zite deviennent des commandes (`zite.py`) ;
2. **rédaction** : les réponses brutes deviennent un brief moteur (`redaction.py`) ;
3. **stratégie** : le brief devient un plan de créas (`strategie.py`).

**Le cycle s'arrête avant la génération.** C'est voulu. Générer dépense des
crédits, et le dernier pack produit sans regard humain, le 08/09, est parti entier
au rebut. Tant que la qualité du moteur n'a pas été validée sur rendus, une commande
planifiée attend un feu vert. `--generer` lève ce verrou quand on l'aura décidé.

**Une commande qui échoue n'arrête pas les autres.** L'erreur est journalisée dans
la commande, qui passe en état `echec`, et le cycle continue. Un seul brief mal
formé ne doit pas bloquer une nuit entière de relevés.

**Un seul cycle à la fois.** Un verrou empêche deux orchestrateurs de traiter la
même soumission en parallèle, ce qui ouvrirait deux fois la même commande.

Cible Python 3.9+. Le `.env` racine doit être chargé dans l'environnement.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import List

RACINE = Path(__file__).resolve().parent
sys.path.insert(0, str(RACINE / "pipeline"))

import redaction  # noqa: E402
import strategie  # noqa: E402
import zite  # noqa: E402
from etat import RACINE_DEFAUT, Commande  # noqa: E402

VERROU = RACINE_DEFAUT / "_zite" / "orchestrateur.lock"
JOURNAL = RACINE_DEFAUT / "_zite" / "orchestrateur.jsonl"
# Au-delà, un verrou est réputé abandonné par un processus mort.
VERROU_PERIME_S = 2 * 3600


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _journal(evenement: str, **details) -> None:
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    ligne = {"horodatage": _maintenant(), "evenement": evenement, **details}
    with JOURNAL.open("a", encoding="utf-8") as flux:
        flux.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    print(f"  {ligne['horodatage'][11:19]}  {evenement}  "
          + " ".join(f"{k}={v}" for k, v in details.items()))


def _prendre_verrou() -> bool:
    VERROU.parent.mkdir(parents=True, exist_ok=True)
    if VERROU.exists():
        age = time.time() - VERROU.stat().st_mtime
        if age < VERROU_PERIME_S:
            return False
        _journal("verrou_perime_repris", age_s=int(age))
    VERROU.write_text(str(os.getpid()), encoding="utf-8")
    return True


def _rendre_verrou() -> None:
    if VERROU.exists():
        VERROU.unlink()


def _commandes_zite() -> List[Commande]:
    """Les commandes issues de Zite, les seules que l'orchestrateur pilote."""
    retenues = []
    for dossier in sorted(RACINE_DEFAUT.iterdir()):
        if dossier.name.startswith("_") or not (dossier / "brief" / "soumission.json").exists():
            continue
        try:
            retenues.append(Commande.charger(dossier.name))
        except (FileNotFoundError, json.JSONDecodeError):
            continue
    return retenues


def _echouer(commande: Commande, etape: str, erreur: Exception) -> None:
    commande.tracer(f"echec_{etape}", erreur=str(erreur)[:500],
                    trace=traceback.format_exc()[-1500:])
    commande.passer_a("echec")
    _journal("echec", commande=commande.dossier.name, etape=etape, erreur=str(erreur)[:160])


def cycle(generer: bool = False, limite: int = 0) -> dict:
    bilan = {"ouvertes": 0, "redigees": 0, "planifiees": 0, "echecs": 0, "en_attente_generation": 0}

    try:
        releve = zite.relever(appliquer=True)
        bilan["ouvertes"] = sum(1 for l in releve if l.get("action") == "ouverture")
        for ligne in releve:
            _journal("soumission", marque=ligne["marque"], pack=ligne["pack"], action=ligne["action"])
    except Exception as erreur:  # le relevé ne doit pas empêcher de traiter l'existant
        _journal("echec_releve", erreur=str(erreur)[:200])

    redactions_restantes = limite or 10**9
    for commande in _commandes_zite():
        nom = commande.dossier.name
        etat = commande.donnees.get("etat")
        brief = commande.donnees.get("brief") or {}

        if etat == "recue" and not brief.get("_redige"):
            if redactions_restantes <= 0:
                continue
            redactions_restantes -= 1
            try:
                redaction.rediger(nom)
                commande = Commande.charger(nom)
                bilan["redigees"] += 1
                _journal("brief_redige", commande=nom,
                         retraits=len(commande.donnees["brief"].get("_retraits", [])))
            except Exception as erreur:
                _echouer(commande, "redaction", erreur)
                bilan["echecs"] += 1
                continue

        if commande.donnees.get("etat") == "recue" and commande.donnees["brief"].get("_redige"):
            try:
                creas, diag = strategie.planifier(commande)
                bilan["planifiees"] += 1
                marquees = sum(1 for f in (commande.dossier / "creas").glob("*.json")
                               if "[A COMPLETER" in f.read_text(encoding="utf-8"))
                _journal("plan_etabli", commande=nom, creas=len(creas),
                         creas_a_completer=marquees)
            except Exception as erreur:
                _echouer(commande, "strategie", erreur)
                bilan["echecs"] += 1
                continue

        if Commande.charger(nom).donnees.get("etat") == "strategie":
            if generer:
                _journal("generation_non_branchee", commande=nom,
                         note="le moteur natif Higgsfield n'est pas encore raccorde")
            bilan["en_attente_generation"] += 1

    _journal("cycle_termine", **bilan)
    return bilan


def etat() -> int:
    commandes = _commandes_zite()
    if not commandes:
        print("Aucune commande issue de Zite.")
        return 0
    print(f"{'commande':<22} {'pack':<8} {'etat':<12} {'redige':<7} {'creas':>5}  a completer")
    for c in commandes:
        b = c.donnees.get("brief") or {}
        nb = len(list((c.dossier / "creas").glob("*.json")))
        manque = len(b.get("a_completer") or [])
        print(f"{c.dossier.name[:22]:<22} {c.donnees.get('pack',''):<8} "
              f"{c.donnees.get('etat',''):<12} {'oui' if b.get('_redige') else 'non':<7} "
              f"{nb:>5}  {manque}")
    return 0


def main() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sous = analyseur.add_subparsers(dest="commande", required=True)
    p_tourner = sous.add_parser("tourner")
    p_tourner.add_argument("--une-fois", action="store_true")
    p_tourner.add_argument("--intervalle", type=int, default=300, help="secondes entre deux cycles")
    p_tourner.add_argument("--limite", type=int, default=0,
                           help="nombre maximal de redactions par cycle, 0 pour aucune limite")
    p_tourner.add_argument("--generer", action="store_true",
                           help="lever le verrou de generation (non branche a ce jour)")
    sous.add_parser("etat")
    args = analyseur.parse_args()

    if args.commande == "etat":
        return etat()

    if not os.environ.get("ZITE_API_KEY"):
        print("ZITE_API_KEY absente : charger le .env racine avant de lancer.", file=sys.stderr)
        return 1

    while True:
        if not _prendre_verrou():
            print("Un cycle tourne deja (verrou present). Abandon de ce cycle.")
        else:
            try:
                _journal("cycle_demarre", generer=args.generer)
                cycle(generer=args.generer, limite=args.limite)
            finally:
                _rendre_verrou()
        if args.une_fois:
            return 0
        time.sleep(args.intervalle)


if __name__ == "__main__":
    raise SystemExit(main())
