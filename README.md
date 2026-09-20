# Kreative : chaîne de production de créatives statiques Meta

Un formulaire client rempli entre, un pack de créatives auditées sort. La
création entière (stratégie, angles, copy, prompts) vient du skill de
Kreative, `skill/strategie-creative.md` : la chaîne n'est que la plomberie autour, du
relevé du formulaire à la livraison.

**Mise en place sur un poste neuf : [INSTALLATION.md](INSTALLATION.md).**
**Consignes de session : [CLAUDE.md](CLAUDE.md)**, chargées automatiquement
par Claude Code à l'ouverture du dépôt.

## L'architecture, en clair

- **Le skill de Kreative décide de toute la création.** Il part octet pour
  octet dans les paquets, jamais modifié. La chaîne ne contient aucune règle
  d'archétype, de composition ou de typographie.
- **Le texte est peint par le modèle** (Nano Banana Pro), comme le skill le
  demande. La copy figure mot pour mot dans le prompt, et `pipeline/plan.py`
  le vérifie.
- **La génération passe par le connecteur MCP Higgsfield, uniquement.**
  Jamais la CLI, jamais une API directe.
- **Les étapes ne peuvent pas être sautées.** La banque de références se lit
  sous registre (`pipeline/banque.py` : ouvrir, lue, retenir, extraire), la
  sortie du skill passe par `pipeline/plan.py importer` qui fait tourner les
  gates, et `pipeline/moteur.py preparer` refuse tout plan qui n'est pas
  passé par là. Chaque refus affiche le remède.
- **Les données clientes ne sont jamais versionnées** : `commandes/` et
  `.env` sont ignorés par git, ce dépôt public ne porte que le système.
- Sur n'importe quel poste, `python3 pipeline/sante.py` dit ce qui est
  branché, ce qui manque et le remède.

## Écarts assumés par rapport au skill, à connaître

Décision du 19/09/2026, documentée dans `paquet/SKILL.md` : la phrase de fin
« Nano Banana Pro en restant gratuit » ne s'écrit plus dans les prompts, le
connecteur fixe le modèle et la facturation par ses paramètres d'appel. Le
reste du skill s'applique intégralement.

## Se repérer entre le dépôt et le skill

Ce dépôt est la source de vérité, pas le livrable. **Il ne contient qu'un
seul skill**, `kreative-production`, et il s'assemble :

    python3 outils/empaqueter.py        # vers ~/Desktop/kreative-production

`paquet/` n'est que sa partie rédigée (SKILL.md, changelog, references,
evals). Le skill créatif de Kreative (`skill/strategie-creative.md`), la
banque `CREAS INSPI DELIVERY` et les scripts y sont injectés à l'assemblage.
Un `references/strategie-creative.md` absent de `paquet/` est donc normal
ici, et anormal dans un paquet assemblé.

`skill/strategie-creative.md` est le fichier de Kreative, repris octet pour
octet : c'est la SOURCE de la création, lue par le skill de production. Ce
n'est pas un skill à installer séparément, et il ne doit jamais l'être : le
déclencher seul court-circuite la banque de références et tous les verrous.

Installation du skill assemblé :

    ln -s ~/Desktop/kreative-production ~/.claude/skills/kreative-production

Dans le dépôt, les scripts s'appellent `pipeline/<module>.py` et
`kreative.py` ; dans le paquet assemblé, les mêmes vivent sous
`scripts/pipeline/` et `scripts/kreative.py`.
