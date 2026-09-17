#!/usr/bin/env python3
"""scraper.py : extrait d'un site client tout ce qui peut servir à une créa.

Point 4.1 du cahier des charges : analyser l'intégralité du site, en extraire
tous les assets exploitables, et comprendre la direction artistique composant par
composant, pas seulement une palette et une police.

    python3 pipeline/scraper.py aspirer <ardoise>
    python3 pipeline/scraper.py aspirer <ardoise> --pages 40
    python3 pipeline/scraper.py url https://exemple.fr --sortie /tmp/essai

Ce qui sort, dans `commandes/<ardoise>/marque/` :

- `assets-site/` : toutes les images du site, dédoublonnées par empreinte, avec
  `index.json` qui dit pour chacune sa page, sa taille, son texte alternatif et
  sa place dans la page (en-tête, héros, contenu, pied) ;
- `logo/` : les candidats logo, classés par score ;
- `captures/` : une capture par page, pour lire la DA à l'oeil ;
- `site.json` : les textes (titres, accroches, CTA, prix, témoignages, données
  structurées), page par page ;
- `charte-site.json` : couleurs, polices et composants, **mesurés sur les styles
  calculés par le navigateur**, pas devinés dans le HTML.

**Un navigateur, pas une requête HTTP.** La plupart des sites récents (Framer,
Webflow, Shopify) construisent la page en JavaScript : un simple téléchargement du
HTML rend une page vide, et une couleur déclarée dans une feuille n'est pas la
couleur affichée. On lit donc ce que Chromium affiche réellement.

**On mesure, on ne tranche pas.** La charte produite est une proposition classée
par fréquence d'usage, pas une décision. Et elle vient des styles de l'interface,
jamais des images : sur un site d'agence, les couleurs des réalisations clients ne
sont pas la charte de l'agence (règle 4 du skill).

**On échoue bruyamment.** Un site derrière un mot de passe ou une page de parking
rendrait une charte parfaitement plausible et fausse. Ces cas lèvent une erreur au
lieu de produire. Cinq contrôles sur la page d'accueil : statut HTTP, titre de page
de garde, champ de mot de passe, nombre d'éléments, volume de texte. Ils viennent
de l'ancien `pipeline/intake.py`, que ce module remplace : intake enveloppait
`brand_intake.py` du pack aloa, dépendance que la décision du 11/09 interdit.

Cible Python 3.9+. Dépendance : playwright, avec Chromium installé. Aucune
dépendance à aloa.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.parse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "pipeline"))

PAGES_MAX_DEFAUT = 25
IMAGE_COTE_MIN = 80            # en dessous : icônes d'interface, pixels de suivi
CAPTURE_HAUTEUR_MAX = 9000     # une page infinie ne doit pas produire un PNG de 80 Mo
DELAI_PAGE_MS = 45000
AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

EXTENSIONS_IGNOREES = (".pdf", ".zip", ".mp4", ".mov", ".webm", ".mp3", ".doc", ".docx",
                       ".xls", ".xlsx", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico")
# Pages sans matière pour une créa. Mesuré sur les Bains de Dax : sans ce filtre,
# 5 pages sur 12 partaient sur les cookies, les mentions légales, la
# confidentialité, le recrutement et un remerciement, et le capital social des
# mentions légales ressortait comme un « prix » à 10 059 500 €.
SEGMENTS_IGNORES = ("/cart", "/panier", "/checkout", "/account", "/compte", "/login",
                    "/connexion", "/wp-admin", "/wp-json", "/feed", "/tag/", "/author/",
                    "mentions", "legal", "cookie", "confidentialite", "privacy", "cgv",
                    "cgu", "conditions-generales", "terms", "rgpd", "gdpr", "recrutement",
                    "carriere", "careers", "jobs", "merci", "thank", "confirmation",
                    "plan-du-site", "sitemap", "404")

# Segments d'espace client qui ne se déclinent jamais : mot entier exigé, sinon
# « compte » attrape « comptes-clients » et « panier » attrape « paniers-garnis ».
MOTS_ENTIERS = {"compte", "account", "panier", "checkout", "connexion", "author"}

MOTIFS_PAGE_DE_GARDE = [
    r"enter password", r"password protected", r"mot de passe", r"coming soon",
    r"en construction", r"bient[oô]t disponible", r"domain (is )?for sale",
    r"this domain", r"parked", r"under construction", r"maintenance mode",
    # Repris de l'ancien `intake.py`, qui portait ces quatre motifs en plus.
    r"site en maintenance", r"restricted", r"connexion requise", r"log ?in required",
]

# Seuils du garde-fou, mesures d'une page reelle. Une page de garde Framer ou
# Webflow tient sous les trois.
NOEUDS_MINIMUM = 60      # elements du DOM
TEXTE_MINIMUM = 400      # caracteres de texte visible


class SiteInexploitable(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Adresses
# ---------------------------------------------------------------------------

def normaliser_url(brute: str) -> str:
    """« www.exemple.fr » et « exemple.fr/ » deviennent « https://www.exemple.fr/ »."""
    brute = (brute or "").strip()
    if not brute:
        raise SiteInexploitable("aucune URL fournie")
    if not re.match(r"^https?://", brute, re.I):
        brute = "https://" + brute
    decoupe = urllib.parse.urlsplit(brute)
    chemin = decoupe.path or "/"
    return urllib.parse.urlunsplit((decoupe.scheme.lower(), decoupe.netloc.lower(), chemin, decoupe.query, ""))


def _hote_racine(hote: str) -> str:
    return hote.lower().removeprefix("www.") if hasattr(str, "removeprefix") else re.sub(r"^www\.", "", hote.lower())


def meme_site(url: str, reference: str) -> bool:
    return _hote_racine(urllib.parse.urlsplit(url).netloc) == _hote_racine(urllib.parse.urlsplit(reference).netloc)


def page_utile(url: str, reference: str) -> bool:
    if not url.startswith("http") or not meme_site(url, reference):
        return False
    chemin = urllib.parse.urlsplit(url).path.lower()
    if chemin.endswith(EXTENSIONS_IGNOREES):
        return False
    # Correspondance sur les mots du chemin, pas sur la chaîne brute : « merci »
    # est contenu dans « commercial », et une page /espace-commercial ne doit pas
    # être prise pour une page de remerciement.
    mots = [m for m in re.split(r"[/_.\-]+", chemin) if m]
    for segment in SEGMENTS_IGNORES:
        cle = segment.strip("/")
        if "-" in cle or "/" in cle:
            if cle in chemin:
                return False
        elif len(cle) <= 5 or cle in MOTS_ENTIERS:
            # Segment court : mot entier seulement, sinon « cart » attrape
            # « cartes-cadeaux » et « legal » attrape « legalite ».
            if cle in mots:
                return False
        elif any(mot.startswith(cle) for mot in mots):
            # Racine longue : elle peut préfixer, « cookie » doit attraper « cookies ».
            return False
    return True


def canonique(url: str) -> str:
    d = urllib.parse.urlsplit(url)
    chemin = d.path.rstrip("/") or "/"
    return urllib.parse.urlunsplit((d.scheme, d.netloc.lower(), chemin, "", ""))


def _slug(url: str) -> str:
    chemin = urllib.parse.urlsplit(url).path.strip("/") or "accueil"
    return re.sub(r"[^a-z0-9]+", "-", chemin.lower()).strip("-")[:60] or "accueil"


# ---------------------------------------------------------------------------
# Ce qu'on lit dans chaque page, exécuté dans le navigateur
# ---------------------------------------------------------------------------

LECTURE_PAGE = r"""
() => {
  const txt = (el) => (el && el.innerText || '').replace(/\s+/g, ' ').trim();
  const zone = (el) => {
    if (el.closest('header, nav, [role=banner]')) return 'entete';
    if (el.closest('footer, [role=contentinfo]')) return 'pied';
    const r = el.getBoundingClientRect();
    if (r.top + window.scrollY < window.innerHeight) return 'heros';
    return 'contenu';
  };
  const absolue = (u) => { try { return new URL(u, location.href).href; } catch (e) { return null; } };
  const plusGrandSrcset = (s) => {
    if (!s) return null;
    let meilleur = null, largeur = -1;
    s.split(',').forEach(p => {
      const [u, w] = p.trim().split(/\s+/);
      const n = parseInt(w) || 1;
      if (n > largeur) { largeur = n; meilleur = u; }
    });
    return meilleur;
  };

  // Images : balises img et picture, fonds CSS, posters vidéo.
  const images = [];
  document.querySelectorAll('img').forEach(img => {
    const src = absolue(plusGrandSrcset(img.getAttribute('srcset')) || img.currentSrc || img.src);
    if (!src || src.startsWith('data:')) return;
    const r = img.getBoundingClientRect();
    images.push({ src, alt: img.alt || '', type: 'img', zone: zone(img),
      largeur: img.naturalWidth, hauteur: img.naturalHeight,
      affichee: [Math.round(r.width), Math.round(r.height)],
      attributs: ((img.className || '') + ' ' + (img.id || '') + ' ' + (img.alt || '')).toLowerCase() });
  });
  document.querySelectorAll('picture source[srcset]').forEach(s => {
    const src = absolue(plusGrandSrcset(s.getAttribute('srcset')));
    if (src) images.push({ src, alt: '', type: 'picture', zone: zone(s), largeur: 0, hauteur: 0, affichee: [0,0], attributs: '' });
  });
  document.querySelectorAll('body *').forEach(el => {
    const bg = getComputedStyle(el).backgroundImage;
    if (!bg || bg === 'none') return;
    const m = bg.match(/url\(["']?([^"')]+)["']?\)/);
    if (!m || m[1].startsWith('data:')) return;
    const r = el.getBoundingClientRect();
    if (r.width < 80 || r.height < 80) return;
    images.push({ src: absolue(m[1]), alt: '', type: 'fond-css', zone: zone(el), largeur: 0, hauteur: 0,
      affichee: [Math.round(r.width), Math.round(r.height)], attributs: (el.className || '').toString().toLowerCase() });
  });
  document.querySelectorAll('video[poster]').forEach(v => {
    const src = absolue(v.getAttribute('poster'));
    if (src) images.push({ src, alt: '', type: 'poster-video', zone: zone(v), largeur: 0, hauteur: 0, affichee: [0,0], attributs: '' });
  });

  // Logos : SVG en ligne dans l'en-tête, icônes déclarées, og:image.
  const logos = [];
  document.querySelectorAll('header svg, nav svg, a[href="/"] svg, [class*=logo] svg, svg[class*=logo]').forEach(svg => {
    const r = svg.getBoundingClientRect();
    if (r.width >= 40) logos.push({ type: 'svg-en-ligne', svg: svg.outerHTML.slice(0, 200000), largeur: Math.round(r.width), hauteur: Math.round(r.height) });
  });
  document.querySelectorAll('link[rel*=icon], link[rel=apple-touch-icon]').forEach(l => {
    const src = absolue(l.href); if (src) logos.push({ type: 'icone', src, taille: l.getAttribute('sizes') || '' });
  });
  const og = document.querySelector('meta[property="og:image"]');
  if (og && og.content) logos.push({ type: 'og-image', src: absolue(og.content) });

  // Styles calculés : ce que le navigateur affiche réellement.
  const couleurs = {};
  const compter = (role, valeur, poids) => {
    if (!valeur || valeur === 'rgba(0, 0, 0, 0)' || valeur === 'transparent') return;
    couleurs[role] = couleurs[role] || {};
    couleurs[role][valeur] = (couleurs[role][valeur] || 0) + poids;
  };
  const surface = (el) => { const r = el.getBoundingClientRect(); return Math.max(1, Math.round(r.width * r.height / 1000)); };
  document.querySelectorAll('body, header, footer, section, main, div').forEach(el => {
    compter('fond', getComputedStyle(el).backgroundColor, surface(el));
  });
  document.querySelectorAll('h1, h2, h3').forEach(el => compter('titres', getComputedStyle(el).color, 10));
  document.querySelectorAll('p, li, span').forEach(el => compter('texte', getComputedStyle(el).color, 1));
  document.querySelectorAll('a').forEach(el => compter('liens', getComputedStyle(el).color, 1));

  const boutons = [];
  document.querySelectorAll('button, a[class*=btn], a[class*=button], a[class*=cta], [role=button], input[type=submit]').forEach(el => {
    const s = getComputedStyle(el);
    const label = txt(el) || el.value || '';
    if (!label || label.length > 60) return;
    compter('boutons', s.backgroundColor, 5);
    boutons.push({ label, fond: s.backgroundColor, couleur: s.color, rayon: s.borderRadius,
      bordure: s.border, ombre: s.boxShadow, graisse: s.fontWeight, casse: s.textTransform,
      police: s.fontFamily, remplissage: s.padding });
  });

  const polices = {};
  const pol = (role, el) => { if (el) polices[role] = { famille: getComputedStyle(el).fontFamily,
      graisse: getComputedStyle(el).fontWeight, taille: getComputedStyle(el).fontSize,
      casse: getComputedStyle(el).textTransform, interlettrage: getComputedStyle(el).letterSpacing }; };
  pol('corps', document.body); pol('h1', document.querySelector('h1'));
  pol('h2', document.querySelector('h2')); pol('h3', document.querySelector('h3'));
  pol('bouton', document.querySelector('button, a[class*=btn], a[class*=button]'));
  const policesChargees = [];
  try { document.fonts.forEach(f => { if (f.status === 'loaded') policesChargees.push(`${f.family} ${f.weight} ${f.style}`); }); } catch (e) {}

  // Composants : cartes, pastilles, ombres, rayons.
  const composants = { rayons: {}, ombres: {}, bordures: {} };
  document.querySelectorAll('div, section, article, li, a, span').forEach(el => {
    const s = getComputedStyle(el), r = el.getBoundingClientRect();
    if (r.width < 24 || r.height < 16) return;
    if (s.borderRadius && s.borderRadius !== '0px') composants.rayons[s.borderRadius] = (composants.rayons[s.borderRadius] || 0) + 1;
    if (s.boxShadow && s.boxShadow !== 'none') composants.ombres[s.boxShadow] = (composants.ombres[s.boxShadow] || 0) + 1;
    if (s.borderStyle !== 'none' && s.borderWidth !== '0px') composants.bordures[`${s.borderWidth} ${s.borderStyle}`] = (composants.bordures[`${s.borderWidth} ${s.borderStyle}`] || 0) + 1;
  });
  const variables = {};
  try {
    for (const feuille of document.styleSheets) {
      let regles; try { regles = feuille.cssRules; } catch (e) { continue; }
      for (const regle of regles) {
        if (regle.selectorText && /:root|html|body/.test(regle.selectorText)) {
          for (const prop of regle.style) if (prop.startsWith('--')) variables[prop] = regle.style.getPropertyValue(prop).trim();
        }
      }
    }
  } catch (e) {}

  // Textes.
  const liste = (sel, n) => Array.from(document.querySelectorAll(sel)).map(txt).filter(t => t && t.length < 300).slice(0, n);
  const corps = txt(document.body);
  const prix = Array.from(new Set((corps.match(/(\d[\d\s.,]*\s?(€|EUR|CHF|\$|XPF))|((€|\$|CHF)\s?\d[\d.,]*)/g) || []).map(p => p.trim()))).slice(0, 40);
  const temoignages = liste('blockquote, [class*=testimonial], [class*=review], [class*=avis], [class*=temoignage]', 20);
  const jsonld = Array.from(document.querySelectorAll('script[type="application/ld+json"]')).map(s => {
    try { return JSON.parse(s.textContent); } catch (e) { return null; }
  }).filter(Boolean);
  const reseaux = Array.from(new Set(Array.from(document.querySelectorAll('a[href]')).map(a => a.href)
    .filter(h => /instagram|facebook|linkedin|tiktok|youtube|twitter|x\.com|pinterest/.test(h)))).slice(0, 12);
  const liens = Array.from(new Set(Array.from(document.querySelectorAll('a[href]')).map(a => a.href)));
  const liensNav = Array.from(new Set(Array.from(document.querySelectorAll('header a[href], nav a[href]')).map(a => a.href)));
  const meta = (n) => { const m = document.querySelector(`meta[name="${n}"], meta[property="${n}"]`); return m ? m.content : null; };

  return {
    titre: document.title, description: meta('description'),
    og: { titre: meta('og:title'), description: meta('og:description') },
    langue: document.documentElement.lang || null,
    h1: liste('h1', 5), h2: liste('h2', 20), h3: liste('h3', 30),
    paragraphes_heros: liste('header p, section:first-of-type p, main > *:first-child p', 6),
    boutons, prix, temoignages, jsonld, reseaux, liens, liens_nav: liensNav,
    images, logos, couleurs, polices, polices_chargees: policesChargees, composants, variables,
    hauteur: document.documentElement.scrollHeight,
    // Les trois mesures qui servent au garde-fou d'exploitabilite. Elles ne
    // decrivent pas la DA, elles disent si la page en porte une.
    texte: (document.body ? document.body.innerText : '').replace(/\s+/g, ' ').trim().length,
    noeuds: document.querySelectorAll('*').length,
    champs_mot_de_passe: document.querySelectorAll('input[type=password]').length,
  };
}
"""


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

def _defiler(page) -> None:
    """Descend la page par paliers pour déclencher le chargement paresseux des images."""
    hauteur = page.evaluate("document.documentElement.scrollHeight")
    pas = 900
    for y in range(0, min(hauteur, 30000), pas):
        page.evaluate(f"window.scrollTo(0, {y})")
        page.wait_for_timeout(120)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(400)


def _pages_du_sitemap(contexte, base: str, limite: int) -> List[str]:
    trouvees: List[str] = []
    candidats = [urllib.parse.urljoin(base, "/sitemap.xml"), urllib.parse.urljoin(base, "/sitemap_index.xml")]
    vus: Set[str] = set()
    while candidats and len(trouvees) < limite * 4:
        url = candidats.pop(0)
        if url in vus:
            continue
        vus.add(url)
        try:
            reponse = contexte.request.get(url, timeout=15000)
            if not reponse.ok:
                continue
            corps = reponse.text()
        except Exception:
            continue
        for loc in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", corps):
            if loc.endswith(".xml"):
                candidats.append(loc)
            elif page_utile(loc, base):
                trouvees.append(loc)
    return trouvees


def raisons_inexploitable(lecture: dict, statut: Optional[int] = None) -> List[str]:
    """Toutes les raisons rendant la page impropre à servir de source de charte.

    On rend la LISTE, pas la première raison venue : un site derrière un mur de
    mot de passe coche en général trois cases à la fois, et n'en montrer qu'une
    envoie chercher au mauvais endroit.

    Les cinq contrôles viennent de l'ancien `intake.py`, qui enveloppait
    `brand_intake.py` et que ce module remplace. Ils sont ici parce qu'ils ne
    valent rien séparés du scraping : le seul moment utile pour refuser un site
    est juste avant d'en tirer une charte.
    """
    raisons: List[str] = []

    if statut is not None:
        if statut in (401, 403):
            raisons.append(f"accès refusé (HTTP {statut})")
        elif statut >= 400 or statut == 0:
            raisons.append(f"page non servie (HTTP {statut})")

    echantillon = " ".join([lecture.get("titre") or ""] + lecture.get("h1", [])).lower()
    for motif in MOTIFS_PAGE_DE_GARDE:
        if re.search(motif, echantillon):
            raisons.append(f"titre de page de garde : « {lecture.get('titre') or ''} »")
            break

    if int(lecture.get("champs_mot_de_passe") or 0) > 0:
        raisons.append("la page présente un champ de mot de passe")

    if int(lecture.get("noeuds") or 0) < NOEUDS_MINIMUM:
        raisons.append(f"page quasi vide ({lecture.get('noeuds')} éléments)")

    if int(lecture.get("texte") or 0) < TEXTE_MINIMUM:
        raisons.append(f"trop peu de texte ({lecture.get('texte')} caractères)")

    if (not lecture.get("images") and not lecture.get("h2")
            and int(lecture.get("hauteur") or 0) < 1200):
        raisons.append("ni image ni structure : rien d'exploitable")

    return raisons


def _verifier_page_de_garde(lecture: dict, statut: Optional[int] = None) -> None:
    """Refuse d'entrer en production sur une charte douteuse.

    C'est le point ouvert #4 du cahier des charges. Sur un site protégé, une
    extraction rend une charte parfaitement plausible : la couleur du bouton du
    mur en primaire, la police du gabarit en typographie de marque. Aucune
    erreur n'est levée, et le pack entier part hors charte sans que personne ne
    s'en aperçoive avant la livraison. On échoue donc bruyamment, ici et pas
    plus tard.
    """
    raisons = raisons_inexploitable(lecture, statut)
    if not raisons:
        return
    raise SiteInexploitable(
        "Le site ne peut pas servir de source de charte :\n  - "
        + "\n  - ".join(raisons)
        + "\n\nUne charte extraite d'une page de garde est plausible mais fausse, "
          "et contaminerait tout le pack. Fournir un accès, ou une autre source "
          "de charte."
    )


# ---------------------------------------------------------------------------
# Synthèse
# ---------------------------------------------------------------------------

def _hex(rgb: str) -> Optional[str]:
    m = re.match(r"rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)", rgb or "")
    if not m:
        return None
    if m.group(4) is not None and float(m.group(4)) < 0.5:
        return None
    return "#{:02X}{:02X}{:02X}".format(*(int(m.group(i)) for i in (1, 2, 3)))


def _neutre(hexa: str) -> bool:
    r, g, b = (int(hexa[i:i + 2], 16) for i in (1, 3, 5))
    return max(r, g, b) - min(r, g, b) < 18


def synthese_charte(lectures: List[dict]) -> dict:
    roles: Dict[str, Counter] = {}
    for lecture in lectures:
        for role, valeurs in lecture.get("couleurs", {}).items():
            compteur = roles.setdefault(role, Counter())
            for rgb, poids in valeurs.items():
                h = _hex(rgb)
                if h:
                    compteur[h] += poids

    def classer(role: str, n: int = 6) -> List[dict]:
        total = sum(roles.get(role, Counter()).values()) or 1
        return [{"hex": h, "part": round(p / total, 3)} for h, p in roles.get(role, Counter()).most_common(n)]

    accents = [c for c in classer("boutons", 10) if not _neutre(c["hex"])]
    if not accents:
        accents = [c for c in classer("liens", 10) + classer("titres", 10) if not _neutre(c["hex"])]

    familles = Counter()
    for lecture in lectures:
        for role, p in lecture.get("polices", {}).items():
            if p and p.get("famille"):
                familles[(role, p["famille"].split(",")[0].strip().strip('"\''))] += 1
    polices: Dict[str, str] = {}
    for (role, famille), _ in familles.most_common():
        polices.setdefault(role, famille)

    boutons = [b for l in lectures for b in l.get("boutons", [])]
    def dominant(cle: str) -> Optional[str]:
        c = Counter(b.get(cle) for b in boutons if b.get(cle))
        return c.most_common(1)[0][0] if c else None

    composants: Dict[str, Counter] = {"rayons": Counter(), "ombres": Counter(), "bordures": Counter()}
    for lecture in lectures:
        for type_, valeurs in lecture.get("composants", {}).items():
            composants[type_].update(valeurs)

    variables: Dict[str, str] = {}
    for lecture in lectures:
        variables.update(lecture.get("variables", {}))

    return {
        "_nature": "proposition mesurée sur les styles calculés, à valider ; jamais tirée des images",
        "fonds": classer("fond"),
        "titres": classer("titres", 4),
        "texte": classer("texte", 4),
        "accents": accents[:4],
        "polices": polices,
        "polices_chargees": sorted({p for l in lectures for p in l.get("polices_chargees", [])})[:30],
        "boutons": {
            "rayon": dominant("rayon"), "graisse": dominant("graisse"), "casse": dominant("casse"),
            "ombre": dominant("ombre"), "bordure": dominant("bordure"),
            "exemples": list(dict.fromkeys(b["label"] for b in boutons))[:15],
        },
        "composants": {k: [{"valeur": v, "occurrences": n} for v, n in c.most_common(6)]
                       for k, c in composants.items()},
        "variables_css": dict(list(variables.items())[:120]),
    }


def variante_luminance(fichier: Path) -> Optional[str]:
    """Sur quel fond ce logo est posable : « pour_fond_sombre » ou « pour_fond_clair ».

    Le nom dit l'USAGE, pas la couleur de l'encre, et c'est délibéré. La version
    précédente répondait « clair » pour un logo à l'encre blanche : un lecteur
    comprend « la version claire, donc pour fond clair », et pose un logo blanc
    sur du blanc. C'est exactement la faute qu'on veut rendre impossible à
    commettre, et elle ne se voit pas à la relecture du code.

    Retourne None pour un SVG ou une image illisible.
    """
    try:
        from PIL import Image
        image = Image.open(fichier).convert("RGBA")
        image.thumbnail((256, 256))
        opaques = [p for p in image.getdata() if p[3] > 128]
        if len(opaques) < 20:
            return None
        luminance = sum(0.299 * r + 0.587 * g + 0.114 * b for r, g, b, _ in opaques) / len(opaques)
        return "pour_fond_sombre" if luminance > 160 else "pour_fond_clair"
    except Exception:
        return None


def _score_logo(image: dict) -> int:
    score = 0
    if "logo" in image.get("attributs", ""):
        score += 50
    if image.get("zone") == "entete":
        score += 30
    if image.get("src", "").lower().endswith(".svg"):
        score += 15
    if "logo" in image.get("src", "").lower():
        score += 25
    return score


def verifier(url: str) -> dict:
    """Charge la seule page d'accueil et dit si le site est exploitable.

    Sert avant d'engager une aspiration complète, qui dure de une à plusieurs
    minutes selon le nombre de pages. Ne produit aucun fichier.
    """
    from playwright.sync_api import sync_playwright

    base = normaliser_url(url)
    with sync_playwright() as p:
        navigateur = p.chromium.launch()
        contexte = navigateur.new_context(user_agent=AGENT, viewport={"width": 1440, "height": 900},
                                          locale="fr-FR", ignore_https_errors=True)
        page = contexte.new_page()
        try:
            reponse = page.goto(base, wait_until="domcontentloaded", timeout=DELAI_PAGE_MS)
            page.wait_for_timeout(1500)
            lecture = page.evaluate(LECTURE_PAGE)
            statut = reponse.status if reponse else 0
        finally:
            navigateur.close()

    raisons = raisons_inexploitable(lecture, statut)
    return {
        "url": base, "statut": statut, "titre": lecture.get("titre"),
        "noeuds": lecture.get("noeuds"), "texte": lecture.get("texte"),
        "images": len(lecture.get("images") or []),
        "raisons": raisons, "exploitable": not raisons,
    }


# ---------------------------------------------------------------------------
# Aspiration
# ---------------------------------------------------------------------------

def aspirer(url: str, sortie: Path, pages_max: int = PAGES_MAX_DEFAUT) -> dict:
    from playwright.sync_api import sync_playwright

    base = normaliser_url(url)
    for sous in ("assets-site", "logo", "captures"):
        (sortie / sous).mkdir(parents=True, exist_ok=True)

    debut = time.time()
    lectures: List[dict] = []
    pages_lues: List[dict] = []
    erreurs: List[str] = []

    with sync_playwright() as p:
        navigateur = p.chromium.launch()
        contexte = navigateur.new_context(user_agent=AGENT, viewport={"width": 1440, "height": 900},
                                          locale="fr-FR", ignore_https_errors=True)
        page = contexte.new_page()

        # L'accueil d'abord : c'est lui qui dit si le site est exploitable. Une
        # URL profonde (page produit) est lue, puis on remonte à la racine.
        racine = urllib.parse.urlunsplit(urllib.parse.urlsplit(base)[:2] + ("/", "", ""))
        file_attente: List[str] = list(dict.fromkeys([base, racine]))
        file_attente += _pages_du_sitemap(contexte, racine, pages_max)
        vues: Set[str] = set()

        while file_attente and len(pages_lues) < pages_max:
            cible = file_attente.pop(0)
            if canonique(cible) in vues:
                continue
            vues.add(canonique(cible))
            try:
                reponse = page.goto(cible, wait_until="domcontentloaded", timeout=DELAI_PAGE_MS)
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
                _defiler(page)
                lecture = page.evaluate(LECTURE_PAGE)
            except Exception as erreur:
                erreurs.append(f"{cible} : {str(erreur)[:160]}")
                continue

            # Le garde-fou ne juge que la premiere page, et il reçoit le statut
            # HTTP : un 401 sur l'accueil est le signal le plus net qu'il y ait,
            # et l'ancienne version ne le voyait pas.
            if not pages_lues:
                _verifier_page_de_garde(lecture, reponse.status if reponse else 0)

            # JPEG et non PNG : ces captures servent à lire la DA à l'oeil, pas à
            # être découpées. Mesuré sur les Bains de Dax, une page pleine pèse
            # 2,8 Mo en PNG, soit 69 Mo par client et 1,4 Go sur les 21 commandes
            # ouvertes. Le JPEG de qualité 82 rend la même lecture pour un huitième.
            slug = _slug(page.url)
            capture = sortie / "captures" / f"{len(pages_lues):02d}-{slug}.jpg"
            try:
                if lecture.get("hauteur", 0) <= CAPTURE_HAUTEUR_MAX:
                    page.screenshot(path=str(capture), full_page=True, type="jpeg", quality=82)
                else:
                    page.screenshot(path=str(capture), type="jpeg", quality=82,
                                    clip={"x": 0, "y": 0, "width": 1440, "height": CAPTURE_HAUTEUR_MAX})
            except Exception as erreur:
                erreurs.append(f"capture {slug} : {str(erreur)[:120]}")

            lecture["url"] = page.url
            lecture["statut"] = reponse.status if reponse else None
            lectures.append(lecture)
            pages_lues.append({"url": page.url, "titre": lecture.get("titre"), "capture": str(capture.relative_to(sortie))})

            # Les pages du menu passent devant : ce sont celles que la marque
            # juge importantes. Le reste des liens suit.
            nav = [l for l in lecture.pop("liens_nav", []) if page_utile(l, racine) and canonique(l) not in vues]
            autres = [l for l in lecture.pop("liens", []) if page_utile(l, racine) and canonique(l) not in vues]
            file_attente = nav + file_attente + autres

        # Téléchargement des images, par le contexte du navigateur pour garder
        # les en-têtes que certains CDN exigent.
        # Deux dédoublonnages, et ils ne servent pas à la même chose. Par SOURCE,
        # pour ne pas retélécharger la même URL vue sur dix pages. Par EMPREINTE,
        # pour ne pas stocker deux fois les mêmes octets servis sous deux URL,
        # ce que font tous les CDN qui suffixent un jeton de cache.
        #
        # `par_source` ne pointe QUE vers une entrée réellement indexée. Le
        # premier jet y écrivait l'empreinte avant les filtres de type et de
        # taille : une image écartée y laissait une empreinte absente d'`index`,
        # et la page suivante qui revoyait la même URL levait un KeyError. Les
        # sources écartées vont dans `ignorees`, qui évite aussi de les
        # retélécharger à chaque page.
        index: Dict[str, dict] = {}
        par_source: Dict[str, str] = {}
        ignorees: Set[str] = set()

        def _noter_page(entree: dict, url_page: str) -> None:
            if url_page not in entree["pages"]:
                entree["pages"].append(url_page)

        for lecture in lectures:
            for image in lecture.get("images", []):
                src = image.get("src")
                if not src or src in ignorees:
                    continue
                if src in par_source:
                    _noter_page(index[par_source[src]], lecture["url"])
                    continue
                try:
                    reponse = contexte.request.get(src, timeout=30000)
                    if not reponse.ok:
                        ignorees.add(src)
                        continue
                    contenu = reponse.body()
                except Exception:
                    ignorees.add(src)
                    continue
                if len(contenu) < 1500:
                    ignorees.add(src)
                    continue

                empreinte = hashlib.sha1(contenu).hexdigest()[:16]
                if empreinte in index:
                    par_source[src] = empreinte
                    _noter_page(index[empreinte], lecture["url"])
                    continue

                type_mime = (reponse.headers.get("content-type") or "").split(";")[0]
                extension = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
                             "image/svg+xml": ".svg", "image/gif": ".gif", "image/avif": ".avif"}.get(type_mime)
                if not extension:
                    ignorees.add(src)
                    continue
                largeur, hauteur = image.get("largeur") or 0, image.get("hauteur") or 0
                if 0 < largeur < IMAGE_COTE_MIN and 0 < hauteur < IMAGE_COTE_MIN and extension != ".svg":
                    ignorees.add(src)
                    continue

                fichier = sortie / "assets-site" / f"{empreinte}{extension}"
                fichier.write_bytes(contenu)
                par_source[src] = empreinte
                index[empreinte] = {
                    "fichier": fichier.name, "source": src, "type": image.get("type"),
                    "zone": image.get("zone"), "alt": image.get("alt"),
                    "largeur": largeur, "hauteur": hauteur, "octets": len(contenu),
                    "score_logo": _score_logo(image), "pages": [lecture["url"]],
                }
        navigateur.close()

    # Logos : SVG en ligne, puis images classées par score.
    logos: List[dict] = []
    for i, lecture in enumerate(lectures[:3]):
        for j, logo in enumerate(lecture.get("logos", [])):
            if logo.get("type") == "svg-en-ligne" and logo.get("svg"):
                fichier = sortie / "logo" / f"svg-en-ligne-{i}-{j}.svg"
                svg = logo["svg"]
                if "xmlns" not in svg[:200]:
                    svg = svg.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
                fichier.write_text(svg, encoding="utf-8")
                logos.append({"fichier": f"logo/{fichier.name}", "type": "svg-en-ligne",
                              "largeur": logo.get("largeur"), "score": 60})
    for entree in sorted(index.values(), key=lambda e: -e["score_logo"]):
        if entree["score_logo"] >= 40:
            logos.append({"fichier": f"assets-site/{entree['fichier']}", "type": "image",
                          "score": entree["score_logo"],
                          "variante": variante_luminance(sortie / "assets-site" / entree["fichier"])})
    logos.sort(key=lambda l: -l["score"])

    # La plupart des créas se composent sur fond clair. Un site qui ne sert son
    # logo qu'en blanc sur transparent, cas des Bains de Dax, n'en offre donc
    # aucun d'utilisable : posé tel quel il disparaît. On le dit ici, pendant
    # qu'on peut encore aller chercher la version foncée, plutôt que de le
    # découvrir sur une planche livrée.
    manques: List[str] = []
    variantes = {l.get("variante") for l in logos}
    if logos and "pour_fond_clair" not in variantes:
        manques.append("aucun logo posable sur fond clair : tous les candidats sont "
                       "en encre claire. Demander la version foncée au client.")
    if not logos:
        manques.append("aucun candidat logo trouvé sur le site.")

    site = {
        "url": base,
        "aspire_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "duree_s": round(time.time() - debut, 1),
        "pages": [{
            "url": l["url"], "titre": l.get("titre"), "description": l.get("description"),
            "og": l.get("og"), "langue": l.get("langue"), "h1": l.get("h1"), "h2": l.get("h2"),
            "h3": l.get("h3"), "paragraphes_heros": l.get("paragraphes_heros"),
            "cta": list(dict.fromkeys(b["label"] for b in l.get("boutons", [])))[:20],
            "prix": l.get("prix"), "temoignages": l.get("temoignages"),
            "reseaux": l.get("reseaux"), "donnees_structurees": l.get("jsonld"),
        } for l in lectures],
        "erreurs": erreurs,
    }
    charte = synthese_charte(lectures)

    (sortie / "site.json").write_text(json.dumps(site, ensure_ascii=False, indent=2), encoding="utf-8")
    (sortie / "charte-site.json").write_text(json.dumps(charte, ensure_ascii=False, indent=2), encoding="utf-8")
    (sortie / "assets-site" / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    (sortie / "logo" / "candidats.json").write_text(json.dumps(logos, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "pages": len(lectures), "images": len(index), "logos": len(logos),
        "captures": len(pages_lues), "erreurs": len(erreurs), "duree_s": site["duree_s"],
        "accents": [c["hex"] for c in charte["accents"]], "polices": charte["polices"],
        "manques": manques,
    }


def aspirer_commande(ardoise: str, pages_max: int = PAGES_MAX_DEFAUT) -> dict:
    from etat import Commande
    commande = Commande.charger(ardoise)
    url = commande.donnees.get("url_site") or (commande.donnees.get("brief") or {}).get("url_site")
    commande.tracer("scraping_demande", url=url)
    try:
        resultat = aspirer(url, commande.dossier / "marque", pages_max)
    except SiteInexploitable as erreur:
        commande.tracer("site_inexploitable", raison=str(erreur))
        raise
    commande.tracer("scraping_termine", **{k: v for k, v in resultat.items() if k != "polices"})
    return resultat


def main() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sous = analyseur.add_subparsers(dest="commande", required=True)
    p_asp = sous.add_parser("aspirer")
    p_asp.add_argument("ardoise")
    p_asp.add_argument("--pages", type=int, default=PAGES_MAX_DEFAUT)
    p_url = sous.add_parser("url")
    p_url.add_argument("url")
    p_url.add_argument("--sortie", required=True)
    p_url.add_argument("--pages", type=int, default=PAGES_MAX_DEFAUT)
    p_ver = sous.add_parser("verifier", help="sonder l'accueil sans rien extraire")
    p_ver.add_argument("url")
    args = analyseur.parse_args()

    if args.commande == "verifier":
        bilan = verifier(args.url)
        print(json.dumps(bilan, ensure_ascii=False, indent=2))
        return 0 if bilan["exploitable"] else 2

    try:
        if args.commande == "aspirer":
            resultat = aspirer_commande(args.ardoise, args.pages)
        else:
            resultat = aspirer(args.url, Path(args.sortie), args.pages)
    except SiteInexploitable as erreur:
        print(f"SITE INEXPLOITABLE : {erreur}", file=sys.stderr)
        return 2
    print(json.dumps(resultat, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
