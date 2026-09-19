#!/usr/bin/env python3
"""vue.py : la page de suivi d'une commande.

Une seule chose à faire, et elle doit être faite bien : mettre côte à côte le
visuel et le prompt qui l'a produit. C'est ce qui manque quand on lance des
générations en lot, et c'est ce qui permet de décider quoi corriger.

Ce n'est pas un tableau de bord. Pas de graphique, pas de compteur décoratif :
une ligne par créa, l'image à gauche, le prompt à droite, la commande de
relance en dessous, prête à copier.

La page est autonome : elle s'ouvre au double clic, sans serveur.

Usage : python3 vue.py --marque "Aloa Design"
"""
from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path
from typing import List

from etat import Commande, Crea


def _credits(creas: List[Crea]) -> str:
    """Le coût du lot, tiré de la table mesurée et non d'un chiffre écrit ici.

    L'ancienne version comptait deux crédits par créa en dur. Le nombre tombait
    juste sur Nano Banana Pro et serait faux sur n'importe quel autre modèle,
    dont les tarifs vont de 1 à 7. On lit donc la table, qui se corrige elle
    même sur les relevés de transactions.
    """
    import couts
    bilan = couts.devis([{"modele": c.prompt.modele,
                          "references": len(c.prompt.references or [])} for c in creas])
    return f"{bilan['total']:g}" if bilan["complet"] else f"{bilan['total']:g}+"


def _bloc_crea(commande: Commande, crea: Crea) -> str:
    # L'angle est le libellé écrit par le skill de Kreative, affiché tel quel.
    # Il passait avant par notre répertoire d'archétypes, qui a été sorti de la
    # chaîne : la page montrait un vocabulaire qui n'était pas le sien.
    classe_visuel = "visuel"
    if crea.master and (commande.dossier / crea.master).exists():
        visuel = f'<img src="{html.escape(crea.master)}" loading="lazy" alt="{crea.identifiant}">'
    elif crea.prompt.scene:
        # Avant génération, cet emplacement affichait « pas encore généré », donc
        # du vide. Or c'est exactement là qu'il faut montrer la MATIERE RETENUE :
        # avant de dépenser des crédits, ce qu'on doit pouvoir juger d'un coup
        # d'oeil, c'est quels assets réels du client entrent dans quelle créa.
        # Un chemin qui ne résout pas se voit ici, pas à la génération.
        vignettes = []
        for chemin in (crea.prompt.references or []):
            existe = (commande.dossier / chemin).exists()
            if existe:
                vignettes.append(f'<img src="{html.escape(chemin)}" loading="lazy" '
                                 f'title="{html.escape(chemin)}" alt="">')
            else:
                vignettes.append(f'<span class="absent" title="{html.escape(chemin)}">'
                                 f'asset introuvable</span>')
        if vignettes:
            # Le prix vient de la table mesuree, jamais d'un chiffre ecrit ici :
            # la legende annoncait 4 credits pour une image vers image, tarif
            # que le releve de transactions du 17/09 a démenti.
            import couts
            prix = couts.prix(crea.prompt.modele, references=len(vignettes))
            chiffre = f"{prix:g} crédits" if prix is not None else "coût non mesuré"
            visuel = (f'<div class="matiere"><div class="grille">{"".join(vignettes)}</div>'
                      f'<span class="legende">{len(vignettes)} asset(s) en référence, '
                      f'{chiffre}</span></div>')
        else:
            import couts
            prix = couts.prix(crea.prompt.modele)
            chiffre = f"{prix:g} crédits" if prix is not None else "coût non mesuré"
            visuel = ('<div class="vide">aucun asset<br><span>scène générée de zéro, '
                      f'{chiffre}</span></div>')
    else:
        visuel = ('<div class="vide compose">pas de prompt<br>'
                  '<span>le plan du skill n\'a rien écrit pour cette créa</span></div>')
        classe_visuel = "visuel plat"

    if crea.prompt.scene:
        corps_prompt = f'<pre class="prompt">{html.escape(crea.prompt.rendu())}</pre>'
        relance = (f'<code class="cmd">python3 kreative.py prompt '
                   f'{html.escape(commande.donnees["ardoise"])} {crea.identifiant} --editer</code>'
                   f'<code class="cmd">python3 kreative.py generer '
                   f'{html.escape(commande.donnees["ardoise"])} --crea {crea.identifiant}</code>')
    else:
        corps_prompt = ('<p class="sans">Aucun prompt pour cette créa : le plan produit par '
                        'le skill ne la couvre pas.</p>')
        relance = ""

    alerte = ""
    if "[A COMPLETER:" in crea.copy.accroche + crea.copy.sous_accroche:
        alerte = '<div class="alerte">Brief incomplet : cette créa contient un marqueur à compléter.</div>'

    return f"""<article id="{crea.identifiant}">
 <div class="{classe_visuel}">{visuel}</div>
 <div class="fiche">
  <header>
    <b>{crea.identifiant}</b>
    <span class="etat e-{html.escape(crea.etat)}">{html.escape(crea.etat)}</span>
    <span class="fab {'gen' if crea.prompt.scene else 'comp'}">
      {'génération' if crea.prompt.scene else 'sans prompt'}</span>
    {f'<span class="tours">{crea.tours} reprise(s)</span>' if crea.tours else ''}
  </header>
  {alerte}
  <div class="c"><span class="k">angle</span><span class="v">{html.escape(crea.angle)}</span></div>
  <div class="c"><span class="k">accroche</span><span class="v">{html.escape(crea.copy.accroche)}</span></div>
  <div class="c"><span class="k">sous-accroche</span><span class="v">{html.escape(crea.copy.sous_accroche)}</span></div>
  <div class="c"><span class="k">prompt</span><span class="v">{corps_prompt}{relance}</span></div>
 </div></article>"""


def _ratio(commande: Commande, creas: List[Crea]) -> str:
    """Le format d'affichage, lu sur un master reel plutot que suppose."""
    for crea in creas:
        if crea.master and (commande.dossier / crea.master).exists():
            try:
                from PIL import Image
                l, h = Image.open(commande.dossier / crea.master).size
                return f"{l}/{h}"
            except Exception:
                break
    return "1/1"


def construire(commande: Commande) -> str:
    creas = commande.creas()
    d = commande.donnees
    a_generer = [x for x in creas if x.prompt.scene]
    generes = [x for x in a_generer if x.master]
    ratio = _ratio(commande, creas)

    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(d['marque'])}, suivi de production</title><style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0f0e0d;color:#eae7e2;padding:28px 34px 70px;
 font:13px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}}
h1{{font-size:19px;font-weight:650;letter-spacing:-.02em}}
.sous{{color:#8b857c;margin:6px 0 8px}}
.jauge{{display:flex;gap:18px;margin:14px 0 26px;padding-bottom:20px;
 border-bottom:1px solid #241f1b;flex-wrap:wrap}}
.jauge div{{font-size:12px;color:#8b857c}}
.jauge b{{display:block;font-size:22px;color:#eae7e2;font-weight:650}}
article{{display:grid;grid-template-columns:420px 1fr;gap:26px;padding:20px 0;
 border-bottom:1px solid #1c1917;align-items:start}}
/* Le cadre suit le format du master, qui est passe en 1:1 le 17/09. Un
   emplacement fige en 9:16 affichait les carres en timbre-poste au milieu
   d'une page de dix-huit entrees : on ne voyait plus ce qu'on avait produit. */
.visuel{{background:#000;border:1px solid #2a2521;border-radius:8px;overflow:hidden;
 position:sticky;top:14px;aspect-ratio:{ratio};display:flex;align-items:center;justify-content:center}}
.visuel img{{width:100%;display:block}}
.vide{{color:#5a534b;font-size:12px;text-align:center;padding:14px}}
.matiere{{width:100%;height:100%;display:flex;flex-direction:column;
 justify-content:center;gap:8px;padding:10px}}
.matiere .grille{{display:grid;gap:5px;
 grid-template-columns:repeat(auto-fit,minmax(58px,1fr))}}
.matiere img{{width:100%;aspect-ratio:1;object-fit:cover;border-radius:5px;
 background:#1c1917;display:block}}
.matiere .absent{{display:flex;align-items:center;justify-content:center;
 aspect-ratio:1;border:1px dashed #6b3a32;border-radius:5px;color:#c4685c;
 font-size:9px;text-align:center;padding:4px}}
.matiere .legende{{color:#5a534b;font-size:10.5px;text-align:center}}
.visuel.plat{{aspect-ratio:auto;min-height:0;padding:20px 12px;background:#131110}}
.vide.compose{{color:#4e7f5e}}
.vide span{{color:#3d3831;font-size:11px}}
header{{display:flex;gap:9px;align-items:center;flex-wrap:wrap;margin-bottom:10px}}
header b{{font-family:ui-monospace,Menlo,monospace;color:#f2b47a;font-size:14px}}
.etat,.fab,.tours{{font-size:10.5px;padding:2px 7px;border-radius:4px;
 text-transform:uppercase;letter-spacing:.05em}}
.etat{{background:#241f1b;color:#a29a90}}
.e-master_ok{{background:#17301f;color:#7ee0a0}}
.e-composee{{background:#17301f;color:#7ee0a0}}
.fab.gen{{background:#31240f;color:#f0b45f}}
.fab.comp{{background:#14241a;color:#6fc98d}}
.tours{{background:#2d1a1a;color:#e28b7a}}
.alerte{{background:#2d1a1a;color:#e2604f;padding:7px 10px;border-radius:5px;
 font-size:12px;margin-bottom:10px}}
.c{{display:grid;grid-template-columns:120px 1fr;gap:14px;padding:6px 0;
 border-bottom:1px solid #191614}}
.c:last-child{{border:none}}
.k{{color:#8b857c;font-size:11px;text-transform:uppercase;letter-spacing:.05em}}
.v{{color:#d6d0c8}}
.prompt{{background:#191614;border:1px solid #241f1b;border-radius:6px;padding:11px 13px;
 font:11.5px/1.65 ui-monospace,Menlo,monospace;color:#c8bfae;white-space:pre-wrap;
 max-height:230px;overflow:auto}}
.sans{{color:#6fc98d;font-size:12px}}
.cmd{{display:block;margin-top:7px;font:11px/1.6 ui-monospace,Menlo,monospace;
 color:#8b857c;background:#141210;border:1px solid #241f1b;border-radius:5px;
 padding:5px 9px;user-select:all}}
@media(max-width:820px){{article{{grid-template-columns:1fr}}.visuel{{position:static;aspect-ratio:auto}}body{{padding:18px}}}}
</style></head><body>
<h1>{html.escape(d['marque'])}</h1>
<div class="sous">pack {html.escape(d['pack'])} &middot;
 {d['quantite_vendue']} vendues, {d['quantite_generee']} produites &middot;
 verticale {html.escape(str(d.get('verticale', 'non définie')))}</div>
<div class="jauge">
 <div><b>{len(creas)}</b>créas au plan</div>
 <div><b>{len(creas) - len(a_generer)}</b>composées, 0 crédit</div>
 <div><b>{len(generes)}/{len(a_generer)}</b>générées</div>
 <div><b>{_credits(a_generer)}</b>crédits au total</div>
</div>
{"".join(_bloc_crea(commande, x) for x in creas)}
</body></html>"""


def ecrire(commande: Commande) -> Path:
    chemin = commande.dossier / "suivi.html"
    chemin.write_text(construire(commande), encoding="utf-8")
    return chemin


def main() -> int:
    parseur = argparse.ArgumentParser(description="Page de suivi d'une commande")
    parseur.add_argument("--marque", required=True)
    arguments = parseur.parse_args()
    try:
        print(ecrire(Commande.charger(arguments.marque)))
    except FileNotFoundError as erreur:
        print(f"Erreur : {erreur}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
