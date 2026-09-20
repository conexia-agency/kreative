# La chaîne, du brief aux visuels

Objectif de cette étape : un brief entre, les visuels sortent, sans coller un
prompt à la main. Le prompt reste visible et rejouable pour les corrections.
La veille concurrentielle est hors périmètre, elle passe en phase 2.

## Les cinq commandes

```bash
cd kreative

python3 kreative.py brief exemples/brief-kreative.json     # commande + plan complet
python3 kreative.py prompts tahiti-premium-water      # voir tous les prompts
python3 kreative.py generer tahiti-premium-water      # tout générer, en un appel
python3 kreative.py composer tahiti-premium-water     # les 3 formats
python3 kreative.py page tahiti-premium-water         # la page de suivi
python3 kreative.py etat tahiti-premium-water         # où en est la commande
```

Pour corriger une créa et la seule :

```bash
python3 kreative.py prompt tahiti-premium-water c12 --editer
python3 kreative.py generer tahiti-premium-water --crea c12
```

Corriger un prompt remet la créa en attente, efface son master et ses rendus,
incrémente son compteur de reprises. Les onze autres créas ne bougent pas.

## Ce qui garantit que le prompt affiché est le prompt envoyé

La consigne de cadrage est écrite dans le champ `prompt.scene` au moment de la
planification, pas ajoutée au moment de l'appel. `generation.construire_prompt`
ne fait donc que retourner le champ, sans rien concaténer. Conséquence : ce que
`prompts` affiche part au modèle à l'octet près, et un prompt corrigé à la main
part tel qu'il a été corrigé.

Un prompt assemblé au dernier moment serait invisible et non modifiable, ce qui
est exactement le défaut que cette étape supprime.

## Ce que le plan décide, et pourquoi

### La plupart des créas ne passent pas par un modèle

Mesuré sur le corpus : 91 créas sur 120 ne demandent aucun appel à un modèle
d'image. Chaque archétype porte donc son mode de fabrication, et
`generer` ne prend que ceux qui en ont un.

Sur le brief d'exemple : 11 créas composées, 1 générée, 2 crédits
pour le pack entier. Sur le brief Aloa Design, verticale agence : 12 composées,
0 crédit, ce qui est conforme au corpus où 23 créas d'agence sur 23 sont
composées.

### La contrainte réelle est le nombre d'ARCHITECTURES, pas de couples

Correction d'une affirmation antérieure. J'avais présenté le stock de couples
ressort plus archétype comme la mesure de la diversité d'un pack. Le gate a
prouvé que c'est faux : les créas c04 et c24 du pack Growth, deux couples
distincts mais un seul archétype, sont ressorties **identiques à 98 %**. Deux
créas qui partagent leur architecture se ressemblent quel que soit leur hook.

La règle exploitable est donc plus dure : **un pack de N créas demande N
architectures disponibles.**

| Verticale | Architectures | Couples | Starter 12 | Growth 24 | Scale 48 |
|---|---:|---:|---|---|---|
| complément et santé | 18 | 44 | ok | manque 6 | manque 30 |
| cosmétique et soin | 19 | 46 | ok | manque 5 | manque 29 |
| agence et service B2B | 20 | 50 | ok | manque 4 | manque 28 |
| e-commerce produit | 18 | 44 | ok | manque 6 | manque 30 |
| alimentaire et boisson | 19 | 46 | ok | manque 5 | manque 29 |
| service en ligne et SaaS | 20 | 50 | ok | manque 4 | manque 28 |

**Seul le pack Starter est couvert sans répétition.** Growth en manque 4 à 6,
Scale 28 à 30. La règle de doublement du volume (4.6) est ce qui rend l'écart
si large : un Scale vendu 24 impose 48 architectures.

Deux voies pour combler, et la seconde est la bonne :

1. écrire une trentaine de gabarits de plus, ce qui est du travail linéaire ;
2. donner à chaque gabarit deux ou trois **variantes de mise en page** réelles,
   texte à gauche ou à droite, produit en haut ou en bas, registre clair ou
   sombre. Vingt gabarits à trois variantes font soixante architectures, ce qui
   couvre Scale. C'est la voie économique, et elle reste honnête tant que les
   variantes sont de vraies architectures et non des permutations cosmétiques.

Le gate distingue les deux cas : une répétition **évitable**, quand il restait
des architectures libres, est un échec bloquant ; une répétition **inévitable**,
quand le répertoire est épuisé, est une alerte assortie du nombre manquant.

### Aucun chiffre n'est inventé

Un champ absent du brief produit un marqueur `[A COMPLETER: champ]` visible
dans le copy et signalé par `etat`. Une créa qui porte un marqueur ne doit pas
partir en l'état. Le brief Aloa a volontairement `offre.prix` à `null` pour que
le mécanisme soit vérifiable.

Une offre sans devise n'est pas écrite : `_formuler_offre` refuse un prix sans
devise, conformément à la règle Conexia.

## Le contrat grammatical du brief

Un moteur de gabarits casse le français s'il n'est pas discipliné. Chaque champ
a un rôle et un seul :

| Champ | Rôle | Exemple |
|---|---|---|
| `douleurs` | groupe nominal | « l'attente de deux à trois semaines » |
| `benefices` | proposition complète | « vos visuels arrivent en 48 heures » |
| `causes` | groupe nominal | « le délai de production » |
| `objections` | phrase citée | « ça va se voir que c'est fait par une IA » |
| `cible` | groupe nominal | « les commerces qui publient sur Facebook » |
| `temoignages` | phrase citée | |
| `preuves[].valeur` | valeur brute | `48 à 72`, l'unité est dans `unite` |
| `decors` | lieu sans heure | l'heure est portée par `lumiere` |

Une passe d'élision corrige ensuite les contractions mécaniques (à les, que un,
de a) et les majuscules après un point. Elle ne remplace pas une relecture,
elle enlève le bruit qui la parasite.

## La composition

Quinze gabarits, un par archétype, dans `compositeur/gabarits.py`. Le système
visuel commun est dans `compositeur/design.py` : polices Inter, Fraunces et
JetBrains Mono embarquées en base64, palette dérivée de la charte du client,
échelle typographique en pixels.

**Rupture avec la version précédente.** L'ancien compositeur rendait un 9:16
puis recadrait au centre pour les deux autres formats. Cela garantissait
l'identité pixel à pixel, mais obligeait tout le texte à vivre dans la bande
22 % à 78 %, seule zone commune. Or le corpus place le texte en haut dans 67
créas sur 120. Le recadrage interdisait donc la mise en page dominante du
marché. Le rendu est maintenant direct pour chaque format, à partir du même
gabarit, du même master et du même copy.

Ce que `verifier_coherence` contrôle à la place : même fichier master, même
copy mot pour mot, même gabarit. C'est ce que la règle 4.2 demande vraiment,
« le même visuel, seul le positionnement change ».

### Contrôles ajoutés parce que le rendu les a révélés

Aucun de ces quatre défauts n'était visible avant de regarder les images.

1. **Packshot non détouré.** Un PNG sans canal alpha se colle en rectangle avec
   son fond. La chaîne teste la transparence des quatre coins et le signale.
2. **Accroche trop longue pour son archétype.** Un titre de note tient en deux
   lignes, pas en six. Chaque archétype porte un `accroche_max`, et le
   dépassement remonte au plan.
3. **Requête de recherche fabriquée.** Le gabarit `emprunt_recherche` prend le
   champ `questions_cible` du brief, jamais l'accroche : une accroche de marque
   dans une barre de recherche tue le format.
4. **Comparaison mensongère.** `comparaison_vignettes` exige désormais
   `assets.comparaison.avant` et `.apres`, deux champs distincts. Prendre
   `captures[0]` et `captures[1]` affichait un visuel du client sous
   l'étiquette « Sans le client ».

À quoi s'ajoutent deux corrections de fond : la rature est rouge et non de la
couleur de marque, sinon elle se lit comme un soulignement décoratif ; et elle
est posée par le moteur de texte et non en absolu, sinon elle tombe entre les
deux lignes d'un item long.

## Le langage caméra des scènes générées

Manque signalé par Tom, et il était réel : les prompts de scène disaient
« photographie publicitaire, profondeur de champ courte », ce qui ne pilote
rien. Le modèle rendait des plans de face à hauteur d'oeil, sans intention.

`pipeline/photographie.py` encode la doctrine photoréalisme d'aloa-design
(`aloa-pack/aloa-design/14-prompt-photorealisme.md`), six couches dans un ordre
imposé : caméra et objectif, pellicule, lumière nommée, matière et
micro-détails, composition de directeur photo, négatif.

Chaque archétype générateur porte son **intention de prise de vue**, parce
qu'un archétype est une façon de regarder autant qu'une mise en page :

| Archétype | Optique | Lumière |
|---|---|---|
| Métaphore par changement d'échelle | Canon R5 35mm f/1.8, à hauteur de genou vers le haut | golden hour rasante |
| Produit dans un décor signifiant | Leica Q3 28mm f/1.7 | fenêtre nord, chute douce |
| Matière en bandeau haut | Canon R5 50mm macro f/2.8 | flash nu latéral, ombre dure |

La pellicule vient de la verticale : Kodak Gold sur l'alimentaire, Portra sur
la cosmétique, Ektar sur le complément, Superia sur les services. Un brief peut
imposer `optique`, `lumiere_cle` et `pellicule`.

**Deux corrections que ce câblage a imposées.** Les gabarits de scène ne
décrivent plus que le sujet et le lieu : la lumière et le cadrage appartiennent
aux couches, et les laisser dans le gabarit produisait deux consignes
contradictoires dans le même prompt. Et les champs `decors` et `matieres` du
brief ne mentionnent plus jamais la lumière, pour la même raison.

**Un défaut que le rendu a révélé.** L'archétype « métaphore par changement
d'échelle » était classé « généré » et son gabarit mettait le produit DANS le
prompt. Le master est sorti avec une bonbonne générée à l'étiquette illisible,
exactement le défaut mesuré sur le corpus. Il est passé en « mixte » : le modèle
fabrique le LIEU, le packshot réel est incrusté ensuite. **Plus aucun archétype
ne fait générer un produit.**

## Les deux rôles typographiques

Le dossier `aloa-idee-crea/typographie` écarte les grotesques neutres pour la
typographie de marque : on y trouve des grasses rondes et des serifs à
caractère. J'avais bâti sur Inter, qui est précisément un grotesque neutre.

La correction ne consiste pas à tout remplacer, parce qu'il y a deux rôles :

- **marque** : Outfit, plus Fraunces pour le serif. Porte le discours de la créa.
- **système** : Inter, cantonné aux archétypes de format emprunté. Une note de
  téléphone, un courriel et une conversation imitent une interface : y mettre
  une police de caractère trahirait la composition en une seconde, et
  l'illusion est le seul avantage de ces formats.

Outfit n'est disponible localement qu'en 400 et 700, pas en 900. La graisse
retenue est donc la 700, ce qui reste nettement plus caractérisé qu'Inter.

## Le gate qualité

Sept contrôles, aucun ne demande de jugement. Chacun se calcule et cite sa
pièce. `python3 kreative.py audit <marque>` sort en code 1 si un contrôle
bloque, ce qui permet de l'enchaîner dans un script sans lire la sortie.

| Contrôle | Ce qu'il mesure |
|---|---|
| C1 texte gravé | OCR du master : le prompt interdit tout texte, si l'OCR en lit, le modèle en a gravé |
| C2 doublon visuel | empreinte perceptuelle 8x8, deux créas identiques comptent pour une |
| C3 gabarit répété | évitable, donc bloquant, ou inévitable, donc chiffré |
| C4 chiffre non sourcé | tout nombre du copy doit se retrouver dans le brief |
| C5 marqueur | une créa portant `[A COMPLETER]` ne part pas |
| C6 contraste | 4,5:1 minimum, texte sur fond et texte sur bouton |
| C7 débordement | mesuré dans le navigateur au rendu, pas sur le PNG |

**Ce que le gate a réellement attrapé** sur le pack Growth, et que la relecture
avait laissé passer : du texte gravé par le modèle dans un master, « nein Sica
ieee », exactement le mode de défaillance mesuré sur le corpus ; deux créas
identiques à 100 % ; et trois débordements de texte coupé par le cadre.

Le C1 mérite une précision honnête : durcir le prompt n'a pas suffi du premier
coup. Il a fallu deux régénérations. C'est cohérent avec la mesure du corpus,
28 % des créas passées par un modèle portent ce défaut, et cela confirme que le
contrôle est nécessaire plutôt que le prompt suffisant.

## Ce qui reste à faire

1. **Les variantes de gabarit**, pour couvrir Growth et Scale sans répétition.
   C'est le chantier le plus rentable : trois variantes par gabarit suffisent.
2. **L'intake**, pour remplir une partie du brief depuis le site du client.
3. **Deux gabarits perfectibles** : `callouts_produit` où les pilules frôlent
   le produit en carré, et `comparaison_vignettes` qui exige deux captures que
   peu de briefs fourniront.
