"""Politique de promotion (SQUELETTE À COMPLÉTER → scripts/promotion.py).

Ici vit **la décision**, séparée de la mécanique d'entraînement. C'est le geste
attendu en M6-B2 : transformer une politique métier en **fonction testable**.

Pourquoi une fonction pure ? Parce qu'elle se teste sur des **métriques
mockées**, sans entraîner quoi que ce soit :

    prod = {"f1_macro": 0.71, "recall_default": 0.62}
    cand = {"f1_macro": 0.74, "recall_default": 0.65}
    assert decide_promotion(cand, prod).promote is True

Un test de décision qui dépend d'un vrai entraînement casse dès que les données
bougent — et ne teste pas votre règle, mais scikit-learn.

Mini-cours : 04 (réentraînement + promotion).
"""

from __future__ import annotations

from dataclasses import dataclass

# Plancher de qualité absolu, hérité de M5-B2.
# Le candidat n'est-il pas simplement cassé ?
THRESHOLDS: dict[str, float] = {"f1_macro": 0.55,
                                "f1_default": 0.35,
                                "roc_auc": 0.65,
                                "recall_default": 0.55}

# Voir decisions.md :
#            - pourquoi le recall de la classe défaut est-il contraignant ?
#              (que coûte un défaut prédit comme remboursé ?)
#            - pourquoi F1 macro plutôt que l'accuracy ?
#              (quel est le taux de défauts dans les données ?)
CRITICAL_METRICS: tuple[str, ...] = (
    "recall_default",
    "f1_macro",
)

# TODO 3 — Tolérance de régression et gain minimum.
#          Sans tolérance, un écart de 3ᵉ décimale (bruit d'échantillonnage)
#          bloque un candidat meilleur sur la métrique métier.
#          Sans gain minimum, un modèle identique est promu pour rien.
REGRESSION_TOLERANCE: dict[str, float] = {
    "f1_macro": 0.05,
    "f1_default": 0.05,
    "roc_auc": 0.05,
    "recall_default": 0.08,
}

MIN_GAIN: dict[str, float] = {
    "f1_macro": 0.03,
    "recall_default": 0.01,
}


@dataclass(frozen=True)
class PromotionDecision:
    """Résultat d'une décision de promotion.

    Attributes:
        promote: True si le candidat doit remplacer le modèle de production.
        reason: Justification lisible, destinée au journal de décision.
    """

    promote: bool
    reason: str


def decide_promotion(
    candidate: dict[str, float],
    production: dict[str, float],
) -> PromotionDecision:
    """Décide si un modèle candidat doit être promu en production.

    Args:
        candidate: Métriques du candidat sur le jeu de référence.
        production: Métriques du modèle en production, sur le **même** jeu.

    Returns:
        La décision et sa justification.
    """
    # TODO 4 — Dans cet ordre :
    #   1. le plancher de qualité est-il tenu ? sinon → refus motivé
    #   2. une métrique critique recule-t-elle de plus que TOLERANCE ?
    #      → refus motivé, en nommant la métrique et l'écart
    #   3. au moins une métrique progresse-t-elle d'au moins MIN_GAIN ?
    #      sinon → refus (le candidat n'achète rien)
    #   4. sinon → promotion, en explicitant le gain ET l'arbitrage consenti
    #
    # La `reason` finit dans le journal de décision et sera relue par Sophie
    # Léger : elle doit être compréhensible sans le code sous les yeux.
    raise NotImplementedError
