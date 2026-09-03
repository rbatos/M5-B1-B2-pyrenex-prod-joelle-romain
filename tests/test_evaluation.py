"""Tests pour le script evaluate_model.py."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "evaluate_model.py"


def load_evaluate_model_module():
    """Charge dynamiquement le module evaluate_model depuis le chemin SCRIPT_PATH."""
    spec = importlib.util.spec_from_file_location("evaluate_model", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Impossible de charger le module depuis {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_check_thresholds_detects_absolute_and_relative_violations():
    """Vérifie que check_thresholds détecte les violations absolues et relatives."""
    mod = load_evaluate_model_module()

    metrics = {
        "f1_macro": 0.54,
        "f1_default": 0.34,
        "roc_auc": 0.64,
        "recall_default": 0.54,
    }
    baseline = {
        "f1_macro": 0.70,
        "f1_default": 0.70,
        "roc_auc": 0.70,
        "recall_default": 0.70,
    }

    violations = mod.check_thresholds(metrics, baseline)

    assert len(violations) >= 4
    assert any("plancher absolu" in violation for violation in violations)
    assert any("chute de" in violation for violation in violations)


def test_load_baseline_requires_frozen_reference_baseline(monkeypatch):
    """Vérifie que le chargement de la baseline échoue si la baseline de référence est manquante."""
    mod = load_evaluate_model_module()
    missing_baseline = ROOT / "data" / "missing_reference_baseline.json"
    monkeypatch.setattr(mod, "REFERENCE_BASELINE", missing_baseline)

    with pytest.raises(SystemExit, match="--freeze-baseline"):
        mod.load_baseline()


def test_cli_exits_non_zero_when_release_is_degraded():
    """Vérifie que le script CLI retourne un code non nul lorsque la release est dégradée."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--release-tag", "bad", "--degrade"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["violations"]
