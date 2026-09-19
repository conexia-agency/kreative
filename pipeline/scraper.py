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
import io
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

# Les couleurs que le NAVIGATEUR pose quand personne n'a choisi : le bleu du lien
# non visite, le violet du lien visite, le rouge du lien actif. Ce ne sont jamais
# des couleurs de marque, et elles se glissent dans la mesure par les liens de
# pied de page laisses sans style.
COULEURS_AGENT = {"#0000EE", "#551A8B", "#EE0000", "#0000FF", "#000080"}


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
  const versRacine = (el) => {
    const a = el.closest('a[href]');
    if (!a) return false;
    try {
      const u = new URL(a.getAttribute('href'), location.href);
      return u.origin === location.origin && (u.pathname === '/' || u.pathname === '');
    } catch (e) { return false; }
  };
  const images = [];
  document.querySelectorAll('img').forEach(img => {
    const src = absolue(plusGrandSrcset(img.getAttribute('srcset')) || img.currentSrc || img.src);
    if (!src || src.startsWith('data:')) return;
    const r = img.getBoundingClientRect();
    images.push({ src, alt: img.alt || '', type: 'img', zone: zone(img),
      largeur: img.naturalWidth, hauteur: img.naturalHeight,
      affichee: [Math.round(r.width), Math.round(r.height)],
      lien_racine: versRacine(img),
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

  // Les BORDURES portent souvent la couleur de marque, et rien ne les lisait.
  // Sur podmax.fr, le violet de la marque ne vit que dans le logo (une image,
  // donc hors charte par doctrine), dans la bordure du rectangle de selection
  // autour d'un mot, et dans le cerne des cartes. Sans cette collecte, la
  // mesure ne trouvait aucun accent et retombait sur la couleur des liens.
  document.querySelectorAll('div, section, span, a, article, li').forEach(el => {
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    if (r.width < 24 || r.height < 12) return;
    if (parseFloat(s.borderTopWidth) >= 1 || parseFloat(s.borderLeftWidth) >= 1) {
      compter('bordures', s.borderTopColor || s.borderLeftColor, 3);
    }
    // Et la LUEUR. Sur une direction artistique en fond sombre, la couleur de
    // marque ne vit ni dans un fond ni dans une bordure : elle est dans le halo
    // porte par box-shadow. C'est tout podmax.fr, dont le violet #780096
    // n'apparait que la, en couches successives autour des cartes.
    if (s.boxShadow && s.boxShadow !== 'none') {
      (s.boxShadow.match(/rgba?\([^)]+\)/g) || []).forEach(c => compter('lueurs', c, 2));
    }
  });

  // Un bouton est une chose VISUELLE, pas une classe qui s'appelle « btn ».
  // Le selecteur par nom de classe ne trouvait rien sur un site Framer, dont
  // les classes sont generees : la charte sortait sans aucun bouton alors que
  // la page en affiche cinq. On garde les selecteurs explicites, et on ajoute
  // la reconnaissance par la forme : un fond, un arrondi, du remplissage, et
  // un texte court.
  const boutons = [];
  const vus = new Set();
  const noter = (el) => {
    if (vus.has(el)) return;
    const s = getComputedStyle(el);
    const label = txt(el) || el.value || '';
    if (!label || label.length > 60) return;
    vus.add(el);
    compter('boutons', s.backgroundColor, 5);
    boutons.push({ label, fond: s.backgroundColor, couleur: s.color, rayon: s.borderRadius,
      bordure: s.border, ombre: s.boxShadow, graisse: s.fontWeight, casse: s.textTransform,
      police: s.fontFamily, remplissage: s.padding });
  };
  document.querySelectorAll('button, a[class*=btn], a[class*=button], a[class*=cta], [role=button], input[type=submit]').forEach(noter);
  document.querySelectorAll('a, div[onclick], [tabindex]').forEach(el => {
    const s = getComputedStyle(el);
    const rayon = parseFloat(s.borderTopLeftRadius) || 0;
    const fond = s.backgroundColor;
    const opaque = fond && fond !== 'transparent' && !/rgba\(0, 0, 0, 0\)/.test(fond);
    const rembourrage = parseFloat(s.paddingLeft) || 0;
    const r = el.getBoundingClientRect();
    if (!opaque || rayon < 4 || rembourrage < 8) return;
    if (r.height < 24 || r.height > 90 || r.width < 60 || r.width > 420) return;
    if (el.querySelectorAll('a, button').length) return;   // un conteneur, pas un bouton
    noter(el);
  });

  const polices = {};
  const pol = (role, el) => { if (el) polices[role] = { famille: getComputedStyle(el).fontFamily,
      graisse: getComputedStyle(el).fontWeight, taille: getComputedStyle(el).fontSize,
      casse: getComputedStyle(el).textTransform, interlettrage: getComputedStyle(el).letterSpacing }; };
  // La police de corps se lit sur un VRAI paragraphe, pas sur `body`. Un body
  // sans `font-family` declaree rend la famille generique de l'agent (« sans-serif »),
  // alors que tous ses enfants affichent la police de la marque : podmax.fr
  // ressortait en « sans-serif » avec Poppins chargee et employee partout.
  const corpsReel = Array.from(document.querySelectorAll('p, li'))
    .find(el => (el.innerText || '').trim().length > 40) || document.body;
  pol('corps', corpsReel); pol('h1', document.querySelector('h1'));
  pol('h2', document.querySelector('h2')); pol('h3', document.querySelector('h3'));
  pol('bouton', document.querySelector('button, a[class*=btn], a[class*=button]'));
  const policesChargees = [];
  try { document.fonts.forEach(f => { if (f.status === 'loaded') policesChargees.push(`${f.family} ${f.weight} ${f.style}`); }); } catch (e) {}

  // Composants. L'article 4.1 du cahier des charges nomme ce qu'il veut voir
  // relevé : « badges, pilules, cartes empilées, pastilles, police d'accent,
  // encadrés tracés à la main, traitement des ombres et des bordures ». Neuf
  // items ; le relevé n'en donnait que trois, et deux sous forme de compteurs
  // bruts. Tout se mesure ici sur les styles CALCULES, comme le reste du
  // fichier : c'est la seule façon d'avoir la valeur réellement affichée.
  const composants = { rayons: {}, ombres: {}, bordures: {},
                       badges: [], cartes: [], pastilles: [],
                       cartes_empilees: 0, encadres_dessines: [] };
  const opaqueDe = (s) => {
    const f = s.backgroundColor;
    return !!f && f !== 'transparent' && !/rgba\([^)]*,\s*0\s*\)$/.test(f);
  };
  // Décompose une ombre CSS en ses nombres et sa couleur, et dit si c'est une
  // LUEUR (posée droit, sans décalage, large) ou une OMBRE PORTEE. Les deux ne
  // se dessinent pas pareil dans une créa, et « box-shadow: ... » brut ne le
  // disait pas.
  const lireOmbre = (valeur) => {
    const couleur = (valeur.match(/(rgba?\([^)]*\)|#[0-9a-f]{3,8})/i) || [''])[0];
    const nombres = (valeur.replace(couleur, '').match(/-?\d*\.?\d+px/g) || [])
      .map(v => parseFloat(v));
    const [dx = 0, dy = 0, flou = 0, etalement = 0] = nombres;
    const lueur = Math.abs(dx) < 2 && Math.abs(dy) < 2 && flou >= 12;
    return { couleur, dx, dy, flou, etalement, nature: lueur ? 'lueur' : 'ombre portée' };
  };
  // La couleur du TEXTE, lue sur l'élément qui le porte vraiment. Un badge est
  // souvent un conteneur dont la couleur est héritée et fausse : podmax
  // ressortait « encre noire sur fond rgb(38,36,41) », c'est-à-dire du noir sur
  // du noir, ce qui n'existe pas à l'écran. Une valeur fausse dans une charte
  // est pire qu'une valeur absente : elle se retrouve telle quelle dans un
  // prompt.
  const encreDe = (el) => {
    const porteur = Array.from(el.querySelectorAll('*'))
      .find(n => n.children.length === 0 && (n.textContent || '').trim());
    return getComputedStyle(porteur || el).color;
  };
  const rectsCartes = [];
  document.querySelectorAll('div, section, article, li, a, span, p, h1, h2, h3').forEach(el => {
    const s = getComputedStyle(el), r = el.getBoundingClientRect();
    if (r.width < 8 || r.height < 8) return;
    const rayon = parseFloat(s.borderTopLeftRadius) || 0;
    const texte = (el.innerText || '').trim();

    if (r.width >= 24 && r.height >= 16) {
      if (s.borderRadius && s.borderRadius !== '0px') composants.rayons[s.borderRadius] = (composants.rayons[s.borderRadius] || 0) + 1;
      if (s.boxShadow && s.boxShadow !== 'none') composants.ombres[s.boxShadow] = (composants.ombres[s.boxShadow] || 0) + 1;
      // La bordure se lit côté par côté : un `border-style` global rend
      // « none none solid none » sur un simple filet bas, et la couleur, qui
      // est ce qui sert vraiment dans une créa, se perdait entièrement.
      ['Top', 'Right', 'Bottom', 'Left'].forEach(cote => {
        const largeur = parseFloat(s[`border${cote}Width`]) || 0;
        const style = s[`border${cote}Style`];
        if (largeur <= 0 || style === 'none') return;
        const cle = `${largeur}px ${style} ${s[`border${cote}Color`]}`;
        composants.bordures[cle] = (composants.bordures[cle] || 0) + 1;
      });
    }

    // Badge ou pilule : petit, très arrondi, fond plein, texte court.
    // Un badge porte UN texte court sur une ligne. Le retour à la ligne
    // trahit un conteneur qui empile deux blocs : podmax sortait « À l'unité
    // / Nos packs » comme un seul badge de 160px de rayon.
    if (texte && texte.length <= 32 && !texte.includes('\n')
        && r.height >= 14 && r.height <= 60
        && r.width <= 300 && rayon >= r.height / 2 - 1 && opaqueDe(s)
        && !el.querySelector('img, svg, input')) {
      composants.badges.push({ texte: texte.slice(0, 32), rayon: Math.round(rayon),
        hauteur: Math.round(r.height), fond: s.backgroundColor, encre: encreDe(el),
        graisse: s.fontWeight, casse: s.textTransform });
    }

    // Pastille : carrée ou ronde, petite, qui porte une icône ou un chiffre.
    const carre = r.height > 0 && r.width / r.height > 0.8 && r.width / r.height < 1.25;
    if (carre && r.width >= 16 && r.width <= 88 && rayon >= r.width * 0.35
        && (opaqueDe(s) || el.querySelector('svg, img'))) {
      composants.pastilles.push({ taille: Math.round(r.width),
        rayon: Math.round(rayon), fond: s.backgroundColor,
        contenu: el.querySelector('svg') ? 'icone' : (texte.slice(0, 8) || 'vide'),
        ronde: rayon >= r.width * 0.45 });
    }

    // Carte : assez grande, arrondie, détachée du fond par une ombre ou un filet.
    const detachee = (s.boxShadow && s.boxShadow !== 'none')
      || (parseFloat(s.borderTopWidth) || 0) > 0 || opaqueDe(s);
    if (r.width >= 160 && r.height >= 110 && rayon >= 4 && detachee && texte.length > 8) {
      composants.cartes.push({ largeur: Math.round(r.width), hauteur: Math.round(r.height),
        rayon: Math.round(rayon), fond: s.backgroundColor,
        ombre: s.boxShadow === 'none' ? null : lireOmbre(s.boxShadow) });
      rectsCartes.push(r);
    }
  });

  // Cartes empilées : deux cartes dont les rectangles se recouvrent
  // franchement. C'est la profondeur en calques que le skill appelle de ses
  // voeux, et elle ne se voit pas dans une liste de rayons.
  for (let i = 0; i < rectsCartes.length && composants.cartes_empilees < 40; i++) {
    for (let j = i + 1; j < rectsCartes.length; j++) {
      const a = rectsCartes[i], b = rectsCartes[j];
      const large = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left));
      const haut = Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
      const aire = large * haut;
      const petite = Math.min(a.width * a.height, b.width * b.height);
      if (petite > 0 && aire / petite > 0.12 && aire / petite < 0.95) {
        composants.cartes_empilees++;
        break;
      }
    }
  }

  // Encadré tracé à la main : un SVG dont le chemin est courbe, posé autour ou
  // derrière un bloc de texte. C'est le trait de surligneur, le cercle au
  // feutre, la flèche dessinée. Un rectangle CSS ne produit jamais ça.
  document.querySelectorAll('svg').forEach(svg => {
    const r = svg.getBoundingClientRect();
    if (r.width < 40 || r.height < 12) return;
    const chemins = Array.from(svg.querySelectorAll('path'));
    const courbe = chemins.find(p => {
      const d = p.getAttribute('d') || '';
      return d.length > 40 && /[CcQqSsTtAa]/.test(d);
    });
    if (!courbe) return;
    const dessous = document.elementFromPoint(
      Math.min(window.innerWidth - 1, Math.max(0, r.left + r.width / 2)),
      Math.min(window.innerHeight - 1, Math.max(0, r.top + r.height / 2)));
    const pres_de_texte = !!(dessous && (dessous.innerText || '').trim().length > 2);
    if (!pres_de_texte && r.width > 200 && r.height > 200) return;
    const trait = getComputedStyle(courbe);
    composants.encadres_dessines.push({
      largeur: Math.round(r.width), hauteur: Math.round(r.height),
      trait: trait.stroke, epaisseur: trait.strokeWidth,
      rempli: trait.fill && trait.fill !== 'none',
      autour_de_texte: pres_de_texte });
  });

  // Police d'accent : une famille employée sur une petite part du texte, et
  // différente de la police de corps. C'est elle qui porte le mot pivot d'une
  // créa ; la confondre avec la police de corps aplatit toute la typographie.
  const parFamille = {};
  document.querySelectorAll('h1, h2, h3, h4, p, li, span, a, button, strong, em').forEach(el => {
    const t = (el.innerText || '').trim();
    if (!t || el.children.length > 0) return;
    const f = getComputedStyle(el).fontFamily;
    parFamille[f] = (parFamille[f] || 0) + t.length;
  });
  const totalTexte = Object.values(parFamille).reduce((a, b) => a + b, 0) || 1;
  const familleCorps = getComputedStyle(corpsReel).fontFamily;
  composants.familles = Object.entries(parFamille)
    .map(([famille, signes]) => ({ famille, signes, part: signes / totalTexte,
      accent: famille !== familleCorps && signes / totalTexte < 0.1 }))
    .sort((a, b) => b.signes - a.signes).slice(0, 8);
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
  // L'accroche TELLE QU'ELLE S'AFFICHE, quel que soit le balisage. Les titres
  // animes mot par mot (Framer, Webflow) mettent chaque mot dans son propre
  // h1 : podmax.fr rendait `h1 = ["videos", "shorts", "podcast", "formations"]`
  // pour une phrase qui se lit « Pret a tourner vos videos dans des decors
  // d'exception ? ». Un skill qui lit ce champ croit que le message du site est
  // le mot « videos ». On repere donc le plus gros texte du haut de page et on
  // remonte au bloc qui le contient.
  let accrocheHeros = '';
  try {
    let plusGros = null, taille = 0;
    document.querySelectorAll('h1, h2, h3, p, span, div').forEach(el => {
      const r = el.getBoundingClientRect();
      if (r.top < 0 || r.top > 900 || r.width < 120) return;
      if (!(el.innerText || '').trim()) return;
      if (el.children.length > 3) return;
      const t = parseFloat(getComputedStyle(el).fontSize) || 0;
      if (t > taille) { taille = t; plusGros = el; }
    });
    if (plusGros) {
      let bloc = plusGros;
      for (let i = 0; i < 4 && bloc.parentElement; i++) {
        const t = txt(bloc.parentElement);
        if (t.length > 220) break;
        bloc = bloc.parentElement;
      }
      accrocheHeros = txt(bloc).slice(0, 220);
    }
  } catch (e) {}

  const liens = Array.from(new Set(Array.from(document.querySelectorAll('a[href]')).map(a => a.href)));
  const liensNav = Array.from(new Set(Array.from(document.querySelectorAll('header a[href], nav a[href]')).map(a => a.href)));
  const meta = (n) => { const m = document.querySelector(`meta[name="${n}"], meta[property="${n}"]`); return m ? m.content : null; };

  return {
    titre: document.title, description: meta('description'),
    og: { titre: meta('og:title'), description: meta('og:description') },
    langue: document.documentElement.lang || null,
    accroche_heros: accrocheHeros,
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
    """Descend la page pour déclencher le chargement paresseux des images.

    Deux mécaniques, parce qu'une seule ne suffit pas : `window.scrollTo` pour
    les pages qui défilent normalement, et la MOLETTE pour celles dont le
    défilement vit dans un conteneur interne (Framer, Webflow et consorts).
    Sur ces dernières, `document.documentElement.scrollHeight` vaut la hauteur
    du viewport et l'ancienne boucle ne défilait pas d'un pixel : le lazy-load
    ne partait pas, et la capture ne voyait que le premier écran (mesuré le
    18/09 sur podmax.fr et mickaelwu.com)."""
    hauteur = page.evaluate("document.documentElement.scrollHeight") or 0
    pas = 900
    for y in range(0, min(max(hauteur, pas), 30000), pas):
        page.evaluate(f"window.scrollTo(0, {y})")
        page.wait_for_timeout(120)
    vue = page.viewport_size or {"width": 1440, "height": 900}
    page.mouse.move(vue["width"] // 2, vue["height"] // 2)
    for _ in range(12):
        page.mouse.wheel(0, vue["height"])
        page.wait_for_timeout(140)
    page.evaluate("window.scrollTo(0, 0)")
    page.mouse.wheel(0, -30000)
    page.wait_for_timeout(400)


def _capturer_entier(page, chemin: Path, hauteur_max: int) -> None:
    """Écrit une capture de la page ENTIÈRE, quel que soit son mode de défilement.

    `full_page=True` suffit pour une page qui défile normalement. Il rend le
    seul premier écran (1440 x 900) quand le défilement vit dans un conteneur
    interne : la chaîne jugeait alors la direction artistique sur le haut des
    pages, sans que rien ne le signale. On prend dans ce cas des bandes
    successives à la molette, qui fait défiler ce qui est réellement sous le
    curseur, et on les assemble. La fin se détecte à l'identité de deux
    clichés consécutifs."""
    import io
    from PIL import Image

    vue = page.viewport_size or {"width": 1440, "height": 900}
    page.evaluate("window.scrollTo(0, 0)")
    page.mouse.move(vue["width"] // 2, vue["height"] // 2)
    page.mouse.wheel(0, -30000)
    page.wait_for_timeout(500)

    entiere = page.screenshot(full_page=True, type="jpeg", quality=82)
    with Image.open(io.BytesIO(entiere)) as im:
        if im.height > vue["height"] + 100:
            chemin.write_bytes(entiere)
            return

    bandes: List[bytes] = []
    precedent: Optional[bytes] = None
    for _ in range(max(1, hauteur_max // vue["height"])):
        cliche = page.screenshot(type="jpeg", quality=82)
        if cliche == precedent:
            break
        bandes.append(cliche)
        precedent = cliche
        page.mouse.wheel(0, vue["height"])
        page.wait_for_timeout(450)

    if len(bandes) <= 1:
        chemin.write_bytes(bandes[0] if bandes else entiere)
        return

    images = [Image.open(io.BytesIO(b)).convert("RGB") for b in bandes]
    planche = Image.new("RGB", (images[0].width, sum(i.height for i in images)))
    y = 0
    for im in images:
        planche.paste(im, (0, y))
        y += im.height
    planche.save(chemin, "JPEG", quality=82)


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
    """Cette couleur peut-elle servir d'accent, ou n'est-elle qu'un fond ?

    L'écart entre les canaux ne suffit pas. `#0D0117` est un violet
    mathématiquement saturé, et c'est le fond de podmax.fr : posé comme accent,
    il donnerait un mot « mis en valeur » en noir sur noir. Un accent doit aussi
    être assez lumineux pour se voir, et assez sombre pour ne pas être un blanc
    cassé. On borne donc la luminance en plus de la saturation.
    """
    r, g, b = (int(hexa[i:i + 2], 16) for i in (1, 3, 5))
    if max(r, g, b) - min(r, g, b) < 18:
        return True
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return luminance < 40 or luminance > 232


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

    # L'accent se cherche là où une marque le pose, dans cet ordre de confiance :
    # le fond des boutons, puis les bordures, puis les liens et les titres. Les
    # bordures ont été ajoutées après podmax.fr, dont le violet ne vit que là.
    #
    # Aucun de ces gisements ne doit rendre une couleur que PERSONNE n'a choisie.
    # Le bleu `#0000EE` est celui qu'un navigateur donne à un lien non stylé : il
    # sortait en tête des accents de podmax.fr à 78 %, et une marque violette
    # serait partie en bleu sans que rien ne le signale.
    def utiles(role: str, n: int = 10) -> List[dict]:
        return [c for c in classer(role, n)
                if not _neutre(c["hex"]) and c["hex"].upper() not in COULEURS_AGENT]

    accents = utiles("boutons")
    if not accents:
        accents = utiles("bordures")
    if not accents:
        accents = utiles("lueurs")
    if not accents:
        accents = utiles("liens") + utiles("titres")

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

    # Les composants arrivent sous deux formes selon leur nature. Les rayons,
    # ombres et bordures sont des COMPTEURS de valeurs CSS : on les cumule. Les
    # badges, pastilles, cartes, encadrés dessinés et familles de police sont
    # des RELEVES d'objets réels : on les collecte, on les dédoublonne, et on
    # garde les plus fréquents. Les écraser dans un compteur, comme le faisait
    # la boucle précédente, aurait perdu leur contenu.
    compteurs: Dict[str, Counter] = {"rayons": Counter(), "ombres": Counter(),
                                     "bordures": Counter()}
    releves: Dict[str, List[dict]] = {"badges": [], "pastilles": [], "cartes": [],
                                      "encadres_dessines": [], "familles": []}
    empilees = 0
    for lecture in lectures:
        bloc = lecture.get("composants") or {}
        for type_, compteur in compteurs.items():
            compteur.update(bloc.get(type_) or {})
        for type_, liste in releves.items():
            liste.extend(bloc.get(type_) or [])
        empilees += int(bloc.get("cartes_empilees") or 0)

    def _resumer(objets: List[dict], cle_signature, garder: int) -> List[dict]:
        """Dédoublonne des objets identiques et compte leurs occurrences."""
        vus: Dict[str, dict] = {}
        for objet in objets:
            if not isinstance(objet, dict):
                continue
            signature = cle_signature(objet)
            entree = vus.setdefault(signature, dict(objet, occurrences=0))
            entree["occurrences"] += 1
        return sorted(vus.values(), key=lambda o: -o["occurrences"])[:garder]

    familles_cumul: Dict[str, dict] = {}
    for f in releves["familles"]:
        entree = familles_cumul.setdefault(f["famille"], {"famille": f["famille"], "signes": 0})
        entree["signes"] += int(f.get("signes") or 0)
    total_signes = sum(f["signes"] for f in familles_cumul.values()) or 1
    familles_triees = sorted(familles_cumul.values(), key=lambda f: -f["signes"])
    famille_corps = familles_triees[0]["famille"] if familles_triees else ""
    for f in familles_triees:
        f["part"] = round(f["signes"] / total_signes, 4)
        f["accent"] = f["famille"] != famille_corps and f["part"] < 0.1

    composants = {
        # Les trois compteurs historiques, inchangés dans leur forme.
        "rayons": [{"valeur": v, "occurrences": n} for v, n in compteurs["rayons"].most_common(6)],
        "ombres": [{"valeur": v, "occurrences": n, **_lire_ombre(v)}
                   for v, n in compteurs["ombres"].most_common(6)],
        "bordures": [{"valeur": v, "occurrences": n}
                     for v, n in compteurs["bordures"].most_common(8)],
        # Les six items que l'article 4.1 nomme et que le relevé ne donnait pas.
        "badges": _resumer(releves["badges"],
                           lambda b: f"{b.get('fond')}|{b.get('rayon')}|{b.get('casse')}", 12),
        "pastilles": _resumer(releves["pastilles"],
                              lambda p: f"{p.get('taille')}|{p.get('fond')}|{p.get('ronde')}", 10),
        "cartes": _resumer(releves["cartes"],
                           lambda c: f"{c.get('rayon')}|{c.get('fond')}|"
                                     f"{(c.get('ombre') or {}).get('nature')}", 10),
        "cartes_empilees": empilees,
        "encadres_dessines": _resumer(
            releves["encadres_dessines"],
            lambda e: f"{e.get('trait')}|{e.get('epaisseur')}|{e.get('rempli')}", 8),
        "familles_de_police": familles_triees[:8],
        "police_accent": next((f["famille"] for f in familles_triees if f["accent"]), None),
    }

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
        "composants": composants,
        "variables_css": dict(list(variables.items())[:120]),
    }


def _lire_ombre(valeur: str) -> dict:
    """Décompose une ombre CSS : décalage, flou, étalement, couleur, nature.

    L'article 4.1 demande le « traitement des ombres », pas la liste des
    chaînes `box-shadow`. La distinction qui compte pour une créa est entre une
    LUEUR (posée droit, sans décalage, large) et une OMBRE PORTEE : les deux se
    dessinent différemment, et la chaîne brute ne le disait pas.
    """
    couleur = re.search(r"rgba?\([^)]*\)|#[0-9a-fA-F]{3,8}", valeur or "")
    reste = (valeur or "").replace(couleur.group(0), "") if couleur else (valeur or "")
    nombres = [float(n) for n in re.findall(r"-?\d*\.?\d+(?=px)", reste)]
    dx, dy, flou, etalement = (nombres + [0.0, 0.0, 0.0, 0.0])[:4]
    return {
        "couleur": couleur.group(0) if couleur else None,
        "decalage_x": dx, "decalage_y": dy, "flou": flou, "etalement": etalement,
        "nature": "lueur" if abs(dx) < 2 and abs(dy) < 2 and flou >= 12 else "ombre portée",
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


def _est_photographique(chemin: Path) -> bool:
    """Une photo, ou un aplat de marque ? Un logo compte peu de couleurs.

    Mesuré le 18/09 sur mickaelwu.com : la photo d'avatar carrée posée en
    en-tête, présente sur toutes les pages, raflait la première place du
    classement logo. Posée comme logo dans une créa, elle aurait mis un
    portrait à la place d'un sigle. Un logo, même dégradé, tient en quelques
    centaines de teintes une fois quantifié ; une photographie en compte des
    milliers."""
    try:
        from PIL import Image
        with Image.open(chemin) as im:
            reduite = im.convert("RGB").resize((96, 96), Image.LANCZOS)
        teintes = {(r // 16, v // 16, b // 16) for r, v, b in reduite.getdata()}
        return len(teintes) > 180
    except Exception:
        return False


def _score_logo(image: dict, nb_pages: int = 1) -> int:
    """Un logo se reconnaît d'abord à sa STRUCTURE, pas à son nom.

    Mesuré le 18/09 sur podmax.fr : le logo est une image Framer sans le mot
    « logo » nulle part (132 x 38, en tête de toutes les pages, cliquable vers
    l'accueil), et le score purement nominal le laissait à zéro, donc
    `logo/candidats.json` vide. Les signaux de structure, indépendants du
    nommage : cliquable vers la racine, présent sur presque toutes les pages,
    silhouette de wordmark (petit et nettement plus large que haut)."""
    score = 0
    attributs = image.get("attributs", "") or ""
    src = (image.get("src") or image.get("source") or "").lower()
    if "logo" in attributs:
        score += 50
    if "logo" in src:
        score += 25
    if image.get("zone") == "entete":
        score += 30
    elif image.get("zone") == "heros":
        score += 10
    if src.endswith(".svg"):
        score += 15
    if image.get("lien_racine"):
        score += 30
    if image.get("type") == "icone":
        score += 25
    pages = image.get("pages")
    if pages is not None and nb_pages > 1 and len(pages) >= max(2, round(0.8 * nb_pages)):
        score += 25
    affichee = (image.get("affichee") or [0, 0]) + [0, 0]
    la, ha = affichee[0], affichee[1]
    if 0 < ha <= 90 and la >= 1.8 * ha:
        score += 20
    # Une photo pleine page n'est jamais un logo, quel que soit son nom.
    if ha > 400 or (image.get("hauteur") or 0) > 1200:
        score -= 30
    # Trop petit pour être posé sur une créa : une vignette de 64 pixels ne se
    # rattrape pas, elle se déclasse pour que le vrai logo passe devant.
    intrinseque = max(image.get("largeur") or 0, image.get("hauteur") or 0)
    if 0 < intrinseque < 96 and not src.endswith(".svg"):
        score -= 40
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
                _capturer_entier(page, capture, CAPTURE_HAUTEUR_MAX)
            except Exception as erreur:
                erreurs.append(f"capture {slug} : {str(erreur)[:120]}")

            # La redirection peut amener deux URL demandees differentes sur la
            # meme page reelle : podmax.fr et www.podmax.fr/ ont ainsi occupe
            # deux des cinq places du relevé pour un seul contenu.
            #
            # On ne compare QUE si l'adresse a bougé. L'URL demandée est déjà
            # dans `vues` depuis le haut de la boucle : comparer sans cette
            # condition rejetait toutes les pages sauf la première.
            arrivee = canonique(page.url)
            if arrivee != canonique(cible):
                if arrivee in vues:
                    continue
                vues.add(arrivee)

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
            # Les icônes déclarées et l'og:image sont souvent la seule version
            # propre du sigle de la marque (une apple-touch-icon en 512 est un
            # logo carré prêt à poser). Elles étaient collectées dans la page
            # mais jamais téléchargées (constaté le 18/09) : elles rejoignent
            # ici la file des images, avec leur type pour le score.
            a_descendre = list(lecture.get("images", []))
            for logo_page in lecture.get("logos", []):
                if logo_page.get("type") in ("icone", "og-image") and logo_page.get("src"):
                    a_descendre.append({
                        "src": logo_page["src"], "alt": "", "type": logo_page["type"],
                        "zone": "entete", "largeur": 0, "hauteur": 0,
                        "affichee": [0, 0], "lien_racine": False,
                        "attributs": logo_page["type"]})
            for image in a_descendre:
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
                # Le plancher de poids écarte les pixels de suivi et les puces
                # décoratives. Il ne s'applique PAS à un SVG ni à une icône
                # déclarée : un logo vectoriel propre pèse souvent moins d'un
                # kilo-octet, et c'est justement l'asset le plus utile du site.
                vectoriel = src.lower().split("?")[0].endswith(".svg")
                if len(contenu) < 1500 and not vectoriel and image.get("type") != "icone":
                    ignorees.add(src)
                    continue
                if len(contenu) < 120:
                    ignorees.add(src)
                    continue

                empreinte = hashlib.sha1(contenu).hexdigest()[:16]
                if empreinte in index:
                    par_source[src] = empreinte
                    _noter_page(index[empreinte], lecture["url"])
                    # Les signaux de structure se cumulent entre occurrences :
                    # le logo peut être cliquable en tête et nu dans le pied.
                    if image.get("lien_racine"):
                        index[empreinte]["lien_racine"] = True
                    if image.get("zone") == "entete":
                        index[empreinte]["zone"] = "entete"
                    if not any(index[empreinte].get("affichee") or []):
                        index[empreinte]["affichee"] = image.get("affichee")
                    continue

                type_mime = (reponse.headers.get("content-type") or "").split(";")[0]
                extension = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
                             "image/svg+xml": ".svg", "image/gif": ".gif", "image/avif": ".avif"}.get(type_mime)
                if not extension:
                    ignorees.add(src)
                    continue
                # Les dimensions se mesurent TOUJOURS sur les octets reçus,
                # jamais sur le naturalWidth du navigateur : une image affichée
                # en petit (logo de pied de page, image paresseuse) est notée
                # minuscule alors que le fichier est en pleine résolution, et le
                # tri par taille l'écartait à tort. Mesuré sur podmax : le logo
                # blanc 3667 x 1184 était indexé 223 x 72 et n'a jamais été vu.
                largeur, hauteur = image.get("largeur") or 0, image.get("hauteur") or 0
                if extension != ".svg":
                    try:
                        from PIL import Image as _Image
                        with _Image.open(io.BytesIO(contenu)) as _im:
                            largeur, hauteur = _im.size
                    except Exception:
                        pass
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
                    "affichee": image.get("affichee"),
                    "lien_racine": bool(image.get("lien_racine")),
                    "attributs": image.get("attributs", ""),
                    "score_logo": 0, "pages": [lecture["url"]],
                }
        navigateur.close()

    # Le score logo se calcule APRÈS la fusion : la présence sur presque
    # toutes les pages est un signal qui n'existe qu'une fois le tour fini.
    # Une image photographique ne concourt pas : c'est un asset, jamais un logo.
    for entree in index.values():
        entree["photographique"] = _est_photographique(
            sortie / "assets-site" / entree["fichier"])
        entree["score_logo"] = (0 if entree["photographique"]
                                else _score_logo(entree, nb_pages=len(lectures)))

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
            "og": l.get("og"), "langue": l.get("langue"),
            "accroche_heros": l.get("accroche_heros"),
            "h1": l.get("h1"), "h2": l.get("h2"),
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
