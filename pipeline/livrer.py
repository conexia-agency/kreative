#!/usr/bin/env python3
"""livrer.py : le dossier de remise, et la notification qui prévient.

Article 6 du cahier des charges de Kreative, mot pour mot : un dossier au nom
de la marque cliente, les visuels dedans, et une notification à la création.
Rien de tout cela n'existait avant le 18/09 : aucune occurrence de notification
dans le code, et les packs vivaient dans le dossier de travail.

Trois choses, et pas une de plus :

1. **Un dossier hors de l'espace de travail.** Les commandes sont un espace de
   production, avec des masters intermédiaires, des lots, un journal. Ce n'est
   pas ce qu'on remet. Le dossier de remise ne contient que ce qui se regarde.
2. **Les fichiers nommés pour un humain.** `podmax-03-1x1.png`, pas `c03.png`.
   Un nom qui se lit sur un téléphone, dans l'ordre du pack.
3. **Une notification.** Vers un webhook si l'adresse est posée dans
   l'environnement, sinon en clair dans le dossier et dans un journal. Ce qui
   compte est qu'il n'y ait jamais de livraison muette.

Où déposer le dossier reste la décision de Kreative : `KREATIVE_LIVRAISONS`
fixe l'endroit. Par défaut `~/Kreative/livraisons`. L'article 8 interdit
seulement d'exiger un connecteur payant, il n'impose pas d'emplacement.

    python3 pipeline/livrer.py <ardoise>
    python3 pipeline/livrer.py <ardoise> --vers /chemin/du/dossier
    python3 pipeline/livrer.py <ardoise> --sans-notification

Cible Python 3.9+. Aucune dépendance externe.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))

from etat import Commande, Crea  # noqa: E402

DELAI_WEBHOOK = 15


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def racine_livraisons() -> Path:
    """Où se posent les dossiers de remise.

    Article 8 du cahier des charges : « Google Drive uniquement comme point de
    dépôt de fichiers », et article 6.2 : le dossier doit être accessible
    depuis le téléphone. Poser `KREATIVE_LIVRAISONS` sur le dossier local que
    l'application Google Drive synchronise répond aux deux sans installer quoi
    que ce soit : la chaîne écrit un dossier, Drive le monte, le téléphone le
    voit. À défaut, `~/Kreative/livraisons`, qui reste sur le poste.
    """
    var = os.environ.get("KREATIVE_LIVRAISONS", "").strip()
    if var:
        return Path(var).expanduser()
    return Path.home() / "Kreative" / "livraisons"


def _dossier_libre(souhaite: Path) -> Path:
    """Le dossier au nom de la marque, ou le suivant s'il est déjà pris.

    Une deuxième livraison n'écrase jamais la première : le client a pu
    partager le lien du premier dossier, et remplacer des fichiers sous ses
    pieds serait pire que de créer un second dossier visiblement nommé.
    """
    if not souhaite.exists():
        return souhaite
    for rang in range(2, 100):
        candidat = souhaite.parent / f"{souhaite.name} ({rang})"
        if not candidat.exists():
            return candidat
    return souhaite.parent / f"{souhaite.name} ({_maintenant().replace(':', '')})"


# ---------------------------------------------------------------------------
# 1. Le dossier
# ---------------------------------------------------------------------------

def _a_livrer(commande: Commande) -> List[Crea]:
    """Les créas qui ont au moins un fichier à remettre, dans l'ordre du pack.

    On ne filtre pas sur l'état : une créa `composee` et une créa `retenue`
    se livrent pareil. Ce qui décide, c'est l'existence des fichiers.
    """
    retenues = []
    for crea in commande.creas():
        if any((commande.dossier / c).exists() for c in (crea.rendus or {}).values()):
            retenues.append(crea)
    return retenues


def _lisez_moi(commande: Commande, creas: List[Crea], fichiers: Dict[str, List[str]]) -> str:
    """Le texte de chaque créa, à côté des images.

    La copy ne se relit pas dans un PNG : pour programmer une publication, il
    faut le texte séparément. Il est ici, créa par créa, dans l'ordre.
    """
    d = commande.donnees
    lignes = [
        f"{d['marque']} : {len(creas)} créas",
        f"Pack {d.get('pack')}, livré le {_maintenant()[:10]}.",
        "",
        "Chaque créa existe en trois formats : 1x1 pour le fil, 4x5 pour le fil "
        "vertical, 9x16 pour les stories et les reels.",
        "",
    ]
    for rang, crea in enumerate(creas, start=1):
        lignes.append(f"--- {rang:02d}  ({crea.identifiant}) " + "-" * 40)
        if crea.angle:
            lignes.append(f"Angle        : {crea.angle}")
        if crea.copy.accroche:
            lignes.append(f"Accroche     : {crea.copy.accroche}")
        if crea.copy.sous_accroche:
            lignes.append(f"Sous-accroche: {crea.copy.sous_accroche}")
        if crea.copy.cta:
            lignes.append(f"CTA          : {crea.copy.cta}")
        if crea.copy.badge:
            lignes.append(f"Badge        : {crea.copy.badge}")
        lignes.append(f"Fichiers     : {', '.join(fichiers.get(crea.identifiant, []))}")
        lignes.append("")

    manques = commande.donnees.get("ce_qui_a_manque") or []
    if manques:
        lignes += ["", "Ce qui a manqué pendant la production :"]
        lignes += [f"  - {m}" for m in manques]

    incomplets = [c.identifiant for c in creas if len(c.rendus or {}) < 3]
    if incomplets:
        lignes += ["", "Créas livrées en moins de trois formats : "
                       + ", ".join(incomplets)]
    return "\n".join(lignes) + "\n"


def construire_dossier(commande: Commande, vers: Optional[Path] = None) -> dict:
    creas = _a_livrer(commande)
    if not creas:
        raise RuntimeError("aucune créa n'a de fichier à livrer : "
                           "lancer d'abord la déclinaison des formats")

    ardoise = commande.donnees["ardoise"]
    # Article 6.1, mot pour mot : « un dossier sur le PC, nommé directement au
    # nom de la marque cliente ». Pas d'horodatage devant, pas d'identifiant
    # technique : le nom que le client reconnaît. Une deuxième livraison de la
    # même marque prend un suffixe plutôt que d'écraser la première.
    nom = commande.donnees.get("marque") or ardoise
    racine = vers or _dossier_libre(racine_livraisons() / nom)
    racine.mkdir(parents=True, exist_ok=True)

    fichiers: Dict[str, List[str]] = {}
    copies = 0
    for rang, crea in enumerate(creas, start=1):
        noms = []
        for format_nom in ("1x1", "4x5", "9x16"):
            chemin = (crea.rendus or {}).get(format_nom)
            if not chemin:
                continue
            source = commande.dossier / chemin
            if not source.exists():
                continue
            nom = f"{ardoise}-{rang:02d}-{format_nom}{source.suffix}"
            shutil.copy2(source, racine / nom)
            noms.append(nom)
            copies += 1
        fichiers[crea.identifiant] = noms

    (racine / "LISEZ-MOI.txt").write_text(
        _lisez_moi(commande, creas, fichiers), encoding="utf-8")

    (racine / "livraison.json").write_text(json.dumps({
        "ardoise": ardoise,
        "marque": commande.donnees.get("marque"),
        "pack": commande.donnees.get("pack"),
        "livre_le": _maintenant(),
        "creas": len(creas),
        "fichiers": copies,
        "par_crea": fichiers,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    commande.tracer("dossier_livraison", dossier=str(racine), creas=len(creas),
                    fichiers=copies)
    return {"dossier": racine, "creas": len(creas), "fichiers": copies,
            "par_crea": fichiers}


# ---------------------------------------------------------------------------
# 2. La notification
# ---------------------------------------------------------------------------

def _texte_notification(commande: Commande, bilan: dict) -> str:
    d = commande.donnees
    incomplets = sum(1 for noms in bilan["par_crea"].values() if len(noms) < 3)
    texte = (f"Pack {d.get('pack')} livré pour {d.get('marque')} : "
             f"{bilan['creas']} créas, {bilan['fichiers']} fichiers.\n"
             f"Dossier : {bilan['dossier']}")
    if incomplets:
        texte += f"\n{incomplets} créa(s) livrée(s) en moins de trois formats."
    manques = d.get("ce_qui_a_manque") or []
    if manques:
        texte += f"\n{len(manques)} carence(s) signalée(s) pendant la production."
    return texte


def notifier(commande: Commande, bilan: dict) -> dict:
    """Prévient qu'un pack est prêt. Ne lève jamais : une notification ratée
    n'annule pas une livraison réussie, elle se consigne.

    Trois voies, dans cet ordre, et toutes les trois sont tentées :

    - `KREATIVE_NOTIF_WEBHOOK` : une adresse HTTPS qui reçoit un JSON. C'est la
      voie qui marche avec un canal d'équipe ou un automate, sans rien installer.
    - la notification du système, sur macOS, quand un écran est allumé.
    - le fichier `NOTIFICATION.txt` dans le dossier livré, et une ligne dans
      `notifications.jsonl` à la racine des livraisons. Cette voie-là ne peut
      pas échouer, et c'est elle qui garantit qu'aucune livraison n'est muette.
    """
    texte = _texte_notification(commande, bilan)
    voies: List[dict] = []

    adresse = os.environ.get("KREATIVE_NOTIF_WEBHOOK", "").strip()
    if adresse:
        charge = json.dumps({
            "text": texte,
            "ardoise": commande.donnees["ardoise"],
            "marque": commande.donnees.get("marque"),
            "pack": commande.donnees.get("pack"),
            "creas": bilan["creas"],
            "dossier": str(bilan["dossier"]),
            "livre_le": _maintenant(),
        }, ensure_ascii=False).encode("utf-8")
        requete = urllib.request.Request(
            adresse, data=charge,
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(requete, timeout=DELAI_WEBHOOK) as reponse:
                voies.append({"voie": "webhook", "ok": True, "code": reponse.status})
        except (urllib.error.URLError, OSError, ValueError) as erreur:
            voies.append({"voie": "webhook", "ok": False, "erreur": str(erreur)[:200]})
    else:
        voies.append({"voie": "webhook", "ok": False,
                      "erreur": "KREATIVE_NOTIF_WEBHOOK absente de l'environnement"})

    if sys.platform == "darwin" and shutil.which("osascript"):
        titre = f"Kreative : {commande.donnees.get('marque')}"
        corps = f"{bilan['creas']} créas livrées"
        try:
            subprocess.run(
                ["osascript", "-e",
                 f'display notification {json.dumps(corps)} with title {json.dumps(titre)}'],
                capture_output=True, timeout=10)
            voies.append({"voie": "systeme", "ok": True})
        except Exception as erreur:
            voies.append({"voie": "systeme", "ok": False, "erreur": str(erreur)[:200]})

    dossier = Path(bilan["dossier"])
    (dossier / "NOTIFICATION.txt").write_text(texte + "\n", encoding="utf-8")
    journal = racine_livraisons() / "notifications.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open("a", encoding="utf-8") as flux:
        flux.write(json.dumps({
            "horodatage": _maintenant(),
            "ardoise": commande.donnees["ardoise"],
            "marque": commande.donnees.get("marque"),
            "dossier": str(dossier),
            "creas": bilan["creas"],
            "voies": voies,
        }, ensure_ascii=False) + "\n")
    voies.append({"voie": "fichier", "ok": True, "chemin": str(journal)})

    commande.tracer("notification", voies=[v["voie"] for v in voies if v.get("ok")])
    return {"texte": texte, "voies": voies}


# ---------------------------------------------------------------------------

def livrer(ardoise: str, vers: Optional[Path] = None,
           avec_notification: bool = True) -> dict:
    commande = Commande.charger(ardoise)
    bilan = construire_dossier(commande, vers)
    bilan["notification"] = notifier(commande, bilan) if avec_notification else None
    commande.passer_a("livree")
    return bilan


def main() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    analyseur.add_argument("ardoise")
    analyseur.add_argument("--vers", type=Path, help="dossier de remise")
    analyseur.add_argument("--sans-notification", action="store_true")
    args = analyseur.parse_args()

    try:
        bilan = livrer(args.ardoise, args.vers, not args.sans_notification)
    except (FileNotFoundError, RuntimeError) as erreur:
        print(f"Erreur : {erreur}", file=sys.stderr)
        return 1

    print(f"{bilan['creas']} créa(s), {bilan['fichiers']} fichier(s) : {bilan['dossier']}")
    notification = bilan.get("notification")
    if notification:
        for voie in notification["voies"]:
            marque = "envoyée" if voie.get("ok") else "non envoyée"
            detail = voie.get("erreur") or voie.get("chemin") or ""
            print(f"  notification {voie['voie']:<9} {marque}  {detail}")
    else:
        print("  notification désactivée par --sans-notification")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
