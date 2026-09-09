"""Réentraînement automatique (SQUELETTE À COMPLÉTER → scripts/retrain.py).

Déclenché sur un seuil de feedbacks **non consommés**. Réutilise la Pipeline M1
(preprocess.py). Mini-cours : 03 (trigger), 04 (réentraînement + promotion).

⚠️ Deux questions distinctes, à ne jamais confondre :
  - « pourquoi réentraîner ? »  → le TRIGGER (ci-dessous)
  - « pourquoi déployer ? »     → la PROMOTION (scripts/promotion.py)
Un réentraînement déclenché n'implique aucune mise en production.
"""

from __future__ import annotations
import argparse
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from preprocess import (
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
)

# implémentez decide_promotion() dans scripts/promotion.py, puis :
from promotion import decide_promotion

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
MODELS = ROOT / "models"
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES

# Le candidat n'est PAS une version officielle tant qu'il n'est pas promu.
CANDIDATE_PATH = MODELS / "pyrenex_risk_candidate.joblib"
PROMOTED_PATH = MODELS / "pyrenex_risk_v2_1.joblib"
PRODUCTION_PATH = MODELS / "pyrenex_risk_v2.joblib"
DECISION_LOG = ROOT / "decisions_log.jsonl"

RF_PARAMS = dict(
    n_estimators=200,
    max_depth=10,
    min_samples_leaf=10,
    class_weight="balanced",
    random_state=42,
    n_jobs=-1,
)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--min-feedback", type=int, default=200)
    args = p.parse_args()
    feedbacks = pd.read_csv(DATA / "feedbacks_simules.csv")

    # TODO 1 — GARDE-SEUIL : comptez les feedbacks NON CONSOMMÉS
    #          (used_for_training == 0), PAS le total. Si < seuil → return 0
    #          (skip, ce n'est pas une erreur).
    #          Piège : avec COUNT(*), le cron redéclenche indéfiniment.

    # TODO 2 — build_training_data : train initial + lignes prod corrigées
    #          (jointure sur request_id). ⚠️ Le reference_set n'entre JAMAIS
    #          dans l'entraînement : c'est l'arbitre, pas un ingrédient.

    # TODO 3 — train_candidate : Pipeline(build_preprocessor(),
    #          RandomForestClassifier(**RF_PARAMS)), puis joblib.dump vers
    #          CANDIDATE_PATH. On écrit un CANDIDAT, pas un v2.1.0.

    # TODO 4 — CONTRACT TEST : le candidat sort une proba dans [0,1] sur le
    #          schéma attendu. Si KO → return 1 (vraie erreur technique).

    # TODO 5 — evaluate_candidate : mesurez le candidat ET le modèle de
    #          production sur le MÊME reference_set, avec le MÊME code.
    #          Sinon vous comparez deux mesures, pas deux modèles.

    # TODO 6 — DÉCISION : decide_promotion(candidate_metrics, production_metrics).
    #          Journalisez TOUJOURS la décision dans DECISION_LOG (promue ou
    #          rejetée) : métriques des deux modèles, verdict, raison.

    # TODO 7 — Si PROMOTE : joblib.dump vers PROMOTED_PATH + métadonnées,
    #          (en prod : git tag v2.1.0 + push).
    #          Si REJECT : aucun tag, aucun fichier v2.1.0 — et return 0.
    #          Un rejet est une décision normale, pas un plantage.
    #
    #          ⚠️ Les métadonnées ont un CONTRAT. Le service `model` de M5 lit
    #          metrics_holdout, sklearn_version et dataset_sha256 en accès
    #          direct : un JSON écrit de zéro avec vos seules clés fait démarrer
    #          le service, répondre /predict… et planter /info en 500 (KeyError).
    #          Repartez du JSON de production et surchargez ce qui change.
    #          Et recalculez dataset_sha256 sur le jeu réellement utilisé :
    #          hérité tel quel, il décrit le dataset de v2.0.0 — il ment.
    raise NotImplementedError


if __name__ == "__main__":
    sys.exit(main())
