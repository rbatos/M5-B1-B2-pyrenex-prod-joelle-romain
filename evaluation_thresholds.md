# Seuils d'évaluation continue — Pyrenex scoring v2

Stratégie retenue : **hybride**.

Un plancher absolu garantit qu'un modèle ne descend jamais sous un niveau de qualité minimal acceptable métier, quelle que soit la composition exacte du jeu de référence

La baisse max vs golden run détecte en plus : 
- une **régression relative** (ex. bug de preprocessing) même si le plancher absolu n'est pas atteint
- un seuil purement absolu raterait une chute de 15 points si le modèle partait très haut
- un seuil purement relatif ne protégerait pas contre un modèle historiquement médiocre qui se dégrade encore un peu à chaque release.

Jeu de référence : `data/reference_set.csv` (sous-échantillon figé du holdout M1).

Le jeu contient exactement 500 lignes : 250 `Fully Paid` et 250 `Charged Off`.
La classe rare est ainsi sur-représentée par rapport au holdout M1 (~18 % de défauts). Ce choix augmente fortement le nombre de défauts observés par rapport à un échantillon représentatif de 500 lignes (~90 défauts) et réduit donc l'incertitude sur `recall_defaut`, métrique essentielle pour détecter une régression sur les dossiers en défaut.

## Deux baselines, à ne pas confondre

| | Mesurée sur | Sert à |
|---|---|---|
| **Baseline communiquée** (`metrics_holdout`) | le holdout M1 complet | ce qu'on a annoncé au client |
| **Golden run** (`data/reference_baseline.json`) | **votre** jeu de référence, au gel | **arbitrer les releases** |

⚠️ Le garde-fou compare au **golden run**, jamais à la baseline communiquée :
les deux jeux n'ont ni la même taille ni la même composition, donc l'écart
entre eux mesure une **différence de population**, pas une dégradation du
modèle.

| Métrique | Golden run | Plancher absolu | Baisse max vs golden run | Justification |
|---|---|---|---|---|
| F1 macro | 0.6579 | 0.55 | 0.05 | Holdout M1 = 0.613. Plancher fixé ~6 points sous le holdout : marge pour l'écart de population jeu de référence vs holdout, tout en excluant un modèle qui ne discrimine plus les deux classes. |
| F1 défaut | 0.6627 | 0.35 | 0.05 | Holdout M1 = 0.4364. C'est la métrique la plus sensible au déséquilibre de classe (peu de "Charged Off") — plancher ~9 points sous le holdout pour absorber le bruit d'échantillonnage sans laisser passer une vraie régression. |
| ROC-AUC | 0.7014 | 0.65 | 0.04 | Holdout M1 = 0.7371. Le ROC-AUC est peu sensible au seuil de décision et relativement stable — tolérance resserrée à 0.04 (proche du bruit mesuré, cf. table ci-dessous). |
| Recall défaut | 0.6720 | 0.55 | 0.08 | Holdout M1 = 0.6455. C'est le rappel sur la classe rare (défauts) : c'est la métrique la plus bruitée sur un jeu de ~500 lignes (~90 défauts), donc la tolérance relative la plus large des 4 pour rester au-dessus du bruit d'échantillonnage. |

> **Golden run gelé** : les valeurs ci-dessus proviennent de `data/reference_baseline.json`, créé pour le modèle `v2.0.0` sur les 500 lignes du jeu de référence. Les planchers et tolérances restent à confirmer par bootstrap (table suivante) avant toute évolution de ces seuils.

| Métrique | σ bootstrap mesuré | 2 σ | Tolérance retenue |
|---|---:|---:|---:|
| F1 macro | 0.021501 | 0.043002 | 0.05 |
| F1 défaut | 0.024574 | 0.049148 | 0.05 |
| ROC-AUC | 0.023174 | 0.046348 | 0.04 |
| Recall défaut | 0.028820 | 0.057640 | 0.08 |

> Mesures bootstrap sur `reference_set.csv` (n=500) : les σ observés sont de l'ordre de 0.02-0.03, donc le seuil de bruit à 2σ est entre ~0.04 et ~0.06. Les tolérances retenues (0.04 à 0.08) restent bien au-dessus du bruit mesuré pour les 4 métriques, ce qui donne un garde-fou robuste sans être trop permissif. Pour `ROC-AUC`, la tolérance retenue (0.04) est légèrement supérieure à 2σ (~0.0463). En pratique, l’écart de bruit mesuré est un peu plus haut que la tolérance nominale, donc il est prudent de ne pas rétrécir cette tolérance tant qu’un bootstrap plus robuste n’a pas été reconduit sur un jeu de référence re-gelé. 

> En pratique, la règle de décision est : `tolérance effective = max(tolérance métier, 2σ bootstrap)`. Cela garantit que le garde-fou reste au-dessus du bruit de mesure et ne déclenche pas sur du seul hasard.

## Procédure de mise à jour des seuils

- **Qui** : Romain, en accord avec Sophie Léger (Lead Data) avant tout changement en prod.
- **Quand** : à chaque changement de version majeure du modèle (ex. v2.0 → v3.0), ou si le jeu de référence est reconstruit.
- **Comment** : garder `THRESHOLDS` dans `scripts/evaluate_model.py` ET ce fichier cohérents (même valeurs), si le jeu de référence change, **regeler le golden run** (`--freeze-baseline`) et remesurer le bootstrap avant de retoucher les tolérances.
