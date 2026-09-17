#!/usr/bin/env python3
"""couts.py : ce qu'une génération va coûter, avant de la lancer.

Pourquoi une table locale plutôt qu'une question au fournisseur. Le connecteur
MCP Higgsfield n'expose aucun devis : il donne `balance`, qui dit le solde, et
`marketing_studio_v2_costs`, qui ne couvre que Marketing Studio v2. Il n'y a pas
d'équivalent du `--cost-only` de l'ancienne ligne de commande. Le prix se calcule
donc ici, et se vérifie après coup.

**Aucun prix n'est inventé.** Un modèle absent de la table rend `None`, et le
devis le dit au lieu de deviner. Un devis faux est pire qu'un devis manquant :
il autorise une dépense sur une base fausse, et personne ne revient vérifier.

**La table se corrige toute seule.** `enregistrer` compare le solde avant et
après un lot et écrit l'observation dans `couts-observes.jsonl`. `ecarts` relit
ce journal et signale les modèles dont le prix affiché ne correspond plus. Le
fournisseur change ses tarifs sans prévenir ; la mesure, elle, ne ment pas.

Un piège d'identifiant, payé le 11/09 : le modèle qui s'affiche « Nano Banana 2 »
dans l'interface est `nano_banana_flash`, à 1,5 crédit, et ce n'est PAS le Pro.
On écrit toujours l'identifiant explicite.

Cible Python 3.9+. Aucune dépendance externe.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

RACINE = Path(__file__).resolve().parent.parent
JOURNAL_COUTS = RACINE / "commandes" / "_couts" / "couts-observes.jsonl"

# Écart toléré entre le prix affiché et le prix mesuré, en proportion. Au delà,
# la table est réputée périmée et le devis porte une alerte.
TOLERANCE = 0.15


class Tarif:
    """Le prix d'un modèle, et d'où vient ce chiffre.

    La source est portée avec le prix, parce qu'un prix sans provenance finit
    toujours par être recopié ailleurs comme s'il était vérifié.

    Trois façons de coûter, et les confondre fausse le devis du simple au
    neuvième :

    `base` : le prix en texte vers image, réglages par défaut.

    `i2i` : le prix quand une image de référence est jointe. Nano Banana Pro
    passe de 2 à 4 crédits, mesuré le 08/09 sur le lot ATCLUB (22 crédits pour
    5 générations t2i et 3 i2i). Une chaîne qui compose ses produits en i2i,
    comme la nôtre, paie donc le double de ce qu'un devis naïf annonce.

    `paliers` : le prix par couple qualité/résolution, pour les modèles qui en
    exposent. MS Image va de 0,5 à 7 crédits, soit un facteur quatorze.
    """

    __slots__ = ("base", "i2i", "paliers", "mesure_le", "note")

    def __init__(self, base: Optional[float], mesure_le: str, note: str = "",
                 i2i: Optional[float] = None,
                 paliers: Optional[Dict[str, float]] = None):
        self.base = base
        self.i2i = i2i
        self.paliers = paliers or {}
        self.mesure_le = mesure_le
        self.note = note


# Relevés des 2026-09-08 (lot ATCLUB, mesure en direct) et 2026-09-11, sur le
# compte Conexia en plan ultra. Les modèles absents de cette table ne sont pas
# gratuits : ils ne sont pas mesurés.
TARIFS: Dict[str, Tarif] = {
    # Mesuré le 17/09 sur le lot Podmax, relevé de transactions à l'appui : six
    # images à 2 crédits, dont CINQ avec références. L'image vers image ne coûte
    # donc pas plus cher, contrairement à ce que cette table affirmait depuis le
    # 08/09. L'ancienne valeur de 4 venait d'un relevé fait à la ligne de
    # commande et jamais recoupé ; ce jour-là, le solde avait bougé de 96 alors
    # que la dépense réelle était de 12, le reste étant des vidéos lancées en
    # parallèle par quelqu'un d'autre. C'est la démonstration que le solde seul
    # ne prouve rien, et que seul le relevé ligne par ligne attribue un coût.
    "nano_banana_pro": Tarif(2.0, "2026-09-17", "mesuré sur relevé, i2i au même prix"),
    "nano_banana_2": Tarif(2.0, "2026-09-17", "ce que le serveur renvoie quand on demande le Pro"),
    "nano_banana_flash": Tarif(1.5, "2026-09-11", "s'affiche « Nano Banana 2 », n'est pas le Pro"),
    "nano_banana_2_lite": Tarif(1.0, "2026-09-11"),
    "gpt_image_2_5": Tarif(1.5, "2026-09-11", "qualité basse ; les paliers hauts coûtent plus"),
    "recraft_v4_1": Tarif(1.25, "2026-09-11", "mode utility pour les packshots"),
    "ms_image": Tarif(0.75, "2026-09-08", "le prix dépend du palier, de 0,5 à 7",
                      paliers={"low/1k": 0.5, "low/2k": 0.75,
                               "medium/1k": 2.0, "medium/2k": 3.0,
                               "high/1k": 4.0, "high/2k": 7.0}),
    "image_background_remover": Tarif(None, "", "non mesuré : le détourage semble gratuit, à vérifier"),
}

# Modèles vus au catalogue MCP le 2026-09-16 mais jamais facturés sur ce compte.
# Ils sont listés pour que `devis` distingue « inconnu du catalogue » de
# « connu mais non mesuré », qui n'appellent pas la même réaction.
CONNUS_NON_MESURES = {
    "soul_2", "soul_v2", "soul_cinematic", "soul_cast", "soul_location",
    "gpt_image_2", "openai_hazel", "cinematic_studio_2_5", "marketing_studio_image",
    "image_auto", "z_image", "nano_banana", "nano_banana_2_shots",
    "seedream_v4_5", "seedream_v5_lite", "seedream_v5_pro", "flux_2", "flux_kontext",
    "kling_omni_image", "grok_image", "grok_image_2_0", "outpaint", "topaz_image",
}


def prix(modele: str, references: int = 0, qualite: Optional[str] = None,
         resolution: str = "2k") -> Optional[float]:
    """Le prix unitaire d'une image, ou None si ce cas n'est pas mesuré.

    `references` est le NOMBRE d'images jointes, pas un booléen : une seule
    suffit à faire basculer le tarif en image vers image, et c'est ce qui compte.
    """
    tarif = TARIFS.get(modele)
    if tarif is None:
        return None
    if tarif.paliers:
        if qualite is None:
            return tarif.base          # le palier par défaut, documenté dans la note
        return tarif.paliers.get(f"{qualite}/{resolution}")
    if references and tarif.i2i is not None:
        return tarif.i2i
    return tarif.base


def _libelle(modele: str, references: int, qualite: Optional[str]) -> str:
    """Le nom affiché d'une ligne de devis : le modèle ET ce qui change son prix."""
    details = []
    if references:
        details.append("i2i")
    if qualite:
        details.append(qualite)
    return f"{modele} ({', '.join(details)})" if details else modele


def devis(jobs: List[dict]) -> dict:
    """Le coût d'un lot, ligne par ligne, avec ce qu'on ne sait pas chiffrer.

    `jobs` accepte soit des chaînes (le nom du modèle seul), soit des objets
    `{modele, references, qualite, resolution}`. La forme longue est la bonne :
    une image vers image coûte le double d'une texte vers image sur Nano Banana
    Pro, et un devis qui l'ignore se trompe de moitié sur une chaîne qui compose
    tous ses produits en référence.

    Rend toujours `total`, `mesures` et `inconnus`. Un total accompagné d'une
    liste `inconnus` non vide est un total PARTIEL : c'est à l'appelant de
    refuser, pas à cette fonction de trancher à sa place.
    """
    groupes: Dict[Tuple[str, int, Optional[str], str], int] = defaultdict(int)
    for job in jobs:
        if isinstance(job, str):
            job = {"modele": job}
        cle = (job.get("modele", ""),
               1 if (job.get("references") or 0) else 0,
               job.get("qualite"),
               job.get("resolution") or "2k")
        groupes[cle] += 1

    lignes, inconnus, total = [], [], 0.0
    for (modele, i2i, qualite, resolution), nombre in sorted(
            groupes.items(), key=lambda e: (e[0][0], e[0][1], e[0][2] or "")):
        unitaire = prix(modele, i2i, qualite, resolution)
        libelle = _libelle(modele, i2i, qualite)
        if unitaire is None:
            inconnus.append({
                "modele": libelle, "nombre": nombre,
                "raison": ("au catalogue mais jamais facturé sur ce compte"
                           if modele in CONNUS_NON_MESURES else
                           "palier non mesuré" if modele in TARIFS else
                           "inconnu du catalogue"),
            })
            continue
        ligne_total = unitaire * nombre
        total += ligne_total
        lignes.append({"modele": libelle, "nombre": nombre,
                       "unitaire": unitaire, "total": round(ligne_total, 2),
                       "mesure_le": TARIFS[modele].mesure_le})

    return {
        "total": round(total, 2),
        "complet": not inconnus,
        "mesures": lignes,
        "inconnus": inconnus,
        "nombre": len(jobs),
    }


def rapport(bilan: dict, solde: Optional[float] = None, plafond: Optional[float] = None) -> str:
    """Le devis en clair, pour la décision humaine qui suit."""
    lignes = []
    for ligne in bilan["mesures"]:
        lignes.append(f"  {ligne['nombre']:>3} x {ligne['modele']:<24} "
                      f"{ligne['unitaire']:>5} = {ligne['total']:>7} crédits")
    for inconnu in bilan["inconnus"]:
        lignes.append(f"  {inconnu['nombre']:>3} x {inconnu['modele']:<24} "
                      f"      NON CHIFFRÉ ({inconnu['raison']})")

    lignes.append("")
    if bilan["complet"]:
        lignes.append(f"Total : {bilan['total']} crédits pour {bilan['nombre']} image(s).")
    else:
        lignes.append(f"Total PARTIEL : {bilan['total']} crédits, "
                      f"{sum(i['nombre'] for i in bilan['inconnus'])} image(s) non chiffrée(s).")
        lignes.append("Un devis incomplet n'autorise pas une dépense : mesurer d'abord "
                      "le modèle manquant sur une image seule.")

    if solde is not None:
        lignes.append(f"Solde : {solde} crédits.")
        if bilan["complet"] and bilan["total"] > solde:
            lignes.append(f"REFUS : il manque {round(bilan['total'] - solde, 2)} crédits.")
    if plafond is not None and bilan["total"] > plafond:
        lignes.append(f"AU DESSUS DU PLAFOND ({plafond} crédits) : "
                      f"cet arrêt attend une décision humaine.")
    return "\n".join(lignes)


# ---------------------------------------------------------------------------
# Calibration : la table se corrige sur la mesure, pas sur la mémoire
# ---------------------------------------------------------------------------

def enregistrer(modele: str, nombre: int, solde_avant: float, solde_apres: float,
                ardoise: str = "", note: str = "") -> dict:
    """Consigne le coût réel d'un lot, mesuré sur l'écart de solde.

    À n'appeler que sur un lot d'UN SEUL modèle, et seulement si rien d'autre
    n'a tourné pendant ce temps. Le compte Higgsfield est utilisé en parallèle :
    le 09/09, dix-huit transactions sont passées en une heure alors que quatre
    jobs seulement avaient été lancés depuis cette chaîne. Un écart de solde
    contient donc parfois la dépense de quelqu'un d'autre, et cette observation
    est une indication, jamais une preuve à elle seule.
    """
    consomme = round(solde_avant - solde_apres, 4)
    unitaire = round(consomme / nombre, 4) if nombre else None
    affiche = prix(modele)
    observation = {
        "horodatage": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "modele": modele, "nombre": nombre, "ardoise": ardoise,
        "solde_avant": solde_avant, "solde_apres": solde_apres,
        "consomme": consomme, "unitaire_mesure": unitaire,
        "unitaire_affiche": affiche, "note": note,
    }
    JOURNAL_COUTS.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL_COUTS.open("a", encoding="utf-8") as flux:
        flux.write(json.dumps(observation, ensure_ascii=False) + "\n")
    return observation


def ecarts() -> List[dict]:
    """Les modèles dont le prix affiché ne colle plus à la mesure.

    On agrège toutes les observations d'un modèle avant de conclure : une seule
    mesure polluée par une dépense parallèle ferait condamner un prix juste.
    """
    if not JOURNAL_COUTS.exists():
        return []

    releves: Dict[str, List[float]] = defaultdict(list)
    for ligne in JOURNAL_COUTS.read_text(encoding="utf-8").splitlines():
        if not ligne.strip():
            continue
        try:
            obs = json.loads(ligne)
        except json.JSONDecodeError:
            continue
        if obs.get("unitaire_mesure") is not None:
            releves[obs["modele"]].append(float(obs["unitaire_mesure"]))

    signales = []
    for modele, mesures in sorted(releves.items()):
        mesures.sort()
        median = mesures[len(mesures) // 2]
        affiche = prix(modele)
        if affiche is None:
            signales.append({"modele": modele, "affiche": None, "median": round(median, 3),
                             "observations": len(mesures),
                             "verdict": "non mesuré dans la table, la mesure existe : à inscrire"})
            continue
        if affiche <= 0:
            continue
        if abs(median - affiche) / affiche > TOLERANCE:
            signales.append({"modele": modele, "affiche": affiche, "median": round(median, 3),
                             "observations": len(mesures),
                             "verdict": "la table est périmée : corriger TARIFS"})
    return signales


def main() -> int:
    import argparse
    analyseur = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sous = analyseur.add_subparsers(dest="action", required=True)
    sous.add_parser("table", help="afficher les prix connus")
    p_dev = sous.add_parser("devis", help="chiffrer un lot")
    p_dev.add_argument("modeles", nargs="+")
    sous.add_parser("ecarts", help="comparer la table aux coûts observés")
    args = analyseur.parse_args()

    if args.action == "table":
        print(f"{'modèle':<26} {'t2i':>7} {'i2i':>7}  mesuré le   note")
        for nom, tarif in sorted(TARIFS.items()):
            base = f"{tarif.base}" if tarif.base is not None else "-"
            deux = f"{tarif.i2i}" if tarif.i2i is not None else "-"
            print(f"{nom:<26} {base:>7} {deux:>7}  {tarif.mesure_le or '-':<11} {tarif.note}")
            for palier, valeur in sorted(tarif.paliers.items()):
                print(f"{'':<26} {palier:>15} = {valeur} crédits")
        print(f"\n{len(CONNUS_NON_MESURES)} autres modèles au catalogue MCP, jamais facturés ici.")
        return 0

    if args.action == "devis":
        # `nom:i2i` pour chiffrer une image vers image, `nom:qualite` pour un palier.
        jobs = []
        for brut in args.modeles:
            nom, _, variante = brut.partition(":")
            jobs.append({"modele": nom,
                         "references": 1 if variante == "i2i" else 0,
                         "qualite": variante if variante in ("low", "medium", "high") else None})
        print(rapport(devis(jobs)))
        return 0

    signales = ecarts()
    if not signales:
        print("Aucun écart : la table colle aux coûts observés.")
        return 0
    for s in signales:
        print(f"{s['modele']:<26} affiché {s['affiche']}  mesuré {s['median']}  "
              f"({s['observations']} obs.)  {s['verdict']}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
