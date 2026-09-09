"""Reproducible preprocessing pipeline for Pyrenex Crédit scoring.

✅ SOLUTION — feature lists résolues. Voir README_correctif.md pour les
choix d'implémentation et les alternatives valables côté apprenant.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

# --- Feature lists ----------------------------------------------------------
# Choix : toutes les features du dataset 2025 sont utilisées, séparées en
# numériques continues vs catégorielles avec faible/moyenne cardinalité.
# Note formatrice : dans le vrai Lending Club il y aurait aussi `state`
# (état US). On l'excluerait car c'est un proxy géographique fortement
# corrélé à des variables sensibles (revenu médian par état, démographie,
# taux de chômage local) — l'inclure ferait du *redlining* statistique
# (discrimination indirecte par zone géographique). Sujet approfondi en M2.
NUMERIC_FEATURES: list[str] = [
    "loan_amnt",
    "int_rate",
    "installment",
    "annual_inc",
    "dti",
    "delinq_2yrs",
    "fico_range_low",
    "revol_util",
]
CATEGORICAL_FEATURES: list[str] = [
    "term",
    "grade",
    "home_ownership",
    "verification_status",
    "purpose",
    "emp_length",
]
TARGET_COLUMN: str = "loan_status"
TARGET_MAPPING: dict[str, int] = {"Fully Paid": 0, "Charged Off": 1}


def load_dataset(path: Path) -> tuple[pd.DataFrame, pd.Series]:
    """Load Lending Club CSV, return (X, y).

    Only the feature columns declared above + the target are kept — extra
    columns of the raw CSV are dropped to keep the schema explicit.
    """
    df = pd.read_csv(path)
    required = [*NUMERIC_FEATURES, *CATEGORICAL_FEATURES, TARGET_COLUMN]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise KeyError(f"Missing columns in dataset: {missing}")

    y = df[TARGET_COLUMN].map(TARGET_MAPPING)
    if y.isna().any():
        unknown = df.loc[y.isna(), TARGET_COLUMN].unique().tolist()
        raise ValueError(f"Unmapped target labels: {unknown}")

    X = df[NUMERIC_FEATURES + CATEGORICAL_FEATURES].copy()
    return X, y


def build_preprocessor() -> ColumnTransformer:
    """Build the ColumnTransformer applying numeric + categorical pipelines."""
    numeric_pipeline = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
        ]
    )
    categorical_pipeline = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ]
    )
    return ColumnTransformer(
        transformers=[
            ("num", numeric_pipeline, NUMERIC_FEATURES),
            ("cat", categorical_pipeline, CATEGORICAL_FEATURES),
        ],
        remainder="drop",
        verbose_feature_names_out=False,
    )
