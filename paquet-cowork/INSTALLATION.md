# Installer Kreative Production dans Claude Cowork

Ce dossier est une **compétence** Claude, prête à installer. Une fois en place,
il suffit d'écrire à Claude « occupe-toi du nouveau formulaire » pour que la
chaîne parte.

## 1. Ce qu'il faut avant

- **Claude Cowork sur ordinateur** (application de bureau). L'accès direct aux
  fichiers et les connecteurs locaux ne fonctionnent que là, pas dans le
  navigateur ni sur mobile.
- Un compte Claude qui donne accès à Cowork.
- **Le connecteur Higgsfield**, à activer dans les connecteurs de Cowork. C'est
  lui qui génère les visuels, et lui seul.

## 2. Installer la compétence

1. Compressez ce dossier en une archive `.zip`, si ce n'est pas déjà fait.
2. Dans Cowork, ouvrez **Personnaliser**, puis **Compétences**.
3. Ajoutez la compétence et déposez l'archive.
4. Vérifiez qu'elle apparaît sous le nom **Kreative Production**.

Pour vérifier qu'elle est bien prise en compte, demandez simplement : « quelles
sont les étapes de la chaîne Kreative ? ». Claude doit répondre en citant le
relevé des formulaires, l'aspiration du site, la stratégie, la génération, le
contrôle et la livraison.

## 3. L'espace de travail

Les commandes clientes ne vivent PAS dans la compétence : elles vivent dans un
dossier à vous, sur votre ordinateur. Créez-le une fois, par exemple
`Documents/Kreative`, et donnez-en l'accès à Claude dans Cowork.

Ce dossier recevra un sous-dossier par commande, avec le brief, les images du
site du client, les visuels produits et le journal de ce qui a été fait.

## 4. Les accès

Dans ce dossier de travail, créez un fichier nommé `.env`. Il contient les clés
d'accès, une par ligne :

    ZITE_API_KEY=...
    PUBLIE_SITE=...
    PUBLIE_SUPABASE_URL=...
    PUBLIE_SUPABASE_ANON_KEY=...
    PUBLIE_EMAIL=...
    PUBLIE_PASSWORD=...

La première sert à relever les formulaires. Les cinq suivantes ne servent qu'à
publier les packs sur la plateforme de revue : si vous ne l'utilisez pas encore,
laissez-les de côté.

**Ce fichier ne se partage jamais** : ni par message, ni dans une capture
d'écran, ni dans une archive. Claude n'affichera jamais une de ces valeurs.

## 5. Le premier pack

Dites à Claude : « relève les formulaires Kreative ». Il vous montre ce qui est
arrivé sans rien écrire, puis ouvre les commandes quand vous le confirmez.

Ensuite, laissez-le enchaîner. Il s'arrêtera de lui-même dans trois cas
seulement : un brief incomplet sur une information qu'il ne peut ni déduire ni
trouver, un site inaccessible, ou un coût de génération au-dessus du plafond.
Dans tous les autres cas il tranche, et il vous dit à la fin ce qui lui a
manqué.

## 6. Ce que coûte un pack

Deux crédits Higgsfield par visuel, que la créa utilise une image du client ou
non. Un pack Starter de six créas coûte douze crédits, un pack Scale de
dix-huit en coûte trente-six. Claude annonce toujours le montant avant de
dépenser, et relève le solde avant et après.

Comptez une à deux reprises par pack : une créa dont un mot est mal rendu se
régénère pour deux crédits, ce qui reste très en dessous du coût d'un pack
rejeté par le client.

## 7. Ce que contient ce dossier

| élément | à quoi ça sert |
|---|---|
| `skill.md` | les instructions que Claude suit, du formulaire à la livraison |
| `resources/strategie-creative.md` | la méthode de Kreative, telle qu'elle a été fournie |
| `resources/chaine-kreative.md` | où la chaîne dépose les fichiers, et ce qui change dans Cowork |
| `CREAS INSPI DELIVERY/` | la banque de références qui fixe le niveau de design attendu |
| `scripts/pipeline/` | les neuf modules de la chaîne |
| `scripts/MODULES.md` | ce qui n'est pas dans ce paquet, et pourquoi |

## 8. Une limite à connaître

Cowork ne peut pas installer de logiciel supplémentaire pendant qu'il travaille.
Deux étapes que la version technique confiait à des programmes sont donc
conduites directement par Claude : la lecture du site du client, avec son
navigateur intégré, et la relecture des visuels produits, à l'oeil.

Pour la relecture, c'est un gain : un programme de reconnaissance de caractères
échoue sur un texte incliné ou peint en couleur vive sur fond sombre, là où
Claude lit correctement. Pour la lecture du site, c'est plus lent qu'un
programme, et un site très volumineux demandera de la patience.
