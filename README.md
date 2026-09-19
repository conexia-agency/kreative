# Kreative : automatisation de la chaîne de production de créas

Implémentation du cahier des charges `Desktop/cahier-des-charges-kreative.pdf`.

## Écarts assumés par rapport au cahier des charges

Trois points du CDC ne sont pas applicables tels qu'écrits. Les décisions prises :

**1. Génération : pas d'API Gemini directe.**
Le CDC prévoit l'envoi des prompts à `generativelanguage.googleapis.com` vers Nano Banana Pro.
Cet endpoint est géobloqué depuis la Polynésie (`User location is not supported for the API use`,
constaté sur les deux clés du `.env` racine, revérifié le 25/08/2026). Le pipeline tournant en
local à Tahiti, il taperait dans un mur.

Décision : passage par la CLI Higgsfield 0.1.40, qui expose le même modèle sous le job type
`nano_banana_2` (affiché "Nano Banana Pro"). C'est aussi la seule porte compatible headless :
le MCP Higgsfield exige un OAuth navigateur, incompatible avec le "zéro intervention humaine"
du point 8.

Rappel opérationnel : la CLI presigne toujours en `.png` mais envoie le content-type réel du
fichier, donc toute image d'entrée doit être convertie en PNG, sinon `SignatureDoesNotMatch`.

**2. Trois formats : recadrage géométrique, pas régénération.**
Le 4.2 exige que les trois formats soient le même visuel décliné. Trois appels au modèle
donnent trois images différentes, et `reframe` comme `outpaint` régénèrent des pixels : les
deux violent la règle.

Décision : le master est généré une seule fois en 9:16, les deux autres formats en sont des
recadrages verticaux purs. Les trois partagent la même largeur, donc les corps de texte en px
sont identiques et la typographie ne bouge pas non plus. Voir `compositeur/`.

**3. Logo et texte jamais gravés par le modèle.**
Un logo généré n'est jamais fidèle. Le logo est posé en overlay PNG, le texte en CSS.
C'est la doctrine aloa, et elle tombe naturellement du point 2 puisque la couche texte est
déjà séparée de la couche image.

## Ce qui existe déjà et qu'on ne réécrit pas

Briques de `conexia/PRODUIT/caravage/skills/aloa-pack/aloa-design/scripts/` :

| Étape CDC | Brique |
|---|---|
| 4.1 analyse du site, charte, logo, assets produit | `brand_intake.py` |
| 5. génération Nano Banana Pro | `aloa_higgsfield.py` |
| point ouvert #3, contrôle qualité automatique | `audit_mesure.py`, `gate_audit.py`, `aloa_loop.py` |
| livraison, compression | `livraison/`, `html_compressor.py` |

## État d'avancement

- [x] Compositeur 3 formats, avec contrôle de cohérence automatique (`compositeur/`)
- [x] Modèle d'état et reprises sélectives du 7.2 (`pipeline/etat.py`)
- [x] Étape stratégie en stub, conforme au contrat (`pipeline/strategie.py`)
- [ ] Branchement du vrai skill de production à la place du stub
- [x] Back-office, prototype navigable sur état réel (`backoffice/index.html`)
- [ ] Serveur FastAPI : mêmes données en direct, actions de reprise branchées
- [ ] Orchestrateur headless : sondage Stripe, file d'attente, exécution, livraison

### Back-office

Ouvrir `backoffice/index.html`. Régénérer l'instantané après un run :

    python3 pipeline/exporter.py

La page lit `/api/etat` si un serveur répond, sinon l'instantané local. La même
page servira donc en direct sans modification quand le serveur existera.

Peupler une commande de démonstration, sans appel à l'API de génération :

    python3 pipeline/etat.py creer --marque "Kreative Demo" --url https://kreative.fr --pack growth
    python3 pipeline/strategie.py --marque "Kreative Demo"
    python3 pipeline/demo_peupler.py --marque "Kreative Demo" --creas 12
    python3 pipeline/exporter.py

Frontière posée sur le point 8 : le pipeline va jusqu'au bout sans intervention,
et la sélection des N créas à livrer se fait après, dans le back-office. Un bouton
de validation placé au milieu de la chaîne réintroduirait le gate humain que le
CDC interdit, et bloquerait jusqu'au matin toute commande passée pendant la nuit.
- [ ] Bibliothèque d'inspiration (4.3) : en attente du zip
- [ ] Veille marque et concurrents (4.4) : méthode à trancher, voir ci-dessous
- [ ] Notification et dépôt Drive (6)

## Points ouverts

**Veille concurrentielle à coût nul (4.4).** L'API Meta Ad Library ne couvre que les publicités
politiques et sociétales ; les publicités commerciales ne sont visibles que dans l'interface web.
En programmatique cela revient à scraper le front : fragile et hors CGU. Information non
revérifiée, à confirmer avant de bâtir dessus. Repli propre : veille limitée aux publicités de
la marque cliente, ou dépôt manuel périodique dans un fichier local.

**Sélection en sortie (point ouvert #3 du CDC).** Le CDC exige zéro intervention humaine et
simultanément le doublement du volume pour permettre un tri. Le gate d'audit sait rejeter les
défauts mécaniques : texte illisible, collision, contraste, devise, hallucination OCR. Il ne
sait pas juger si une créa vend. Livrer sans oeil humain revient donc à livrer "conforme",
pas "bon". Arbitrage commercial, pas technique.

**Le gate d'audit tourne sur les trois rendus, pas sur le master.** Constaté au premier test :
une accroche qui respire en 9:16 peut chevaucher le sujet en 1:1, parce que le cadre est plus
serré. Le risque de collision est donc propre à chaque format.

## Se repérer entre dépôt et paquets

Ce dépôt est la source de vérité, pas le livrable. `paquet/` n'en est que la
partie rédigée (SKILL.md, changelog, evals) : le skill créatif de Kreative,
la banque `CREAS INSPI DELIVERY` et les scripts y sont injectés à
l'assemblage par `python3 outils/empaqueter.py` (paquet Claude Code) ou
`python3 outils/empaqueter_cowork.py` (paquet Cowork). Un
`references/strategie-creative.md` absent de `paquet/` est donc normal ici,
et anormal dans un paquet assemblé.

Sur n'importe quel poste, `python3 pipeline/sante.py` (ou
`scripts/pipeline/sante.py` depuis un paquet) dit ce qui est branché, ce qui
manque et le remède, et rend un code 1 si la chaîne ne doit pas tourner.
