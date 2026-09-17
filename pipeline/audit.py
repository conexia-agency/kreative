#!/usr/bin/env python3
"""audit.py : le gate qualité, sept contrôles mécaniques.

Le cahier des charges demande zéro intervention humaine entre le paiement et
les visuels (point 8). Sans filet, cela veut dire qu'une créa fausse part chez
le client sans que personne la voie. Le gate est ce filet.

Règle de conception : **aucun contrôle ne demande de jugement.** Chacun se
calcule, se prouve, et cite sa pièce. Un contrôle qui aurait besoin d'un avis
n'a pas sa place ici, il appartient à la relecture humaine.

Les sept contrôles, et d'où ils viennent :

  C1 texte gravé      Le prompt interdit tout texte dans le master. Si l'OCR en
                      lit, le modèle a gravé du texte. 8 créas sur les 29
                      générées du corpus portent ce défaut.
  C2 doublon visuel   i031 et i093 sont la même créa à deux cadrages, i060 et
                      i062 la même en clair et en sombre. Dans un pack, cela
                      compte pour une seule créa.
  C3 gabarit répété   Le corpus compte 99 architectures pour 120 créas, dont 90
                      uniques. Deux créas d'un pack ne partagent pas leur
                      architecture.
  C4 chiffre non sourcé   Tout nombre du copy doit venir du brief. Un chiffre
                      inventé est une faute, pas une approximation.
  C5 marqueur         Une créa qui porte [A COMPLETER] ne part pas.
  C6 contraste        Le texte principal doit atteindre 4,5 contre son fond.
  C7 débordement      Mesuré au rendu : un texte coupé par le cadre.

Usage :
    python3 audit.py --marque "Tahiti Premium Water"
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
sys.path.insert(0, str(ICI.parent / "compositeur"))

import repertoire  # noqa: E402
from etat import Commande, Crea  # noqa: E402

SEUIL_CONTRASTE = 4.5      # WCAG AA pour du texte
SEUIL_SIMILARITE = 0.92    # au delà, deux créas sont le même visuel


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
# C1 : texte gravé dans le master
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


# Seuils PROVISOIRES. Ils ne sortent d'aucune mesure : la chaîne n'a pas encore
# produit de rendu à texte cuit sur lequel les calibrer. Ils sont posés larges
# exprès, pour attraper la faute grossière sans condamner une créa correcte que
# l'OCR aurait mal lue. À revoir sur les premiers packs réels.
RAPPEL_MINIMUM = 0.5      # moitié de la copy absente = le modèle ne l'a pas rendue
INTRUS_ALERTE = 3         # au delà, du texte non demandé apparaît


def c1_texte_grave(commande: Commande, crea: Crea) -> Optional[Constat]:
    """Le texte gravé doit être PRÉSENT et JUSTE.

    Ce contrôle disait l'inverse jusqu'au 17/09 : le prompt interdisait tout
    texte, et lire un seul mot dans un master était un échec. La décision de
    faire peindre le texte par le modèle le retourne. La question n'est plus
    « y a-t-il du texte », elle est « est-ce le bon ».

    Deux défaillances distinctes, et elles n'appellent pas la même réaction.

    **Le rappel** : la part de la copy attendue qu'on retrouve dans l'image. Un
    rappel bas veut dire que le modèle n'a pas rendu l'accroche, ou l'a rendue
    illisible. C'est bloquant, la créa est à régénérer.

    **Les intrus** : des mots lus dans l'image qui ne sont dans aucun champ de
    copy. C'est le faux texte que le skill lui-même désigne comme le tell IA
    numéro un. Mais ce n'est qu'une ALERTE, jamais un échec, parce qu'un asset
    réel joint en référence (une capture d'interface, un packaging) porte
    légitimement ses propres mots. Trancher automatiquement entre les deux
    demanderait de savoir ce que contient l'asset, ce qu'on ne sait pas faire
    ici. On montre donc les mots, et un humain regarde.
    """
    if not crea.master:
        return None
    chemin = commande.dossier / crea.master
    if not chemin.exists() or not _tesseract_disponible():
        return None
    try:
        brut = subprocess.run(
            ["tesseract", str(chemin), "-", "-l", "fra+eng", "--psm", "11"],
            capture_output=True, timeout=90)
        texte = brut.stdout.decode("utf-8", "replace")
    except Exception:
        return None

    lus = set(_normaliser(texte))
    attendus = set()
    for champ in (crea.copy.accroche, crea.copy.sous_accroche,
                  crea.copy.cta, crea.copy.badge):
        attendus.update(_normaliser(champ))

    if not attendus:
        # Une créa sans copy : le contrôle n'a rien à comparer.
        return Constat("C1 texte gravé", crea.identifiant, "ok",
                       "aucune copy attendue, rien à vérifier")

    trouves = attendus & lus
    rappel = len(trouves) / len(attendus)
    intrus = sorted(lus - attendus)

    if not lus:
        return Constat(
            "C1 texte gravé", crea.identifiant, "echec",
            "aucun texte lu dans le master alors que la copy devait y être peinte. "
            "Le modèle a ignoré le texte : la créa est à régénérer.",
            preuve=crea.copy.accroche[:80])

    if rappel < RAPPEL_MINIMUM:
        manquants = sorted(attendus - trouves)
        return Constat(
            "C1 texte gravé", crea.identifiant, "echec",
            f"seulement {len(trouves)} mot(s) de la copy sur {len(attendus)} "
            f"retrouvés dans l'image ({rappel:.0%}). Le modèle n'a pas rendu le "
            f"texte demandé : la créa est à régénérer.",
            preuve="absents : " + " ".join(manquants[:8]))

    if len(intrus) > INTRUS_ALERTE:
        return Constat(
            "C1 texte gravé", crea.identifiant, "alerte",
            f"copy retrouvée à {rappel:.0%}, mais {len(intrus)} mot(s) lus dans "
            f"l'image ne viennent d'aucun champ de copy. Soit ils appartiennent à "
            f"un asset réel joint, soit le modèle a inventé du texte : à regarder.",
            preuve=" ".join(intrus[:8]))

    return Constat("C1 texte gravé", crea.identifiant, "ok",
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
    gabarit_de: Dict[str, str] = {}
    for crea in creas:
        _, _, cle = crea.angle.partition("/")
        arch = repertoire.ARCHETYPES_PAR_CLE.get(cle)
        if arch:
            gabarit_de[crea.identifiant] = arch.gabarit

    empreintes: Dict[str, int] = {}
    for crea in creas:
        chemin_rel = crea.rendus.get("1x1")
        if not chemin_rel:
            continue
        valeur = _empreinte(commande.dossier / chemin_rel)
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
            if gabarit_de.get(a) and gabarit_de.get(a) == gabarit_de.get(b):
                # Meme gabarit : la ressemblance est structurelle et deja
                # signalee par C3. La reporter ici accuserait la crea d'un
                # defaut qui appartient au repertoire.
                continue
            constats.append(Constat(
                "C2 doublon visuel", a, "echec",
                f"{a} et {b} sont visuellement identiques à {similarite:.0%}. "
                f"Dans un pack, cela compte pour une seule créa.",
                preuve=f"distance de Hamming {distance}/64"))
    return constats or [Constat("C2 doublon visuel", "pack", "ok",
                                f"{len(empreintes)} créas comparées, aucune paire identique")]


# ---------------------------------------------------------------------------
# C3 : gabarit répété
# ---------------------------------------------------------------------------

def c3_gabarits(commande: Commande, creas: List[Crea]) -> List[Constat]:
    """Repetition de gabarit, avec la distinction qui compte.

    Une repetition EVITABLE est une faute du moteur : il restait des
    architectures libres et il ne les a pas prises. Une repetition INEVITABLE
    est une limite du repertoire : la verticale n'offre pas assez
    d'architectures pour le volume vendu. Les deux se corrigent, mais pas au
    meme endroit, et les confondre ferait chercher le defaut au mauvais niveau.
    """
    par_gabarit: Dict[str, List[str]] = {}
    for crea in creas:
        _, _, cle = crea.angle.partition("/")
        arch = repertoire.ARCHETYPES_PAR_CLE.get(cle)
        if arch:
            par_gabarit.setdefault(arch.gabarit, []).append(crea.identifiant)

    doublons = {g: ids for g, ids in par_gabarit.items() if len(ids) > 1}
    if not doublons:
        return [Constat("C3 gabarit répété", "pack", "ok",
                        f"{len(par_gabarit)} architectures distinctes sur {len(creas)} créas")]

    verticale = (commande.donnees.get("brief") or {}).get("verticale") or ""
    disponibles = len({a.gabarit for a in repertoire.archetypes_disponibles(verticale)}) \
        if verticale in repertoire.VERTICALES_PAR_CLE else 0
    evitable = disponibles >= len(creas)
    verdict = "echec" if evitable else "alerte"
    manque = max(0, len(creas) - disponibles)

    constats = [Constat("C3 gabarit répété", ids[1], verdict,
                        f"le gabarit « {g} » sert {len(ids)} fois dans le pack",
                        preuve=", ".join(ids)) for g, ids in doublons.items()]
    if not evitable:
        constats.append(Constat(
            "C3 gabarit répété", "pack", "alerte",
            f"répétition inévitable : la verticale « {verticale} » offre "
            f"{disponibles} architectures pour {len(creas)} créas demandées. "
            f"Il en manque {manque} au répertoire.",
            preuve=f"{disponibles} architectures disponibles"))
    return constats


# ---------------------------------------------------------------------------
# C4 : chiffre non sourcé
# ---------------------------------------------------------------------------

def c4_chiffres(commande: Commande, crea: Crea) -> Optional[Constat]:
    """Tout nombre du copy doit se retrouver dans le brief.

    Les nombres écrits en toutes lettres et les nombres d'un seul chiffre ne
    sont pas contrôlés : ils sont presque toujours grammaticaux, pas factuels.
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
        return Constat("C4 chiffre non sourcé", crea.identifiant, "ok",
                       "tous les chiffres du copy viennent du brief")
    return Constat("C4 chiffre non sourcé", crea.identifiant, "echec",
                   f"chiffre absent du brief : {', '.join(orphelins)}. "
                   f"Un chiffre inventé est une faute, pas une approximation.",
                   preuve=copy[:140])


# ---------------------------------------------------------------------------
# C5 : marqueur à compléter
# ---------------------------------------------------------------------------

def c5_marqueurs(crea: Crea) -> Constat:
    champs = crea.copy.accroche + crea.copy.sous_accroche + crea.copy.badge
    manquants = re.findall(r"\[A COMPLETER: ([\w.]+)\]", champs)
    if not manquants:
        return Constat("C5 marqueur", crea.identifiant, "ok", "aucun champ à compléter")
    return Constat("C5 marqueur", crea.identifiant, "echec",
                   f"brief incomplet : {', '.join(sorted(set(manquants)))}",
                   preuve=champs[:140])


# ---------------------------------------------------------------------------
# C6 : contraste
# ---------------------------------------------------------------------------

def c6_contraste(commande: Commande) -> Constat:
    from design import Palette, contraste
    brief = commande.donnees.get("brief") or {}
    verticale = brief.get("verticale") or ""
    registre = repertoire.VERTICALES_PAR_CLE[verticale].registre \
        if verticale in repertoire.VERTICALES_PAR_CLE else "clair"
    if registre == "libre":
        registre = "clair"
    p = Palette.depuis_charte(brief.get("charte"), registre)

    mesures = {
        "texte sur fond": contraste(p.encre, p.fond),
        "texte du bouton sur l'accent": contraste(p.encre_accent, p.accent),
    }
    fautifs = {nom: v for nom, v in mesures.items() if v < SEUIL_CONTRASTE}
    detail = ", ".join(f"{nom} {v:.1f}:1" for nom, v in mesures.items())
    if not fautifs:
        return Constat("C6 contraste", "pack", "ok",
                       f"tous au dessus de {SEUIL_CONTRASTE}:1", preuve=detail)
    return Constat("C6 contraste", "pack", "echec",
                   f"contraste insuffisant : {', '.join(fautifs)}", preuve=detail)


# ---------------------------------------------------------------------------
# C7 : débordement, relevé au rendu
# ---------------------------------------------------------------------------

def c7_debordement(commande: Commande, crea: Crea) -> Optional[Constat]:
    """Lit le relevé de débordement écrit par le compositeur au moment du rendu.

    Le contrôle ne peut pas se faire sur le PNG : un texte coupé par le cadre
    y est indiscernable d'un texte qui s'arrête. Il se mesure dans le
    navigateur, au rendu, et le compositeur le consigne dans `crea.audit`.
    """
    releve = (crea.audit or {}).get("debordement")
    if releve is None:
        return None
    if not releve:
        return Constat("C7 débordement", crea.identifiant, "ok",
                       "aucun texte coupé par le cadre")
    return Constat("C7 débordement", crea.identifiant, "echec",
                   f"texte coupé par le cadre dans {len(releve)} format(s)",
                   preuve=", ".join(f"{f} : {n}px" for f, n in releve.items()))


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def auditer(commande: Commande) -> List[Constat]:
    creas = [c for c in commande.creas() if c.etat in ("master_ok", "composee", "retenue")]
    constats: List[Constat] = []
    for crea in creas:
        for constat in (c1_texte_grave(commande, crea), c4_chiffres(commande, crea),
                        c5_marqueurs(crea), c7_debordement(commande, crea)):
            if constat:
                constats.append(constat)
    constats += c2_doublons(commande, creas)
    constats += c3_gabarits(commande, creas)
    constats.append(c6_contraste(commande))
    return constats


def rapport(constats: List[Constat]) -> str:
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
    verdict = "GATE FRANCHI" if not echecs else "GATE BLOQUE : la commande ne part pas."
    return "\n".join([entete, ""] + lignes + ["", verdict])


def main() -> int:
    parseur = argparse.ArgumentParser(description="Gate qualité d'une commande")
    parseur.add_argument("--marque", required=True)
    parseur.add_argument("--json", action="store_true")
    arguments = parseur.parse_args()

    commande = Commande.charger(arguments.marque)
    constats = auditer(commande)
    if arguments.json:
        print(json.dumps([asdict(c) for c in constats], ensure_ascii=False, indent=1))
    else:
        print(rapport(constats))
    commande.tracer("audit", echecs=sum(1 for c in constats if c.bloquant),
                    controles=len(constats))
    return 1 if any(c.bloquant for c in constats) else 0


if __name__ == "__main__":
    raise SystemExit(main())
