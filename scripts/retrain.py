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
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import f1_score, recall_score, roc_auc_score
from sklearn.pipeline import Pipeline

sys.path.insert(0, str(Path(__file__).parent))
from preprocess import (
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
    TARGET_COLUMN,
    TARGET_MAPPING,
    build_preprocessor,
)

# implémentez decide_promotion() dans scripts/promotion.py, puis :
from promotion import decide_promotion

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
MODELS = ROOT / "services" / "model" / "models"
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES

# Le candidat n'est PAS une version officielle tant qu'il n'est pas promu.
CANDIDATE_PATH = MODELS / "pyrenex_risk_candidate.joblib"
PROMOTED_PATH = MODELS / "pyrenex_risk_v2_1.joblib"
PRODUCTION_PATH = MODELS / "pyrenex_risk_v2.joblib"
PRODUCTION_META_PATH = MODELS / "pyrenex_risk_v2.json"
DECISION_LOG = ROOT / "decisions_log.jsonl"

RF_PARAMS = dict(
    n_estimators=200,
    max_depth=10,
    min_samples_leaf=10,
    class_weight="balanced",
    random_state=42,
    n_jobs=-1,
)


def _compute_metrics(model: Any, data: pd.DataFrame) -> dict[str, float]:
    """Calcule les métriques de performance pour un modèle donné sur un jeu de données.

    Args:
        model: Modèle entraîné (pipeline ou classifieur).
        data: Jeu de données contenant les features et la cible.

    Returns:
        Dictionnaire des métriques calculées.
    """
    features = data[FEATURES]
    target = data[TARGET_COLUMN].map(TARGET_MAPPING)
    predictions = model.predict(features)
    probabilities = model.predict_proba(features)[:, 1]
    return {
        "f1_macro": round(f1_score(target, predictions, average="macro"), 4),
        "f1_default": round(f1_score(target, predictions, pos_label=1), 4),
        "roc_auc": round(roc_auc_score(target, probabilities), 4),
        "recall_default": round(recall_score(target, predictions, pos_label=1), 4),
    }


def _training_data(feedbacks: pd.DataFrame) -> pd.DataFrame:
    """Construit le jeu de données d'entraînement à partir des feedbacks et des lignes de production corrigées.

    Args:
        feedbacks: DataFrame contenant les feedbacks simulés.

    Returns:
        DataFrame prêt pour l'entraînement, avec les features et la cible.
    """
    training = pd.read_csv(DATA / "lending_club_train.csv")
    production_rows = pd.read_csv(DATA / "prod_scored.csv")
    corrected = feedbacks.merge(
        production_rows, on="request_id", how="inner", validate="one_to_one"
    )
    if not corrected.empty:
        corrected[TARGET_COLUMN] = corrected["true_label"].map(
            {0: "Fully Paid", 1: "Charged Off"}
        )
        training = pd.concat([training, corrected[training.columns]], ignore_index=True)
    return training[[*FEATURES, TARGET_COLUMN]]


def _sha256(data: pd.DataFrame) -> str:
    """Calcule le hash SHA-256 d'un DataFrame.

    Args:
        data: DataFrame à hasher.

    Returns:
        Chaîne hexadécimale représentant le hash SHA-256 du DataFrame.
    """
    return hashlib.sha256(data.to_csv(index=False).encode("utf-8")).hexdigest()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--min-feedback", type=int, default=200)
    args = p.parse_args()
    with sqlite3.connect(DATA / "feedbacks.db") as connection:
        feedbacks = pd.read_sql_query(
            "SELECT request_id, true_label, used_for_training FROM feedbacks",
            connection,
        )

    # GARDE-SEUIL : comptez les feedbacks NON CONSOMMÉS
    #          (used_for_training == 0), PAS le total. Si < seuil → return 0
    #          (skip, ce n'est pas une erreur).
    #          Piège : avec COUNT(*), le cron redéclenche indéfiniment.
    new_feedbacks = feedbacks[feedbacks["used_for_training"].eq(0)].copy()
    if len(new_feedbacks) < args.min_feedback:
        print(f"Skip: {len(new_feedbacks)} feedback(s) non consomme(s), seuil={args.min_feedback}")
        return 0

    # build_training_data : train initial + lignes prod corrigées
    #          (jointure sur request_id). ⚠️ Le reference_set n'entre JAMAIS
    #          dans l'entraînement : c'est l'arbitre, pas un ingrédient.
    train_data = _training_data(new_feedbacks[["request_id", "true_label"]])
    X_train = train_data[FEATURES]
    y_train = train_data[TARGET_COLUMN].map(TARGET_MAPPING)

    # train_candidate : Pipeline(build_preprocessor(),
    #          RandomForestClassifier(**RF_PARAMS)), puis joblib.dump vers
    #          CANDIDATE_PATH. On écrit un CANDIDAT, pas un v2.1.0.
    candidate = Pipeline(
        steps=[
            ("preprocessor", build_preprocessor()),
            ("classifier", RandomForestClassifier(**RF_PARAMS)),
        ]
    )
    candidate.fit(X_train, y_train)
    MODELS.mkdir(parents=True, exist_ok=True)
    joblib.dump(candidate, CANDIDATE_PATH)

    # CONTRACT TEST : le candidat sort une proba dans [0,1] sur le
    #          schéma attendu. Si KO → return 1 (vraie erreur technique).
    try:
        probabilities = candidate.predict_proba(X_train.iloc[:1])
        if probabilities.shape != (1, 2) or not 0 <= float(probabilities[0, 1]) <= 1:
            raise ValueError("probabilite hors intervalle [0, 1]")
    except Exception as exc:  # noqa: BLE001
        print(f"Contract test failed: {exc}", file=sys.stderr)
        return 1

    # evaluate_candidate : mesurez le candidat ET le modèle de
    #          production sur le MÊME reference_set, avec le MÊME code.
    #          Sinon vous comparez deux mesures, pas deux modèles.
    reference = pd.read_csv(DATA / "reference_set.csv")
    production = joblib.load(PRODUCTION_PATH)
    production_metadata = json.loads(
        PRODUCTION_META_PATH.read_text(encoding="utf-8")
    )
    candidate_metrics = _compute_metrics(candidate, reference)
    production_metrics = _compute_metrics(production, reference)

    # DÉCISION : decide_promotion(candidate_metrics, production_metrics).
    #          Journalisez TOUJOURS la décision dans DECISION_LOG (promue ou
    #          rejetée) : métriques des deux modèles, verdict, raison.
    decision = decide_promotion(candidate_metrics, production_metrics)
    decision_record = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "candidate_metrics": candidate_metrics,
        "production_metrics": production_metrics,
        "promote": decision.promote,
        "reason": decision.reason,
    }
    with DECISION_LOG.open("a", encoding="utf-8") as log:
        log.write(json.dumps(decision_record) + "\n")

    # Si PROMOTE : joblib.dump vers PROMOTED_PATH + métadonnées,
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
    if decision.promote:
        promoted_metadata = dict(production_metadata)
        promoted_metadata.update(
            {
                "model_version": "v2.1.0",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "sklearn_version": __import__("sklearn").__version__,
                "dataset_sha256": _sha256(train_data),
                "metrics_holdout": candidate_metrics,
                "hyperparameters": RF_PARAMS,
            }
        )
        joblib.dump(candidate, PROMOTED_PATH)
        (MODELS / "pyrenex_risk_v2_1.json").write_text(
            json.dumps(promoted_metadata, indent=2), encoding="utf-8"
        )

    with sqlite3.connect(DATA / "feedbacks.db") as connection:
        connection.executemany(
            "UPDATE feedbacks SET used_for_training = 1 WHERE request_id = ?",
            [(request_id,) for request_id in new_feedbacks["request_id"]],
        )
    print(json.dumps(decision_record, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
