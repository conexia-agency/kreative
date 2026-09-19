---
name: Kreative Production
description: Relie les outils autour du skill de Kreative : relève le formulaire, lance la génération, décline les formats et livre le dossier.
---

# Kreative Production

Ce fichier ne contient aucune règle de création. Il dit seulement quelles
commandes lancer, et dans quel ordre.

**La méthode est dans `resources/strategie-creative.md`**, le skill de Kreative.
Il fait foi sur la stratégie, les angles, la copy, le choix des assets, la
lecture du site et l'écriture des prompts, y compris sa phrase de fin
obligatoire. Applique-le intégralement, sans rien y ajouter ni en retrancher.

`resources/chaine-kreative.md` dit seulement où la chaîne a déjà déposé les
fichiers que le skill demande d'aller chercher.

## 1. Relever les formulaires

    python3 scripts/pipeline/zite.py relever

Affiche les nouvelles soumissions sans rien écrire. Puis :

    python3 scripts/pipeline/zite.py relever --appliquer

Chaque soumission devient un dossier de commande, avec le brief et les fichiers
joints par le client.

## 2. Analyser le site

Fais-le comme le skill le décrit, avec le navigateur, et enregistre les
résultats aux emplacements listés dans `resources/chaine-kreative.md`.

## 3. Préparer le brief

    python3 scripts/pipeline/redaction.py <ardoise>

## 4. Stratégie, copy et prompts

Lis `resources/strategie-creative.md` et applique-le jusqu'aux prompts
finalisés.

## 5. Générer

Par le connecteur Higgsfield, avec les paramètres que le skill indique.

Annonce le coût avant de générer, et relève le solde avant et après.

## 6. Décliner et livrer

    python3 scripts/pipeline/moteur.py recolter <ardoise> --resultats <fichier>
    python3 scripts/pipeline/publier.py <ardoise> --client <slug>

Pour récupérer les commentaires du client :

    python3 scripts/pipeline/retours.py <ardoise> --client <slug>
