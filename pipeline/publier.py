#!/usr/bin/env python3
"""publier.py : pousse un pack validé vers la plateforme de revue.

    python3 pipeline/publier.py <ardoise> --client <slug> --dry-run
    python3 pipeline/publier.py <ardoise> --client <slug>

Le protocole est celui de la fonction `publish-campagne` de la plateforme
(schéma `aloa-campagne/1`) : login, `prepare`, PUT des fichiers sur les URLs
signées, `finalize`. Ce script est autonome : Python et Pillow, aucun npm.

Deux décisions de conception, à connaître avant de modifier :

**Le master au texte peint part comme fond ET comme aperçu.** Le schéma est né
pour la composition en CSS et son invariant dit « le fond est la scène sans
texte ». La chaîne Kreative peint le texte dans l'image (décision du 17/09) et
la revue de la plateforme affiche `apercu || fond` sans jamais recomposer les
textes par-dessus (Validation.jsx) : le master cuit est donc la pièce dans les
deux rôles, et les champs `textes` portent la copy en clair pour la recherche
et les commentaires. Si un jour la plateforme recompose les fonds, ce choix
est à revoir ICI, pas en silence là-bas.

**Jamais une donnée personnelle.** Le manifest porte l'ardoise, la marque, la
copy et les visuels. Le nom, l'adresse, le téléphone ou le mail du client
final restent dans `brief/` sur le poste : un contrôle final refuse l'envoi
si une valeur de contact du brief se retrouve dans le manifest sérialisé.

Accès, dans l'environnement du shell (mêmes noms que l'outillage Conexia) :
    PUBLIE_SITE                l'URL du portail (https://....netlify.app)
    PUBLIE_SUPABASE_URL        l'URL du projet Supabase
    PUBLIE_SUPABASE_ANON_KEY   la clé publique anon, jamais service_role
    PUBLIE_EMAIL / PUBLIE_PASSWORD   le compte qui publie
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib import error, request

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "pipeline"))

from etat import Commande  # noqa: E402

GENERATEUR = "kreative-production/publier.py 1.0"
COTE = 1080          # le format d'affichage de la plateforme, pas celui du master
QUALITE_APERCU = 82

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,60}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
BALISE_HTML_RE = re.compile(r"<[a-zA-Z!/]")

REGISTRE = "claim"   # un master fini revendique, il ne hiérarchise rien
THEME = "master"     # l'unique thème du pack : le layout ne pilote aucun rendu ici


# ---------------------------------------------------------------------------
# Construction du manifest
# ---------------------------------------------------------------------------

def _slug(texte: str) -> str:
    plat = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()
    plat = re.sub(r"[^a-z0-9]+", "-", plat.lower()).strip("-")
    return plat or "x"


def _univers(creas) -> Tuple[List[dict], Dict[str, str]]:
    """Les angles du pack deviennent les univers de la plateforme.

    L'angle est le libellé écrit par le skill de Kreative, en clair : « Le
    lieu qu'on ne trouve pas ». Il était auparavant découpé sur une barre
    oblique, parce que notre planificateur écrivait « ressort/archétype ». Ce
    planificateur est sorti de la chaîne le 18/09, et découper le libellé du
    skill sur un caractère qu'il n'emploie pas rendait le libellé entier.

    Contrainte du schéma : la PREMIÈRE lettre de chaque clé d'univers fabrique
    les codes visuels (V1, O2...), donc les initiales doivent être uniques.
    Deux angles peuvent commencer par la même lettre : on choisit pour chacun
    une lettre encore libre, prise dans ses mots, sinon la première libre de
    l'alphabet, et la clé d'univers est reconstruite derrière cette lettre.
    """
    ressorts: List[str] = []
    for crea in creas:
        ressort = _slug(crea.angle or "") or "pack"
        if ressort not in ressorts:
            ressorts.append(ressort)

    prises: set = set()
    cles: Dict[str, str] = {}
    for ressort in ressorts:
        candidates = [m[0] for m in ressort.split("-") if m] + \
                     [c for c in "abcdefghijklmnopqrstuvwxyz"]
        lettre = next(l for l in candidates if l not in prises)
        prises.add(lettre)
        corps = _slug(ressort)[:18].strip("-")
        cle = lettre + "-" + corps if not corps.startswith(lettre) else corps
        cles[ressort] = cle[:22].rstrip("-")

    univers = [{"cle": cles[r], "nom": r.replace("-", " "), "ordre": i + 1}
               for i, r in enumerate(ressorts)]
    return univers, cles


def _textes(crea) -> dict:
    textes = {"head": crea.copy.accroche.strip()}
    if crea.copy.sous_accroche.strip():
        textes["sub"] = crea.copy.sous_accroche.strip()
    if crea.copy.cta.strip():
        textes["sc"] = crea.copy.cta.strip()
    return textes


def _accent(commande) -> str:
    plan = commande.donnees.get("plan", {}) or {}
    for candidat in (plan.get("accent"),
                     (commande.donnees.get("charte") or {}).get("accent")):
        if candidat and HEX_RE.match(str(candidat)):
            return candidat
    return "#8B2FD6"


def construire(commande, creas, client: str,
               remplacements: Optional[Dict[str, Dict[str, str]]] = None,
               rangs_pris: Optional[Dict[str, int]] = None) -> dict:
    """`remplacements` : {identifiant local: {"id": nouvel id, "remplace": id
    distant remplacé}}. C'est la doctrine du schéma pour un visuel REPRIS : un
    fond différent est un AUTRE visuel, qui porte `remplace: <id actif>` au
    lieu de réécrire l'ancien (le serveur répond 409 sinon, et c'est voulu).
    Le remplacé est l'ACTIF distant, pas forcément l'identifiant local : après
    une première reprise, c04 actif s'appelle c04-b, et son remplaçant
    c04-b-b (mesuré le 18/09, republication du pack v3).

    `rangs_pris` : {lettre d'univers: plus haut rang de code déjà publié}. Le
    serveur exige pour chaque remplaçant un code jamais publié, et le compteur
    local ne connaît pas les rangs consommés par les reprises passées : ils se
    lisent en base au moment du conflit (voir _etat_distant)."""
    remplacements = remplacements or {}
    rangs_pris = rangs_pris or {}
    univers, cles = _univers(creas)
    compteur: Dict[str, int] = {}
    codes_figes: set = set()
    visuels = []
    for crea in creas:
        ressort = _slug(crea.angle or "") or "pack"
        cle = cles[ressort]
        lettre = cle[0].upper()
        compteur[lettre] = compteur.get(lettre, 0) + 1
        execution = (crea.angle or "").strip() or crea.identifiant
        reprise = remplacements.get(crea.identifiant)
        identifiant = reprise["id"] if reprise else crea.identifiant
        visuel_remplace = (reprise or {}).get("remplace")
        code_force = (reprise or {}).get("code")
        if code_force:
            codes_figes.add(identifiant)
        visuels.append({
            "id": identifiant,
            **({"remplace": visuel_remplace} if visuel_remplace else {}),
            "code": code_force or f"{lettre}{compteur[lettre]}",
            "univers": cle,
            "label": execution or crea.identifiant,
            "format": {"w": COTE, "h": COTE, "ratio": "1:1"},
            "fond": {"src": f"img/{identifiant}.png", "sha256": ""},
            "apercu": {"src": f"out/{identifiant}.jpg"},
            "layout": {"theme": THEME, "reg": REGISTRE, "pos": "bl",
                       "inset": None, "hs": 64, "accent": _accent(commande)},
            "textes": _textes(crea),
        })

    # Le serveur juge les conflits PAR CODE : un remplaçant est un AUTRE
    # visuel et doit porter un code encore jamais publié. Il prend donc un
    # rang AU-DELÀ de tous ceux de sa lettre (O1, O2 pris : le remplaçant de
    # O2 devient O3), en comptant AUSSI les rangs déjà publiés en base
    # (`rangs_pris`), que le compteur local ne voit pas.
    for lettre_v, rang in rangs_pris.items():
        compteur[lettre_v] = max(compteur.get(lettre_v, 0), rang)
    for v in visuels:
        if v.get("remplace") and v["id"] not in codes_figes:
            lettre_v = v["code"][0]
            compteur[lettre_v] = compteur.get(lettre_v, 0) + 1
            v["code"] = f"{lettre_v}{compteur[lettre_v]}"

    marque = commande.donnees.get("marque", commande.donnees.get("ardoise", ""))
    pack = commande.donnees.get("pack", "pack")
    mois = datetime.now(timezone.utc).strftime("%Y-%m")
    return {
        "schema": "aloa-campagne/1",
        "genere_le": datetime.now(timezone.utc).isoformat(),
        "generateur": GENERATEUR,
        "campagne": {
            "slug": f"{commande.donnees.get('ardoise', _slug(marque))}-{mois}",
            "client": client,
            "marque": marque,
            "modele": f"pack {pack}",
            "titre": (f"{marque}, pack {pack}, {len(visuels)} créative"
                      + ("s" if len(visuels) > 1 else "")),
            "date_campagne": mois,
            "secteur": "autre",
            "charte": {
                "accent": _accent(commande),
                "fonts": [{"role": "head", "famille": "Archivo"},
                          {"role": "body", "famille": "IBM Plex Sans"}],
                "themes": [THEME],
            },
        },
        "univers": univers,
        "visuels": visuels,
    }


def preparer_fichiers(commande, creas, manifest: dict) -> Path:
    """Écrit le dossier campagne : les pièces aux dimensions de la plateforme.

    Le master 2048 reste la source dans `masters/` ; la plateforme reçoit la
    pièce d'affichage en 1080. Le sha256 du manifest se calcule sur le fichier
    réellement envoyé, jamais sur le master.
    """
    from PIL import Image

    dossier = commande.dossier / "publication" / manifest["campagne"]["slug"]
    if dossier.exists():
        shutil.rmtree(dossier)
    (dossier / "img").mkdir(parents=True)
    (dossier / "out").mkdir(parents=True)

    # L'identifiant local d'un remplaçant se retrouve en pelant ses suffixes
    # de reprise : c04-b-b vient du master c04.
    par_source = {re.sub(r"(-b)+$", "", v["id"]): v for v in manifest["visuels"]}
    for crea in creas:
        visuel = par_source[crea.identifiant]
        master = commande.dossier / "masters" / f"{crea.identifiant}.png"
        image = Image.open(master).convert("RGB")
        reduite = image.resize((COTE, COTE), Image.LANCZOS)

        chemin_fond = dossier / visuel["fond"]["src"]
        reduite.save(chemin_fond, "PNG")
        visuel["fond"]["sha256"] = hashlib.sha256(
            chemin_fond.read_bytes()).hexdigest()

        reduite.save(dossier / visuel["apercu"]["src"], "JPEG",
                     quality=QUALITE_APERCU)

    (dossier / "campagne.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return dossier


# ---------------------------------------------------------------------------
# Validation locale : refuser AVANT d'envoyer
# ---------------------------------------------------------------------------

def valider(manifest: dict, commande) -> List[str]:
    fautes = []
    c = manifest["campagne"]
    if not SLUG_RE.match(c["slug"]):
        fautes.append(f"slug invalide : {c['slug']}")
    if not SLUG_RE.match(c["client"]):
        fautes.append(f"client invalide : {c['client']}")

    initiales = [u["cle"][0] for u in manifest["univers"]]
    if len(initiales) != len(set(initiales)):
        fautes.append("collision d'initiales entre univers")

    codes, ids = set(), set()
    for v in manifest["visuels"]:
        ou = v["id"]
        if not ID_RE.match(v["id"]) or v["id"] in ids:
            fautes.append(f"{ou} : id invalide ou en double")
        ids.add(v["id"])
        if v["code"] in codes:
            fautes.append(f"{ou} : code {v['code']} en double")
        codes.add(v["code"])
        if not re.match(r"^[0-9a-f]{64}$", v["fond"]["sha256"]):
            fautes.append(f"{ou} : sha256 manquant")
        if not v["textes"].get("head", "").strip():
            fautes.append(f"{ou} : head vide")
        for champ, texte in v["textes"].items():
            if BALISE_HTML_RE.search(texte) or chr(0x2014) in texte:
                fautes.append(f"{ou} : {champ} porte une balise ou un tiret cadratin")

    # Aucune donnée personnelle du brief ne doit fuir dans le manifest.
    serialise = json.dumps(manifest, ensure_ascii=False).lower()
    brief = (commande.donnees.get("brief") or {})
    for cle in ("email", "mail", "telephone", "phone", "contact", "nom_contact"):
        valeur = str(brief.get(cle) or "").strip().lower()
        if len(valeur) >= 6 and valeur in serialise:
            fautes.append(f"donnée personnelle du brief ({cle}) présente dans le manifest")
    return fautes


# ---------------------------------------------------------------------------
# Le protocole réseau
# ---------------------------------------------------------------------------

def _requete(url: str, donnees: Optional[bytes], entetes: dict,
             methode: str = "POST") -> Tuple[int, bytes]:
    req = request.Request(url, data=donnees, headers=entetes, method=methode)
    try:
        with request.urlopen(req, timeout=120) as reponse:
            return reponse.status, reponse.read()
    except error.HTTPError as err:
        return err.code, err.read()


def _config() -> dict:
    noms = ("PUBLIE_SITE", "PUBLIE_SUPABASE_URL", "PUBLIE_SUPABASE_ANON_KEY",
            "PUBLIE_EMAIL", "PUBLIE_PASSWORD")
    absents = [n for n in noms if not os.environ.get(n)]
    if absents:
        raise RuntimeError(
            "ÉTAPE OPTIONNELLE NON CONFIGURÉE, à sauter sans conséquence : "
            "la plateforme de revue n'est pas branchée sur ce poste ("
            + ", ".join(absents) + " absents de l'environnement). La livraison "
            "du pack est déjà complète sans elle : livrer.py a fait le dossier "
            "et la notification. Ne configurer ces accès que si Kreative "
            "utilise le portail de revue (voir installation.md), jamais en "
            "clair ailleurs que dans le .env.")
    return {n: os.environ[n].rstrip("/") if n.endswith(("SITE", "URL"))
            else os.environ[n] for n in noms}


def se_connecter(cfg: dict) -> str:
    statut, corps = _requete(
        f"{cfg['PUBLIE_SUPABASE_URL']}/auth/v1/token?grant_type=password",
        json.dumps({"email": cfg["PUBLIE_EMAIL"],
                    "password": cfg["PUBLIE_PASSWORD"]}).encode(),
        {"apikey": cfg["PUBLIE_SUPABASE_ANON_KEY"],
         "Content-Type": "application/json"})
    if statut != 200:
        raise RuntimeError(f"login refusé ({statut}) : {corps[:300].decode(errors='replace')}")
    jeton = json.loads(corps).get("access_token")
    if not jeton:
        raise RuntimeError("login sans access_token")
    return jeton


def _etat_distant(cfg: dict, jeton: str, client: str) -> dict:
    """Les visuels déjà publiés pour ce client : par référence de manifest,
    leur code, leur sha de fond et leur statut, plus le plus haut rang de code
    par lettre d'univers. C'est la seule source de vérité pour nommer un
    remplaçant et lui donner un code jamais publié : le compteur local ignore
    les reprises passées, et un prepare serveur interrompu peut avoir laissé
    des visuels à moitié publiés (mesuré le 18/09 : trois remplaçants insérés
    sans leurs fichiers)."""
    entetes = {"apikey": cfg["PUBLIE_SUPABASE_ANON_KEY"],
               "Authorization": f"Bearer {jeton}"}
    statut, corps = _requete(
        f"{cfg['PUBLIE_SUPABASE_URL']}/rest/v1/clients?slug=eq.{client}&select=id",
        None, entetes, "GET")
    lignes = json.loads(corps) if statut == 200 else []
    if not lignes:
        return {"refs": {}, "rangs": {}}
    statut, corps = _requete(
        f"{cfg['PUBLIE_SUPABASE_URL']}/rest/v1/visuels"
        f"?client_id=eq.{lignes[0]['id']}"
        f"&select=ref_manifest,code,fond_sha256,statut",
        None, entetes, "GET")
    visuels = json.loads(corps) if statut == 200 else []
    rangs: Dict[str, int] = {}
    refs: Dict[str, dict] = {}
    for v in visuels:
        m = re.match(r"^([A-Z])(\d+)$", v.get("code") or "")
        if m:
            rangs[m.group(1)] = max(rangs.get(m.group(1), 0), int(m.group(2)))
        if v.get("ref_manifest"):
            refs[v["ref_manifest"]] = {"code": v["code"],
                                       "sha": v.get("fond_sha256"),
                                       "statut": v.get("statut")}
    return {"refs": refs, "rangs": rangs}


def _actif_famille(refs_distantes: Dict[str, dict], source: str) -> str:
    """Le dernier maillon de la chaîne de reprises d'un visuel : c04 remplacé
    par c04-b, lui-même remplacé par c04-b-b... L'actif est le plus suffixé."""
    actif = source
    while actif + "-b" in refs_distantes:
        actif += "-b"
    return actif


def publier(ardoise: str, client: str, dry_run: bool) -> int:
    commande = Commande.charger(ardoise)
    creas = [c for c in commande.creas()
             if c.etat == "master_ok"
             and (commande.dossier / "masters" / f"{c.identifiant}.png").exists()]
    if not creas:
        print("Aucune créa en master_ok avec son fichier : rien à publier.",
              file=sys.stderr)
        return 1

    manifest = construire(commande, creas, client)
    dossier = preparer_fichiers(commande, creas, manifest)
    fautes = valider(manifest, commande)
    if fautes:
        print("MANIFEST REFUSÉ localement :")
        for f in fautes:
            print("  -", f)
        return 1
    print(f"{len(creas)} visuel(s), manifest valide : {dossier / 'campagne.json'}")
    if dry_run:
        print("dry-run : rien n'est parti.")
        return 0

    cfg = _config()
    jeton = se_connecter(cfg)
    fonction = f"{cfg['PUBLIE_SITE']}/.netlify/functions/publish-campagne"
    auth = {"Authorization": f"Bearer {jeton}", "Content-Type": "application/json",
            "apikey": cfg["PUBLIE_SUPABASE_ANON_KEY"]}

    statut, corps = _requete(fonction, json.dumps(
        {"mode": "prepare", "campagne": manifest, "apercu_ext": "jpg"}).encode(), auth)
    if statut == 409:
        # Un fond a changé sur un code déjà publié : c'est la doctrine du
        # schéma, pas une erreur. Chaque visuel repris devient un nouvel id
        # (les suffixes s'enchaînent : -b, -b-b) qui `remplace` l'ACTIF
        # distant de sa famille, avec un code au-delà de tous les rangs déjà
        # publiés. L'un et l'autre se lisent en base : le compteur local ne
        # connaît pas les reprises passées (mesuré le 18/09, c04 déjà
        # remplacé par c04-b la veille).
        distant = _etat_distant(cfg, jeton, client)
        remplacements: Dict[str, Dict[str, str]] = {}
        sha_locaux = {re.sub(r"(-b)+$", "", v["id"]): v["fond"]["sha256"]
                      for v in manifest["visuels"]}
        for tentative in range(3):
            try:
                conflits = json.loads(corps).get("conflits", [])
            except json.JSONDecodeError:
                conflits = []
            ids = [c.get("id") for c in conflits if c.get("id")]
            if not ids:
                print(f"409 sans liste de conflits : "
                      f"{corps[:400].decode(errors='replace')}", file=sys.stderr)
                return 1
            for id_conflit in ids:
                source = re.sub(r"(-b)+$", "", id_conflit)
                actif = _actif_famille(distant["refs"], source)
                info = distant["refs"].get(actif) or {}
                if info.get("sha") == sha_locaux.get(source):
                    # Ce fond est DÉJÀ en base sous cette référence (prepare
                    # interrompu) : on adopte la ligne existante, même id et
                    # même code, et le serveur fera une mise à jour éditoriale
                    # en redonnant l'URL d'upload du fichier manquant.
                    remplacements[source] = {"id": actif, "code": info["code"]}
                else:
                    remplacements[source] = {"id": actif + "-b", "remplace": actif}
            print(f"reprise détectée sur {', '.join(ids)} : "
                  + ", ".join((f"{r['id']} (remplace {r['remplace']})"
                               if r.get("remplace")
                               else f"{r['id']} (adopté, code {r['code']})")
                              for r in remplacements.values()))
            manifest = construire(commande, creas, client, remplacements,
                                  rangs_pris=distant["rangs"])
            dossier = preparer_fichiers(commande, creas, manifest)
            fautes = valider(manifest, commande)
            if fautes:
                print("MANIFEST REFUSÉ localement après reprise : " + " ; ".join(fautes))
                return 1
            statut, corps = _requete(fonction, json.dumps(
                {"mode": "prepare", "campagne": manifest, "apercu_ext": "jpg"}).encode(),
                auth)
            if statut != 409:
                break
    if statut != 200:
        print(f"prepare refusé ({statut}) : {corps[:500].decode(errors='replace')}",
              file=sys.stderr)
        return 1
    prepare = json.loads(corps)
    print(f"campagne préparée : {prepare.get('campagne_id')}, "
          f"{len(prepare.get('uploads', []))} entrée(s) d'upload")

    par_code = {v["code"]: v for v in manifest["visuels"]}
    for entree in prepare.get("uploads", []):
        v = par_code.get(entree.get("code"))
        if not v:
            continue
        if entree.get("fond_url"):
            contenu = (dossier / v["fond"]["src"]).read_bytes()
            statut, corps = _requete(entree["fond_url"], contenu,
                                     {"Content-Type": "image/png"}, "PUT")
            if statut not in (200, 201):
                print(f"upload du fond {v['code']} refusé ({statut})", file=sys.stderr)
                return 1
            print(f"  + fond {v['code']} ({len(contenu) // 1024} Ko)")
        if entree.get("apercu_url"):
            contenu = (dossier / v["apercu"]["src"]).read_bytes()
            statut, corps = _requete(entree["apercu_url"], contenu,
                                     {"Content-Type": "image/jpeg"}, "PUT")
            if statut not in (200, 201):
                print(f"upload de l'aperçu {v['code']} refusé ({statut})", file=sys.stderr)
                return 1
            print(f"  + aperçu {v['code']} ({len(contenu) // 1024} Ko)")

    statut, corps = _requete(fonction, json.dumps(
        {"mode": "finalize", "campagne_id": prepare["campagne_id"]}).encode(), auth)
    if statut != 200:
        print(f"finalize refusé ({statut}) : {corps[:500].decode(errors='replace')}. "
              f"La campagne reste en préparation, relancer corrige.", file=sys.stderr)
        return 1

    rapport = {
        "campagne_id": prepare.get("campagne_id"),
        "slug": manifest["campagne"]["slug"],
        "publie_le": datetime.now(timezone.utc).isoformat(),
        "visuels": [v["id"] for v in manifest["visuels"]],
        "reponse_finalize": json.loads(corps or b"{}"),
    }
    chemin_rapport = dossier / "rapports" / (
        "publication-" + datetime.now().strftime("%Y%m%d-%H%M") + ".json")
    chemin_rapport.parent.mkdir(exist_ok=True)
    chemin_rapport.write_text(json.dumps(rapport, ensure_ascii=False, indent=1))
    print(f"publié. rapport : {chemin_rapport}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Publier un pack vers la plateforme de revue")
    p.add_argument("ardoise")
    p.add_argument("--client", required=True,
                   help="slug du client sur la plateforme (fourni par Conexia)")
    p.add_argument("--dry-run", action="store_true",
                   help="construire et valider sans rien envoyer")
    a = p.parse_args()
    try:
        return publier(a.ardoise, a.client, a.dry_run)
    except (RuntimeError, FileNotFoundError) as erreur:
        print(f"Erreur : {erreur}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
