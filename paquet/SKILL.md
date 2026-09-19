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
2. **Le skill créatif se lit EN ENTIER avant la première stratégie.**
   `references/strategie-creative.md` se lit en une seule lecture, du début à
   la fin, avant d'écrire la moindre ligne de stratégie : c'est lui le métier,
   pas ce fichier-ci. Les captures de `marque/captures/` se REGARDENT (outil
   Read), la banque de références s'ouvre sous registre (`banque.py`), et la
   sortie passe par `plan.py importer`. Rien de tout cela n'est optionnel :
   `moteur.py preparer` REFUSE un plan qui n'est pas passé par l'import, et
   l'import refuse un plan écrit sans avoir ouvert la banque.
3. **La génération passe par le MCP Higgsfield, uniquement.** Jamais la CLI,
   jamais une API directe. Le protocole d'appel est
   décrit dans `references/chaine-kreative.md`.
4. **Les fichiers locaux font foi.** L'état d'une commande est
   `commandes/<ardoise>/commande.json` et ses créas ; la plateforme de revue
   n'est qu'une projection. Un doute se lève en lisant le disque, pas en
   se souvenant.
5. **Le devis se valide avant de générer.** `preparer` écrit le lot et son
   coût au tarif mesuré (`scripts/pipeline/couts.py`) ; au-dessus du plafond,
   c'est un arrêt. Le solde se relève avant et après chaque lot, et
   `recolter` journalise l'écart : c'est ce qui garde la table juste.
6. **Un prompt est un champ de fichier, jamais une chaîne assemblée au vol.**
   Ce que `prompts` affiche est ce qui part au modèle, à l'octet près.
7. **Aucun secret ne s'écrit** dans un fichier livrable, un commit ou une
   sortie : les clés vivent dans le `.env` de l'espace de travail et se
   référencent par leur nom.
8. **Zéro tiret cadratin, zéro emoji** dans tout ce qui est produit.

## Workflow

Étape 0, une fois par poste : `python3 scripts/pipeline/sante.py` puis
`python3 scripts/kreative.py verifier`. Chaque ligne dit ce qui est branché,
ce qui manque et le remède (détail : `references/installation.md`). Verdict
« ne doit pas tourner » : on répare, on ne contourne pas.

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
   par page dans `marque/captures/`. `scraper.py` est la RÉCOLTE et la
   MESURE, obligatoires ; il ne vaut pas analyse : ses captures figent la
   page au chargement, accordéons fermés, pop-up par-dessus. Ensuite,
   ANALYSER réellement : ouvrir le site avec le MCP Chrome DevTools, pages
   produit et FAQ comprises, déplier avant de capturer, relever la DA avec
   `evaluate_script`, puis tenter la bibliothèque publicitaire Meta (non
   bloquante : deux essais, on le dit en une ligne, on poursuit). Navigateur
   indisponible : travailler sur les captures est permis, mais cela se dit à
   l'utilisateur au moment où cela arrive. Le MCP Chrome ne lit jamais des
   fichiers locaux. Si le site refuse le scraping, le motif est écrit dans
   `marque/scraping.json` : c'est l'arrêt 2 si le brief seul ne porte pas
   la DA.
3. **Ouvrir la banque de références, sous registre.**
   `python3 scripts/pipeline/banque.py ouvrir <ardoise>` liste la famille et
   les planches. Ouvrir TOUTES les planches listées (outil Read), puis
   consigner : `banque.py lue <ardoise> --planches ...`, retenir les
   références en pleine résolution `banque.py retenir <ardoise> --refs ...
   --du-client ...`, et `banque.py extraire <ardoise>` : une image par
   référence retenue (les fichiers HD portent deux créas côte à côte, les
   lire tels quels partage la résolution). Ouvrir les fichiers découpés UN
   PAR UN : c'est là que se lit la finition, pas sur les planches. Sans ce
   registre, le plan sera refusé à l'étape 4.
4. **La stratégie.** Lire d'abord `references/strategie-creative.md` EN
   ENTIER (règle d'or 2), puis l'appliquer jusqu'aux prompts finalisés, dans
   son format de sortie, écrit dans UN fichier markdown. Ranger ensuite ce
   plan : `python3 scripts/pipeline/plan.py importer <ardoise> --fichier
   <plan.md>`. C'est l'import qui fait tourner les gates (banque ouverte et
   retenue, copy dans le prompt, zéro tiret cadratin) ; un refus cite la
   règle du skill en cause, on reprend la créa, jamais le contournement. On
   n'écrit JAMAIS `creas/` à la main. Relecture :
   `python3 scripts/kreative.py prompts <ardoise>`.
5. **Chiffrer et décider.** `python3 scripts/pipeline/moteur.py preparer
   <ardoise>` écrit le lot dans `jobs/` avec son devis. Il REFUSE un plan qui
   n'est pas passé par `plan.py importer` ou une banque sans registre : c'est
   le verrou, pas une erreur à contourner. Plafond dépassé : arrêt 3.
   Sinon : GO.
6. **Générer, par le MCP.** Relever `balance`, monter les références
   (`media_upload`, PUT, `media_confirm`), lancer `generate_image_batch` par
   paquets de 12 maximum, attendre `jobs_wait`, télécharger chaque
   `result_url` immédiatement (les rendus expirent en sept jours). Le protocole est dans
   `references/chaine-kreative.md`.
7. **Récolter.** `python3 scripts/pipeline/moteur.py recolter <ardoise>
   --resultats <fichier.json> --solde-avant X --solde-apres Y` range les
   masters et journalise le coût réel.
8. **Auditer et relire.** `python3 scripts/kreative.py audit <ardoise>` : le
   gate lit les images (texte peint contre copy, par OCR). Un échec bloque ;
   une alerte se vérifie À L'ŒIL sur le master en pleine résolution avant
   toute conclusion, l'OCR se trompe sur le petit texte. Pour cette
   relecture : `python3 scripts/pipeline/loupe.py <ardoise>` découpe chaque
   master en quatre zones qui se recouvrent, dans `session/loupe/`. Ouvrir
   chaque zone une par une : un texte peint ne se juge jamais sur la vignette
   entière, toutes les fautes se voient au zoom.
9. **Montrer.** `python3 scripts/kreative.py page <ardoise>` écrit la page de
   suivi ; les masters restent dans `commandes/<ardoise>/masters/`.
10. **Publier en revue, étape FACULTATIVE** : à sauter si les accès `PUBLIE_*` ne sont pas posés, le pack est déjà livré au complet par l'étape 9. Si la plateforme est branchée sur le poste :
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
- L'écriture des prompts : `references/strategie-creative.md`, et elle
  seule. Une exception, décidée le 19/09/2026 : sa phrase de fin « Nano
  Banana Pro en restant gratuit » ne s'écrit plus, le connecteur fixe le
  modèle et la facturation par ses paramètres d'appel.
- Le poste, les clés, les prérequis : `references/installation.md`.
- La carte du système, module par module : `references/architecture.md`.
