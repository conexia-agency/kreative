#!/usr/bin/env python3
"""redaction.py : transforme les réponses brutes du client en brief moteur.

Deuxième maillon de la chaîne, après `zite.py`. Le formulaire rend des paragraphes
écrits par le client ; le moteur attend des éléments courts et typés : une
promesse, un CTA, des douleurs en groupes nominaux, des preuves chiffrées avec
leur source. Passer de l'un à l'autre est un travail de rédaction, confié à Claude
Code en mode non interactif, conformément au point 5 du cahier des charges.

    python3 pipeline/redaction.py rediger <ardoise>
    python3 pipeline/redaction.py rediger <ardoise> --forcer
    python3 pipeline/redaction.py verifier <ardoise>

**Le modèle rédige, le code contrôle.** Un modèle de langage qui reformule finit
toujours par ajouter un chiffre plausible. Le contrôle ne lui fait donc pas
confiance : chaque nombre présent dans le brief rédigé doit exister dans les
réponses du client, chaque couleur hexadécimale doit avoir été fournie, et chaque
témoignage doit s'y trouver mot pour mot. Ce qui échoue est retiré et journalisé,
jamais corrigé en silence.

**Le modèle ne touche pas à l'identité de la commande.** Marque, site, pack,
verticale et assets sont posés par le code à partir du relevé Zite, puis recopiés
par dessus la réponse du modèle. Il ne peut ni renommer un client ni inventer un
fichier.

Cible Python 3.9+. Dépend de la commande `claude` (Claude Code) dans le PATH.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Dict, List, Tuple

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "pipeline"))

from etat import Commande  # noqa: E402

SKILL = RACINE / "skill" / "strategie-creative-SKILL.md"
DELAI_REDACTION = 600

# Le tiret cadratin, écrit par son code pour que ce fichier n'en contienne aucun.
TIRET_CADRATIN = chr(0x2014)

# Champs que le modèle a le droit d'écrire. Tout autre champ de sa réponse est
# ignoré.
CHAMPS_REDIGES = (
    "produit", "cible", "promesse_courte", "cta", "ton", "adresse",
    "douleurs", "benefices", "objections", "causes", "temoignages",
    "preuves", "offre", "angles_a_eviter", "metaphores", "decors", "lumiere",
    "charte", "occasion", "questions_cible", "a_completer",
)

CONSIGNE = """Tu rédiges le brief moteur d'une commande Kreative à partir des réponses
brutes du client à son formulaire. Tu appliques la section « Règles d'or » du skill
joint, en particulier : le brief prime, tu n'inventes aucune valeur.

Réponds UNIQUEMENT par un objet JSON valide, sans texte autour, avec ces clés :

- "produit" : une phrase, ce que le client vend.
- "cible" : une phrase, à qui.
- "promesse_courte" : moins de dix mots, le bénéfice principal.
- "cta" : deux à quatre mots, l'action attendue.
- "ton" : le ton demandé par le client, repris de sa réponse.
- "adresse" : "tu", "vous" ou "les deux", d'après sa réponse.
- "douleurs" : liste de groupes nominaux courts.
- "benefices" : liste de propositions complètes et courtes.
- "objections" : liste de phrases, formulées comme le prospect les pense.
- "causes" : liste de groupes nominaux, les causes des douleurs.
- "temoignages" : liste de citations EXACTES trouvées dans les réponses, sinon [].
- "preuves" : liste d'objets {"type", "valeur", "unite", "source"}. "valeur" est un
  nombre écrit tel que le client l'a donné. "source" est le nom du champ d'où il vient.
- "offre" : {"prix", "devise", "mention"} si le client donne un prix, sinon null.
- "angles_a_eviter" : liste reprise de sa réponse, sinon [].
- "occasion" : l'événement ou la période qui justifie une promo (soldes, fête,
  lancement), UNIQUEMENT si le client en nomme une dans sa réponse sur la promo,
  sinon null. Jamais une date inventée.
- "questions_cible" : trois à cinq questions que le prospect se pose avant
  d'acheter, formulées dans ses mots, déduites de ses freins et objections.
- "metaphores" : deux ou trois métaphores visuelles qui incarnent le message.
- "decors" : un ou deux décors plausibles pour ce client.
- "lumiere" : une phrase de direction de lumière.
- "charte" : {"primaire", "accent", "fond", "texte_sur_clair"} en hexadécimal
  UNIQUEMENT si le client a donné ces couleurs en hexadécimal, sinon null.
- "a_completer" : liste des informations nécessaires que les réponses ne donnent pas.
- "_trace" : objet qui associe chaque clé ci-dessus au nom du champ source.

Règles absolues :
1. Aucun chiffre, aucun prix, aucun pourcentage, aucune durée, aucun nombre de
   clients qui ne figure pas mot pour mot dans les réponses.
2. Aucun témoignage inventé ni reformulé : citation exacte ou rien.
3. Une information absente va dans "a_completer", jamais dans un champ rempli.
4. Français correct, accents compris. Jamais de tiret cadratin.
5. "metaphores", "decors" et "lumiere" sont de la direction créative : tu peux les
   proposer, mais sans y glisser un seul fait sur le client.
"""


# ---------------------------------------------------------------------------
# Contrôle anti-invention
# ---------------------------------------------------------------------------

def _plat(texte: str) -> str:
    sans_accent = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in sans_accent if not unicodedata.combining(c)).lower()


def _nombres(texte: str) -> List[str]:
    """Les nombres d'un texte, normalisés : 4,8 et 4.8 comptent pour le même."""
    return [n.replace(",", ".").rstrip(".") for n in re.findall(r"\d+(?:[.,]\d+)?", texte)]


def _textes(valeur) -> List[str]:
    if isinstance(valeur, str):
        return [valeur]
    if isinstance(valeur, dict):
        return [t for v in valeur.values() for t in _textes(v)]
    if isinstance(valeur, list):
        return [t for v in valeur for t in _textes(v)]
    if isinstance(valeur, (int, float)):
        return [str(valeur)]
    return []


def controler(redige: dict, reponses: Dict[str, str]) -> Tuple[dict, List[str]]:
    """Retire ce qui n'est pas adossé aux réponses. Retourne le brief propre et les retraits."""
    source = " ".join(reponses.values())
    nombres_source = set(_nombres(source))
    source_plate = _plat(source)
    retraits: List[str] = []

    def adosse(texte: str) -> bool:
        return all(n in nombres_source for n in _nombres(texte))

    propre: dict = {}
    for cle in CHAMPS_REDIGES:
        if cle not in redige:
            continue
        valeur = redige[cle]

        if cle == "charte" and isinstance(valeur, dict):
            renseignees = {k: v for k, v in valeur.items() if v}
            gardee = {k: v for k, v in renseignees.items()
                      if isinstance(v, str) and v.lower() in source.lower()}
            for k in set(renseignees) - set(gardee):
                retraits.append(f"charte.{k} = {renseignees[k]} : couleur absente des réponses")
            propre[cle] = gardee or None
            continue

        if cle == "temoignages" and isinstance(valeur, list):
            gardes = [t for t in valeur if isinstance(t, str) and _plat(t).strip() in source_plate]
            for t in valeur:
                if t not in gardes:
                    retraits.append(f"témoignage non trouvé mot pour mot : « {str(t)[:60]} »")
            propre[cle] = gardes
            continue

        if isinstance(valeur, list):
            gardes = [v for v in valeur if all(adosse(t) for t in _textes(v))]
            for v in valeur:
                if v not in gardes:
                    retraits.append(f"{cle} : chiffre absent des réponses dans « {str(v)[:80]} »")
            propre[cle] = gardes
            continue

        if valeur is not None and not all(adosse(t) for t in _textes(valeur)):
            retraits.append(f"{cle} : chiffre absent des réponses dans « {str(valeur)[:80]} »")
            propre[cle] = None
            continue

        propre[cle] = valeur

    if any(TIRET_CADRATIN in t for t in _textes(propre)):
        retraits.append("tiret cadratin présent, remplacé par une virgule")
        propre = json.loads(json.dumps(propre, ensure_ascii=False).replace(TIRET_CADRATIN, ","))
    return propre, retraits


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------

def ranger_assets(brut: Dict[str, List[str]], verticale: str) -> dict:
    """Range les pièces jointes Zite dans les cases que lit le compositeur.

    Les « visuels à inclure » changent de nature selon le métier : une capture
    d'écran chez un SaaS ou une agence, une photo produit chez un e-commerçant.
    """
    logos = brut.get("logo") or []
    visuels = brut.get("visuels") or []
    ecran = verticale in ("saas", "agence")
    return {
        "logo": logos[0] if logos else None,
        "packshots": list(brut.get("packshots") or []) + ([] if ecran else list(visuels)),
        "captures": list(visuels) if ecran else [],
        "lifestyle": list(brut.get("lifestyle") or []),
        "charte_fournie": list(brut.get("charte") or []),
        "refs_aimees": list(brut.get("refs_aimees") or []),
        "refs_rejetees": list(brut.get("refs_rejetees") or []),
    }


# ---------------------------------------------------------------------------
# Rédaction
# ---------------------------------------------------------------------------

def _extraire_json(texte: str) -> dict:
    debut, fin = texte.find("{"), texte.rfind("}")
    if debut < 0 or fin <= debut:
        raise ValueError("la réponse ne contient aucun objet JSON")
    return json.loads(texte[debut:fin + 1])


def appeler_claude(reponses: Dict[str, str]) -> dict:
    if not shutil.which("claude"):
        raise RuntimeError("commande « claude » introuvable dans le PATH")
    invite = (
        CONSIGNE
        + "\n\nRÉPONSES DU CLIENT, par champ :\n"
        + json.dumps(reponses, ensure_ascii=False, indent=2)
    )
    resultat = subprocess.run(
        ["claude", "-p", "--output-format", "json",
         "--append-system-prompt-file", str(SKILL)],
        input=invite, capture_output=True, text=True, timeout=DELAI_REDACTION,
    )
    if resultat.returncode != 0:
        raise RuntimeError(f"claude a échoué (code {resultat.returncode}) : {resultat.stderr[-600:]}")
    enveloppe = json.loads(resultat.stdout)
    if enveloppe.get("is_error"):
        raise RuntimeError(f"claude a renvoyé une erreur : {str(enveloppe.get('result'))[:600]}")
    return _extraire_json(enveloppe.get("result", ""))


def rediger(ardoise: str, forcer: bool = False) -> dict:
    commande = Commande.charger(ardoise)
    brief = commande.donnees.get("brief") or {}
    if brief.get("_redige") and not forcer:
        raise RuntimeError("brief déjà rédigé : relancer avec --forcer pour refaire")
    reponses = brief.get("reponses")
    if not reponses:
        raise RuntimeError("aucune réponse brute : cette commande ne vient pas de Zite")

    commande.tracer("redaction_demandee")
    redige = appeler_claude(reponses)
    propre, retraits = controler(redige, reponses)

    nouveau = dict(brief)
    nouveau.update(propre)
    # L'identité de la commande reste celle du relevé, quoi que le modèle ait écrit.
    for cle in ("marque", "url_site", "pack", "verticale", "_source", "reponses"):
        nouveau[cle] = brief.get(cle)
    nouveau["assets"] = ranger_assets(brief.get("assets") or {}, brief.get("verticale") or "")
    nouveau["_trace"] = redige.get("_trace", {})
    nouveau["_retraits"] = retraits
    nouveau["_redige"] = True

    commande.donnees["brief"] = nouveau
    commande.sauver()
    (commande.dossier / "brief" / "brief.json").write_text(
        json.dumps(nouveau, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    commande.tracer(
        "brief_redige",
        retraits=len(retraits),
        a_completer=len(propre.get("a_completer") or []),
    )
    return nouveau


# ---------------------------------------------------------------------------
# Ligne de commande
# ---------------------------------------------------------------------------

def main() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sous = analyseur.add_subparsers(dest="commande", required=True)
    p_rediger = sous.add_parser("rediger")
    p_rediger.add_argument("ardoise")
    p_rediger.add_argument("--forcer", action="store_true")
    p_verifier = sous.add_parser("verifier", help="rejouer le controle sur un brief deja redige")
    p_verifier.add_argument("ardoise")
    args = analyseur.parse_args()

    if args.commande == "verifier":
        brief = Commande.charger(args.ardoise).donnees.get("brief") or {}
        _, retraits = controler({k: brief.get(k) for k in CHAMPS_REDIGES if k in brief},
                                brief.get("reponses") or {})
        print(f"{len(retraits)} écart(s)")
        for r in retraits:
            print(f"  {r}")
        return 1 if retraits else 0

    brief = rediger(args.ardoise, forcer=args.forcer)
    print(f"Brief rédigé : {args.ardoise}")
    for cle in ("promesse_courte", "cta", "cible"):
        print(f"  {cle:<16} {brief.get(cle)}")
    print(f"  douleurs         {len(brief.get('douleurs') or [])}")
    print(f"  bénéfices        {len(brief.get('benefices') or [])}")
    print(f"  preuves          {len(brief.get('preuves') or [])}")
    print(f"  à compléter      {brief.get('a_completer')}")
    print(f"\n{len(brief['_retraits'])} retrait(s) par le contrôle anti-invention")
    for r in brief["_retraits"]:
        print(f"  {r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
