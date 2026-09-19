#!/usr/bin/env python3
"""audit.py : cinq contrôles mécaniques sur ce que le modèle a rendu.

Règle de conception : **aucun contrôle ne demande de jugement, et aucun ne porte
une règle de création.** Chacun se calcule, se prouve, cite sa pièce, et renvoie
soit à une règle écrite dans le skill de Kreative, soit à un fait vérifiable du
fichier produit. Juger si une créa est bonne n'appartient pas à ce fichier.

Trois contrôles ont été retirés le 18/09 : la répétition de gabarit, le
contraste de palette et le débordement de texte. Tous les trois mesuraient la
chaîne composée en HTML, avec notre répertoire d'archétypes et notre
compositeur. Le texte est désormais peint par le modèle et la création vient du
skill de Kreative : ces trois contrôles jugeaient un objet qui n'existe plus.

Les cinq qui restent :

  C1 copy peinte      La copy écrite par le skill doit réellement se lire dans
                      le master. L'OCR compare ce qui est lu à ce qui était
                      demandé.
  C2 doublon visuel   Deux créas visuellement identiques comptent pour une.
                      Le skill l'écrit dans sa propre liste de contrôle :
                      « aucune paire clonable ».
  C3 chiffre sourcé   Tout nombre du copy doit venir du brief. Règle d'or 5 du
                      skill : vérifier chaque chiffre et chaque attribution.
  C4 marqueur         Une créa qui porte [A COMPLETER] ne part pas.
  C5 format du master Le skill impose le carré 1:1 par défaut. Le fichier
                      produit doit l'être.

**Le gate ne bloque pas par défaut.** Le point ouvert 9.3 du cahier des charges
de Kreative demande encore si le pipeline doit rejeter et relancer les visuels
ratés, ou si le tri se fait à l'oeil à la réception. Tant qu'Evan n'a pas
tranché, `audit.py` rapporte et rend 0. `--bloquant` rend 1 sur échec, pour le
jour où la réponse sera oui.

Usage :
    python3 audit.py --marque "Tahiti Premium Water"
    python3 audit.py --marque "Tahiti Premium Water" --bloquant
    python3 audit.py --marque "Tahiti Premium Water" --json

Cible Python 3.9+. Dépendances : Pillow. Tesseract pour C1, optionnel.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))

from etat import Commande, Crea  # noqa: E402

SEUIL_SIMILARITE = 0.92    # au delà, deux créas sont le même visuel

# Le format que le skill de Kreative impose : « Le 1:1 (carré) est le format par
# défaut, toujours, tu ne changes de ratio que si le brief l'exige
# explicitement. » On tolère un écart d'un pour cent, une image 2048x2047 reste
# un carré.
TOLERANCE_RATIO = 0.01


@dataclass
class Constat:
    controle: str
    crea: str
    verdict: str        # "ok" | "alerte" | "echec"
    message: str
    preuve: str = ""

    @property
    def bloquant(self) -> bool:
        return self.verdict == "echec"


# ---------------------------------------------------------------------------
# C1 : la copy est-elle réellement peinte dans le master
# ---------------------------------------------------------------------------

def _tesseract_disponible() -> bool:
    try:
        subprocess.run(["tesseract", "--version"], capture_output=True, timeout=8)
        return True
    except Exception:
        return False


def _normaliser(texte: str) -> List[str]:
    """Les mots d'au moins quatre lettres, sans accent ni casse.

    Quatre lettres, parce que l'OCR produit toujours des parasites d'une ou deux
    lettres sur une photo. Sans accent, parce que tesseract confond régulièrement
    é et e sur une typographie grasse, et qu'un rejet sur cette base serait faux.
    """
    plie = unicodedata.normalize("NFD", texte or "")
    plie = "".join(c for c in plie if unicodedata.category(c) != "Mn").lower()
    return re.findall(r"[a-z]{4,}", plie)


# Seuils PROVISOIRES. Ils ne sortent d'aucune mesure calibrée : ils sont posés
# larges exprès, pour attraper la faute grossière sans condamner une créa
# correcte que l'OCR aurait mal lue. Un faux négatif constaté se traite par une
# dérogation nominative, jamais en baissant le seuil.
RAPPEL_MINIMUM = 0.5      # moitié de la copy absente = le modèle ne l'a pas rendue
INTRUS_ALERTE = 3         # au delà, du texte non demandé apparaît


def c1_copy_peinte(commande: Commande, crea: Crea) -> Optional[Constat]:
    """La copy doit être PRÉSENTE et JUSTE dans l'image.

    Deux défaillances distinctes, qui n'appellent pas la même réaction.

    **Le rappel** : la part de la copy attendue qu'on retrouve dans l'image. Un
    rappel bas veut dire que le modèle n'a pas rendu l'accroche, ou l'a rendue
    illisible. C'est bloquant, la créa est à régénérer.

    **Les intrus** : des mots lus dans l'image qui ne sont dans aucun champ de
    copy. C'est le faux texte que le skill désigne comme le tell IA numéro un.
    Mais ce n'est qu'une ALERTE, jamais un échec, parce qu'un asset réel joint
    en référence (une capture d'interface, un packaging) porte légitimement ses
    propres mots. Trancher demanderait de savoir ce que contient l'asset, ce
    qu'on ne sait pas faire ici. On montre les mots, un humain regarde.
    """
    if not crea.master:
        return None
    chemin = commande.dossier / crea.master
    if not chemin.exists() or not _tesseract_disponible():
        return None

    # Deux modes de segmentation, et on garde l'union. Le mode 11, texte
    # épars, ne lisait RIEN sur les quatre masters Podmax du 19/09, dont un
    # chiffre de 900 px de haut, alors que le mode 3, page entière, lisait
    # tout. Un seul mode produisait donc quatre faux échecs sur quatre créas
    # correctes, et un gate qui se trompe à ce point apprend à être ignoré.
    # Le chemin est RESOLU avant d'être passé à tesseract. Sur macOS, /tmp est
    # un lien vers /private/tmp, et la bibliothèque d'image de tesseract ne le
    # suit pas : elle répond « image file not found » sur un fichier que Python
    # vient de lire. Quatre masters Podmax ont ainsi été déclarés sans texte le
    # 19/09, alors que l'OCR les lisait parfaitement par leur chemin réel.
    reel = str(chemin.resolve())
    lus: set = set()
    for segmentation in ("3", "11"):
        try:
            brut = subprocess.run(
                ["tesseract", reel, "-", "-l", "fra+eng", "--psm", segmentation],
                capture_output=True, timeout=90)
            lus |= set(_normaliser(brut.stdout.decode("utf-8", "replace")))
        except Exception:
            continue
    attendus = set()
    for champ in (crea.copy.accroche, crea.copy.sous_accroche,
                  crea.copy.cta, crea.copy.badge):
        attendus.update(_normaliser(champ))

    if not attendus:
        return Constat("C1 copy peinte", crea.identifiant, "ok",
                       "aucune copy attendue, rien à vérifier")

    trouves = attendus & lus
    rappel = len(trouves) / len(attendus)
    intrus = sorted(lus - attendus)

    if not lus:
        return Constat(
            "C1 copy peinte", crea.identifiant, "echec",
            "aucun texte lu dans le master alors que la copy devait y être peinte. "
            "Le modèle a ignoré le texte : la créa est à régénérer.",
            preuve=crea.copy.accroche[:80])

    if rappel < RAPPEL_MINIMUM:
        manquants = sorted(attendus - trouves)
        return Constat(
            "C1 copy peinte", crea.identifiant, "echec",
            f"seulement {len(trouves)} mot(s) de la copy sur {len(attendus)} "
            f"retrouvés dans l'image ({rappel:.0%}). Le modèle n'a pas rendu le "
            f"texte demandé : la créa est à régénérer.",
            preuve="absents : " + " ".join(manquants[:8]))

    if len(intrus) > INTRUS_ALERTE:
        return Constat(
            "C1 copy peinte", crea.identifiant, "alerte",
            f"copy retrouvée à {rappel:.0%}, mais {len(intrus)} mot(s) lus dans "
            f"l'image ne viennent d'aucun champ de copy. Soit ils appartiennent à "
            f"un asset réel joint, soit le modèle a inventé du texte : à regarder.",
            preuve=" ".join(intrus[:8]))

    return Constat("C1 copy peinte", crea.identifiant, "ok",
                   f"copy retrouvée à {rappel:.0%}, aucun texte étranger notable")


# ---------------------------------------------------------------------------
# C2 : doublon visuel
# ---------------------------------------------------------------------------

def _empreinte(chemin: Path) -> Optional[int]:
    """Empreinte perceptuelle 8x8, robuste au recadrage et au changement de teinte."""
    try:
        from PIL import Image
        with Image.open(chemin) as im:
            gris = im.convert("L").resize((9, 8), Image.LANCZOS)
        pixels = list(gris.getdata())
        bits = 0
        for ligne in range(8):
            for col in range(8):
                gauche = pixels[ligne * 9 + col]
                droite = pixels[ligne * 9 + col + 1]
                bits = (bits << 1) | (1 if gauche > droite else 0)
        return bits
    except Exception:
        return None


def c2_doublons(commande: Commande, creas: List[Crea]) -> List[Constat]:
    """Deux masters visuellement identiques comptent pour une créa.

    Le skill de Kreative le pose dans sa propre liste de contrôle : les créas
    d'un pack sont franchement différentes, aucune paire clonable. Ici on ne
    juge pas la différence de concept, seulement la ressemblance des pixels.
    """
    empreintes: Dict[str, int] = {}
    for crea in creas:
        if not crea.master:
            continue
        valeur = _empreinte(commande.dossier / crea.master)
        if valeur is not None:
            empreintes[crea.identifiant] = valeur

    constats: List[Constat] = []
    identifiants = sorted(empreintes)
    for i, a in enumerate(identifiants):
        for b in identifiants[i + 1:]:
            distance = bin(empreintes[a] ^ empreintes[b]).count("1")
            similarite = 1 - distance / 64
            if similarite < SEUIL_SIMILARITE:
                continue
            constats.append(Constat(
                "C2 doublon visuel", a, "echec",
                f"{a} et {b} sont visuellement identiques à {similarite:.0%}. "
                f"Dans un pack, cela compte pour une seule créa.",
                preuve=f"distance de Hamming {distance}/64"))
    return constats or [Constat("C2 doublon visuel", "pack", "ok",
                                f"{len(empreintes)} créas comparées, aucune paire identique")]


# ---------------------------------------------------------------------------
# C3 : chiffre non sourcé
# ---------------------------------------------------------------------------

def c3_chiffres(commande: Commande, crea: Crea) -> Optional[Constat]:
    """Tout nombre du copy doit se retrouver dans le brief.

    Règle d'or 5 du skill de Kreative : vérifier chaque chiffre et chaque
    attribution, pas de promesse chiffrée non vérifiable. Les nombres écrits en
    toutes lettres et les nombres d'un seul chiffre ne sont pas contrôlés : ils
    sont presque toujours grammaticaux, pas factuels.
    """
    brief = commande.donnees.get("brief") or {}
    source = json.dumps(brief, ensure_ascii=False)
    autorises = set(re.findall(r"\d[\d\s.,]*", source))
    autorises = {a.replace(" ", "").replace(",", ".").rstrip(".") for a in autorises}

    copy = " ".join([crea.copy.accroche, crea.copy.sous_accroche, crea.copy.badge])
    trouves = re.findall(r"\d[\d\s.,]*", copy)
    orphelins = []
    for brut in trouves:
        valeur = brut.replace(" ", "").replace(",", ".").rstrip(".")
        if len(valeur) < 2:
            continue
        if not any(valeur in a or a in valeur for a in autorises):
            orphelins.append(brut.strip())
    if not orphelins:
        return Constat("C3 chiffre sourcé", crea.identifiant, "ok",
                       "tous les chiffres du copy viennent du brief")
    return Constat("C3 chiffre sourcé", crea.identifiant, "echec",
                   f"chiffre absent du brief : {', '.join(orphelins)}. "
                   f"Un chiffre inventé est une faute, pas une approximation.",
                   preuve=copy[:140])


# ---------------------------------------------------------------------------
# C4 : marqueur à compléter
# ---------------------------------------------------------------------------

def c4_marqueurs(crea: Crea) -> Constat:
    champs = crea.copy.accroche + crea.copy.sous_accroche + crea.copy.badge
    manquants = re.findall(r"\[A COMPLETER: ([\w.]+)\]", champs)
    if not manquants:
        return Constat("C4 marqueur", crea.identifiant, "ok", "aucun champ à compléter")
    return Constat("C4 marqueur", crea.identifiant, "echec",
                   f"brief incomplet : {', '.join(sorted(set(manquants)))}",
                   preuve=champs[:140])


# ---------------------------------------------------------------------------
# C5 : le master est bien au format demandé
# ---------------------------------------------------------------------------

def c5_format(commande: Commande, crea: Crea) -> Optional[Constat]:
    """Le master respecte le ratio que le skill impose.

    Le contrôle porte sur le fichier, pas sur l'intention : un modèle rend
    parfois un 1:1 demandé en 4:5 réel, et personne ne s'en aperçoit avant que
    la créa soit coupée dans le feed.
    """
    if not crea.master:
        return None
    chemin = commande.dossier / crea.master
    if not chemin.exists():
        return Constat("C5 format du master", crea.identifiant, "echec",
                       f"master déclaré mais absent du disque : {crea.master}")
    try:
        from PIL import Image
        with Image.open(chemin) as im:
            largeur, hauteur = im.size
    except Exception as erreur:
        return Constat("C5 format du master", crea.identifiant, "alerte",
                       f"image illisible : {erreur}")

    ratio = largeur / hauteur if hauteur else 0
    if abs(ratio - 1.0) <= TOLERANCE_RATIO:
        return Constat("C5 format du master", crea.identifiant, "ok",
                       f"carré, {largeur}x{hauteur}")
    return Constat("C5 format du master", crea.identifiant, "echec",
                   f"le master n'est pas carré : {largeur}x{hauteur}, ratio "
                   f"{ratio:.2f}. Le skill impose le 1:1 par défaut.",
                   preuve=str(chemin.name))


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def _derogations(commande: Commande) -> dict:
    """Les échecs couverts par une vérification humaine consignée.

    Un contrôle mécanique peut se tromper : tesseract ne lit pas un texte
    incliné (mesuré le 18/09 sur c09, texte exact à l'oeil en pleine
    résolution, rappel OCR à 45%). Baisser le seuil couvrirait aussi les vrais
    défauts ; la sortie honnête est la dérogation NOMINATIVE : un humain a
    regardé le master, l'écrit dans `audit-derogations.json`, et l'audit
    convertit ce seul échec en alerte en citant le motif. Le fichier vit dans
    le dossier de la commande, versionné avec elle.

    Format : {"c09": {"C1 copy peinte": {"date": "...", "verifie_par": "...",
    "motif": "..."}}}. Une dérogation sans motif est ignorée.
    """
    chemin = commande.dossier / "audit-derogations.json"
    if not chemin.exists():
        return {}
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def auditer(commande: Commande) -> List[Constat]:
    creas = [c for c in commande.creas() if c.etat in ("master_ok", "composee", "retenue")]
    constats: List[Constat] = []
    for crea in creas:
        for constat in (c1_copy_peinte(commande, crea), c3_chiffres(commande, crea),
                        c4_marqueurs(crea), c5_format(commande, crea)):
            if constat:
                constats.append(constat)
    constats += c2_doublons(commande, creas)

    derogations = _derogations(commande)
    for constat in constats:
        derog = (derogations.get(constat.crea) or {}).get(constat.controle) or {}
        if constat.verdict == "echec" and derog.get("motif"):
            constat.verdict = "alerte"
            constat.message = (
                f"échec couvert par dérogation consignée du {derog.get('date', '?')} "
                f"({derog.get('verifie_par', 'vérificateur non nommé')}) : "
                f"{derog['motif']} Message du contrôle : {constat.message}")
    return constats


def rapport(constats: List[Constat], bloquant: bool = False) -> str:
    echecs = [c for c in constats if c.verdict == "echec"]
    alertes = [c for c in constats if c.verdict == "alerte"]
    lignes = []
    for constat in echecs + alertes:
        marque = "ECHEC " if constat.bloquant else "ALERTE"
        lignes.append(f"  [{marque}] {constat.controle} / {constat.crea}")
        lignes.append(f"           {constat.message}")
        if constat.preuve:
            lignes.append(f"           preuve : {constat.preuve}")
    entete = (f"{len(constats)} contrôles, {len(echecs)} échec(s), "
              f"{len(alertes)} alerte(s).")
    if not echecs:
        verdict = "Aucun échec."
    elif bloquant:
        verdict = "GATE BLOQUE : la commande ne part pas."
    else:
        verdict = ("Le gate ne bloque pas : point ouvert 9.3 du cahier des charges, "
                   "en attente de la réponse de Kreative. Relancer avec --bloquant "
                   "pour qu'un échec arrête la commande.")
    return "\n".join([entete, ""] + lignes + ["", verdict])


def main() -> int:
    parseur = argparse.ArgumentParser(description="Contrôles mécaniques d'une commande")
    parseur.add_argument("--marque", required=True)
    parseur.add_argument("--json", action="store_true")
    parseur.add_argument("--bloquant", action="store_true",
                         help="rendre 1 en cas d'échec, pour enchaîner dans un script")
    arguments = parseur.parse_args()

    commande = Commande.charger(arguments.marque)
    constats = auditer(commande)
    if arguments.json:
        print(json.dumps([asdict(c) for c in constats], ensure_ascii=False, indent=1))
    else:
        print(rapport(constats, bloquant=arguments.bloquant))
    commande.tracer("audit", echecs=sum(1 for c in constats if c.bloquant),
                    controles=len(constats), bloquant=arguments.bloquant)
    return 1 if arguments.bloquant and any(c.bloquant for c in constats) else 0


if __name__ == "__main__":
    raise SystemExit(main())
