from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import services.feedback.app.main as feedback_main
import scripts.retrain as retrain


@pytest.fixture()
def isolated_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    temp_root = ROOT / "tmp_test_artifacts" / "retrain_runtime"
    temp_data = temp_root / "data"
    temp_models = temp_root / "services" / "model" / "models"

    if temp_root.exists():
        shutil.rmtree(temp_root)

    temp_data.mkdir(parents=True)
    temp_models.mkdir(parents=True)

    source_data = ROOT / "data"
    source_models = ROOT / "services" / "model" / "models"

    shutil.copy(source_data / "lending_club_train.csv", temp_data / "lending_club_train.csv")
    shutil.copy(source_data / "reference_set.csv", temp_data / "reference_set.csv")
    shutil.copy(source_models / "pyrenex_risk_v2.joblib", temp_models / "pyrenex_risk_v2.joblib")
    shutil.copy(source_models / "pyrenex_risk_v2.json", temp_models / "pyrenex_risk_v2.json")

    prod_seed = pd.read_csv(source_data / "prod_scored.csv").iloc[[0]].copy()
    prod_seed.to_csv(temp_data / "prod_scored.csv", index=False)

    db_path = temp_data / "feedbacks.db"
    decision_log = temp_root / "decisions_log.jsonl"
    candidate_path = temp_models / "pyrenex_risk_candidate.joblib"
    promoted_path = temp_models / "pyrenex_risk_v2_1.joblib"

    monkeypatch.setattr(feedback_main, "DATA", temp_data)
    monkeypatch.setattr(feedback_main, "DB_PATH", db_path)

    monkeypatch.setattr(retrain, "ROOT", temp_root)
    monkeypatch.setattr(retrain, "DATA", temp_data)
    monkeypatch.setattr(retrain, "MODELS", temp_models)
    monkeypatch.setattr(retrain, "CANDIDATE_PATH", candidate_path)
    monkeypatch.setattr(retrain, "PROMOTED_PATH", promoted_path)
    monkeypatch.setattr(retrain, "PRODUCTION_PATH", temp_models / "pyrenex_risk_v2.joblib")
    monkeypatch.setattr(retrain, "PRODUCTION_META_PATH", temp_models / "pyrenex_risk_v2.json")
    monkeypatch.setattr(retrain, "DECISION_LOG", decision_log)

    monkeypatch.setattr(
        retrain,
        "decide_promotion",
        lambda candidate, production: SimpleNamespace(
            promote=True,
            reason="forced by test",
        ),
    )

    print(f"db_path={db_path}")
    print(f"decision_log={decision_log}")
    print(f"candidate_path={candidate_path}")
    print(f"promoted_path={promoted_path}")

    return {
        "db_path": db_path,
        "decision_log": decision_log,
        "candidate_path": candidate_path,
        "promoted_path": promoted_path,
        "request_id": str(prod_seed.iloc[0]["request_id"]),
    }


def test_feedback_to_retrain_e2e(isolated_runtime: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    request_id = isolated_runtime["request_id"]

    with TestClient(feedback_main.app) as client:
        response = client.post(
            "/feedback",
            json={
                "request_id": request_id,
                "true_label": 1,
                "comments": "e2e test",
            },
        )
        assert response.status_code == 201
        assert response.json() == {"status": "stored", "request_id": request_id}

        count_before = client.get("/feedback/count")
        assert count_before.status_code == 200
        assert count_before.json() == {"count": 1, "new": 1}

    monkeypatch.setattr(sys, "argv", ["retrain.py", "--min-feedback", "1"])
    exit_code = retrain.main()
    assert exit_code == 0

    with sqlite3.connect(isolated_runtime["db_path"]) as connection:
        row = connection.execute(
            "SELECT request_id, true_label, used_for_training FROM feedbacks"
        ).fetchone()

    assert row == (request_id, 1, 1)
    assert isolated_runtime["candidate_path"].exists()
    assert isolated_runtime["promoted_path"].exists()
    assert isolated_runtime["decision_log"].exists()

    record = json.loads(isolated_runtime["decision_log"].read_text(encoding="utf-8").splitlines()[-1])
    assert record["promote"] is True
    assert record["reason"] == "forced by test"

    with TestClient(feedback_main.app) as client:
        count_after = client.get("/feedback/count")
        assert count_after.status_code == 200
        assert count_after.json() == {"count": 1, "new": 0}


def test_retrain_skips_when_threshold_not_reached(
    isolated_runtime: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    request_id = isolated_runtime["request_id"]

    with TestClient(feedback_main.app) as client:
        response = client.post(
            "/feedback",
            json={"request_id": request_id, "true_label": 1},
        )
        assert response.status_code == 201

    monkeypatch.setattr(sys, "argv", ["retrain.py", "--min-feedback", "2"])
    exit_code = retrain.main()
    assert exit_code == 0

    stdout = capsys.readouterr().out
    assert "Skip:" in stdout
    assert not isolated_runtime["candidate_path"].exists()
    assert not isolated_runtime["promoted_path"].exists()
    assert not isolated_runtime["decision_log"].exists()

    with TestClient(feedback_main.app) as client:
        count_after = client.get("/feedback/count")
        assert count_after.status_code == 200
        assert count_after.json() == {"count": 1, "new": 1}