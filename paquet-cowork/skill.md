---
name: Kreative Production
description: Relie les outils autour du skill de Kreative : relève le formulaire, tient le registre de la banque, lance la génération, décline les formats et livre le dossier.
---

# Kreative Production

Ce fichier ne contient aucune règle de création. Il dit seulement quelles
commandes lancer, et dans quel ordre.

**La méthode est dans `resources/strategie-creative.md`**, le skill de Kreative.
Il fait foi sur la stratégie, les angles, la copy, le choix des assets, la
lecture du site et l'écriture des prompts. Applique-le intégralement, à
une exception près, décidée le 19/09/2026 : sa phrase de fin « Nano
Banana Pro en restant gratuit » ne s'écrit plus dans les prompts, le
connecteur fixe le modèle et la facturation par ses paramètres d'appel.

`resources/chaine-kreative.md` dit seulement où la chaîne a déjà déposé les
fichiers que le skill demande d'aller chercher, et comment sa sortie se range.

## 0. Vérifier les branchements

    python3 scripts/pipeline/sante.py

À jouer en premier, à chaque nouveau poste et à chaque doute. Chaque ligne
dit ce qui est branché, ce qui manque et le remède. Si le verdict est
« ne doit pas tourner », on répare avant de produire, on ne contourne pas.
Le connecteur Higgsfield et le navigateur ne se prouvent qu'en session :
un appel de solde et une capture du site font foi.

## 1. Relever les formulaires

    python3 scripts/pipeline/zite.py relever

Affiche les nouvelles soumissions sans rien écrire. Puis :

    python3 scripts/pipeline/zite.py relever --appliquer

Chaque soumission devient un dossier de commande, avec le brief et les fichiers
joints par le client.

## 2. Analyser le site

Fais-le comme le skill le décrit, avec le navigateur, et enregistre les
résultats aux emplacements listés dans `resources/chaine-kreative.md`.

## 3. Ouvrir la banque de références, sous registre

    python3 scripts/pipeline/banque.py ouvrir <ardoise>

Ouvre toutes les planches listées, puis consigne :

    python3 scripts/pipeline/banque.py lue <ardoise> --planches ...
    python3 scripts/pipeline/banque.py retenir <ardoise> --refs ... --du-client ...
    python3 scripts/pipeline/banque.py extraire <ardoise>

`extraire` écrit une image par référence retenue : les fichiers HD de la
banque portent deux créas côte à côte, et les lire tels quels partage la
résolution entre les deux. Ouvre les fichiers découpés UN PAR UN : c'est
là que se lit la finition, pas sur les planches.

Sans ce registre, le plan sera refusé à l'étape 5.

## 4. Stratégie, copy et prompts

Lis `resources/strategie-creative.md` et applique-le jusqu'aux prompts
finalisés, dans son format de sortie. Écris ta sortie dans un fichier.

## 5. Ranger le plan

    python3 scripts/pipeline/plan.py importer <ardoise> --fichier <ta-sortie.md>

Un refus n'est jamais corrigé à ta place : le motif cite la règle du skill en
cause, reprends la créa concernée.

## 6. Générer

Par le connecteur Higgsfield, avec les paramètres que le lot indique :

    python3 scripts/pipeline/moteur.py preparer <ardoise>

Annonce le coût avant de générer, relève le solde avant et après, puis :

    python3 scripts/pipeline/moteur.py recolter <ardoise> --resultats <fichier>

## 7. Décliner, contrôler, livrer

    python3 scripts/pipeline/formats.py decliner <ardoise>
    python3 scripts/pipeline/audit.py --marque <ardoise>
    python3 scripts/pipeline/livrer.py <ardoise>

Les formats que le prolongement de bord refuse se produisent par le connecteur
puis se rangent avec `formats.py ranger-extension`. L'audit ne bloque pas :
regarde ses alertes à l'oeil, c'est toi qui tranches. Pour cette relecture :

    python3 scripts/pipeline/loupe.py <ardoise>

découpe chaque master en quatre zones qui se recouvrent, dans
`session/loupe/`. Ouvre chaque zone une par une : un texte peint ne se
juge jamais sur la vignette entière, toutes les fautes se voient au zoom. La livraison crée le
dossier au nom de la marque et envoie la notification.

Pour la plateforme de revue, étape FACULTATIVE : sans les accès `PUBLIE_*` dans l'environnement, elle se saute sans conséquence, la livraison ci-dessus est déjà complète. Si Kreative utilise le portail :

    python3 scripts/pipeline/publier.py <ardoise> --client <slug>
    python3 scripts/pipeline/retours.py <ardoise> --client <slug>
