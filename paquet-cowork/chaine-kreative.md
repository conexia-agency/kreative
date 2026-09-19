# Où sont les fichiers, et ce qui change selon l'environnement

Le skill de Kreative est dans `strategie-creative.md`, à côté de ce fichier. Il
est la seule source pour la stratégie, la copy et les prompts. Rien ici ne le
complète, ne le corrige ni ne le remplace.

Ce fichier répond à deux questions de mécanique, et à rien d'autre.

## 1. Où la chaîne a déjà déposé ce que le skill demande d'aller chercher

Le skill décrit comment analyser le site du client et récupérer ses assets.
Quand la chaîne tourne, ce travail est déjà fait au moment où la stratégie
commence, et les résultats sont dans `commandes/<ardoise>/marque/` :

| fichier | contenu |
|---|---|
| `captures/` | une capture par page |
| `charte-site.json` | couleurs, polices, boutons, rayons, ombres, composants |
| `site.json` | titres, accroches, boutons, prix, témoignages, page par page |
| `assets-site/index.json` | les images du site, avec dimensions, texte alternatif et zone |
| `logo/candidats.json` | les logos possibles, avec le fond sur lequel chacun se pose |

Les fichiers joints par le client au formulaire sont dans
`commandes/<ardoise>/brief/pieces-jointes/`.

Si `charte-site.json` est absent, le site n'a pas pu être lu et le motif est
dans `marque/scraping.json`.

Si le brief annonce un logo, une charte ou des photos sans qu'aucun fichier ne
soit joint, le brief porte une ligne `_declare_sans_fournir`.

## 2. Ce qui change dans Cowork

Cowork exécute du Python mais ne peut pas installer de logiciel pendant qu'il
travaille. L'analyse du site, que la version technique confie à un script, s'y
fait donc avec le navigateur de Cowork, en enregistrant les résultats aux
emplacements du tableau ci-dessus.

Le skill décrit déjà cette analyse et les outils de navigateur à employer :
c'est lui qui fait foi.
