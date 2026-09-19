# Où sont les fichiers, et ce qui change selon l'environnement

Le skill de Kreative est dans `strategie-creative.md`, à côté de ce fichier. Il
est la seule source pour la stratégie, les angles, la copy et les prompts. Rien
ici ne le complète, ne le corrige ni ne le remplace.

Ce fichier répond à deux questions de mécanique, et à rien d'autre.

## 1. Où la chaîne a déjà déposé ce que le skill demande d'aller chercher

Le skill décrit comment analyser le site du client et récupérer ses assets.
Quand la chaîne tourne, ce travail est déjà fait au moment où la stratégie
commence, et les résultats sont dans `commandes/<ardoise>/` :

| fichier | contenu |
|---|---|
| `marque/captures/` | une capture par page, pleine hauteur |
| `marque/charte-site.json` | couleurs, polices, boutons, rayons, ombres décomposées, badges, pilules, cartes, cartes empilées, police d'accent, encadrés tracés à la main : les neuf items du 4.1, mesurés sur les styles calculés |
| `marque/site.json` | titres, accroches, boutons, prix, témoignages, page par page |
| `marque/assets-site/index.json` | les images du site, avec dimensions, texte alternatif et zone |
| `marque/logo/candidats.json` | les logos possibles, avec le fond sur lequel chacun se pose |
| `brief/pieces-jointes/` | les fichiers joints au formulaire par le client |
| `session/entrees.json` | l'inventaire de tout ce qui précède, écrit par `plan.py dossier` |

Si `charte-site.json` est absent, le site n'a pas pu être lu et le motif est
dans `marque/scraping.json`.

Si le brief annonce un logo, une charte ou des photos sans qu'aucun fichier ne
soit joint, le brief porte une ligne `_declare_sans_fournir`.

## 2. La banque de références se lit sous registre

Le skill dit que la banque vit « à côté du SKILL.md ». Dans ce paquet,
elle vit à la racine, dans `CREAS INSPI DELIVERY`, pas à côté de
`resources/strategie-creative.md` : ne la cherche pas par chemin relatif
au fichier du skill. `banque.py ouvrir` donne les chemins exacts de
chaque planche, et `sante.py` vérifie qu'elle est complète.

Le skill demande d'ouvrir toutes les planches de la famille, d'en retenir une
vingtaine, et de les ouvrir en pleine résolution avant d'écrire les créas. La
chaîne rend ce process vérifiable, sans en changer une ligne :

    python3 scripts/pipeline/banque.py ouvrir <ardoise>

dit quelle famille s'applique, si les ugly ads sont ouvertes et par quelle
phrase du brief, et liste toutes les planches à ouvrir. Après les avoir
regardées :

    python3 scripts/pipeline/banque.py lue <ardoise> --planches AG1_1 AG1_2 ...
    python3 scripts/pipeline/banque.py retenir <ardoise> --refs AG1-05 AG2-03 ... --du-client <refs>
    python3 scripts/pipeline/banque.py extraire <ardoise>

La dernière commande découpe chaque référence retenue en un fichier à elle,
dans `commandes/<ardoise>/session/references/` : une créa par image, toute
la résolution pour elle. C'est sur ces fichiers, ouverts un par un, que se
fait la lecture en pleine résolution que le skill exige, jamais sur les
paires HD ni sur les planches.

`--du-client` liste les références qui portent la marque du client du jour :
le skill interdit de les reprendre, et le plan sera refusé si l'une d'elles
figure dans la sélection.

## 3. La sortie du skill se range telle quelle

Le skill écrit sa sortie dans son propre format, en markdown. La chaîne la lit
directement, sans lui demander un autre format :

    python3 scripts/pipeline/plan.py importer <ardoise> --fichier <sortie-du-skill.md>

L'import refuse le plan entier si le process de la banque n'a pas été suivi,
si la copy déclarée porte des mots que le prompt ne peint pas, ou si une
indication technique colle au texte à afficher. Rien n'est corrigé en
silence : chaque refus cite son motif, et la créa repart au skill.

Écart assumé au skill, décidé le 19/09/2026 : sa phrase de fin « Utilise
la meilleure qualité de Nano Banana Pro en restant gratuit. » ne s'écrit
plus, et l'import la retire d'un prompt qui la porterait encore. Le
connecteur fixe le modèle, la résolution et la facturation par ses
paramètres d'appel, la phrase n'y pilote rien. À signaler à Evan.

## 4. Après la génération

    python3 scripts/pipeline/formats.py decliner <ardoise>      # 4:5 et 9:16 depuis le master carré
    python3 scripts/pipeline/audit.py --marque <ardoise>        # contrôles mécaniques, ne bloque pas
    python3 scripts/pipeline/livrer.py <ardoise>                # dossier au nom de la marque + notification

Quand un format ne peut pas être tiré du master par prolongement de bord, la
liste vit dans `commandes/<ardoise>/formats/a-etendre.json` : ces formats se
produisent par le connecteur (extension à 2 crédits), puis se rangent avec

    python3 scripts/pipeline/formats.py ranger-extension <ardoise> --crea cXX --format 9x16 --fichier <sortie>

qui repose le master d'origine au centre, à l'octet près.

La relecture des textes peints se fait sur les découpes de

    python3 scripts/pipeline/loupe.py <ardoise>

une zone par image, toute la résolution pour chacune. La créa entière sert
à juger la composition ; les zones servent à lire les lettres.

## 5. Ce qui change dans Cowork

Cowork exécute du Python mais ne peut pas installer de logiciel pendant qu'il
travaille. L'analyse du site, que la version technique confie à un script, s'y
fait donc avec le navigateur de Cowork, en enregistrant les résultats aux
emplacements du tableau ci-dessus. La relecture des visuels s'y fait à l'oeil,
ce qui est un gain : un moteur de reconnaissance de caractères échoue sur un
texte incliné ou peint en couleur vive, là où l'oeil lit correctement.

Le skill décrit déjà cette analyse et les outils de navigateur à employer :
c'est lui qui fait foi.
