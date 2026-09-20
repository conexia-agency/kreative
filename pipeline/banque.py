#!/usr/bin/env python3
"""banque.py : rend verifiable la lecture de la banque de references.

Le skill de Kreative decrit precisement comment se sert sa banque : ouvrir
toutes les planches contact de la famille que le secteur designe, retenir les
references pertinentes, **les ouvrir en pleine resolution**, puis seulement
ecrire les creas. Et il termine sa sortie par une liste de controle ou la
session coche elle-meme qu'elle l'a fait.

**Le probleme est la : cocher ne prouve rien.** Le 19/09, un run a cite seize
references dans son plan apres avoir ouvert deux planches sur vingt et aucun
fichier pleine resolution. Rien ne l'a arrete, parce que rien ne regardait.
L'ecart de finition s'est vu sur les visuels, pas sur le plan.

Ce module ne change pas une ligne de son skill. Il rend seulement son propre
process mesurable, en trois temps :

1. `ouvrir` dit quelle famille s'applique, liste TOUTES les planches a ouvrir
   avec leur chemin absolu, et pose l'attendu dans `session/banque.json` ;
2. `retenir` enregistre les references retenues, refuse un identifiant qui
   n'existe pas dans la banque, et donne le chemin pleine resolution de
   chacune ;
3. `verifier` compare, et c'est ce controle que `plan.py` appelle avant
   d'accepter un plan.

    python3 pipeline/banque.py ouvrir <ardoise>
    python3 pipeline/banque.py lue <ardoise> --planches AG1_1 AG1_2
    python3 pipeline/banque.py retenir <ardoise> --refs AG1-07 AG2-10 --du-client AG2-10
    python3 pipeline/banque.py verifier <ardoise>

**Ce que ce controle ne prouve pas, et il faut le savoir.** `lue` est une
DECLARATION de la session, pas une preuve de lecture. La preuve par le systeme
de fichiers a ete cherchee et elle n'existe pas ici : la date de dernier acces
n'est pas mise a jour sur le volume de ce poste, verifie le 19/09 sur une
planche lue en entier, date inchangee.

Ce qui est reellement attrape : l'ETAPE SAUTEE. Une session qui ne consigne
rien voit son plan refuse ; une session qui cite une reference qu'elle n'a pas
retenue se fait nommer la reference ; une session qui invente un identifiant
se fait refuser parce qu'aucun fichier ne porte ce nom. Ce qui reste possible :
declarer avoir lu onze planches sans les avoir ouvertes. Ce module transforme
donc un oubli silencieux en acte explicite et trace, ce qui est un progres
reel, pas en impossibilite. Le jour ou la difference comptera, la suite est de
faire decrire le contenu de chaque planche et de le comparer a un index de la
banque construit une fois.

Cible Python 3.9+. Aucune dependance externe.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))

from etat import Commande  # noqa: E402

NOM_BANQUE = "CREAS INSPI DELIVERY"

# Les trois familles, et les prefixes d'identifiant de chacune. Le skill les
# nomme ainsi : AG1 a AG3 pour agence et SaaS, EC1 a EC5 pour l'e-commerce,
# UG1 a UG6 pour les ugly ads.
FAMILLES: Dict[str, Tuple[str, ...]] = {
    "AGENCE - SAAS": ("AG1", "AG2", "AG3"),
    "ECOMMERCE": ("EC1", "EC2", "EC3", "EC4", "EC5"),
    "UGLY ADS": ("UG1", "UG2", "UG3", "UG4", "UG5", "UG6"),
}

# Routage par le secteur declare au formulaire, comme le skill le pose :
# e-commerce et produit physique vers ECOMMERCE, tout le reste, agence, SaaS,
# service, coaching, business local, vers AGENCE - SAAS.
MOTS_ECOMMERCE = ("commerc", "ecommerc", "e-commerc", "boutique", "produit",
                  "marque", "dtc", "shop")

# Ce qui, dans le brief, ouvre la famille UGLY ADS. Le skill est formel :
# jamais par defaut, uniquement si le client le demande explicitement.
MOTS_UGLY = ("ugly ad", "uglyads", "ugly-ad", "meme", "mème", "format natif",
             "formats natifs", "format decale", "formats decales",
             "format décalé", "formats décalés")

# Le plancher de references a retenir, cale sur le volume du pack, d'apres son
# skill : autour de 10 pour 6 creas, 16 pour 12, 20 pour 24. On retient le
# plancher, pas le nombre exact : c'est la pertinence qui tranche, et il le dit.
PLANCHER_REFERENCES = {6: 10, 12: 16, 18: 18, 24: 20, 48: 20}


def _racine_banque() -> Path:
    """La banque, aux emplacements possibles selon l'installation."""
    candidats = [
        ICI.parent / "skill" / NOM_BANQUE,
        ICI.parent / NOM_BANQUE,
        ICI.parent.parent / NOM_BANQUE,
        ICI.parent / "resources" / NOM_BANQUE,
    ]
    for chemin in candidats:
        if chemin.is_dir():
            return chemin
    raise FileNotFoundError(
        f"banque de references introuvable : le dossier « {NOM_BANQUE} » doit "
        f"etre livre a cote du skill")


def _sans_accent(valeur: str) -> str:
    import unicodedata
    plie = unicodedata.normalize("NFD", valeur or "")
    return "".join(c for c in plie if unicodedata.category(c) != "Mn").lower()


def familles_pour(commande: Commande) -> Tuple[str, List[str], Optional[str]]:
    """La famille principale, les familles a ouvrir, et le motif de l'ugly.

    Le secteur decide de la famille principale. Les ugly ads ne s'ajoutent que
    si le client les demande, et on rend la phrase exacte qui les a declenchees
    pour que la decision soit verifiable.
    """
    brief = commande.donnees.get("brief") or {}
    reponses = brief.get("reponses") or {}
    secteur = _sans_accent(str(reponses.get("secteur") or brief.get("verticale") or ""))

    principale = "ECOMMERCE" if any(m in secteur for m in MOTS_ECOMMERCE) \
        else "AGENCE - SAAS"

    # Les deux champs dedies du formulaire d'abord. Ils portent la demande par
    # un curseur et un menu, donc ils ne contiennent JAMAIS les mots ci-dessus :
    # les chercher dans leur valeur ne pouvait rien trouver. Mesure du 19/09 sur
    # Attar Studio, qui demandait 30 % d'ugly ads par le curseur et n'ouvrait
    # aucune planche UG. Le champ se nomme « part_ugly_ads », sa valeur vaut
    # « 30 » : c'est le nom qui porte le mot, pas le contenu.
    motif = None
    part = str(reponses.get("part_ugly_ads") or "").strip().replace("%", "")
    try:
        if float(part.replace(",", ".")) > 0:
            motif = f"part_ugly_ads : {part}"
    except ValueError:
        pass
    if not motif:
        style = _sans_accent(str(reponses.get("style_creas") or ""))
        if "les deux" in style or "ugly" in style:
            brut = " ".join(str(reponses.get("style_creas") or "").split())
            motif = f"style_creas : {brut[:160]}"

    # La demande d'ugly ads se cherche ensuite partout ou le client ecrit librement.
    champs = ("style_creas", "notes_libres", "part_ugly_ads", "ambiance",
              "promo", "angles_a_eviter")
    for champ in champs:
        if motif:
            break
        texte = _sans_accent(str(reponses.get(champ) or ""))
        for mot in MOTS_UGLY:
            if _sans_accent(mot) in texte:
                brut = str(reponses.get(champ) or "")
                motif = f"{champ} : {' '.join(brut.split())[:160]}"
                break
        if motif:
            break

    familles = [principale] + (["UGLY ADS"] if motif else [])
    return principale, familles, motif


def planches_de(familles: List[str]) -> List[dict]:
    """Toutes les planches contact des familles retenues, avec leur chemin."""
    racine = _racine_banque() / "_PLANCHES"
    prefixes = tuple(p for f in familles for p in FAMILLES.get(f, ()))
    trouvees = []
    for fichier in sorted(racine.glob("PLANCHE_*.jpg")):
        cle = fichier.stem.replace("PLANCHE_", "")
        if cle.split("_")[0] in prefixes:
            trouvees.append({"planche": cle, "chemin": str(fichier)})
    return trouvees


def index_references() -> Dict[str, str]:
    """Chaque identifiant de reference vers son fichier pleine resolution.

    Les fichiers se nomment `HD_AG3-05.jpg` ou `HD_UG1-09_10.jpg`, un ou deux
    identifiants par fichier. On indexe les deux.
    """
    racine = _racine_banque()
    index: Dict[str, str] = {}
    for fichier in racine.rglob("HD_*.jpg"):
        corps = fichier.stem[3:]                       # apres « HD_ »
        morceaux = corps.split("_")
        base = morceaux[0]                             # « AG3-05 »
        index[base] = str(fichier)
        prefixe = base.rsplit("-", 1)[0]               # « AG3 »
        for suite in morceaux[1:]:
            if re.fullmatch(r"\d+", suite):
                index[f"{prefixe}-{suite}"] = str(fichier)
    return index


def _fichier_etat(commande: Commande) -> Path:
    chemin = commande.dossier / "session" / "banque.json"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    return chemin


def _lire_etat(commande: Commande) -> dict:
    chemin = _fichier_etat(commande)
    if not chemin.exists():
        return {}
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _ecrire_etat(commande: Commande, etat: dict) -> None:
    _fichier_etat(commande).write_text(
        json.dumps(etat, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Ouvrir : poser l'attendu
# ---------------------------------------------------------------------------

def ouvrir(commande: Commande) -> dict:
    principale, familles, motif = familles_pour(commande)
    planches = planches_de(familles)
    attendues = commande.donnees.get("quantite_generee") or 0
    plancher = PLANCHER_REFERENCES.get(attendues, 20)

    etat = {
        "famille_principale": principale,
        "familles_ouvertes": familles,
        "ugly_ads_motif": motif,
        "planches_attendues": [p["planche"] for p in planches],
        "planches_lues": [],
        "references_retenues": [],
        "references_du_client": [],
        "plancher_references": plancher,
    }
    _ecrire_etat(commande, etat)
    commande.tracer("banque_ouverte", famille=principale,
                    planches=len(planches), ugly=bool(motif))
    etat["_planches"] = planches
    return etat


def rapport_ouverture(etat: dict) -> str:
    lignes = [
        f"Famille : {etat['famille_principale']}"
        + (f" + UGLY ADS" if "UGLY ADS" in etat["familles_ouvertes"] else ""),
    ]
    if etat.get("ugly_ads_motif"):
        lignes.append(f"  ugly ads ouvertes parce que le brief le demande, {etat['ugly_ads_motif']}")
    else:
        lignes.append("  ugly ads NON ouvertes : le brief ne les demande pas")
    lignes += ["",
               f"{len(etat['planches_attendues'])} planche(s) a ouvrir, toutes, "
               f"avant d'ecrire la moindre crea :"]
    for p in etat.get("_planches", []):
        lignes.append(f"  {p['planche']:<8} {p['chemin']}")
    lignes += ["",
               f"Plancher de references a retenir : {etat['plancher_references']}.",
               "Les ouvrir ensuite en pleine resolution :",
               "  python3 pipeline/banque.py retenir <ardoise> --refs AG1-07 AG2-03 ..."]
    return "\n".join(lignes)


# ---------------------------------------------------------------------------
# 2. Consigner ce qui a ete lu et retenu
# ---------------------------------------------------------------------------

def marquer_lues(commande: Commande, planches: List[str]) -> dict:
    etat = _lire_etat(commande)
    if not etat:
        raise RuntimeError("lancer d'abord : banque.py ouvrir")
    connues = set(etat["planches_attendues"])
    inconnues = [p for p in planches if p not in connues]
    if inconnues:
        raise ValueError(f"planche(s) hors de la famille retenue : {', '.join(inconnues)}. "
                         f"Attendues : {', '.join(sorted(connues))}")
    etat["planches_lues"] = sorted(set(etat.get("planches_lues", [])) | set(planches))
    _ecrire_etat(commande, etat)
    commande.tracer("banque_planches_lues", lues=len(etat["planches_lues"]),
                    attendues=len(connues))
    return etat


def retenir(commande: Commande, refs: List[str],
            du_client: Optional[List[str]] = None) -> dict:
    etat = _lire_etat(commande)
    if not etat:
        raise RuntimeError("lancer d'abord : banque.py ouvrir")

    index = index_references()
    prefixes = tuple(p for f in etat["familles_ouvertes"] for p in FAMILLES.get(f, ()))

    inconnues = [r for r in refs if r not in index]
    if inconnues:
        raise ValueError(f"reference(s) inexistante(s) dans la banque : "
                         f"{', '.join(inconnues)}. Une reference qu'on n'a pas "
                         f"ouverte ne se cite pas.")
    hors_famille = [r for r in refs if not r.startswith(prefixes)]
    if hors_famille:
        raise ValueError(f"reference(s) hors de la famille retenue : "
                         f"{', '.join(hors_famille)}. Familles ouvertes : "
                         f"{', '.join(etat['familles_ouvertes'])}")

    etat["references_retenues"] = sorted(set(refs))
    etat["references_du_client"] = sorted(set(du_client or []))
    etat["chemins_pleine_resolution"] = {r: index[r] for r in sorted(set(refs))}
    _ecrire_etat(commande, etat)
    commande.tracer("banque_references_retenues", retenues=len(refs),
                    du_client=len(etat["references_du_client"]))
    return etat


def extraire(commande: Commande) -> Dict[str, str]:
    """Donne à chaque référence retenue son fichier à elle, pleine résolution.

    Les fichiers `HD_` de la banque portent DEUX créas côte à côte : une
    lecture d'image partage donc ses pixels entre les deux, et sur les plus
    petits fichiers (712 px de large pour deux créas, mesuré), chaque
    référence descend à ~350 px : on y lit la composition, pas la finition.
    Ce découpage écrit une image par référence retenue, moitié gauche ou
    droite selon la position de l'identifiant dans le nom du fichier, dans
    `session/references/` de la commande. La lecture se fait ensuite une
    créa par image, avec toute la résolution disponible pour chacune.
    """
    from PIL import Image  # local : banque.py reste importable sans Pillow

    etat = _lire_etat(commande)
    chemins = etat.get("chemins_pleine_resolution") or {}
    if not chemins:
        raise RuntimeError("aucune référence retenue : lancer « retenir » d'abord.")

    dossier = commande.dossier / "session" / "references"
    dossier.mkdir(parents=True, exist_ok=True)
    sorties: Dict[str, str] = {}
    for ref, chemin in sorted(chemins.items()):
        source = Path(chemin)
        if not source.exists():
            raise RuntimeError(f"{ref} : fichier disparu, {source}")
        # HD_<A>_<B>.jpg : A à gauche, B à droite. HD_<A>.jpg : la créa seule.
        ids = source.stem.replace("HD_", "").split("_")
        destination = dossier / f"{ref}.jpg"
        with Image.open(source) as image:
            if len(ids) == 2 and ref in ids:
                largeur, hauteur = image.size
                moitie = (0, 0, largeur // 2, hauteur) if ref == ids[0] \
                    else (largeur // 2, 0, largeur, hauteur)
                image.crop(moitie).save(destination, quality=92)
            else:
                image.convert("RGB").save(destination, quality=92)
        sorties[ref] = str(destination)
    return sorties


# ---------------------------------------------------------------------------
# 3. Verifier : le gate que plan.py appelle
# ---------------------------------------------------------------------------

def verifier(commande: Commande, refs_du_plan: Optional[List[str]] = None) -> List[str]:
    """Les manquements, en clair. Liste vide si le process a ete suivi."""
    etat = _lire_etat(commande)
    if not etat:
        return ["la banque de references n'a jamais ete ouverte pour cette commande : "
                "lancer banque.py ouvrir, puis lire les planches"]

    fautes: List[str] = []

    attendues = set(etat.get("planches_attendues") or [])
    lues = set(etat.get("planches_lues") or [])
    manquantes = sorted(attendues - lues)
    if manquantes:
        fautes.append(f"{len(manquantes)} planche(s) de la famille non ouverte(s) : "
                      f"{', '.join(manquantes)}. Le skill demande de les ouvrir toutes.")

    retenues = set(etat.get("references_retenues") or [])
    plancher = etat.get("plancher_references") or 10
    if not retenues:
        fautes.append("aucune reference retenue, et aucune ouverte en pleine resolution")
    elif len(retenues) < plancher:
        fautes.append(f"{len(retenues)} reference(s) retenue(s) pour un plancher de "
                      f"{plancher} sur ce volume de pack")

    # Les fichiers d'extraire, preuve que la pleine resolution a ete produite.
    # Declarer une reference retenue ne coute rien ; le fichier decoupe sur le
    # disque, lui, ne peut pas etre coche : il existe ou il n'existe pas.
    # C'est le seul cran de plus qu'un controle mecanique peut serrer, la
    # lecture des images reste un acte de la session.
    if retenues:
        dossier_extraits = commande.dossier / "session" / "references"
        sans_fichier = sorted(r for r in retenues
                              if not (dossier_extraits / f"{r}.jpg").exists())
        if sans_fichier:
            fautes.append(f"{len(sans_fichier)} reference(s) retenue(s) sans fichier "
                          f"pleine resolution sur le disque : {', '.join(sans_fichier)}. "
                          f"Lancer banque.py extraire, puis OUVRIR chaque fichier de "
                          f"session/references/ un par un avant d'ecrire le plan.")

    du_client = set(etat.get("references_du_client") or [])
    reprises = sorted(retenues & du_client)
    if reprises:
        fautes.append(f"reference(s) retenue(s) alors qu'elles portent la marque du "
                      f"client : {', '.join(reprises)}. Le skill l'interdit, un client "
                      f"qui revient veut du neuf.")

    if refs_du_plan is not None:
        citees = set(refs_du_plan)
        non_ouvertes = sorted(citees - retenues)
        if non_ouvertes:
            fautes.append(f"le plan cite {len(non_ouvertes)} reference(s) qui n'ont pas "
                          f"ete ouvertes en pleine resolution : {', '.join(non_ouvertes)}")
    return fautes


MOTIF_REFERENCE = re.compile(r"\b(?:AG[1-3]|EC[1-5]|UG[1-6])-\d{2}\b")

# La ligne du format de sortie du skill qui porte la selection, et elle seule.
MOTIF_LIGNE_RETENUES = re.compile(
    r"^[-*\s]*\**\s*R[ée]f[ée]rences?\s+visuelles?\s+retenues?\s*\**\s*:(.*)$",
    re.I | re.M)


def references_citees(texte: str) -> List[str]:
    """Les references que le plan declare RETENIR, et rien d'autre.

    La nuance est necessaire. Un plan honnete NOMME aussi les references qu'il
    ecarte, par exemple les anciennes creas du client, et il a raison de le
    faire : c'est la trace de la decision. Chercher les identifiants dans tout
    le texte confondait les deux, et refusait un plan justement parce qu'il
    expliquait ce qu'il avait ecarte. Constate le 19/09 sur le plan Podmax v2.

    On lit donc la seule ligne que le format de sortie du skill prevoit pour la
    selection, « References visuelles retenues ». A defaut de cette ligne, on
    retombe sur le texte entier : mieux vaut un controle trop large qu'aucun.
    """
    ligne = MOTIF_LIGNE_RETENUES.search(texte or "")
    portee = ligne.group(1) if ligne else (texte or "")
    return sorted(set(MOTIF_REFERENCE.findall(portee)))


# ---------------------------------------------------------------------------

def main() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sous = analyseur.add_subparsers(dest="action", required=True)

    p = sous.add_parser("ouvrir", help="poser la famille et les planches a ouvrir")
    p.add_argument("ardoise")

    p = sous.add_parser("lue", help="consigner les planches ouvertes")
    p.add_argument("ardoise")
    p.add_argument("--planches", nargs="+", required=True)

    p = sous.add_parser("retenir", help="consigner les references retenues")
    p.add_argument("ardoise")
    p.add_argument("--refs", nargs="+", required=True)
    p.add_argument("--du-client", nargs="*", dest="du_client",
                   help="celles qui portent la marque du client du jour")

    p = sous.add_parser("extraire", help="une image par reference retenue, pleine resolution")
    p.add_argument("ardoise")

    p = sous.add_parser("verifier", help="controler que le process a ete suivi")
    p.add_argument("ardoise")

    args = analyseur.parse_args()

    try:
        commande = Commande.charger(args.ardoise)

        if args.action == "extraire":
            sorties = extraire(commande)
            for ref, chemin in sorties.items():
                print(f"  {ref}  {chemin}")
            print(f"{len(sorties)} référence(s) découpée(s), une créa par image : les ouvrir une par une.")
            return 0

        if args.action == "ouvrir":
            print(rapport_ouverture(ouvrir(commande)))
            return 0

        if args.action == "lue":
            etat = marquer_lues(commande, args.planches)
            reste = sorted(set(etat["planches_attendues"]) - set(etat["planches_lues"]))
            print(f"{len(etat['planches_lues'])}/{len(etat['planches_attendues'])} planche(s) lue(s).")
            if reste:
                print(f"  reste a ouvrir : {', '.join(reste)}")
            return 0

        if args.action == "retenir":
            etat = retenir(commande, args.refs, args.du_client)
            print(f"{len(etat['references_retenues'])} reference(s) retenue(s), "
                  f"plancher {etat['plancher_references']}.")
            for ref, chemin in etat["chemins_pleine_resolution"].items():
                marque = "  [marque du client]" if ref in etat["references_du_client"] else ""
                print(f"  {ref:<8} {chemin}{marque}")
            return 0

        fautes = verifier(commande)
        if not fautes:
            print("Banque : process suivi.")
            return 0
        print(f"{len(fautes)} manquement(s) :")
        for f in fautes:
            print(f"  {f}")
        return 1

    except (FileNotFoundError, RuntimeError, ValueError) as erreur:
        print(f"Erreur : {erreur}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
