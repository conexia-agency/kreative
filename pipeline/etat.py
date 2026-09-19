#!/usr/bin/env python3
"""etat.py : le modèle d'état du pipeline, en fichiers.

Le cahier des charges interdit toute base de données (point 8). "Pas de base de
données" veut dire pas de serveur à administrer, pas que l'état est interdit :
sans état persistant, aucune des reprises du 7.2 n'est possible et une commande
interrompue est perdue. L'état vit donc en JSON sur disque, une commande par
dossier.

Arborescence d'une commande :

    commandes/<marque>/
        commande.json          état global, brief, pack, compteurs
        creas/c01.json ...     état d'une créa
        marque/                sortie de brand_intake : charte, logo, produits
        masters/               images générées, une par créa
        dist/<crea>/           les trois formats rendus
        journal.jsonl          trace horodatée de tout ce qui s'est passé

Ce que ce module fixe, et qui n'est pas négociable pour la suite : le CONTRAT de
sortie de l'étape stratégie. Le reste du pipeline ne connaît que ce contrat, pas
la façon dont les angles et le copy ont été trouvés. C'est ce qui permet de
brancher le skill de production plus tard sans retoucher la plomberie.

Usage :
    python3 etat.py creer --marque "Kreative" --url https://kreative.fr --pack growth
    python3 etat.py etat --marque "Kreative"
    python3 etat.py reprise-visuel --marque "Kreative" --crea c03
    python3 etat.py reprise-copy --marque "Kreative" --crea c03 --accroche "..."

Cible Python 3.9+. Aucune dépendance externe.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

VERSION_SCHEMA = 1


def _racine_travail() -> Path:
    """Où vivent les commandes clientes. Trois cas, dans cet ordre.

    1. `KREATIVE_TRAVAIL` est posée : c'est elle, toujours. C'est le mode
       « skill installé » : le code vit dans un dossier skill immuable, les
       données clientes vivent ailleurs, chez Kreative.
    2. Pas de variable, mais un dossier `commandes/` existe à côté du code :
       c'est le dépôt de développement Conexia, on ne change rien.
    3. Ni l'un ni l'autre : `~/Kreative/commandes`, créé au premier usage.
    """
    var = os.environ.get("KREATIVE_TRAVAIL", "").strip()
    if var:
        return Path(var).expanduser() / "commandes"
    locale = Path(__file__).resolve().parent.parent / "commandes"
    if locale.is_dir():
        return locale
    return Path.home() / "Kreative" / "commandes"


RACINE_DEFAUT = _racine_travail()

# ---------------------------------------------------------------------------
# Packs. Les valeurs sont celles du CAHIER DES CHARGES de Kreative, article
# 4.6 : 6, 12 et 24 créas vendues, et le double généré pour laisser une marge
# de tri à la réception.
#
# **Ses deux documents ne disent pas la même chose, et c'est à lui de
# trancher.** Son cahier des charges dit Scale = 24 vendues et 48 générées ;
# son skill du 17/09 dit Scale = 18 créas pour 9 angles. On applique ici le
# cahier des charges, parce que c'est lui qui décrit ce que le client a acheté,
# et le skill décrit comment le produire. Si Evan répond l'inverse, c'est cette
# table qui change, et elle seule.
#
# Le facteur porte la surproduction. Il était passé à 1 le 17/09 sur une
# décision interne qui n'était pas la sienne : sans marge, chaque créa doit
# être bonne, alors que le 4.6 prévoit qu'on en produise deux pour en garder
# une.
# ---------------------------------------------------------------------------

PACKS: Dict[str, int] = {
    "starter": 6,
    "growth": 12,
    "scale": 24,
}

FACTEUR_SURPRODUCTION = 2


def volume_genere(quantite_vendue: int) -> int:
    return quantite_vendue * FACTEUR_SURPRODUCTION


# ---------------------------------------------------------------------------
# États
# ---------------------------------------------------------------------------

ETATS_COMMANDE = [
    "recue",        # paiement encaissé, brief reçu
    "intake",       # analyse du site en cours
    "strategie",    # angles, copy et prompts en cours
    "generation",   # masters en cours de génération
    "composition",  # déclinaison en trois formats
    "audit",        # gate qualité
    "livree",
    "echec",
]

ETATS_CREA = [
    "prevue",       # existe, rien de produit
    "briefee",      # copy et prompt de scène arrêtés
    "master_ok",    # image générée
    "composee",     # trois formats rendus
    "retenue",      # a passé le gate, part en livraison
    "rejetee",      # recalée par le gate ou par l'oeil
]


def maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ardoise(valeur: str) -> str:
    """Normalise un nom de marque en identifiant de dossier."""
    sans_accent = unicodedata.normalize("NFKD", valeur)
    sans_accent = "".join(c for c in sans_accent if not unicodedata.combining(c))
    nettoye = re.sub(r"[^a-zA-Z0-9]+", "-", sans_accent).strip("-").lower()
    return nettoye or "sans-nom"


# ---------------------------------------------------------------------------
# Contrat de sortie de l'étape stratégie
# ---------------------------------------------------------------------------

@dataclass
class Copy:
    """Le texte de la créa. Il ne part JAMAIS dans le prompt du modèle.

    Conséquence directe sur le 7.2, cas B. Le CDC décrit la méthode manuelle
    actuelle : réémettre le prompt complet en ne remplaçant que la phrase entre
    guillemets, en espérant que le visuel ne bouge pas. Ici le texte n'est pas
    dans l'image, donc corriger un copy raté ne relance aucune génération : on
    change le champ et on recompose. Coût nul, résultat déterministe, le visuel
    validé ne peut pas dériver.
    """

    accroche: str = ""
    sous_accroche: str = ""
    cta: str = ""
    badge: str = ""


@dataclass
class Prompt:
    """Le prompt de scène. Il ne décrit que l'image, jamais le texte.

    `phrase_gravee` reste disponible pour le cas résiduel où un mot doit
    réellement exister dans la scène : une étiquette produit, un packaging.
    Hors de ce cas, elle reste vide, et c'est la règle.
    """

    scene: str = ""
    negatif: str = ""
    phrase_gravee: str = ""
    # `nano_banana_pro` en toutes lettres, pas l'alias. Sous l'ancienne ligne de
    # commande, `nano_banana_2` passait pour le Pro, et le modèle qui s'affiche
    # « Nano Banana 2 » est en réalité `nano_banana_flash`, moins cher et moins
    # bon. Le connecteur MCP expose les trois séparément : on nomme celui du
    # cahier des charges.
    modele: str = "nano_banana_pro"
    # Images de référence pour l'image-to-image, chemins relatifs à la commande.
    # C'est par là que le vrai produit entre dans une scène sans être redessiné :
    # le test du 27/08 a montré que le modèle préserve un grand texte 4 fois sur
    # 4, mais redessine un logo 0 fois sur 4. Un produit qui porte une marque ne
    # se génère donc jamais, il se compose ou se passe en référence.
    references: List[str] = field(default_factory=list)

    def rendu(self) -> str:
        texte = self.scene
        if self.phrase_gravee:
            texte = f'{texte}\nTexte visible dans la scène : "{self.phrase_gravee}"'
        return texte


@dataclass
class Crea:
    identifiant: str
    angle: str = ""
    etat: str = "prevue"
    copy: Copy = field(default_factory=Copy)
    prompt: Prompt = field(default_factory=Prompt)
    master: Optional[str] = None          # chemin relatif à la commande
    job_generation: Optional[str] = None  # identifiant du job Higgsfield
    rendus: Dict[str, str] = field(default_factory=dict)   # format -> chemin
    audit: Dict[str, object] = field(default_factory=dict)  # format -> verdict
    tours: int = 0                        # nombre de reprises subies

    def vers_dict(self) -> dict:
        donnees = asdict(self)
        return donnees

    @staticmethod
    def depuis_dict(donnees: dict) -> "Crea":
        return Crea(
            identifiant=donnees["identifiant"],
            angle=donnees.get("angle", ""),
            etat=donnees.get("etat", "prevue"),
            copy=Copy(**donnees.get("copy", {})),
            prompt=Prompt(**donnees.get("prompt", {})),
            master=donnees.get("master"),
            job_generation=donnees.get("job_generation"),
            rendus=donnees.get("rendus", {}),
            audit=donnees.get("audit", {}),
            tours=donnees.get("tours", 0),
        )


# ---------------------------------------------------------------------------
# Commande
# ---------------------------------------------------------------------------

class Commande:
    def __init__(self, dossier: Path, donnees: dict):
        self.dossier = dossier
        self.donnees = donnees

    # -- création et chargement --------------------------------------------

    @staticmethod
    def creer(
        marque: str,
        url_site: str,
        pack: str,
        *,
        brief: Optional[dict] = None,
        reference_paiement: Optional[str] = None,
        racine: Path = RACINE_DEFAUT,
    ) -> "Commande":
        if pack not in PACKS:
            raise ValueError(f"Pack inconnu : {pack}. Connus : {', '.join(PACKS)}")

        vendues = PACKS[pack]
        generees = volume_genere(vendues)
        dossier = racine / ardoise(marque)
        if (dossier / "commande.json").exists():
            raise FileExistsError(f"Une commande existe déjà : {dossier}")

        for sous in ("creas", "marque", "masters", "dist"):
            (dossier / sous).mkdir(parents=True, exist_ok=True)

        donnees = {
            "version_schema": VERSION_SCHEMA,
            "marque": marque,
            "ardoise": ardoise(marque),
            "url_site": url_site,
            "pack": pack,
            "quantite_vendue": vendues,
            "quantite_generee": generees,
            "reference_paiement": reference_paiement,
            "brief": brief or {},
            "etat": "recue",
            "cree_le": maintenant(),
            "modifie_le": maintenant(),
            "tours_revision_restants": 2,
        }
        commande = Commande(dossier, donnees)

        # Les créas sont créées vides dès l'ouverture de la commande : le
        # volume à produire est connu au paiement, pas après la stratégie.
        for index in range(1, generees + 1):
            commande.ecrire_crea(Crea(identifiant=f"c{index:02d}"))

        commande.sauver()
        commande.tracer("commande_creee", pack=pack, quantite_generee=generees)
        return commande

    @staticmethod
    def charger(marque: str, racine: Path = RACINE_DEFAUT) -> "Commande":
        dossier = racine / ardoise(marque)
        fichier = dossier / "commande.json"
        if not fichier.exists():
            raise FileNotFoundError(f"Commande introuvable : {fichier}")
        return Commande(dossier, json.loads(fichier.read_text(encoding="utf-8")))

    def sauver(self) -> None:
        self.donnees["modifie_le"] = maintenant()
        (self.dossier / "commande.json").write_text(
            json.dumps(self.donnees, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # -- créas --------------------------------------------------------------

    def chemin_crea(self, identifiant: str) -> Path:
        return self.dossier / "creas" / f"{identifiant}.json"

    def ecrire_crea(self, crea: Crea) -> None:
        self.chemin_crea(crea.identifiant).write_text(
            json.dumps(crea.vers_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def lire_crea(self, identifiant: str) -> Crea:
        fichier = self.chemin_crea(identifiant)
        if not fichier.exists():
            raise FileNotFoundError(f"Créa introuvable : {fichier}")
        return Crea.depuis_dict(json.loads(fichier.read_text(encoding="utf-8")))

    def creas(self) -> List[Crea]:
        dossier = self.dossier / "creas"
        return [
            Crea.depuis_dict(json.loads(f.read_text(encoding="utf-8")))
            for f in sorted(dossier.glob("*.json"))
        ]

    # -- journal ------------------------------------------------------------

    def tracer(self, evenement: str, **details) -> None:
        """Ajoute une ligne au journal.

        Le journal est la seule mémoire de ce qui s'est passé quand un run
        échoue à trois heures du matin sans personne devant l'écran. Il répond
        au point ouvert #4 du cahier des charges, le traitement d'erreur.
        """
        ligne = {"horodatage": maintenant(), "evenement": evenement}
        ligne.update(details)
        with (self.dossier / "journal.jsonl").open("a", encoding="utf-8") as flux:
            flux.write(json.dumps(ligne, ensure_ascii=False) + "\n")

    def passer_a(self, etat: str) -> None:
        if etat not in ETATS_COMMANDE:
            raise ValueError(f"État de commande inconnu : {etat}")
        precedent = self.donnees.get("etat")
        self.donnees["etat"] = etat
        self.sauver()
        self.tracer("etat_commande", de=precedent, vers=etat)

    # -- reprises du 7.2 ----------------------------------------------------

    def reprise_visuel(self, identifiant: str) -> Crea:
        """Cas A : le copy est bon, le visuel est raté.

        On efface le master et les rendus, on garde l'angle, le copy et le
        prompt. La créa repart à la génération, sans repasser par la stratégie.
        """
        crea = self.lire_crea(identifiant)
        crea.master = None
        crea.job_generation = None
        crea.rendus = {}
        crea.audit = {}
        crea.etat = "briefee"
        crea.tours += 1
        self.ecrire_crea(crea)
        self.tracer("reprise_visuel", crea=identifiant, tour=crea.tours)
        return crea

    def reprise_copy(self, identifiant: str, **champs: str) -> Crea:
        """Cas B : le visuel est bon, le copy est raté.

        Aucune génération n'est relancée. Le master validé est conservé tel
        quel, seuls les champs de copy fournis sont remplacés, et la créa
        repart à la composition. Le visuel ne peut pas dériver puisqu'il n'est
        pas retouché.
        """
        crea = self.lire_crea(identifiant)
        if not crea.master:
            raise ValueError(
                f"{identifiant} n'a pas de master validé : "
                "une reprise de copy n'a pas de sens ici."
            )
        connus = {"accroche", "sous_accroche", "cta", "badge"}
        inconnus = set(champs) - connus
        if inconnus:
            raise ValueError(f"Champs de copy inconnus : {', '.join(sorted(inconnus))}")

        avant = asdict(crea.copy)
        for cle, valeur in champs.items():
            if valeur is not None:
                setattr(crea.copy, cle, valeur)
        crea.rendus = {}
        crea.audit = {}
        crea.etat = "master_ok"
        crea.tours += 1
        self.ecrire_crea(crea)
        self.tracer("reprise_copy", crea=identifiant, tour=crea.tours,
                    avant=avant, apres=asdict(crea.copy))
        return crea

    # -- lecture ------------------------------------------------------------

    def resume(self) -> str:
        creas = self.creas()
        par_etat: Dict[str, int] = {}
        for crea in creas:
            par_etat[crea.etat] = par_etat.get(crea.etat, 0) + 1

        lignes = [
            f"Marque      : {self.donnees['marque']}",
            f"Site        : {self.donnees['url_site']}",
            f"Pack        : {self.donnees['pack']} "
            f"({self.donnees['quantite_vendue']} vendues, "
            f"{self.donnees['quantite_generee']} générées)",
            f"État        : {self.donnees['etat']}",
            f"Révisions   : {self.donnees['tours_revision_restants']} tour(s) restant(s)",
            f"Créas       : {len(creas)}",
        ]
        for etat in ETATS_CREA:
            if etat in par_etat:
                lignes.append(f"  {etat:<12} {par_etat[etat]}")
        retenues = par_etat.get("retenue", 0)
        vendues = self.donnees["quantite_vendue"]
        if retenues:
            lignes.append(
                f"Sélection   : {retenues} retenue(s) pour {vendues} à livrer"
                + ("" if retenues >= vendues else "  [!] insuffisant")
            )
        return "\n".join(lignes)


# ---------------------------------------------------------------------------

def main() -> int:
    parseur = argparse.ArgumentParser(description="Modèle d'état du pipeline Kreative")
    sous = parseur.add_subparsers(dest="commande", required=True)

    p_creer = sous.add_parser("creer", help="Ouvrir une commande")
    p_creer.add_argument("--marque", required=True)
    p_creer.add_argument("--url", required=True)
    p_creer.add_argument("--pack", required=True, choices=list(PACKS))
    p_creer.add_argument("--paiement", help="Référence du paiement Stripe")

    p_etat = sous.add_parser("etat", help="Afficher l'état d'une commande")
    p_etat.add_argument("--marque", required=True)

    p_rv = sous.add_parser("reprise-visuel", help="Cas A : régénérer le visuel, garder le copy")
    p_rv.add_argument("--marque", required=True)
    p_rv.add_argument("--crea", required=True)

    p_rc = sous.add_parser("reprise-copy", help="Cas B : garder le visuel, corriger le copy")
    p_rc.add_argument("--marque", required=True)
    p_rc.add_argument("--crea", required=True)
    p_rc.add_argument("--accroche")
    p_rc.add_argument("--sous-accroche", dest="sous_accroche")
    p_rc.add_argument("--cta")
    p_rc.add_argument("--badge")

    arguments = parseur.parse_args()

    try:
        if arguments.commande == "creer":
            commande = Commande.creer(
                arguments.marque, arguments.url, arguments.pack,
                reference_paiement=arguments.paiement,
            )
            print(f"Commande ouverte : {commande.dossier}")
            print(commande.resume())

        elif arguments.commande == "etat":
            print(Commande.charger(arguments.marque).resume())

        elif arguments.commande == "reprise-visuel":
            commande = Commande.charger(arguments.marque)
            crea = commande.reprise_visuel(arguments.crea)
            print(f"{crea.identifiant} repart en génération (tour {crea.tours}), copy conservé.")

        elif arguments.commande == "reprise-copy":
            commande = Commande.charger(arguments.marque)
            champs = {
                cle: getattr(arguments, cle)
                for cle in ("accroche", "sous_accroche", "cta", "badge")
                if getattr(arguments, cle) is not None
            }
            if not champs:
                print("Rien à corriger : donner au moins un champ de copy.", file=sys.stderr)
                return 1
            crea = commande.reprise_copy(arguments.crea, **champs)
            print(f"{crea.identifiant} repart en composition (tour {crea.tours}), "
                  "master conservé, aucune génération relancée.")

    except (ValueError, FileNotFoundError, FileExistsError) as erreur:
        print(f"Erreur : {erreur}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
