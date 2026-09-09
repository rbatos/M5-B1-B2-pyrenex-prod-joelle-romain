# Décisions binôme — M6-B2 (À COMPLÉTER)

> **À remplir avant de coder.** Les briques forment une chaîne (feedback →
> stockage → jointure → réentraînement → promotion) : figer les contrats est ce
> qui vous permet d'avancer à deux en parallèle sans vous bloquer.

## Contrats d'interface (à figer en premier)

```text
Feedback   : {request_id: str, true_label: 0|1, comments: str|None}
Stockage   : table feedbacks(request_id PK, true_label, comments,
             created_at, used_for_training=0)
Comptage   : GET /feedback/count → {"count": int, "new": int}
Retrain    : python scripts/retrain.py --min-feedback N → exit 0
Promotion  : decide_promotion(candidate: dict, production: dict)
             → PromotionDecision(promote: bool, reason: str)
```

Modifications apportées à ces contrats en cours de route : ...

## Trigger de réentraînement

**Seuil retenu : 200 justification : évite un réentraînement trop fréquent sur trop peu d’annotations, donc trop bruité et peu utile.

**On compte** : _les feedbacks non consommés (`used_for_training = 0`)
pourquoi pas le total ? On ne veut pas ajouter plusieurs fois les mêmes données dans le dataset d'apprentissage

⭐ Second déclencheur « ou dérive confirmée » (bonus) : _traité / non traité_ —
si traité, quelle fonction de M6-B1 est appelée ? Est-ce qu'en production dans un projet réel on lance des réentrainements si aucune dérive du modèle n'est détectée?

## Jeu de référence retenu (à figer AVANT tout le reste)

**Jeu adopté** : reference_set.csv de M5-B2 de 500 lignes, 250 Fully Paid et 250 Charged Off

**Pourquoi** : réutilisation des seuils calculés lors du brief précedent

> ⚠️ Le plancher de qualité de la politique de promotion vient de vos **seuils
> M5-B2**, calibrés sur **votre** jeu. Mesurer les métriques sur un autre jeu
> revient à comparer deux populations : sur un modèle **inchangé**, l'écart va
> de 0.01 à 0.23 selon la composition. Un seul jeu, du début à la fin.

## Politique de promotion

| Paramètre | Valeur retenue | Justification |
|---|---|---|
| Métriques critiques | recall_default et f1_macro | recall_default protège le risque métier principal, rater un dossier en défaut. f1_macro évite une amélioration d’une seule classe au prix d’un déséquilibre global trop fort. |
| Plancher de qualité | f1_macro ≥ 0.55 ; f1_default ≥ 0.35 ; roc_auc ≥ 0.65 ; recall_default ≥ 0.55 | Ces planchers sont déjà définis dans scripts/evaluate_model.py et documentés dans evaluation_thresholds.md. |
| Tolérance de régression | f1_macro : 0.05 ; f1_default : 0.05 ; roc_auc : 0.05 ; recall_default : 0.08, avec tolérance effective = max(tolérance métier, 2σ bootstrap) | C’est la règle déjà implémentée dans scripts/evaluate_model.py |
| Gain minimum exigé | au moins +0.01 sur recall_default ou +0.03 sur f1_macro sans dégradation du recall_default | On privilégie le recall afin d'améliorer le critère métier plus que la qualité globale du modèle |

**Pourquoi le recall de la classe défaut est-il contraignant ?**
Le recall correspond aux dossiers aboutissants à un défaut de paiement non détecté

**Pourquoi F1 macro plutôt que l'accuracy ?**
Car la variable cible est déséquilibrée (moins de 20% de défaut)

## Politique de doublon sur les feedbacks

| Cas | Réponse retenue | Justification |
|---|---|---|
| `request_id` inconnu | 404 | ne pas accepter de feedback non rattachable à une prédiction réelle  |
| Même `request_id`, même label | 201 | C’est un rejeu réseau idempotent, pas une nouvelle vérité terrain. |
| Même `request_id`, label différent | 409 | Arbitrage nécessaire par un humain. On n'écrase pas silencieusement la valeur |

## Résultat de notre exécution

**Décision obtenue** : _PROMOTE / REJECT_

| Métrique | Production | Candidat | Écart |
|---|---|---|---|
| f1_macro | _…_ | _…_ | _…_ |
| recall_default | _…_ | _…_ | _…_ |
| roc_auc | _…_ | _…_ | _…_ |

**Ce qu'on en conclut, en une phrase défendable devant Sophie Léger** : _…_

**Chemin de rejet démontré ?** _oui / non_ — comment : _…_

## RGPD

Le stockage retenu est request_id, true_label, comments et created_at. Le request_id agit comme identifiant interne, pas comme PII directe. Le champ comments devra être anonymisé.

## Point de mi-parcours (jeudi 17h)

- État des briques : _…_
- **Switch des rôles** — qui reprend quoi : _…_
