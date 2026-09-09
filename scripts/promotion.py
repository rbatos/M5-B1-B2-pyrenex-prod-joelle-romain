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

# Tolérance de régression et gain minimum.
#          Sans tolérance, un écart de 3ᵉ décimale (bruit d'échantillonnage)
#          bloque un candidat meilleur sur la métrique métier.
#          Sans gain minimum, un modèle identique est promu pour rien.
REGRESSION_TOLERANCE: dict[str, float] = {
    "f1_macro": 0.05,
    "f1_default": 0.05,
    "roc_auc": 0.05,
    "recall_default": 0.0,
}

MIN_GAIN: dict[str, float] = {
    "f1_macro": 0.03,
    "recall_default": 0.01,
}

def _fmt_delta(value: float) -> str:
    return f"{value:+.4f}"

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
    # Dans cet ordre :
    #   1. le plancher de qualité est-il tenu ? sinon → refus motivé
    #   2. une métrique critique recule-t-elle de plus que TOLERANCE ?
    #      → refus motivé, en nommant la métrique et l'écart
    #   3. au moins une métrique progresse-t-elle d'au moins MIN_GAIN ?
    #      sinon → refus (le candidat n'achète rien)
    #   4. sinon → promotion, en explicitant le gain ET l'arbitrage consenti
    #
    # La `reason` finit dans le journal de décision et sera relue par Sophie
    # Léger : elle doit être compréhensible sans le code sous les yeux.
    
    expected_metrics = set(THRESHOLDS)

    missing_candidate = sorted(expected_metrics - set(candidate))
    missing_production = sorted(expected_metrics - set(production))

    if missing_candidate:
        raise ValueError(f"Métriques manquantes côté candidat: {missing_candidate}")
    if missing_production:
        raise ValueError(f"Métriques manquantes côté production: {missing_production}")

    # 1. Plancher absolu
    for metric_name, floor in THRESHOLDS.items():
        cand_value = float(candidate[metric_name])
        if cand_value < floor:
            return PromotionDecision(
                promote=False,
                reason=(
                    f"REJECT: {metric_name}={cand_value:.4f} sous le plancher "
                    f"absolu {floor:.4f}."
                ),
            )

    # 2. Régression critique au-delà de la tolérance
    critical_deltas: dict[str, float] = {}
    for metric_name in CRITICAL_METRICS:
        cand_value = float(candidate[metric_name])
        prod_value = float(production[metric_name])
        delta = cand_value - prod_value
        critical_deltas[metric_name] = delta

        tolerance = REGRESSION_TOLERANCE[metric_name]
        if delta < -tolerance:
            return PromotionDecision(
                promote=False,
                reason=(
                    f"REJECT: {metric_name} régresse de {_fmt_delta(delta)} "
                    f"(production={prod_value:.4f}, candidat={cand_value:.4f}), "
                    f"au-delà de la tolérance {tolerance:.4f}."
                ),
            )

    # 3. Gain minimum sur au moins une métrique critique
    significant_gains = {
        metric_name: delta
        for metric_name, delta in critical_deltas.items()
        if delta >= MIN_GAIN[metric_name]
    }

    if not significant_gains:
        gains_text = ", ".join(
            f"{metric}={_fmt_delta(delta)} "
            f"(min requis {MIN_GAIN[metric]:.4f})"
            for metric, delta in critical_deltas.items()
        )
        return PromotionDecision(
            promote=False,
            reason=(
                "REJECT: aucun gain minimum atteint sur les métriques critiques. "
                f"{gains_text}."
            ),
        )

    # 4. Promotion avec justification lisible
    best_metric = max(significant_gains, key=significant_gains.get)
    best_gain = significant_gains[best_metric]

    tradeoffs = []
    for metric_name, delta in critical_deltas.items():
        if metric_name == best_metric:
            continue
        if delta < 0:
            tolerance = REGRESSION_TOLERANCE[metric_name]
            tradeoffs.append(
                f"{metric_name} {_fmt_delta(delta)} dans la tolérance {tolerance:.4f}"
            )

    reason = (
        f"PROMOTE: gain minimum atteint sur {best_metric} "
        f"avec {_fmt_delta(best_gain)} "
        f"(min requis {MIN_GAIN[best_metric]:.4f}, "
        f"production={production[best_metric]:.4f}, "
        f"candidat={candidate[best_metric]:.4f})."
    )

    if tradeoffs:
        reason += " Arbitrage assumé: " + "; ".join(tradeoffs) + "."

    return PromotionDecision(promote=True, reason=reason)
