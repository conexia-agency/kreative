# Consignes de session

Chargé au début de chaque session ouverte sur ce dépôt. Vaut pour **toutes les
commandes**, jamais pour une seule.

## Règle zéro : lire `skill/SKILL.md` EN ENTIER, à chaque commande

**379 lignes, 18 sections, de la première à la dernière.** Pas un survol, pas les
sections dont on croit se souvenir, pas celles qui semblent utiles sur le moment.
Le fichier entier, avant d'écrire la moindre ligne de stratégie ou de prompt.

C'est la règle qui rend toutes les autres superflues. Tout ce qui suit dans ce
fichier n'existe que parce que le skill n'a pas été lu en entier.

**La preuve, mesurée.** Deux packs Attar Studio ont été produits les 19 et
20/09/2026. Deux sections du skill n'avaient jamais été ouvertes :
« Performance Meta & hiérarchie de layout » et « Gestion des assets ». Les deux
échecs viennent exactement de là :

- La formule anti-régénération exacte est dans « Gestion des assets ». Elle dit
  « ne réinvente aucun détail, aucun objet **ni aucun texte** ». Une paraphrase
  affaiblie a été employée à la place, et le modèle a réécrit les étiquettes des
  flacons, inventant un format 80 ml puis 78 ml qui n'existe pas au catalogue.
- « Le prompt de génération » dit de **nommer le format visuel** dans le prompt.
  À la place, le prompt citait la référence de la banque, ce qui a produit des
  décalques au lieu de créas.
- « Performance Meta » impose de faire varier l'architecture d'une créa à
  l'autre, de varier les fonds clairs et sombres, et de passer trois tests sur
  chaque créa : rareté, lecture muette, micro-question. Rien de tout cela
  n'avait été appliqué.

Aucun de ces problèmes n'appelait un arbitrage de l'utilisateur. Tous étaient
écrits dans le skill.

**Les sections à ouvrir**, pour vérification : Contexte d'exécution · Règles d'or
· Les échelles continues · Audit du site · Ce qui fait GAGNER et PERDRE ·
Performance Meta & hiérarchie de layout · Le prompt de génération · Lecture de la
bibliothèque Meta · Banque de créas de référence · Process · Répertoire d'angles ·
Packs · Format de sortie · Style de sortie.

**Le process du skill se suit dans l'ordre**, étapes 0 à 6, sans en sauter. La
synthèse stratégique de l'étape 3 pose les curseurs qui décident du registre de
toute la copy : la sauter, c'est écrire à l'aveugle.

## La banque nourrit le pack globalement, jamais créa par créa

Le skill est explicite :

> « La banque nourrit le pack globalement, **jamais créa par créa**. Tu ne colles
> pas une référence à une créa, comme s'il fallait une inspiration par visuel. Tu
> absorbes l'ensemble de ta sélection et tu composes le pack à partir de ce
> vocabulaire visuel, adapté au client. »

**Les deux fautes symétriques, toutes deux constatées :**

- **Ignorer la banque** et inventer le design. Donne des photographies de produit
  génériques avec du texte posé dessus, toutes bâties pareil. C'est le pack du
  19/09 : vingt-quatre références citées, aucune utilisée.
- **Coller une référence par créa** et la transposer littéralement. Donne des
  décalques qui ne tiennent pas, parce qu'une construction pensée pour un autre
  produit et un autre message ne se transpose pas telle quelle. C'est le pack du
  20/09.

Ce qu'on reprend : la structure de layout, la composition, le traitement du fond
et de la matière, le rapport texte/image, le type de mise en scène, le niveau de
finition. Une même référence peut irriguer plusieurs créas, et une créa peut en
croiser plusieurs. Ce qui reste non négociable, c'est que les créas du pack
soient radicalement différentes entre elles.

## La copy ne se reprend JAMAIS d'une référence

> « Ce que tu ne reprends jamais : ses couleurs, ses polices, **sa copy**, sa
> marque, ses produits, ses visuels. Tout ça vient du client. »
> « Les headlines sont toujours **dérivées de l'angle et du brief, jamais
> plaquées**. »

Le skill liste des **motifs** de headline : affirmation définitive,
question-douleur, hook négatif, secret ou curiosité, douleur incarnée en une
phrase, différenciation, bénéfice en contraste. Le motif se réutilise. **La
phrase de la référence, jamais.**

Mesuré le 20/09 sur Attar Studio : cinq accroches sur dix-huit étaient des
traductions de la banque. « Notre flacon n'est pas comme les autres » venait de
EC1-07, « N'achetez pas ce parfum » de EC1-13, « Notre politique de retour ? Vous
n'en aurez pas besoin » de UG6-02. Elles sonnaient creux parce qu'elles ne
sortaient pas du brief du client.

Rappels de dosage, du skill : headline courte et frappante, viser moins de dix
mots, si un mot peut sauter il saute. Sous-titre d'une ligne, deux au maximum,
jamais trois, et il ajoute UNE précision. Le pavé est la faute numéro un.

## L'analyse du site se fait au navigateur

**Chrome DevTools MCP est l'outil d'analyse. Playwright ne l'est pas.**

`pipeline/scraper.py` pilote Playwright, télécharge et range les assets,
packshots haute définition compris, et mesure la charte dans `charte-site.json`.
C'est un outil de **récolte et de mesure**, obligatoire, mais ses captures ne
valent pas analyse : elles figent la page au chargement, accordéons fermés,
onglets non cliqués, pop-up par-dessus le contenu.

**Ordre, pour toute commande :** `scraper.py aspirer` récolte et mesure, puis
Chrome DevTools ouvre le site et l'analyse réellement, pages produit et FAQ
comprises, en dépliant avant de capturer et en relevant les valeurs de DA avec
`evaluate_script`, puis la bibliothèque publicitaire Meta.

Le 19/09, vingt-cinq captures produites et une seule ouverte. Ont été manqués :
le badge UNISEXE des fiches produit alors que toute la copy était au féminin, la
tenue officielle « jusqu'à 10h » alors qu'une créa en promettait seize, une
troisième police, les mentions cruelty free et vegan, une promotion en cours, et
le portrait de marque du hero, caché par une pop-up, d'où la conclusion erronée
que le client n'avait aucune photographie lifestyle.

Si le navigateur est indisponible, travailler sur les captures est permis, mais
cela se dit à l'utilisateur au moment où cela arrive.

## La bibliothèque publicitaire Meta se consulte à chaque fois

Sans elle, on ignore quels angles le client diffuse déjà et on risque de les
redoubler. Elle reste non bloquante : si elle ne charge pas ou exige une
connexion, on abandonne après deux tentatives, on le dit en une ligne, et on
poursuit. Ce qui n'est pas permis, c'est de ne pas essayer.

## Le texte peint par le modèle

Le contrat de `pipeline/etat.py` dit que la copy ne part jamais dans le prompt et
que `compositeur/` la pose ensuite. Ce dossier **n'existe pas** dans le dépôt, et
`pipeline/plan.py` exige aujourd'hui l'inverse. Tant que les deux se
contredisent, le signaler à l'utilisateur plutôt que de suivre `plan.py` en
silence.

Tant que le texte est peint, deux précautions :

- **Ne jamais nommer une police dans la phrase qui porte le texte à afficher**, et
  ne jamais employer un mot de liaison comme « puis » entre deux textes à
  afficher. Le modèle les peint. Constaté quatre fois : « DM Sans: » devant le
  nom d'un client, « Glacial » dans un titre, « puis » dans une pastille.
  `plan.py` garde contre ce cas mais sa liste ne contient ni DM Sans, ni Glacial
  Indifference, ni IBM Plex Mono : la compléter.
- **Relire chaque master au zoom, jamais sur la vignette.** Le modèle reconstruit
  les étiquettes des flacons passés en référence et se trompe environ quatre fois
  sur dix. Cadrer les produits pour que les mentions légales ne soient pas
  lisibles réduit le risque à la source.
