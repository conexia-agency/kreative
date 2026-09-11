# Deux moteurs Higgsfield, deux methodes

Releve du 2026-09-08, mesure en direct sur le lot ATCLUB (8 creas Nano Banana Pro
puis 1 crea MS Image). Tout ce qui suit est verifie par la CLI, rien n'est estime.

## Qui est qui

| | Nano Banana Pro | MS Image |
|---|---|---|
| appel | `higgsfield generate create nano_banana_2` | `higgsfield marketing-studio dtc-ads generate` |
| nom reel | `nano_banana_pro` (`nano_banana_2` est un alias) | MS Image, moteur Marketing Studio |
| parametres | aspect_ratio, image_references (14 max), prompt, resolution | format-id (requis), brand-kit-id, prompt, media (14 max), avatar (1), product (1), aspect-ratio, batch-size 1-20, quality, resolution |
| reglage qualite | aucun | low / medium / high |
| resolution | 1k / 2k / 4k, defaut **2k** | 1k / 2k / 4k |

## Le cout, mesure le 2026-09-08

| MS Image | 1k | 2k |
|---|---|---|
| low | 0,5 credit | **0,75** |
| medium | 2 | 3 |
| high | 4 | **7** |

Nano Banana Pro : **2 credits** en texte vers image, **4 credits** en image vers image
(mesure : 22 credits pour 5 generations t2i et 3 i2i). Pas de reglage possible.

**Consequence directe : MS Image en basse qualite coute moins cher que Nano Banana Pro
et compose mieux.** On explore a 0,75 credit, on trie, on ne finit en haute qualite que
ce qui est retenu.

## Pourquoi MS Image rend nettement mieux

Quatre causes, dans l'ordre d'importance.

1. **Le `format-id` porte un gabarit d'agence.** Ce n'est pas un mot-cle dans un prompt,
   c'est un preset qui impose la hierarchie typographique, le placement des blocs, le style
   du bouton et le traitement photo. 42 formats disponibles (`marketing-studio ad-formats list`).
2. **Le prompt passe par un enhancement backend.** Le serveur reecrit le brief selon les
   conventions du format avant de generer. Sur Nano Banana Pro, le texte part tel quel.
3. **Le prompt doit etre COURT.** ~700 caracteres suffisent : sur-specifier bride le preset.
   Sur Nano Banana Pro c'est l'inverse, il faut tout decrire (lumiere, matiere, ombres,
   profondeur), sinon le rendu est plat. Les 8 creas ATCLUB faisaient 1 800 a 2 400 caracteres
   et sont sorties conformes mais convenues.
4. **Le brand kit** injecte nom, palette et univers sans les repeter dans le prompt.

Ce n'est **ni** la resolution **ni** la qualite : Nano Banana Pro sort en 2k par defaut,
comme la crea MS Image comparee.

## Les pieges, verifies sur rendu

### MS Image
- **Il invente les ecrans de produit**, meme avec la vraie capture passee en `--media`.
  Sur ATCLUB il a fabrique une interface complete avec des chiffres credibles et faux :
  « Tennis 1 250 joueurs », « Padel 980 joueurs », « Running 2 430 coureurs ». **Plus dangereux
  que du charabia** : ca passe la relecture et part en diffusion.
- **Il glisse vers le registre sexualise** des qu'on lui laisse la scene avec un humain,
  meme quand le brief l'interdit. Curseur a tenir explicitement dans le prompt.
- **Il fait apparaitre des marques tierces reelles** (un sac Wilson sur le rendu ATCLUB).
- Le brand kit produit une **tagline en anglais** meme sur un site francais : forcer le
  francais dans le prompt.

### Nano Banana Pro
- **En i2i il ne colle pas l'asset non plus**, il le redessine avec du texte corrompu :
  « Selectiar̃oe ons tes sport(s) » au lieu de « Selectionne ton/tes sport(s) ».
- Sur-dirige, il rend une image correcte et sans relief.

## La regle qui en sort

1. Explorer en **MS Image low 2k** (0,75 credit), trier, finir en **high 2k** (7 credits).
2. **Ne jamais confier un ecran de produit reel a un moteur**, quel qu'il soit. Generer la
   scene avec l'ecran eteint ou hors champ, composer la vraie capture par-dessus.
3. Prompt **court** pour MS Image, prompt **long** pour Nano Banana Pro.
4. Tenir le registre (sexualise, marques tierces) explicitement dans le prompt.

## La banque Marketing Studio, enumeree le 2026-09-08

40 avatars preset · 9 hooks · 14 settings · **42 formats d'annonce** · 0 brand kit avant
celui d'AtClub · 1 produit deja enregistre (une HOKA Clifton 10 scrapee sur intersport.pf).

Le brand kit ne se cree **que** par `brand-kits fetch --url`, pas manuellement, et le logo
qu'il extrait peut etre faux : pour AtClub il a pris le rectangle de degrade du site.

## Les deux appels, litteralement

Les huit creas convenues :

    higgsfield generate create nano_banana_2 --prompt "<1800 a 2400 caracteres>"

Rien d'autre. Prompt ou je decrivais chaque ombre, chaque bokeh, chaque tiers de cadre.

La crea nettement superieure :

    higgsfield marketing-studio dtc-ads generate \
      --prompt "<700 caracteres>" \
      --format-id <un des 42 formats> \
      --brand-kit-id <brand kit de la marque> \
      --media <upload_id de l'asset> \
      --aspect-ratio 1:1 --quality high --resolution 2k --wait

Ce qui change dans l'ecriture du prompt :

- **une phrase de scene au lieu de dix.** « Une jeune femme en tenue de tennis assise sur
  un banc de vestiaire, lumiere chaude de fin de journee » et c'est tout. Aucune ombre,
  aucun bokeh, aucune poussiere, aucun point focal decrit.
- **le texte donne brut**, sans mise en scene typographique. « Titre affiche en haut : ... »
  et non « titre grave en grotesque tres gras avec ombre portee, texte exact ... ».
- le `--format-id` remplace tout le paragraphe de layout, le `--brand-kit-id` remplace les
  rappels de marque, et `--quality` / `--resolution` n'existent meme pas sur l'autre commande.
- la phrase de cloture imposee par le skill Kreative (« Utilise la meilleure qualite de Nano
  Banana Pro en restant gratuit ») disparait : elle n'a aucun sens sur un appel API.

**Regle : sur MS Image on decrit le sujet et on donne le texte, on ne met jamais en scene.
L'inverse exact de Nano Banana Pro.**

## Piege majeur des formats MS Image : ils remplissent les vides en inventant

Constate le 2026-09-09 sur Podmax, deux formats, deux inventions differentes.

- **Then vs Now** a fabrique les dates « 12 MAI » et « APRES 27 MAI », que personne n'avait
  demandees, et a grave au mur du bureau une enseigne « PODMAX STUDIO DE PRODUCTION VIDEO
  PUBLICITAIRE » plus un mug a la marque. Trois inventions dans une seule image.
- **Bold Statement** a ajoute un bandeau de bas de creative : « DES MARQUES A PARIS NOUS FONT
  DEJA CONFIANCE », « TOURNAGES CHAQUE SEMAINE », « PLACES LIMITEES ». Aucun de ces claims
  n'est dans le brief. Plus trois blocs de reassurance inventes.

Le preset ne laisse aucune zone vide : s'il a prevu un emplacement de date, de badge ou de
bandeau de preuve, il le remplit, avec ou sans matiere fournie. **Ce sont des claims
publicitaires inventes, donc un risque juridique**, pas une coquette.

**Parade a coller dans chaque prompt MS Image :**

    N'ajoute aucun texte, aucune date, aucun chiffre, aucun badge, aucune mention et aucun
    bandeau que je n'ai pas ecrits ci-dessus. Toute zone prevue par le gabarit et non
    renseignee reste vide.

A verifier sur chaque rendu, zone par zone, avant livraison.
