# Conventions de rangement et de mise à jour

Ce document fait autorité sur la forme des dossiers de commande. Le code s'y
conforme, pas l'inverse. Si une règle d'ici gêne le code, on change la règle
ici d'abord, en disant pourquoi.

Motif de son existence : au 11/09/2026 deux conventions coexistaient dans
`commandes/`. Une vieille commande portait `brief.md`, `ETAT.md`, `out/`, `out-v2/`,
`out-v3/`, `creas/`, `creas-v2/`, `creas-v3/`, `refs/`. `kreative` portait
`commande.json`, `journal.jsonl`, `suivi.html`, `masters/`, `dist/`. Aucun
script ne pouvait lire les deux, et les suffixes `-v2` et `-v3` étaient des
reprises rangées à la main.

## 1. Un dossier par commande

Le nom du dossier est l'ardoise : le nom de la marque normalisé par
`etat.ardoise()`, sans accent ni majuscule, les séparateurs en tirets.
`Les Bains de Dax` devient `les-bains-de-dax`. Jamais de date, jamais de suffixe
de version dans le nom du dossier : la version vit à l'intérieur.

Une marque qui recommande une seconde fois garde son dossier. C'est la commande
qui est neuve, pas le client.

Cette arborescence prolonge celle que `pipeline/etat.py` crée déjà. Les quatre
dossiers existants (`creas/`, `marque/`, `masters/`, `dist/`) ne changent ni de
nom ni de rôle : ce serait casser le pipeline pour une question de goût. Les
ajouts sont `brief/` et `reprises/`, plus trois sous-dossiers de `marque/`.

```
commandes/<ardoise>/
  commande.json          etat canonique, seule source de verite machine
  journal.jsonl          historique en ajout seul, jamais reecrit
  suivi.html             page de suivi, regeneree, jamais editee a la main
  brief/                 AJOUT
    soumission.json      la reponse Zite brute, figee
    brief.md             version lisible, derivee
    pieces-jointes/      les fichiers televerses par le client
  marque/
    charte.json          palette et polices, deja produit par l'intake
    tokens.json          jetons de design
    composants.json      AJOUT : badges, pilules, ombres, bordures (CDC 4.1)
    logo/                AJOUT : le logo dans ses declinaisons trouvees
    assets-site/         AJOUT : ce que le scraper a rapporte du site
    captures/            captures de pages, pour lecture de la DA
    references/          images produit retenues
  creas/
    cNN.json             l'etat de la crea : copy, prompt, audit, compteurs
  masters/
    cNN.png              l'image generee, une seule fois, en 9:16
  dist/
    cNN/                 les trois formats : cNN-1x1, cNN-4x5, cNN-9x16
  reprises/              AJOUT
    cNN/<horodatage>/    l'etat, le master et les formats precedents
```

## 2. La soumission brute ne se modifie jamais

`brief/soumission.json` est la réponse Zite telle qu'elle est arrivée. On ne la
corrige pas, on ne la complète pas, on ne la reformate pas. Tout le reste en
dérive : `brief.md`, les champs de `commande.json`, les prompts.

Conséquence recherchée : n'importe quel pack est rejouable à partir de sa
soumission. Si une créa est fausse, on sait si c'est le brief qui manquait ou le
moteur qui a dérivé, et cette distinction est perdue dès qu'on retouche le brut.

Un champ absent du brief reste absent. Il ressort en `[A COMPLETER: ...]` dans
le copy, jamais en valeur plausible.

## 3. Une reprise n'écrase rien

Corriger une créa met de côté l'ancienne version dans `reprises/cNN/<horodatage>/`,
avec son `cNN.json`, son master et ses trois formats, puis produit la nouvelle à
sa place. Le compteur de reprises de la créa est incrémenté. Les autres créas ne
bougent pas.

C'est ce qui remplace les `out-v2` et `out-v3` : la reprise est rangée sous la
créa concernée, pas dans un dossier parallèle qui duplique tout le pack alors
qu'une seule image a changé.

## 4. Le journal est en ajout seul

`journal.jsonl` reçoit une ligne par événement, horodatée en UTC. On n'en retire
jamais une ligne. L'état de la commande doit pouvoir être reconstitué à partir du
seul journal si `commande.json` est perdu ou corrompu.

## 5. Les états sont ceux du code

Commande : `recue`, `intake`, `strategie`, `generation`, `composition`, `audit`,
`livree`, `echec`.

Créa : `prevue`, `briefee`, `master_ok`, `composee`, `retenue`, `rejetee`.

Ces listes vivent dans `pipeline/etat.py` (`ETATS_COMMANDE`, `ETATS_CREA`). Ce
document les recopie pour la lecture ; en cas d'écart, c'est le code qui fait foi.

## 6. Ce qui est versionné

Le dépôt porte le système : le code, les gabarits, le répertoire d'archétypes,
l'analyse, les conventions, le back-office sans ses données.

Il ne porte pas les dossiers de commande, le corpus, les inspirations, ni les
rendus binaires. Deux raisons, et la première suffit : les briefs contiennent les
données personnelles des clients de Kreative et des assets qui leur appartiennent,
et le point 8 du cahier des charges impose l'exécution locale sans connecteur
SaaS. La seconde est que git garde chaque version de chaque binaire pour
toujours.

Le détail exact est dans `.gitignore`, qui fait foi.

## 7. Créer ou migrer un dossier

Ne jamais créer un dossier de commande à la main : `outils/ranger.py` le fait.
Il crée l'arborescence complète, écrit un `commande.json` valide et ouvre le
journal.

Le même outil migre un ancien dossier vers cette convention. Il copie, il ne
déplace pas, et il ne supprime jamais l'ancien : la suppression reste une
décision humaine, prise après vérification.
