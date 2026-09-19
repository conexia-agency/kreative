# Installation du poste de production

Ce document s'adresse à la personne qui installe la chaîne Kreative sur un
poste neuf. Chaque étape se vérifie à la fin par UNE commande, qui redit tout
ce qui manque :

```
python3 scripts/kreative.py verifier
```

Neuf contrôles, chacun nomme son remède. Tant qu'un `MANQUE` reste, la chaîne
ne tournera pas entière.

## 1. Les logiciels

| quoi | pourquoi | installation |
|---|---|---|
| Python 3.9 ou plus | toute la chaîne | livré avec macOS, sinon python.org |
| Playwright + Chromium | l'aspiration des sites clients | `pip3 install playwright && python3 -m playwright install chromium` |
| tesseract + langues fra, eng | le gate lit le texte peint dans les images | `brew install tesseract tesseract-lang` |
| Claude Code | la session qui pilote tout | https://claude.com/claude-code |

## 2. Le MCP Higgsfield

La génération d'images passe par le connecteur MCP Higgsfield, et par rien
d'autre. Dans `~/.claude.json`, sous `mcpServers`, déclarer :

```json
"higgsfield": {
  "type": "http",
  "url": "https://mcp.higgsfield.ai/mcp"
}
```

L'authentification est un OAuth déclenché au premier appel d'un outil
`mcp__higgsfield__*`. Le compte doit être un plan payant avec des crédits :
la chaîne relève le solde avant et après chaque lot.

**Piège payé une fois, à ne pas repayer :** un connecteur MCP autorisé en
cours de session ne publie pas ses outils avant un REDÉMARRAGE de Claude
Code. Si les outils `mcp__higgsfield__*` n'apparaissent pas, redémarrer avant
de chercher plus loin.

## 3. Le skill

Poser le dossier `kreative-production/` où l'on veut, puis le faire voir de
Claude Code :

```
ln -s "<chemin>/kreative-production" ~/.claude/skills/kreative-production
```

La banque de références (`CREAS INSPI DELIVERY/`, 30 Mo) fait partie du
dossier et doit y rester : la stratégie la lit par chemin relatif.

## 4. L'espace de travail et les clés

Les données clientes ne vivent JAMAIS dans le skill. Choisir un dossier de
travail et le déclarer dans l'environnement du shell (par exemple dans
`~/.zshrc`) :

```
export KREATIVE_TRAVAIL="$HOME/Kreative"
```

Y créer un fichier `.env` :

```
ZITE_API_KEY=<la clé du compte Zite Forms>
```

Et le charger avant chaque session de travail :

```
cd "$KREATIVE_TRAVAIL" && set -a && source .env && set +a
```

Règles sur les clés, sans exception : une clé ne s'écrit jamais dans un
fichier livrable, un message, une capture d'écran ou un commit ; elle se
référence par son nom (`$ZITE_API_KEY`). **La clé Zite qui a servi aux tests
de septembre 2026 a transité en clair le 11/09 : elle doit être tournée dans
le compte Zite avant la mise en production.**

## 5. Le cloud, côté Kreative

- **Zite Forms** : le formulaire client est le point d'entrée de la chaîne.
  L'API se relève par la clé ci-dessus ; il n'y a pas de webhook, la chaîne
  interroge (`zite.py relever`, ou l'orchestrateur en boucle).
- **Higgsfield** : un compte avec crédits, voir section 2. Prévoir le plafond
  par commande (120 crédits par défaut) dans le budget mensuel.
- **La plateforme de revue** (dépôt des visuels, commentaires de l'équipe,
  téléchargement client) est fournie séparément par Conexia, en location :
  les accès (URL, compte, clé publique) sont remis à l'ouverture du compte
  et se posent aussi dans le `.env`. Sans elle, la chaîne fonctionne jusqu'à
  la page de suivi locale incluse.

## 6. Un dossier de dépôt final

Le pack validé se remet au client dans un dossier accessible depuis un
téléphone (Google Drive ou équivalent). Ce choix appartient à Kreative ; la
chaîne n'impose que le contenu : les masters PNG et la page de suivi.
