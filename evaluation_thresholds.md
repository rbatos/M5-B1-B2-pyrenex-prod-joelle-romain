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

Cette distinction vaut aussi pour l'interprétation des seuils. Le **plancher absolu** ne cherche pas à dire si le modèle a changé : il répond à la question métier « ce modèle est-il encore utilisable par Pyrenex ? ». Ni le holdout M1 ni le bootstrap ne peuvent trancher cette question. La **baisse maximale vs golden run**, elle, répond à la question « le modèle a-t-il changé ? » : c'est
un garde-fou statistique, calibré à partir de la variabilité mesurée sur le jeu de référence.

| Métrique | Golden run | Plancher absolu | Baisse max vs golden run | Justification |
|---|---|---|---|---|
| F1 macro | 0.6579 | 0.55 | 0.05 | En dessous de 0.55, la qualité moyenne entre les deux classes devient insuffisante pour considérer le tri automatique comme fiable pour Pyrenex : trop de déséquilibre entre détection des défauts et maintien des dossiers sains. |
| F1 défaut | 0.6627 | 0.35 | 0.05 | En dessous de 0.35, la détection de la classe défaut devient trop faible : le modèle laisse passer trop de dossiers à risque pour que son usage justifie le coût de l'instruction manuelle. |
| ROC-AUC | 0.7014 | 0.65 | 0.04 | En dessous de 0.65, le modèle ne sépare plus suffisamment les dossiers susceptibles de faire défaut des autres : le classement produit n'est plus assez discriminant pour piloter le tri Pyrenex. |
| Recall défaut | 0.6720 | 0.55 | 0.08 | En dessous de 0.55, Pyrenex laisse passer plus de 45 % des dossiers qui feront défaut : le tri automatique n'apporte plus assez pour justifier le coût de l'instruction manuelle. |

> **Golden run gelé** : les valeurs ci-dessus proviennent de `data/reference_baseline.json`, créé pour le modèle `v2.0.0` sur les 500 lignes du jeu de référence. Les planchers sont des décisions métier, le bootstrap sert à calibrer les tolérances de baisse relative, pas à fixer ces planchers.

| Métrique | σ bootstrap mesuré | 2 σ | Tolérance retenue |
|---|---:|---:|---:|
| F1 macro | 0.021501 | 0.043002 | 0.05 |
| F1 défaut | 0.024574 | 0.049148 | 0.05 |
| ROC-AUC | 0.023174 | 0.046348 | 0.05 |
| Recall défaut | 0.028820 | 0.057640 | 0.08 |

> Mesures bootstrap sur `reference_set.csv` (n=500) : les σ observés sont de l'ordre de 0.02-0.03, donc le seuil de bruit à 2σ est entre ~0.04 et ~0.06. Les tolérances retenues (0.04 à 0.08) restent bien au-dessus du bruit mesuré pour les 4 métriques, ce qui donne un garde-fou robuste sans être trop permissif. Pour `ROC-AUC`, la tolérance retenue (0.05) est légèrement supérieure à 2σ (~0.0463). En pratique, l’écart de bruit mesuré est un peu plus haut que la tolérance nominale, donc il est prudent de ne pas rétrécir cette tolérance tant qu’un bootstrap plus robuste n’a pas été reconduit sur un jeu de référence re-gelé. 

> En pratique, la règle de décision est : `tolérance effective = max(tolérance métier, 2σ bootstrap)`. Cela garantit que le garde-fou reste au-dessus du bruit de mesure et ne déclenche pas sur du seul hasard.

## Procédure de mise à jour des seuils

- **Qui** : Romain, en accord avec Sophie Léger (Lead Data) avant tout changement en prod.
- **Quand** : à chaque changement de version majeure du modèle (ex. v2.0 → v3.0), ou si le jeu de référence est reconstruit.
- **Comment** : garder `THRESHOLDS` dans `scripts/evaluate_model.py` ET ce fichier cohérents (même valeurs), si le jeu de référence change, **regeler le golden run** (`--freeze-baseline`) et remesurer le bootstrap avant de retoucher les tolérances.
