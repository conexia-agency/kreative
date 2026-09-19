---
name: kreative-production
description: Pilote la chaîne de production Kreative de bout en bout, du formulaire client rempli jusqu'aux créatives Meta auditées et déposées en revue. À utiliser quand un nouveau formulaire arrive, quand l'utilisateur demande de relever les commandes, de produire ou régénérer un pack de créas pour un client, ou nomme une commande existante par sa marque. Couvre le relevé Zite, l'aspiration du site, la stratégie créative, le devis en crédits, la génération par le MCP Higgsfield, le gate qualité et la page de suivi. Ne pas utiliser pour créer une vidéo, ni pour un client hors Kreative, ni pour modifier la plateforme de revue elle-même.
---

# Production Kreative

La chaîne complète : un formulaire rempli entre, un pack de créatives Meta
auditées sort, et personne n'intervient entre les deux sauf trois arrêts
prévus. Tout se fait en **français**, accents compris.

## Objectif

Kreative vend des packs de créatives statiques Meta. Ce skill orchestre leur
production : relever les formulaires, construire le dossier client, aspirer le
site, écrire la stratégie et les prompts, chiffrer, générer par le MCP
Higgsfield, auditer, montrer. Résultat attendu : des masters 1:1 au texte
peint, gate franchi, page de suivi ouverte, coût réel journalisé.

## Quand utiliser ce skill

- « Un nouveau formulaire est arrivé », « relève les commandes », « regarde
  s'il y a du nouveau côté Zite »
- « Produis le pack de [marque] », « regénère c07 de [marque] », « où en est
  la commande [marque] ? »
- « Combien coûterait le pack de [marque] ? » (devis sans générer)

## Quand NE PAS utiliser ce skill

- Une demande de vidéo, d'audio ou de 3D : la chaîne ne produit que des
  créatives statiques.
- Un client hors Kreative : ce skill porte les règles et la banque d'UNE
  agence, il n'est pas générique.

## Quick start

```
set -a && source .env && set +a               # les clés, jamais en clair
python3 scripts/kreative.py verifier          # 9 contrôles, tout doit être OK
python3 scripts/pipeline/zite.py relever      # les nouveaux formulaires
python3 scripts/kreative.py etat <ardoise>    # où en est une commande
```

## Règles d'or

1. **Trois arrêts, pas un de plus.** Brief incomplet sur une valeur
   indéductible, site inexploitable (motif écrit dans `marque/scraping.json`),
   devis au-dessus du plafond (120 crédits par défaut). Tout le reste se
   tranche, se fait, et se signale en fin de sortie dans « Ce qui a manqué ».
2. **La génération passe par le MCP Higgsfield, uniquement.** Jamais la CLI,
   jamais une API directe. Le protocole d'appel est
   décrit dans `references/chaine-kreative.md`.
3. **Les fichiers locaux font foi.** L'état d'une commande est
   `commandes/<ardoise>/commande.json` et ses créas ; la plateforme de revue
   n'est qu'une projection. Un doute se lève en lisant le disque, pas en
   se souvenant.
4. **Le devis se valide avant de générer.** `preparer` écrit le lot et son
   coût au tarif mesuré (`scripts/pipeline/couts.py`) ; au-dessus du plafond,
   c'est un arrêt. Le solde se relève avant et après chaque lot, et
   `recolter` journalise l'écart : c'est ce qui garde la table juste.
5. **Un prompt est un champ de fichier, jamais une chaîne assemblée au vol.**
   Ce que `prompts` affiche est ce qui part au modèle, à l'octet près.
6. **Aucun secret ne s'écrit** dans un fichier livrable, un commit ou une
   sortie : les clés vivent dans le `.env` de l'espace de travail et se
   référencent par leur nom.
7. **Zéro tiret cadratin, zéro emoji** dans tout ce qui est produit.

## Workflow

Étape 0, une fois par poste : `python3 scripts/kreative.py verifier` liste les
neuf prérequis et dit quoi installer (détail : `references/installation.md`).

1. **Relever et ouvrir.** `python3 scripts/pipeline/zite.py relever` simule et
   affiche ce qui arriverait ; avec `--appliquer`, il range chaque soumission
   dans `commandes/_zite/`, ouvre la commande (`commandes/<ardoise>/` : brief
   figé, pièces jointes rangées) et télécharge les fichiers. Une deuxième
   soumission de la même marque sous 30 jours complète la commande existante :
   le brief le plus récent gagne, les pièces jointes s'accumulent. Le mode
   sans personne, qui enchaîne tout : `python3 scripts/orchestrateur.py
   tourner`.
2. **Aspirer le site.** `python3 scripts/pipeline/scraper.py aspirer
   <ardoise>` :
   pages parcourues dans Chromium, charte MESURÉE sur les styles calculés
   (`marque/charte-site.json`), textes (`site.json`), images dédoublonnées et
   indexées (`assets-site/index.json`), candidats logo scorés, une capture
   par page dans `marque/captures/`. Si le site refuse, le motif est écrit
   dans `marque/scraping.json` : c'est l'arrêt 2 si le brief seul ne porte
   pas la DA.
3. **La stratégie.** Suivre `references/strategie-creative.md`, qui est le
   métier entier : audit visuel des captures, angles, copy, choix des assets,
   prompts. Sa sortie s'écrit dans `commandes/<ardoise>/creas/` (un JSON par
   créa) et se relit avec `python3 scripts/kreative.py prompts <ardoise>`.
4. **Chiffrer et décider.** `python3 scripts/pipeline/moteur.py preparer
   <ardoise>` écrit le lot dans `jobs/` avec son devis. Plafond dépassé :
   arrêt 3. Sinon : GO.
5. **Générer, par le MCP.** Relever `balance`, monter les références
   (`media_upload`, PUT, `media_confirm`), lancer `generate_image_batch` par
   paquets de 12 maximum, attendre `jobs_wait`, télécharger chaque
   `result_url` immédiatement (les rendus expirent en sept jours). Le protocole est dans
   `references/chaine-kreative.md`.
6. **Récolter.** `python3 scripts/pipeline/moteur.py recolter <ardoise>
   --resultats <fichier.json> --solde-avant X --solde-apres Y` range les
   masters et journalise le coût réel.
7. **Auditer.** `python3 scripts/kreative.py audit <ardoise>` : le gate lit
   les images (texte peint contre copy, par OCR). Un échec bloque ; une
   alerte se vérifie À L'ŒIL sur le master en pleine résolution avant toute
   conclusion, l'OCR se trompe sur le petit texte.
8. **Montrer.** `python3 scripts/kreative.py page <ardoise>` écrit la page de
   suivi ; les masters restent dans `commandes/<ardoise>/masters/`.
9. **Publier en revue** (si la plateforme est branchée sur le poste) :
    `python3 scripts/pipeline/publier.py <ardoise> --dry-run` puis sans
    `--dry-run`. Les commentaires de l'équipe redescendent avec
    `python3 scripts/pipeline/retours.py <ardoise>`, et chaque reprise se
    range dans `reprises/` sans rien écraser.

## L'espace de travail

Le skill est immuable ; les données clientes vivent ailleurs. L'emplacement
se choisit avec la variable `KREATIVE_TRAVAIL` (défaut : `~/Kreative`), et
`commandes/` s'y crée au premier usage. Le `.env` (dont `ZITE_API_KEY`) vit
là aussi, jamais dans le skill.

## En cas de doute

- Le métier créatif (angles, copy, prompts, assets, banque de références) :
  `references/strategie-creative.md`.
- L'écriture des prompts, y compris la phrase de fin obligatoire :
  `references/strategie-creative.md`, et elle seule.
- Le poste, les clés, les prérequis : `references/installation.md`.
- La carte du système, module par module : `references/architecture.md`.
