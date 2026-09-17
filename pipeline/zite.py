#!/usr/bin/env python3
"""zite.py : relève les briefs soumis sur Zite et ouvre les commandes.

C'est le point d'entrée de la chaîne. Une soumission arrive sur un formulaire
d'onboarding, ce module la tire, la range selon `CONVENTIONS.md`, télécharge les
pièces jointes et ouvre une commande prête pour l'étape stratégie.

    python3 pipeline/zite.py formulaires
    python3 pipeline/zite.py relever                # simulation, rien n'est écrit
    python3 pipeline/zite.py relever --appliquer

Quatre choix, tous vérifiés sur les 21 briefs réels relevés le 11/09.

**Polling, pas de webhook.** Le poste tourne en local sans adresse publique : un
webhook entrant n'arriverait jamais. On interroge, et on retient les
`submissionId` déjà traités.

**Mappage par libellé normalisé, pas par identifiant.** Les trois formulaires ont
été dupliqués les uns des autres mais ne partagent que 27 identifiants de question
sur 39. Le libellé, lui, est stable à une coquille près (« téléchargez les » contre
« téléchargez-les »), que la normalisation absorbe.

**Fidélité stricte.** Les réponses sont reprises telles quelles. Ce module ne
reformule rien, ne résume rien, ne complète rien : un paragraphe du client reste un
paragraphe. La mise en forme courte que réclame le moteur (promesse, CTA, douleurs
en groupes nominaux) est l'affaire de l'étape suivante, pas d'un mappage.

**On ne touche jamais un dossier existant.** Les dossiers d'avant la convention
(atclub, podmax, turnly) portent le même nom que leurs soumissions Zite. Écrire
dedans mélangerait un état neuf à des rendus déjà livrés. Une soumission dont le
dossier existe part en attente, visible, et n'est pas produite.

Deux pièges d'API documentés ici parce qu'ils ont coûté du temps. `limit` plafonne
à 150 et renvoie un 400 au-delà. `totalResponses` compte la page renvoyée, pas le
total. Et Zite refuse le User-Agent par défaut de urllib avec un 403, d'où l'en-tête
explicite.

Cible Python 3.9+. Aucune dépendance externe.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "pipeline"))
sys.path.insert(0, str(RACINE / "outils"))

from etat import RACINE_DEFAUT, Commande, ardoise  # noqa: E402

API = "https://api.zite.com/v1/api"
AGENT = "kreative-pipeline/1.0"
LIMITE_PAGE = 150

# Les formulaires qui déclenchent une production, et le pack qu'ils vendent.
FORMULAIRES_PACK: Dict[str, str] = {
    "hSWiGFjTVhus": "starter",
    "soMTps1WZmus": "growth",
    "sPx62jwVQqus": "scale",
}

DOSSIER_ZITE = RACINE_DEFAUT / "_zite"
FICHIER_TRAITEES = DOSSIER_ZITE / "traitees.json"
DOSSIER_ATTENTE = DOSSIER_ZITE / "en-attente"


# ---------------------------------------------------------------------------
# Mappage
# ---------------------------------------------------------------------------

def normaliser(libelle: str) -> str:
    """Réduit un libellé à ses lettres : sans accent, sans ponctuation, sans espace."""
    sans_accent = unicodedata.normalize("NFKD", libelle)
    sans_accent = "".join(c for c in sans_accent if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", sans_accent.lower())


# Début de libellé normalisé vers champ. Un préfixe suffit : il survit aux
# retouches de fin de phrase que Kreative fera sur ses formulaires.
CHAMPS_TEXTE: Dict[str, str] = {
    "quelestlenomdevotreentreprise": "marque",
    "quelleestlurldevotresiteweb": "url_site",
    "quelestvotresecteurdactivite": "secteur",
    "combiendeproduitssouhaitez": "nombre_produits",
    "veuillezdecrirevotreoffre": "offre_description",
    "questcequivousdifferencie": "differenciation",
    "nomduproduitetprix": "produit_et_prix",
    "pourquoivosclientsachetent": "raison_achat",
    "quelproblemeconcretresoutil": "probleme_resolu",
    "quelssontvosproduits": "produits",
    "commentsouhaitezvousrepartir": "repartition_produits",
    "veuillezdecrirevotreclientideal": "client_ideal",
    "questcequifreinevosprospects": "freins",
    "quelestvotreobjectifprincipal": "objectif",
    "quelleestcettepromo": "promo",
    "quelsanglesouelementsfautileviter": "angles_a_eviter",
    "quelssontcesresultats": "preuves",
    "quellessontvoscouleursprincipales": "couleurs",
    "quellessontvospolices": "polices",
    "en3motsdecrivezvotreambiance": "ambiance",
    "yatilautrechosequenousdevonssavoir": "notes_libres",
    "queltonvoulezvous": "ton",
    "preferezvousquonsadresse": "adresse",
}

# Pièces jointes : libellé normalisé vers catégorie d'asset.
CHAMPS_FICHIER: Dict[str, str] = {
    "veuilleztelechargervotrelogo": "logo",
    "sivousavezunlogo": "logo",
    "veuilleztelechargervosphotosproduit": "packshots",
    "veuilleztelechargervosphotoslifestyle": "lifestyle",
    "sivousavezdesvisuels": "visuels",
    "veuilleztelechargezvotrechartegraphique": "charte",
    "veuilleztelechargerlescreativesquevousaimez": "refs_aimees",
    "veuilleztelechargerlescreativesquevousnaimezpas": "refs_rejetees",
}

# Champs personnels : conservés dans la soumission brute, jamais recopiés dans le
# brief qui circule dans le pipeline et ses journaux.
CHAMPS_PERSONNELS = ("quelestvotrenometprenom", "quelestvotreemail", "quelestvotrenumero")

# Secteur Zite vers verticale du moteur, par libellé normalisé.
#
# Deux secteurs du menu n'ont pas de verticale propre dans le corpus : ils sont
# rattachés à la plus proche et MARQUÉS, pour que l'approximation se voie au lieu
# de passer pour une correspondance.
SECTEURS: Dict[str, Tuple[str, bool]] = {
    "saas": ("saas", False),
    "agence": ("agence", False),
    "ecommercant": ("ecommerce", False),
    "mediabuyer": ("agence", True),
    "formateurcoach": ("agence", True),
}

# Le menu accepte une saisie libre : sur 21 briefs réels, 7 secteurs sont écrits à
# la main (« Groupe thermal », « Application Mobile », « Agence Automobile »...).
# Un mot-clé net donne une verticale approchée. Rien de net donne la verticale de
# repli, marquée elle aussi. On ne rejette JAMAIS un client payant pour son
# secteur : ouvrir une commande ne coûte aucun crédit, et c'est un contrôle avant
# génération qui décidera, pas un filtre d'entrée.
MOTS_CLES_SECTEUR: List[Tuple[str, str]] = [
    ("ecommerc", "ecommerce"),
    ("boutique", "ecommerce"),
    ("application", "saas"),
    ("logiciel", "saas"),
    ("plateforme", "saas"),
    ("saas", "saas"),
    ("cosmet", "cosmetique"),
    ("complement", "complement"),
    ("alimentaire", "alimentaire"),
    ("boisson", "alimentaire"),
    ("agence", "agence"),
]
VERTICALE_REPLI = "agence"


def verticale_du_secteur(secteur: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Retourne la verticale et, si elle n'est pas exacte, la raison de l'écart."""
    if not secteur or not secteur.strip():
        return None, None
    cle = normaliser(secteur)
    if cle in SECTEURS:
        verticale, approchee = SECTEURS[cle]
        raison = f"« {secteur.strip()} » n'a pas de verticale dans le corpus" if approchee else None
        return verticale, raison
    for mot, verticale in MOTS_CLES_SECTEUR:
        if mot in cle:
            return verticale, f"secteur libre « {secteur.strip()} », rattaché par le mot « {mot} »"
    return VERTICALE_REPLI, (
        f"secteur libre « {secteur.strip()} » sans verticale dans le moteur, repli sur « {VERTICALE_REPLI} »"
    )


def _correspond(libelle: str, table: Dict[str, str]) -> Optional[str]:
    cle = normaliser(libelle)
    # Le préfixe le plus long gagne : « ...creativesquevousnaimezpas » ne doit
    # pas être capturé par « ...creativesquevousaimez ».
    for prefixe in sorted(table, key=len, reverse=True):
        if cle.startswith(prefixe):
            return table[prefixe]
    return None


def lire_soumission(soumission: dict) -> Tuple[Dict[str, str], Dict[str, List[dict]]]:
    """Sépare les réponses texte et les fichiers, en écartant les données personnelles."""
    textes: Dict[str, str] = {}
    fichiers: Dict[str, List[dict]] = {}
    for question in soumission.get("questions", []):
        libelle = question.get("name", "")
        valeur = question.get("value")
        if valeur in (None, "", []):
            continue
        if any(normaliser(libelle).startswith(p) for p in CHAMPS_PERSONNELS):
            continue
        if question.get("type") == "FileUpload":
            categorie = _correspond(libelle, CHAMPS_FICHIER)
            if categorie and isinstance(valeur, list):
                fichiers.setdefault(categorie, []).extend(
                    f for f in valeur if isinstance(f, dict) and f.get("url")
                )
            continue
        champ = _correspond(libelle, CHAMPS_TEXTE)
        if champ:
            textes[champ] = valeur if isinstance(valeur, str) else json.dumps(valeur, ensure_ascii=False)
    return textes, fichiers


def vers_brief(soumission: dict, pack: str) -> Tuple[dict, List[str]]:
    """Construit le brief du moteur. Retourne le brief et la liste de ce qui manque."""
    textes, fichiers = lire_soumission(soumission)
    manques: List[str] = []

    secteur = textes.get("secteur")
    verticale, ecart = verticale_du_secteur(secteur)
    if not verticale:
        manques.append("secteur")

    brief = {
        "_source": {
            "outil": "zite",
            "submission_id": soumission.get("submissionId"),
            "soumis_le": soumission.get("submissionTime"),
            "releve_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
        "marque": (textes.get("marque") or "").strip(),
        "url_site": (textes.get("url_site") or "").strip(),
        "pack": pack,
        "verticale": verticale,
        "secteur_declare": secteur,
        # Réponses brutes, dans les mots du client. Voir la docstring : pas de
        # reformulation ici.
        "reponses": textes,
        "assets": {categorie: [] for categorie in sorted(set(CHAMPS_FICHIER.values()))},
    }
    if ecart:
        brief["_verticale_approchee"] = ecart

    for champ in ("marque", "url_site"):
        if not brief[champ]:
            manques.append(champ)

    brief["_fichiers_zite"] = fichiers
    return brief, manques


# ---------------------------------------------------------------------------
# Filtre des soumissions inexploitables
# ---------------------------------------------------------------------------

def motif_de_rejet(brief: dict) -> Optional[str]:
    """Une soumission qui ne peut pas donner un pack. None si elle est exploitable.

    Motivé par un cas réel du 13/08 : marque « Dgjdjdb », sans site ni fichier.
    Produire là-dessus, c'est facturer du vide.
    """
    marque = brief.get("marque", "")
    if len(marque) < 2:
        return "marque absente"
    lettres = re.sub(r"[^a-zA-Zàâäéèêëîïôöùûüç]", "", marque.lower())
    if len(lettres) >= 5 and not re.search(r"[aeiouyàâäéèêëîïôöùûü]", lettres):
        return f"marque illisible « {marque} »"
    nb_fichiers = sum(len(v) for v in brief.get("_fichiers_zite", {}).values())
    if not brief.get("url_site") and nb_fichiers == 0:
        return "ni site ni fichier : aucune matière pour produire"
    return None


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def _cle() -> str:
    cle = os.environ.get("ZITE_API_KEY")
    if not cle:
        raise RuntimeError("ZITE_API_KEY absente. Lancer depuis un shell où le .env est chargé.")
    return cle


def _obtenir(url: str) -> dict:
    requete = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {_cle()}", "User-Agent": AGENT}
    )
    with urllib.request.urlopen(requete, timeout=60) as reponse:
        return json.load(reponse)


def formulaires() -> List[dict]:
    return _obtenir(f"{API}/forms")


def soumissions(form_id: str) -> List[dict]:
    """Toutes les soumissions terminées d'un formulaire, pagination comprise."""
    toutes: List[dict] = []
    decalage = 0
    while True:
        page = _obtenir(f"{API}/forms/{form_id}/submissions?limit={LIMITE_PAGE}&offset={decalage}")
        reponses = page.get("responses", [])
        toutes.extend(reponses)
        # Ne jamais se fier à totalResponses, qui compte la page : on s'arrête
        # quand une page revient incomplète.
        if len(reponses) < LIMITE_PAGE:
            return toutes
        decalage += LIMITE_PAGE


def telecharger(url: str, destination: Path) -> bool:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return True
    try:
        requete = urllib.request.Request(url, headers={"User-Agent": AGENT})
        with urllib.request.urlopen(requete, timeout=120) as reponse:
            destination.write_bytes(reponse.read())
        return True
    except (urllib.error.URLError, OSError):
        return False


# ---------------------------------------------------------------------------
# Relevé
# ---------------------------------------------------------------------------

def _lire_traitees() -> Dict[str, dict]:
    if FICHIER_TRAITEES.exists():
        return json.loads(FICHIER_TRAITEES.read_text(encoding="utf-8"))
    return {}


def _ecrire_traitees(traitees: Dict[str, dict]) -> None:
    DOSSIER_ZITE.mkdir(parents=True, exist_ok=True)
    FICHIER_TRAITEES.write_text(json.dumps(traitees, ensure_ascii=False, indent=2), encoding="utf-8")


def _nom_fichier(fichier: dict, index: int) -> str:
    brut = fichier.get("filename") or f"fichier-{index}"
    propre = re.sub(r"[^A-Za-z0-9._-]+", "-", unicodedata.normalize("NFKD", brut)).strip("-")
    return f"{index:02d}-{propre}"[:120]


def ouvrir_commande(soumission: dict, brief: dict) -> Path:
    """Crée la commande conforme, range la soumission et les pièces jointes."""
    from ranger import completer_arborescence  # import tardif : outils/ est optionnel

    fichiers = brief.pop("_fichiers_zite", {})
    commande = Commande.creer(
        marque=brief["marque"], url_site=brief["url_site"], pack=brief["pack"], brief=brief
    )
    dossier = commande.dossier
    completer_arborescence(dossier)

    (dossier / "brief" / "soumission.json").write_text(
        json.dumps(soumission, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    echecs = []
    for categorie, liste in fichiers.items():
        for index, fichier in enumerate(liste, start=1):
            cible = dossier / "brief" / "pieces-jointes" / categorie / _nom_fichier(fichier, index)
            if telecharger(fichier["url"], cible):
                brief["assets"][categorie].append(str(cible.relative_to(dossier)))
            else:
                echecs.append(f"{categorie}/{fichier.get('filename')}")

    commande.donnees["brief"] = brief
    commande.sauver()
    (dossier / "brief" / "brief.json").write_text(
        json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    commande.tracer(
        "brief_zite_recu",
        submission_id=soumission.get("submissionId"),
        pieces_jointes=sum(len(v) for v in brief["assets"].values()),
        echecs_telechargement=echecs,
    )
    return dossier


# Deux soumissions de la même marque sur le même pack à moins de ce délai sont
# le MÊME brief : un client qui revient le lendemain complète, il ne recommande
# pas. Podmax l'a fait le 24 puis le 25 août, la première portant son logo et la
# seconde le brief complet. Au delà, c'est une nouvelle commande, et un humain
# tranche. Un pack se livre en jours : trente est large et sans ambiguïté.
FENETRE_COMPLEMENT_JOURS = 30


def _complementaire(soumission: dict, pack: str, dossier: Path) -> bool:
    """Cette soumission complète-t-elle la commande déjà ouverte ?"""
    fichier = dossier / "commande.json"
    if not fichier.exists():
        return False
    try:
        donnees = json.loads(fichier.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    if donnees.get("pack") != pack:
        return False
    # Une commande déjà passée en production ne se laisse pas réécrire par une
    # soumission tardive : les créas sont planifiées, les crédits peut-être
    # dépensés. Ce cas-là demande un humain.
    if donnees.get("etat") not in (None, "recue", "intake"):
        return False

    precedente = (dossier / "brief" / "soumission.json")
    if not precedente.exists():
        return False
    try:
        avant = json.loads(precedente.read_text(encoding="utf-8")).get("submissionTime") or ""
        apres = soumission.get("submissionTime") or ""
        ecart = datetime.fromisoformat(apres.replace("Z", "+00:00")) - \
            datetime.fromisoformat(avant.replace("Z", "+00:00"))
    except (json.JSONDecodeError, ValueError):
        return False
    return 0 <= ecart.days <= FENETRE_COMPLEMENT_JOURS


def completer_commande(soumission: dict, brief: dict, dossier: Path) -> dict:
    """Fusionne une soumission tardive dans la commande déjà ouverte.

    Le texte du brief le plus récent gagne, parce que c'est la dernière chose
    que le client a dite. Les **pièces jointes s'additionnent** : la première
    soumission de Podmax portait son logo et la seconde n'a rien joint, garder
    seulement la dernière ferait perdre le seul asset de marque du dossier.

    Aucune soumission n'est écrasée. Elles vivent toutes dans
    `brief/soumissions/`, et `soumission.json` pointe sur la plus récente :
    la convention exige qu'une soumission brute ne soit jamais modifiée, elle
    n'interdit pas qu'il y en ait plusieurs.
    """
    from etat import Commande

    commande = Commande.charger(dossier.name)
    ancien = commande.donnees.get("brief") or {}
    fichiers = brief.pop("_fichiers_zite", {})

    # Les anciennes pièces jointes d'abord : ce sont les chemins déjà sur disque.
    assets = {cle: list(valeurs) for cle, valeurs in (ancien.get("assets") or {}).items()}
    for cle, valeurs in (brief.get("assets") or {}).items():
        assets.setdefault(cle, [])

    archives = dossier / "brief" / "soumissions"
    archives.mkdir(parents=True, exist_ok=True)
    for source in (dossier / "brief" / "soumission.json",):
        if source.exists():
            precedent = json.loads(source.read_text(encoding="utf-8"))
            nom = f"{(precedent.get('submissionTime') or '')[:19].replace(':', '')}-{precedent.get('submissionId')}.json"
            (archives / nom).write_text(json.dumps(precedent, ensure_ascii=False, indent=2),
                                        encoding="utf-8")

    (dossier / "brief" / "soumission.json").write_text(
        json.dumps(soumission, ensure_ascii=False, indent=2), encoding="utf-8")

    echecs, ajoutes = [], 0
    for categorie, liste in fichiers.items():
        for index, fichier in enumerate(liste, start=1):
            cible = (dossier / "brief" / "pieces-jointes" / categorie
                     / _nom_fichier(fichier, index))
            if telecharger(fichier["url"], cible):
                chemin = str(cible.relative_to(dossier))
                if chemin not in assets.setdefault(categorie, []):
                    assets[categorie].append(chemin)
                    ajoutes += 1
            else:
                echecs.append(f"{categorie}/{fichier.get('filename')}")

    brief["assets"] = assets
    commande.donnees["brief"] = brief
    commande.sauver()
    (dossier / "brief" / "brief.json").write_text(
        json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
    commande.tracer("brief_zite_complete",
                    submission_id=soumission.get("submissionId"),
                    pieces_jointes_ajoutees=ajoutes,
                    pieces_jointes_totales=sum(len(v) for v in assets.values()),
                    echecs_telechargement=echecs)
    return {"ajoutes": ajoutes, "total": sum(len(v) for v in assets.values())}


def relever(appliquer: bool = False) -> List[dict]:
    traitees = _lire_traitees()
    rapport: List[dict] = []

    for form_id, pack in FORMULAIRES_PACK.items():
        for soumission in sorted(soumissions(form_id), key=lambda s: s.get("submissionTime", "")):
            identifiant = soumission.get("submissionId")
            if identifiant in traitees:
                continue

            brief, manques = vers_brief(soumission, pack)
            ligne = {
                "submission_id": identifiant,
                "soumis_le": (soumission.get("submissionTime") or "")[:10],
                "pack": pack,
                "marque": brief["marque"],
                "fichiers": sum(len(v) for v in brief["_fichiers_zite"].values()),
                "manques": manques,
                "verticale": brief.get("verticale"),
                "ecart_verticale": brief.get("_verticale_approchee"),
            }

            rejet = motif_de_rejet(brief)
            dossier_existant = RACINE_DEFAUT / ardoise(brief["marque"]) if brief["marque"] else None

            if rejet:
                ligne["action"] = f"rejet : {rejet}"
            elif dossier_existant and dossier_existant.exists():
                if _complementaire(soumission, pack, dossier_existant):
                    ligne["action"] = "complement du brief"
                else:
                    ligne["action"] = "en attente : un dossier porte deja ce nom"
            else:
                ligne["action"] = "ouverture"

            if appliquer:
                if ligne["action"] == "ouverture":
                    ligne["dossier"] = str(ouvrir_commande(soumission, brief))
                elif ligne["action"] == "complement du brief":
                    bilan = completer_commande(soumission, brief, dossier_existant)
                    ligne["dossier"] = str(dossier_existant)
                    ligne["pieces_jointes_ajoutees"] = bilan["ajoutes"]
                elif ligne["action"].startswith("en attente"):
                    attente = DOSSIER_ATTENTE / f"{ardoise(brief['marque'])}-{identifiant}"
                    attente.mkdir(parents=True, exist_ok=True)
                    (attente / "soumission.json").write_text(
                        json.dumps(soumission, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    ligne["dossier"] = str(attente)
                traitees[identifiant] = {
                    "action": ligne["action"],
                    "marque": brief["marque"],
                    "pack": pack,
                    "le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                }
                _ecrire_traitees(traitees)

            rapport.append(ligne)
    return rapport


# ---------------------------------------------------------------------------
# Ligne de commande
# ---------------------------------------------------------------------------

def main() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sous = analyseur.add_subparsers(dest="commande", required=True)
    sous.add_parser("formulaires", help="lister les formulaires du compte")
    p_relever = sous.add_parser("relever", help="tirer les nouvelles soumissions")
    p_relever.add_argument("--appliquer", action="store_true",
                           help="ouvrir reellement les commandes ; sans ce drapeau, simulation")
    args = analyseur.parse_args()

    if args.commande == "formulaires":
        for f in formulaires():
            pack = FORMULAIRES_PACK.get(f["formId"], "")
            print(f"  {f['formId']:<14} {pack:<8} {f['name']}")
        return 0

    rapport = relever(appliquer=args.appliquer)
    entete = "APPLIQUE" if args.appliquer else "SIMULATION, rien n'est ecrit"
    print(f"{entete} : {len(rapport)} soumission(s) nouvelle(s)\n")
    for ligne in rapport:
        drapeaux = []
        if ligne["ecart_verticale"]:
            drapeaux.append(ligne["ecart_verticale"])
        if ligne["manques"]:
            drapeaux.append("manque " + ", ".join(ligne["manques"]))
        suffixe = f"  [{' ; '.join(drapeaux)}]" if drapeaux else ""
        print(f"  {ligne['soumis_le']}  {ligne['pack']:<7} {ligne['marque'][:20]:<20} "
              f"{str(ligne['verticale']):<10} {ligne['fichiers']:>2} fich.  {ligne['action']}")
        if suffixe:
            print(f"{'':42}{suffixe.strip()}")
    if not args.appliquer and rapport:
        print("\nRelancer avec --appliquer pour ouvrir les commandes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
