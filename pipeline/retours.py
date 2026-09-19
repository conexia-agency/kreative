#!/usr/bin/env python3
"""retours.py : redescend les commentaires de la plateforme en corrections.

    python3 pipeline/retours.py <ardoise> --client <slug>
    python3 pipeline/retours.py <ardoise> --client <slug> --tout   # même les traités

Le principe qui a fait échouer son prédécesseur, et qu'on inverse ici : aucun
export manuel, aucun fichier à déplacer depuis un dossier de téléchargements.
Les retours vivent en base, ce script les lit par l'API, les écrit dans
`commandes/<ardoise>/retours/`, et c'est le FICHIER LOCAL qui déclenche la
reprise. La base n'est jamais l'état de la chaîne, elle n'est que la boîte
aux lettres.

Chaque retour descendu produit :

    retours/<id>.json            le retour brut, plus le contexte résolu
    reprises/<cNN>/<horodatage>/consigne.md    le dossier de reprise, prêt

La consigne suit la grammaire éprouvée d'aloa-production : une phrase
`CORRECTIONS, apply strictly: <Add|Remove|Replace|Change> ...` quand le
payload la porte, sinon le commentaire libre est laissé à la session, qui la
rédige avant de régénérer.

Les deux cas de reprise, réécrits pour le texte cuit (décision du 17/09) :

    cas A, le visuel est raté et la copy est bonne : régénérer, même scène
           corrigée, copy STRICTEMENT inchangée.
    cas B, la copy est ratée : le texte est PEINT dans l'image, il n'y a
           plus de recomposition gratuite. On régénère avec la seule copy
           changée, même scène, et le coût (2 crédits) se journalise comme
           tout le reste.

Ce script ne marque jamais un retour `traite` en base : l'écriture appartient
à la plateforme. L'idempotence est locale : un retour déjà descendu n'est pas
redescendu (index `retours/index.json`).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib import error, parse, request

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "pipeline"))

from etat import Commande  # noqa: E402


# ---------------------------------------------------------------------------
# Accès REST, mêmes conventions que publier.py
# ---------------------------------------------------------------------------

def _config() -> dict:
    noms = ("PUBLIE_SUPABASE_URL", "PUBLIE_SUPABASE_ANON_KEY",
            "PUBLIE_EMAIL", "PUBLIE_PASSWORD")
    absents = [n for n in noms if not os.environ.get(n)]
    if absents:
        raise RuntimeError("accès plateforme absents : " + ", ".join(absents))
    return {n: os.environ[n].rstrip("/") if n.endswith("URL") else os.environ[n]
            for n in noms}


def _requete(url: str, donnees: Optional[bytes], entetes: dict,
             methode: str = "GET") -> Tuple[int, bytes]:
    req = request.Request(url, data=donnees, headers=entetes, method=methode)
    try:
        with request.urlopen(req, timeout=60) as reponse:
            return reponse.status, reponse.read()
    except error.HTTPError as err:
        return err.code, err.read()


def se_connecter(cfg: dict) -> dict:
    statut, corps = _requete(
        f"{cfg['PUBLIE_SUPABASE_URL']}/auth/v1/token?grant_type=password",
        json.dumps({"email": cfg["PUBLIE_EMAIL"],
                    "password": cfg["PUBLIE_PASSWORD"]}).encode(),
        {"apikey": cfg["PUBLIE_SUPABASE_ANON_KEY"],
         "Content-Type": "application/json"}, "POST")
    if statut != 200:
        raise RuntimeError(f"login refusé ({statut})")
    jeton = json.loads(corps)["access_token"]
    return {"apikey": cfg["PUBLIE_SUPABASE_ANON_KEY"],
            "Authorization": f"Bearer {jeton}"}


def _lire(cfg: dict, entetes: dict, table: str, filtres: Dict[str, str],
          select: str) -> List[dict]:
    q = parse.urlencode({"select": select, **filtres})
    statut, corps = _requete(
        f"{cfg['PUBLIE_SUPABASE_URL']}/rest/v1/{table}?{q}", None, entetes)
    if statut != 200:
        raise RuntimeError(f"lecture {table} refusée ({statut}) : "
                           f"{corps[:200].decode(errors='replace')}")
    return json.loads(corps)


# ---------------------------------------------------------------------------
# La grammaire de correction, reprise d'aloa-production
# ---------------------------------------------------------------------------

def consigne_normalisee(payload: dict) -> Optional[str]:
    corr = (payload or {}).get("corr") or {}
    verbe = corr.get("verbe")
    quoi = (corr.get("quoi") or "").strip()
    ou = (corr.get("ou") or "").strip()
    if verbe not in ("Add", "Remove", "Replace", "Change") or not quoi:
        deja = (payload or {}).get("correction", "").strip()
        return deja or None
    liaison = {"Add": " ", "Remove": " ", "Replace": " with ", "Change": " to "}
    phrase = verbe + " " + quoi + (liaison[verbe] + ou if ou else "")
    return "CORRECTIONS, apply strictly: " + " ".join(phrase.split()).rstrip(". ") + "."


def cas_de_reprise(retour: dict) -> str:
    """Cas A (visuel) ou cas B (copy) : une proposition, que la session peut
    requalifier en rédigeant la consigne. Les mots qui visent le texte font
    pencher vers B, tout le reste est A.

    Les marqueurs se cherchent en MOTS ENTIERS : « fauteuils » contient
    « faute », et ce faux positif a réellement classé en B un retour qui
    parlait des fauteuils du studio (mesuré le 17/09)."""
    import re

    texte = " ".join([str(retour.get("commentaire") or ""),
                      json.dumps(retour.get("payload") or {}, ensure_ascii=False)]).lower()
    marqueurs_copy = ("textes?", "titres?", "copy", "fautes?", "orthographe",
                      "accroches?", "wording", "phrases?", "mots?")
    motif = r"\b(" + "|".join(marqueurs_copy) + r")\b"
    return "B" if re.search(motif, texte) else "A"


# ---------------------------------------------------------------------------
# La descente
# ---------------------------------------------------------------------------

def descendre(ardoise: str, client: str, tout: bool) -> int:
    commande = Commande.charger(ardoise)
    dossier_retours = commande.dossier / "retours"
    dossier_retours.mkdir(exist_ok=True)
    chemin_index = dossier_retours / "index.json"
    index = json.loads(chemin_index.read_text()) if chemin_index.exists() else {}

    cfg = _config()
    entetes = se_connecter(cfg)

    clients = _lire(cfg, entetes, "clients", {"slug": f"eq.{client}"}, "id,slug,nom")
    if not clients:
        print(f"Client « {client} » invisible pour ce compte : vérifier le slug "
              f"et le rattachement (memberships).", file=sys.stderr)
        return 1
    client_id = clients[0]["id"]

    # Le lien visuel_id (uuid plateforme) -> créa locale passe par le code,
    # que notre manifest de publication porte : on le résout par l'API.
    visuels = _lire(cfg, entetes, "visuels",
                    {"client_id": f"eq.{client_id}"}, "id,code,campagne_id")
    par_visuel_id: Dict[str, str] = {}
    manifest = _dernier_manifest(commande)
    code_vers_crea = {v["code"]: v["id"] for v in (manifest or {}).get("visuels", [])}
    for v in visuels:
        if v["code"] in code_vers_crea:
            par_visuel_id[v["id"]] = code_vers_crea[v["code"]]

    filtres = {"client_id": f"eq.{client_id}", "order": "cree_le.asc"}
    if not tout:
        filtres["statut"] = "eq.nouveau"
    retours = _lire(cfg, entetes, "retours", filtres,
                    "id,type,visuel_id,version_id,poste,commentaire,payload,"
                    "statut,auteur_email,cree_le")

    nouveaux = 0
    for retour in retours:
        if retour["id"] in index:
            continue
        crea = par_visuel_id.get(retour.get("visuel_id") or "")
        cas = cas_de_reprise(retour)
        consigne = consigne_normalisee(retour.get("payload") or {})
        fiche = {
            **retour,
            "crea": crea,
            "cas_propose": cas,
            "consigne_normalisee": consigne,
            "descendu_le": datetime.now(timezone.utc).isoformat(),
        }
        (dossier_retours / f"{retour['id']}.json").write_text(
            json.dumps(fiche, ensure_ascii=False, indent=1), encoding="utf-8")

        if crea:
            horodatage = datetime.now().strftime("%Y%m%dT%H%M%S")
            reprise = commande.dossier / "reprises" / crea / horodatage
            reprise.mkdir(parents=True, exist_ok=True)
            (reprise / "consigne.md").write_text(_consigne_md(
                crea, cas, consigne, retour), encoding="utf-8")
            print(f"  {crea}  cas {cas}  retour {retour['id'][:8]}  "
                  f"-> reprises/{crea}/{horodatage}/")
        else:
            print(f"  (sans visuel)  retour {retour['id'][:8]} rangé, "
                  f"type {retour.get('type')}")

        index[retour["id"]] = {"crea": crea, "descendu_le": fiche["descendu_le"]}
        nouveaux += 1

    chemin_index.write_text(json.dumps(index, ensure_ascii=False, indent=1))
    print(f"{nouveaux} retour(s) descendu(s), {len(retours) - nouveaux} déjà connus.")
    return 0


def _dernier_manifest(commande) -> Optional[dict]:
    dossiers = sorted((commande.dossier / "publication").glob("*/campagne.json"))
    if not dossiers:
        return None
    return json.loads(dossiers[-1].read_text())


def _consigne_md(crea: str, cas: str, consigne: Optional[str], retour: dict) -> str:
    commentaire = (retour.get("commentaire") or "").strip() or "(aucun commentaire libre)"
    lignes = [
        f"# Reprise {crea}, cas {cas} (proposé)",
        "",
        f"Retour plateforme `{retour['id']}` du {retour.get('cree_le', '?')}, "
        f"par {retour.get('auteur_email') or 'auteur inconnu'}.",
        "",
        "## Commentaire",
        "",
        commentaire,
        "",
        "## Consigne",
        "",
        consigne or ("À RÉDIGER par la session avant toute génération, dans la "
                     "grammaire : CORRECTIONS, apply strictly: "
                     "Add|Remove|Replace|Change ..."),
        "",
        "## Règles du cas",
        "",
        ("Cas A : la copy est bonne, elle ne change pas d'un caractère. La scène "
         "se corrige, le prompt se régénère, 2 crédits." if cas == "A" else
         "Cas B : la copy change, la scène reste identique. Le texte est peint "
         "dans l'image : la reprise coûte une génération, 2 crédits, il n'y a "
         "plus de recomposition gratuite."),
        "",
        "La reprise n'écrase rien : le nouveau master remplace l'ancien "
        "APRÈS validation, et ce dossier garde l'historique.",
    ]
    return "\n".join(lignes) + "\n"


def main() -> int:
    p = argparse.ArgumentParser(description="Descendre les retours de la plateforme")
    p.add_argument("ardoise")
    p.add_argument("--client", required=True, help="slug du client sur la plateforme")
    p.add_argument("--tout", action="store_true",
                   help="descendre aussi les retours déjà traités")
    a = p.parse_args()
    try:
        return descendre(a.ardoise, a.client, a.tout)
    except (RuntimeError, FileNotFoundError) as erreur:
        print(f"Erreur : {erreur}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
