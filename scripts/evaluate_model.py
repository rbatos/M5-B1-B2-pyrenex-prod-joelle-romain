"""Évaluation continue + tracking MLflow (SQUELETTE M5-B2 À COMPLÉTER).

À chaque release : recalcule les métriques cibles sur un jeu de référence
figé, **trace le run dans MLflow**, compare aux seuils, et **sort un code
retour non-zéro** si dégradation (→ bloque la release en CI).

Renommez ce fichier en `scripts/evaluate_model.py` une fois complété.
Mini-cours : `07_MLflow_tracking_essentiel.md` + `08_Evaluation_continue_seuils`.

Usage cible::

    python scripts/evaluate_model.py --freeze-baseline             # une fois, au gel du jeu
    python scripts/evaluate_model.py --release-tag v2.0.0
    python scripts/evaluate_model.py --release-tag bad --degrade   # test du rouge
    mlflow ui    # comparer les runs

⚠️ **Le piège central du brief.** La tentation est de comparer vos métriques à
la baseline holdout annoncée en M1 (`metrics_holdout` dans le `.json`). Ne le
faites pas : le holdout et votre jeu de référence n'ont ni la même taille ni la
même composition. Vous mesureriez l'écart entre **deux populations**, pas la
dégradation du **modèle** — et votre garde-fou se déclencherait tout seul.
La baseline du garde-fou, c'est le **golden run** : les métriques mesurées sur
**votre** jeu de référence, au moment où vous le gelez.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import joblib
import mlflow
import numpy as np
import pandas as pd
from sklearn.metrics import f1_score, recall_score, roc_auc_score

ROOT = Path(__file__).parent.parent
MODELS_DIR = ROOT / "services" / "model" / "models"
REFERENCE_SET = ROOT / "data" / "reference_set.csv"
REFERENCE_BASELINE = ROOT / "data" / "reference_baseline.json"

# TODO 1 — définir vos seuils (stratégie absolu / relatif / hybride).
#   Documentez-les ET justifiez-les dans evaluation_thresholds.md.
#   ⚠️ Une tolérance relative n'a de sens que si elle est **plus grande que le
#   bruit de mesure** de votre jeu de référence. Mesurez ce bruit (bootstrap,
#   cf. mini-cours 08) et prenez au moins 2 σ. Sous le bruit, le garde-fou se
#   déclenche sur du hasard et vous perdez confiance en lui.
# Stratégie hybride : plancher absolu (marge modérée vs holdout M1) + baisse
# max tolérée vs golden run. recall_default a la tolérance la plus large car
# c'est la métrique la plus bruitée (peu de positifs dans le jeu de référence).
# Cf. evaluation_thresholds.md pour la justification complète.
THRESHOLDS: dict[str, dict[str, float]] = {
    "f1_macro": {"absolute_min": 0.55, "max_drop_vs_baseline": 0.05},
    "f1_default": {"absolute_min": 0.35, "max_drop_vs_baseline": 0.05},
    "roc_auc": {"absolute_min": 0.65, "max_drop_vs_baseline": 0.04},
    "recall_default": {"absolute_min": 0.55, "max_drop_vs_baseline": 0.08},
}


def compute_metrics(model, df: pd.DataFrame, meta: dict) -> dict[str, float]:
    """Calcule les métriques cibles sur le jeu de référence."""
    # TODO 2 — construire X (feature_columns_*) et y (target + target_mapping),
    #   prédire, et calculer f1_macro / f1_default / roc_auc / recall_default.
    feature_columns = meta["feature_columns_numeric"] + meta["feature_columns_categorical"]
    X = df[feature_columns]
    y = df[meta["target_column"]].map(meta["target_mapping"])

    preds = model.predict(X)
    proba = model.predict_proba(X)[:, 1]

    return {
        "f1_macro": round(f1_score(y, preds, average="macro"), 4),
        "f1_default": round(f1_score(y, preds, pos_label=1), 4),
        "roc_auc": round(roc_auc_score(y, proba), 4),
        "recall_default": round(recall_score(y, preds, pos_label=1), 4),
    }


def estimate_metric_std_bootstrap(model, df: pd.DataFrame, meta: dict, metric_name: str, n_bootstrap: int = 200, seed: int = 42) -> float:
    """Estime le bruit de mesure sur une métrique via bootstrap non paramétrique.

    On rééchantillonne le jeu de référence avec remise, on recalcule la métrique,
    puis on prend l'écart type empirique de la distribution bootstrap. Le garde-fou
    de release doit être au moins supérieur à 2σ pour rester au-dessus du bruit.
    """
    feature_columns = meta["feature_columns_numeric"] + meta["feature_columns_categorical"]
    target_column = meta["target_column"]
    target_mapping = meta["target_mapping"]
    rng = np.random.default_rng(seed)
    values: list[float] = []

    for _ in range(n_bootstrap):
        sample_idx = rng.integers(0, len(df), size=len(df))
        sample = df.iloc[sample_idx].reset_index(drop=True)
        X = sample[feature_columns]
        y = sample[target_column].map(target_mapping)
        preds = model.predict(X)
        proba = model.predict_proba(X)[:, 1]

        if metric_name == "f1_macro":
            value = f1_score(y, preds, average="macro")
        elif metric_name == "f1_default":
            value = f1_score(y, preds, pos_label=1)
        elif metric_name == "roc_auc":
            value = roc_auc_score(y, proba)
        elif metric_name == "recall_default":
            value = recall_score(y, preds, pos_label=1)
        else:
            raise ValueError(f"Metric inconnue: {metric_name}")

        values.append(float(value))

    return float(np.std(values, ddof=1))


def check_thresholds(metrics: dict[str, float], baseline: dict) -> list[str]:
    """Retourne la liste des violations de seuil (vide = release OK).

    Le seuil de baisse relative est au moins la tolérance métier et, si le bruit
    mesuré par bootstrap est plus élevé, on remonte au moins à 2σ pour rester au-dessus
    du bruit de mesure.
    """
    # TODO 3 — comparer chaque métrique à son plancher absolu ET à la baisse
    #   max tolérée vs baseline. Retourner les messages de violation.
    violations = []
    for name, rule in THRESHOLDS.items():
        value = metrics[name]
        if value < rule["absolute_min"]:
            violations.append(f"{name}={value} < plancher absolu {rule['absolute_min']}")

        baseline_value = baseline.get(name)
        sigma = baseline.get(f"{name}_sigma")
        effective_drop = rule["max_drop_vs_baseline"]
        if sigma is not None:
            effective_drop = max(effective_drop, 2.0 * float(sigma))

        if baseline_value is not None and baseline_value - value > effective_drop:
            sigma_text = f"; 2σ={2.0 * float(sigma):.4f}" if sigma is not None else ""
            violations.append(
                f"{name}={value} a chute de {baseline_value - value:.4f} "
                f"(> {effective_drop:.4f} tolere vs golden run {baseline_value}{sigma_text})"
            )
    return violations


def load_baseline() -> dict:
    """Charge le golden run (baseline mesurée sur le jeu de référence)."""
    # TODO 3bis — lire REFERENCE_BASELINE et renvoyer ses métriques.
    #   Si le fichier n'existe pas : lever une erreur explicite qui dit de
    #   lancer `--freeze-baseline`. Surtout **pas** de repli silencieux sur
    #   `meta["metrics_holdout"]` : ce serait comparer deux populations.
    if not REFERENCE_BASELINE.exists():
        raise SystemExit(
            f"{REFERENCE_BASELINE} est absent.\n"
            "Gelez d'abord le golden run : "
            "`python scripts/evaluate_model.py --freeze-baseline`."
        )
    return json.loads(REFERENCE_BASELINE.read_text(encoding="utf-8"))


def freeze_baseline(model, df: pd.DataFrame, meta: dict) -> dict:
    """Mesure et gèle le golden run sur le jeu de référence."""
    # TODO 3ter — calculer les métriques sur le jeu de référence et les écrire
    #   dans REFERENCE_BASELINE (avec model_version, reference_set,
    #   n_reference). Ce fichier est **versionné** : c'est lui qui arbitre les
    #   releases. À regeler seulement si le jeu OU le modèle de référence change.
    metrics = compute_metrics(model, df, meta)
    sigma_by_metric = {
        metric_name: estimate_metric_std_bootstrap(model, df, meta, metric_name)
        for metric_name in THRESHOLDS
    }
    baseline = {
        **metrics,
        **{f"{metric_name}_sigma": round(value, 6) for metric_name, value in sigma_by_metric.items()},
        "model_version": meta["model_version"],
        "reference_set": str(REFERENCE_SET.relative_to(ROOT)),
        "n_reference": len(df),
    }
    REFERENCE_BASELINE.write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    return baseline


def load_reference_set() -> pd.DataFrame:
    """Charge le jeu de référence, avec un garde-fou sur sa validité.

    Le jeu de référence est VOTRE instrument de mesure : vous le construisez
    à partir du holdout M1 (cf. `data/README.md`). Le fichier
    `reference_set_TEMPLATE.csv` livré dans le repo est un **exemple de
    format** de 20 lignes, pas un jeu de référence utilisable.
    """
    if not REFERENCE_SET.exists():
        raise SystemExit(
            f"{REFERENCE_SET} est absent.\n"
            "Ce fichier n'est pas fourni : c'est à vous de le construire à "
            "partir du holdout M1 (`data/lending_club_holdout.csv`).\n"
            "Mode d'emploi : data/README.md — étape 0."
        )
    df = pd.read_csv(REFERENCE_SET)
    if len(df) < 100 or df.iloc[:, -1].nunique() < 2:
        raise SystemExit(
            f"{REFERENCE_SET} contient {len(df)} ligne(s) et "
            f"{df.iloc[:, -1].nunique()} classe(s) de cible.\n"
            "Un instrument de mesure a besoin des DEUX classes et d'assez "
            "d'observations de la classe rare (~500 lignes attendues).\n"
            "Avez-vous copié reference_set_TEMPLATE.csv ? C'est un exemple de "
            "format, pas un jeu de référence — cf. data/README.md."
        )
    return df


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-tag", default="dev")
    parser.add_argument("--degrade", action="store_true")
    parser.add_argument("--freeze-baseline", action="store_true")
    args = parser.parse_args()

    model = joblib.load(MODELS_DIR / "pyrenex_risk_v2.joblib")
    meta = json.loads((MODELS_DIR / "pyrenex_risk_v2.json").read_text(encoding="utf-8"))
    df = load_reference_set()

    if args.freeze_baseline:
        print(json.dumps(freeze_baseline(model, df, meta), indent=2))
        return 0

    if args.degrade:
        # TODO 4 — simuler un bug de preprocessing réaliste (ex. désaligner
        #   X et y) pour PROUVER que le rouge bloque bien la release.
        # Bug de preprocessing réaliste : la cible est mélangée indépendamment
        # des features (ex. tri/jointure qui désynchronise X et y).
        df = df.copy()
        df[meta["target_column"]] = (
            df[meta["target_column"]].sample(frac=1, random_state=123).reset_index(drop=True)
        )

    metrics = compute_metrics(model, df, meta)
    baseline = load_baseline()  # ← le golden run, PAS metrics_holdout
    violations = check_thresholds(metrics, baseline)

    # --- Bloc MLflow PRÉ-CÂBLÉ — complétez params + metrics ------------------
    mlflow.set_experiment("pyrenex-eval-continue")
    sigma_metrics = {
        f"{metric_name}_sigma": float(baseline.get(f"{metric_name}_sigma", 0.0))
        for metric_name in THRESHOLDS
    }
    with mlflow.start_run(run_name=args.release_tag):
        mlflow.log_params(
            {
                "model_version": meta["model_version"],
                "release_tag": args.release_tag,
                # TODO 5 — ajouter reference_set, n_reference…
                "reference_set": str(REFERENCE_SET.relative_to(ROOT)),
                "n_reference": len(df),
                "degrade": args.degrade,
            }
        )
        mlflow.log_metrics({**metrics, **sigma_metrics})
        mlflow.set_tag("release_blocked", str(bool(violations)))
    # ------------------------------------------------------------------------

    print(json.dumps({"metrics": metrics, "violations": violations}, indent=2))
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
