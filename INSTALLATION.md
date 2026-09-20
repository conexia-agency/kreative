# Mettre en place la chaîne Kreative sur votre poste

Ce guide part de zéro et se termine quand `python3 pipeline/sante.py` est au
vert. Chaque étape se vérifie ; en cas de doute, cette commande redit ce qui
manque et le remède.

## 1. Les logiciels

| quoi | pourquoi | installation |
|---|---|---|
| Python 3.9 ou plus | toute la chaîne | livré avec macOS, sinon python.org |
| Pillow | déclinaison des formats, découpe des références | `pip3 install Pillow` |
| Playwright + Chromium | l'aspiration des sites clients | `pip3 install playwright && python3 -m playwright install chromium` |
| tesseract + langues fra, eng | l'audit lit le texte peint (optionnel : sans lui, relecture à l'oeil) | `brew install tesseract tesseract-lang` |
| Claude Code | la session qui pilote tout | https://claude.com/claude-code |

## 2. Récupérer le code

```
git clone https://github.com/kreativeadsfr/kreative.git
cd kreative
```

Pour recevoir les mises à jour de Conexia dans votre dépôt :

```
git remote add conexia https://github.com/conexia-agency/kreative.git
git pull conexia main
```

À faire à chaque annonce de mise à jour, et avant de signaler un problème :
le correctif est peut-être déjà poussé.

## 3. Les clés

```
cp .env.example .env
```

Ouvrir `.env` et poser au minimum `ZITE_API_KEY` (la clé du compte Zite
Forms). Les autres variables sont commentées dans le fichier ; les cinq
`PUBLIE_*` ne servent qu'à la plateforme de revue, optionnelle : sans elles,
la chaîne livre quand même, elle saute juste cette étape.

Charger le fichier avant chaque session de travail :

```
set -a && source .env && set +a
```

Règle sans exception : une clé ne s'écrit jamais dans un livrable, un
message, une capture d'écran ou un commit. Elle se référence par son nom
(`$ZITE_API_KEY`). Le `.env` est ignoré par git et doit le rester.

## 4. Le connecteur MCP Higgsfield

La génération d'images passe par le connecteur MCP Higgsfield, et par rien
d'autre. Jamais la CLI `higgsfield`, jamais une API directe.

```
claude mcp add --transport http --scope user higgsfield https://mcp.higgsfield.ai/mcp
```

Puis redémarrer Claude Code. L'authentification est un OAuth qui s'ouvre
dans le navigateur au premier appel d'un outil `mcp__higgsfield__*` : il
faut donc un navigateur sur le poste, une fois. Le compte doit être un plan
avec des crédits ; la chaîne relève le solde avant et après chaque lot.

Piège connu, payé une fois : un connecteur autorisé en cours de session ne
publie pas ses outils avant un REDÉMARRAGE de Claude Code. Si les outils
`mcp__higgsfield__*` n'apparaissent pas, redémarrer avant de chercher plus
loin.

## 5. Vérifier le poste

```
python3 pipeline/sante.py
python3 kreative.py verifier
```

Tout doit être `ok` ou `option`. Chaque `MANQUE` nomme son remède ; tant
qu'il en reste un, la chaîne ne doit pas tourner. Les deux contrôles marqués
`session` (connecteur Higgsfield, navigateur) se prouvent au premier appel
en session Claude.

## 6. L'espace de travail

Les données clientes ne vivent jamais dans le dépôt. Par défaut elles vont
dans `~/Kreative/commandes/` ; pour choisir un autre endroit, poser
`KREATIVE_TRAVAIL` dans le `.env`. Le dossier se crée au premier usage.

## 7. Première commande

Ouvrir une session Claude Code dans le dépôt : le `CLAUDE.md` se charge et
porte les consignes de session, à commencer par la règle zéro, lire
`skill/strategie-creative.md` EN ENTIER. L'ordre d'une commande est celui de
`paquet/SKILL.md` (section Workflow) :

1. `pipeline/zite.py relever` puis `--appliquer` : le formulaire devient un
   dossier de commande.
2. `pipeline/scraper.py aspirer <ardoise>` : récolte et mesure. L'analyse
   réelle se fait ensuite au navigateur, et la bibliothèque publicitaire
   Meta se tente à chaque commande.
3. `pipeline/banque.py ouvrir / lue / retenir / extraire` : la banque de
   références, sous registre. Ouvrir chaque fichier extrait un par un.
4. La stratégie, selon `skill/strategie-creative.md`, écrite dans UN fichier markdown,
   puis `pipeline/plan.py importer <ardoise> --fichier <plan.md>`.
5. `pipeline/moteur.py preparer <ardoise>` : le devis, puis la génération
   par le MCP, puis `recolter`.
6. Audit, relecture au zoom (`pipeline/loupe.py`), déclinaison des formats,
   livraison.

La chaîne REFUSE d'avancer si une étape est sautée : plan non importé,
banque sans registre ou sans fichiers extraits, tout arrête la génération
avec le remède affiché. Un refus n'est pas un obstacle à contourner, c'est
l'étape manquante qui se rappelle.

## 8. En cas de problème

- `python3 pipeline/sante.py` d'abord : il diagnostique la plupart des cas.
- Puis `git pull conexia main` : le correctif est peut-être déjà là.
- Sinon, signaler à Conexia avec le message d'erreur exact.
