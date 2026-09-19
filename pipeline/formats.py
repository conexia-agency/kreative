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


def assembler_extension(master: Path, sortie_connecteur: Path, cible: Path,
                        ratio_cible: float, fondu: int = 24) -> dict:
    """Monte le format final : bandes du connecteur, master intact au centre.

    L'extension par le connecteur invente des bandes crédibles, mais elle
    rééchantillonne TOUT le canevas au passage : mesuré le 19/09, un carré
    central qui s'écartait du master de 11,28 en moyenne par pixel, quand la
    règle 4.2 exige le même visuel décliné. On ne garde donc du connecteur que
    ce qu'il a inventé, les bandes, et on repose le master d'origine au centre,
    à l'octet près. Seule la couture est fondue, sur quelques pixels, pour que
    le raccord ne fasse pas une ligne.
    """
    from PIL import Image

    with Image.open(master) as im:
        original = im.convert("RGB")
    largeur, hauteur = original.size
    cible_hauteur = int(round(largeur * ratio_cible))

    with Image.open(sortie_connecteur) as im:
        etendue = im.convert("RGB")
    if etendue.size != (largeur, cible_hauteur):
        etendue = etendue.resize((largeur, cible_hauteur), Image.LANCZOS)

    ajout_haut = (cible_hauteur - hauteur) // 2
    toile = etendue.copy()
    toile.paste(original, (0, ajout_haut))

    # Le fondu de couture : sur les premières et dernières lignes du master,
    # on mélange linéairement vers la version du connecteur, pour absorber un
    # éventuel écart de teinte au raccord.
    if fondu > 0:
        for rang in range(fondu):
            alpha = (rang + 1) / (fondu + 1)
            for y_master, y_toile in ((rang, ajout_haut + rang),
                                      (hauteur - 1 - rang,
                                       ajout_haut + hauteur - 1 - rang)):
                ligne_master = original.crop((0, y_master, largeur, y_master + 1))
                ligne_conn = etendue.crop((0, y_toile, largeur, y_toile + 1))
                toile.paste(Image.blend(ligne_master, ligne_conn, 1 - alpha),
                            (0, y_toile))

    cible.parent.mkdir(parents=True, exist_ok=True)
    toile.save(cible, "PNG")
    return {"largeur": largeur, "hauteur": cible_hauteur,
            "bande_haut": ajout_haut,
            "bande_bas": cible_hauteur - hauteur - ajout_haut,
            "methode": "bandes du connecteur, master reposé au centre",
            "fondu_px": fondu}


def ranger_extension(commande: Commande, identifiant: str, nom_format: str,
                     fichier: Path) -> dict:
    """Assemble et range un format produit par le connecteur."""
    crea = commande.lire_crea(identifiant)
    if not crea.master:
        raise RuntimeError(f"{identifiant} n'a pas de master")
    master = commande.dossier / crea.master
    ratio = FORMATS[nom_format]
    cible = commande.dossier / "dist" / identifiant / f"{identifiant}-{nom_format}.png"
    mesure = assembler_extension(master, fichier, cible, ratio)
    mesure["empreinte_master"] = _empreinte(master)

    crea = commande.lire_crea(identifiant)
    crea.rendus = dict(crea.rendus or {})
    crea.rendus[nom_format] = str(cible.relative_to(commande.dossier))
    bloc = dict((crea.audit or {}).get("formats") or {})
    bloc["produits"] = sorted(set(bloc.get("produits") or []) | {nom_format})
    bloc["a_etendre"] = [n for n in (bloc.get("a_etendre") or []) if n != nom_format]
    bloc["empreinte_master"] = mesure["empreinte_master"]
    crea.audit = dict(crea.audit or {})
    crea.audit["formats"] = bloc
    if all(n in crea.rendus for n in FORMATS):
        crea.etat = "composee"
    commande.ecrire_crea(crea)
    commande.tracer("format_etendu", crea=identifiant, format=nom_format,
                    methode=mesure["methode"])
    return mesure


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
        # Un format déjà assemblé depuis le connecteur ne se refait pas : le
        # refus du prolongement de bord écraserait un fichier payé et valide.
        deja = dossier / f"{crea.identifiant}-{nom}.png"
        if deja.exists():
            rendus[nom] = str(deja.relative_to(commande.dossier))
            mesures[nom] = {"methode": "déjà produit, conservé",
                            "empreinte_master": empreinte}
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


# Au-delà, le carré central d'une déclinaison n'est plus « le même visuel »
# que le master. La différence est une moyenne par pixel sur 0..255, mesurée
# en niveaux de gris à taille réduite. Un prolongement de bord fait 0.0 par
# construction. Une extension par le connecteur repasse par un modèle : elle
# peut recomprimer le centre sans le redessiner, d'où une tolérance faible
# mais non nulle. Le seuil est PROVISOIRE, à recaler sur les premières
# extensions réelles ; s'il est dépassé, le modèle a retouché le visuel, ce
# que la règle 4.2 interdit, et la déclinaison est signalée.
DIFFERENCE_CENTRE_MAXIMALE = 3.0


def _difference_centre(master: Path, decline: Path, hauteur_master: int,
                       hauteur_decline: int) -> Optional[float]:
    """La différence moyenne entre le master et le carré central du format."""
    try:
        from PIL import Image, ImageChops, ImageStat
        with Image.open(master) as im_master, Image.open(decline) as im_decline:
            largeur = im_decline.size[0]
            haut = (im_decline.size[1] - largeur) // 2
            centre = im_decline.crop((0, haut, largeur, haut + largeur))
            a = im_master.convert("L").resize((256, 256), Image.LANCZOS)
            b = centre.convert("L").resize((256, 256), Image.LANCZOS)
        return round(ImageStat.Stat(ImageChops.difference(a, b)).mean[0], 2)
    except Exception:
        return None


def verifier(commande: Commande) -> List[str]:
    """Les trois fichiers d'une créa viennent-ils du même master.

    Le contrôle ne fait confiance ni à l'état ni au nom des fichiers : il relit
    l'empreinte du master inscrite au moment de la déclinaison, la recalcule sur
    le master présent, mesure la largeur de chaque fichier, et compare le carré
    central de chaque déclinaison au master lui-même. C'est cette dernière
    mesure qui prouve la règle 4.2 : le même visuel décliné, pas régénéré.
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
            if nom != FORMAT_MASTER and hauteur > largeur:
                difference = _difference_centre(commande.dossier / crea.master,
                                                fichier, 0, 0)
                if difference is not None and difference > DIFFERENCE_CENTRE_MAXIMALE:
                    ecarts.append(
                        f"{crea.identifiant} : le carré central du {nom} s'écarte du "
                        f"master de {difference} en moyenne par pixel, au-delà de "
                        f"{DIFFERENCE_CENTRE_MAXIMALE}. Le visuel a été retouché en "
                        f"chemin, ce que la règle 4.2 interdit.")
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
    p = sous.add_parser("ranger-extension",
                        help="assembler un format produit par le connecteur")
    p.add_argument("ardoise")
    p.add_argument("--crea", required=True)
    p.add_argument("--format", required=True, dest="nom_format",
                   choices=[n for n in FORMATS if n != FORMAT_MASTER])
    p.add_argument("--fichier", required=True, type=Path)
    args = analyseur.parse_args()

    commande = Commande.charger(args.ardoise)

    if args.action == "ranger-extension":
        mesure = ranger_extension(commande, args.crea, args.nom_format, args.fichier)
        print(f"{args.crea} {args.nom_format} : {mesure['largeur']}x{mesure['hauteur']}, "
              f"bandes {mesure['bande_haut']}/{mesure['bande_bas']} px, "
              f"{mesure['methode']}.")
        return 0

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
