#!/usr/bin/env python3
"""formats.py : tire le 4:5 et le 9:16 du master carré, sans le régénérer.

Le cahier des charges de Kreative, article 4.2, demande trois formats. Son
skill, lui, impose le carré 1:1 pour le master et fait vérifier ce format par sa
propre liste de contrôle. Les deux tiennent ensemble à une condition : **le
master carré ne bouge pas d'un pixel**, et les deux autres formats l'entourent.

Pourquoi pas un recadrage. Le texte est peint dans l'image par le modèle.
Découper un carré pour en faire un 9:16 couperait l'accroche par le côté. Le
sens de l'opération est donc l'inverse : on AJOUTE du cadre en haut et en bas,
on n'en retire jamais.

Ce que ce module ne fait pas, et c'est délibéré : il n'invente pas d'image. La
bande ajoutée prolonge le bord du master quand ce bord est uniforme, ce qui
arrive sur un fond plein, un dégradé ou une matière régulière. Quand il ne
l'est pas, prolonger produirait des traînées verticales visibles : le module
REFUSE, et inscrit la créa dans `formats/a-etendre.json`. Une session reprend
alors ces créas-là avec le connecteur, qui sait étendre une image. Un format
raté vaut mieux qu'un format sale livré sans que personne le regarde.

    python3 pipeline/formats.py decliner <ardoise>
    python3 pipeline/formats.py decliner <ardoise> --creas c01 c02
    python3 pipeline/formats.py verifier <ardoise>

Cible Python 3.9+. Dépend de Pillow.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))

from etat import Commande, Crea  # noqa: E402

# Les trois formats de l'article 4.2, exprimés en hauteur pour une largeur de 1.
FORMATS: Dict[str, float] = {
    "1x1": 1.0,
    "4x5": 5 / 4,
    "9x16": 16 / 9,
}

# Le format du master, celui que le skill impose. Il n'est pas produit ici : il
# est recopié tel quel, pour que les trois fichiers vivent au même endroit.
FORMAT_MASTER = "1x1"

# Au-delà, le bord du master n'est pas assez uniforme pour être prolongé. C'est
# un écart type de luminance, sur 255, mesuré sur les dernières lignes de
# l'image. Le seuil est posé bas exprès : dans le doute, on refuse et on laisse
# le connecteur faire le travail.
ECART_TYPE_MAXIMAL = 6.0

# Nombre de lignes du bord lues pour décider, et pour fabriquer la bande.
LIGNES_DE_BORD = 8


def _empreinte(chemin: Path) -> str:
    """L'empreinte du master, inscrite à côté de chaque déclinaison.

    C'est ce qui prouve, sans faire confiance à personne, que les trois
    fichiers d'une créa viennent bien du même master.
    """
    return hashlib.sha256(chemin.read_bytes()).hexdigest()[:16]


def _bande(image, en_haut: bool):
    """Les lignes de bord, et leur écart type de luminance."""
    from PIL import ImageStat
    largeur, hauteur = image.size
    boite = (0, 0, largeur, LIGNES_DE_BORD) if en_haut else \
            (0, hauteur - LIGNES_DE_BORD, largeur, hauteur)
    morceau = image.crop(boite)
    stat = ImageStat.Stat(morceau.convert("L"))
    return morceau, stat.stddev[0]


def etendre(master: Path, ratio_cible: float) -> Tuple[object, dict]:
    """Rend (image étendue, mesure). L'image est None quand le bord refuse.

    La bande est fabriquée en étirant verticalement les dernières lignes du
    master. Sur un fond uniforme ou en dégradé horizontal, l'ajout est
    invisible. Sur une matière, il est régulier. Sur une photo, il serait laid :
    c'est le cas que la mesure écarte avant de produire quoi que ce soit.
    """
    from PIL import Image

    with Image.open(master) as source:
        image = source.convert("RGB")
        largeur, hauteur = image.size
        if hauteur == 0:
            return None, {"refus": "image de hauteur nulle"}

        cible_hauteur = int(round(largeur * ratio_cible))
        if cible_hauteur <= hauteur:
            # Le master est déjà au moins aussi haut : on ne rogne jamais.
            return None, {"refus": f"le master est déjà en {largeur}x{hauteur}, "
                                   f"un {cible_hauteur}px de haut demanderait de rogner"}

        haut, ecart_haut = _bande(image, en_haut=True)
        bas, ecart_bas = _bande(image, en_haut=False)
        mesure = {"ecart_type_haut": round(ecart_haut, 2),
                  "ecart_type_bas": round(ecart_bas, 2),
                  "seuil": ECART_TYPE_MAXIMAL}

        if max(ecart_haut, ecart_bas) > ECART_TYPE_MAXIMAL:
            mesure["refus"] = (
                f"bord non uniforme (écart type {max(ecart_haut, ecart_bas):.1f} "
                f"pour un seuil de {ECART_TYPE_MAXIMAL}) : prolonger ce bord "
                f"ferait des traînées. À étendre par le connecteur.")
            return None, mesure

        total_ajout = cible_hauteur - hauteur
        ajout_haut = total_ajout // 2
        ajout_bas = total_ajout - ajout_haut

        toile = Image.new("RGB", (largeur, cible_hauteur))
        if ajout_haut:
            toile.paste(haut.resize((largeur, ajout_haut), Image.LANCZOS), (0, 0))
        toile.paste(image, (0, ajout_haut))
        if ajout_bas:
            toile.paste(bas.resize((largeur, ajout_bas), Image.LANCZOS),
                        (0, ajout_haut + hauteur))

        mesure.update({"largeur": largeur, "hauteur": cible_hauteur,
                       "bande_haut": ajout_haut, "bande_bas": ajout_bas,
                       "methode": "prolongement du bord"})
        return toile, mesure


def decliner_crea(commande: Commande, crea: Crea) -> dict:
    """Produit les trois fichiers d'une créa. Rend le bilan de l'opération."""
    from PIL import Image

    if not crea.master:
        return {"crea": crea.identifiant, "etat": "sans master"}
    master = commande.dossier / crea.master
    if not master.exists():
        return {"crea": crea.identifiant, "etat": "master absent", "chemin": crea.master}

    dossier = commande.dossier / "dist" / crea.identifiant
    dossier.mkdir(parents=True, exist_ok=True)
    empreinte = _empreinte(master)

    rendus: Dict[str, str] = {}
    mesures: Dict[str, dict] = {}
    a_etendre: List[str] = []

    # Le 1:1 est le master lui-même, recopié sans être touché.
    cible = dossier / f"{crea.identifiant}-1x1.png"
    with Image.open(master) as source:
        source.convert("RGB").save(cible, "PNG")
    rendus["1x1"] = str(cible.relative_to(commande.dossier))
    mesures["1x1"] = {"methode": "copie du master", "empreinte_master": empreinte}

    for nom, ratio in FORMATS.items():
        if nom == FORMAT_MASTER:
            continue
        image, mesure = etendre(master, ratio)
        mesure["empreinte_master"] = empreinte
        mesures[nom] = mesure
        if image is None:
            a_etendre.append(nom)
            continue
        cible = dossier / f"{crea.identifiant}-{nom}.png"
        image.save(cible, "PNG")
        rendus[nom] = str(cible.relative_to(commande.dossier))

    (dossier / "formats.json").write_text(
        json.dumps({"crea": crea.identifiant, "empreinte_master": empreinte,
                    "mesures": mesures}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    crea.rendus = rendus
    crea.audit = dict(crea.audit or {})
    crea.audit["formats"] = {"produits": sorted(rendus), "a_etendre": a_etendre,
                             "empreinte_master": empreinte}
    if len(rendus) == len(FORMATS):
        crea.etat = "composee"
    commande.ecrire_crea(crea)
    commande.tracer("crea_declinee", crea=crea.identifiant,
                    produits=len(rendus), a_etendre=a_etendre)

    return {"crea": crea.identifiant, "etat": "ok", "produits": sorted(rendus),
            "a_etendre": a_etendre,
            "motifs": {n: mesures[n].get("refus") for n in a_etendre}}


def decliner(commande: Commande, filtre: Optional[List[str]] = None) -> dict:
    creas = [c for c in commande.creas() if c.master]
    if filtre:
        voulus = set(filtre)
        creas = [c for c in creas if c.identifiant in voulus]

    bilans = [decliner_crea(commande, c) for c in creas]
    reste = {b["crea"]: b.get("motifs", {}) for b in bilans if b.get("a_etendre")}

    dossier = commande.dossier / "formats"
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "a-etendre.json").write_text(
        json.dumps({
            "ardoise": commande.donnees["ardoise"],
            "creas": reste,
            "quoi_faire": (
                "Ces formats n'ont pas pu être tirés du master par prolongement "
                "de bord : le bord du master n'est pas uniforme. Les produire par "
                "le connecteur avec le modèle d'extension `flux_2_pro_outpaint`, "
                "qui ajoute des pixels côté par côté sans toucher à l'image "
                "d'origine : `expand_top` et `expand_bottom` seuls, `expand_left` "
                "et `expand_right` à zéro, aucune valeur négative puisqu'une "
                "valeur négative rogne. Le carré du master doit rester intact au "
                "centre, c'est la règle 4.2 du cahier des charges : les trois "
                "formats sont le même visuel décliné, pas trois visuels "
                "régénérés. Enregistrer dans dist/<crea>/ sous le nom "
                "<crea>-<format>.png, puis relancer `formats.py verifier`."),
            "pixels_a_ajouter": {
                "4x5": "hauteur du master fois 0,25, moitié en haut, moitié en bas",
                "9x16": "hauteur du master fois 0,778, moitié en haut, moitié en bas",
            },
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    complets = sum(1 for b in bilans if b.get("etat") == "ok" and not b.get("a_etendre"))
    return {"traitees": len(bilans), "completes": complets,
            "a_etendre": reste, "bilans": bilans}


def verifier(commande: Commande) -> List[str]:
    """Les trois fichiers d'une créa viennent-ils du même master.

    Le contrôle ne fait confiance ni à l'état ni au nom des fichiers : il relit
    l'empreinte du master inscrite au moment de la déclinaison, la recalcule sur
    le master présent, et mesure la largeur de chaque fichier.
    """
    from PIL import Image

    ecarts: List[str] = []
    for crea in commande.creas():
        if not crea.rendus:
            continue
        if not crea.master or not (commande.dossier / crea.master).exists():
            ecarts.append(f"{crea.identifiant} : des rendus sans master sur le disque")
            continue
        attendue = _empreinte(commande.dossier / crea.master)
        inscrite = ((crea.audit or {}).get("formats") or {}).get("empreinte_master")
        if inscrite and inscrite != attendue:
            ecarts.append(f"{crea.identifiant} : les rendus viennent d'un autre master "
                          f"({inscrite} au lieu de {attendue})")

        largeurs = {}
        for nom, chemin in crea.rendus.items():
            fichier = commande.dossier / chemin
            if not fichier.exists():
                ecarts.append(f"{crea.identifiant} : {nom} déclaré mais absent, {chemin}")
                continue
            with Image.open(fichier) as im:
                largeur, hauteur = im.size
            largeurs[nom] = largeur
            attendu = FORMATS.get(nom)
            if attendu and abs(hauteur / largeur - attendu) > 0.01:
                ecarts.append(f"{crea.identifiant} : {nom} fait {largeur}x{hauteur}, "
                              f"ratio {hauteur / largeur:.3f} au lieu de {attendu:.3f}")
        if len(set(largeurs.values())) > 1:
            ecarts.append(f"{crea.identifiant} : les formats n'ont pas la même largeur, "
                          f"{largeurs}")
        manquants = [n for n in FORMATS if n not in crea.rendus]
        if manquants:
            ecarts.append(f"{crea.identifiant} : format(s) manquant(s) "
                          f"{', '.join(manquants)}")
    return ecarts


def main() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sous = analyseur.add_subparsers(dest="action", required=True)
    p = sous.add_parser("decliner", help="tirer le 4:5 et le 9:16 des masters")
    p.add_argument("ardoise")
    p.add_argument("--creas", nargs="+")
    p = sous.add_parser("verifier", help="contrôler que les trois formats se tiennent")
    p.add_argument("ardoise")
    args = analyseur.parse_args()

    commande = Commande.charger(args.ardoise)

    if args.action == "verifier":
        ecarts = verifier(commande)
        print(f"{len(ecarts)} écart(s)")
        for ecart in ecarts:
            print(f"  {ecart}")
        return 1 if ecarts else 0

    bilan = decliner(commande, args.creas)
    print(f"{bilan['traitees']} créa(s) traitée(s), {bilan['completes']} "
          f"aux trois formats.")
    for identifiant, motifs in bilan["a_etendre"].items():
        for nom, motif in motifs.items():
            print(f"  [à étendre] {identifiant} {nom} : {motif}")
    if bilan["a_etendre"]:
        print(f"\nListe reprise dans {commande.dossier}/formats/a-etendre.json : "
              "ces formats se produisent par le connecteur.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
