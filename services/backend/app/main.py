"""Service `backend` — orchestrateur (SQUELETTE À COMPLÉTER).

Rôle attendu : exposé au navigateur (via le frontend nginx), il valide
l'entrée avec le **même schéma Pydantic** que le modèle, appelle le service
`model` en interne (`http://model:8000/predict`), et expose `/health`,
`/score`, `/metrics`.

👉 Inspirez-vous du service `model` (déjà fourni) pour le pattern `/metrics`
   et le middleware de logging. Mini-cours : `02_FastAPI_metrics_Prometheus`.
"""
from __future__ import annotations

import os

import httpx
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware

from app.middleware import LoggingMiddleware
from app.schemas import HealthResponse, LoanApplication, Prediction

from prometheus_client import Counter, Histogram
from prometheus_fastapi_instrumentator import Instrumentator

from pathlib import Path
from datetime import datetime, timezone
import csv

# URL du service model — configurable par variable d'env (dev/staging/prod)
MODEL_URL = os.environ.get("MODEL_URL", "http://model:8000")
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "http://localhost:8088").split(",")

app = FastAPI(title="Pyrenex Backend Orchestrator", version="1.0.0")
app.add_middleware(LoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Request-ID"],
)


# TODO 1 — exposer /metrics avec prometheus-fastapi-instrumentator
#   (cf. service model). Pensez à une métrique métier : compteur d'erreurs
#   upstream lors de l'appel au model.
# Expose /metrics (latence, RPS, codes retour) + métrique métier sur les
# erreurs remontées par le service model lors de l'appel upstream.
# Métriques métier custom
MODEL_UPSTREAM_ERRORS_TOTAL = Counter(
    "backend_model_upstream_errors_total",
    "Nombre d'erreurs remontées par le service model lors d'un appel /score.",
    labelnames=("kind",),
)
# Buckets fins sur la plage attendue (appel interne réseau, quelques ms à ~1s)
# pour obtenir des p50/p95/p99 précis via histogram_quantile en Grafana.
MODEL_CALL_DURATION_SECONDS = Histogram(
    "backend_model_call_duration_seconds",
    "Durée de l'appel HTTP interne vers le service model (hors traitement backend).",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0),
)
BACKEND_PREDICTIONS_TOTAL = Counter(
    "backend_predictions_total",
    "Décisions renvoyées au client, par classe prédite et version de modèle.",
    labelnames=("predicted_class", "model_version"),
)
BACKEND_PREDICTION_PROBA = Histogram(
    "backend_prediction_proba",
    "Distribution des probabilités de défaut renvoyées au client (dérive du comportement du modèle).",
    buckets=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)
# Métriques HTTP automatiques + endpoint /metrics
Instrumentator(should_group_status_codes=False).instrument(app).expose(
    app, endpoint="/metrics", include_in_schema=False
)


# Stockage des appels pour recherche lors de feedbacks
DATA = Path(__file__).resolve().parents[3] / "data"
SCORED_PATH = DATA / "prod_scored.csv"

def persist_scored_application(
    request_id: str,
    application: LoanApplication,
    prediction: Prediction,
) -> None:
    DATA.mkdir(exist_ok=True)

    row = {
        "request_id": request_id,
        **application.model_dump(),
        "prediction": prediction.prediction,
        "probability": prediction.probability,
        "model_version": prediction.model_version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    file_exists = SCORED_PATH.exists()
    with SCORED_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness du backend (ne dépend PAS du model)."""
    return HealthResponse(status="ok")



# TODO 2 — route POST /score :
#   - reçoit une LoanApplication (validée par Pydantic),
#   - appelle MODEL_URL/predict en interne (httpx async),
#   - propage le header X-Request-ID,
#   - gère les erreurs : model injoignable → 503, model en erreur → 502,
#   - retourne un objet Prediction.
#
# @app.post("/score", response_model=Prediction)
# async def score(application: LoanApplication, request: Request) -> Prediction:
#     ...
@app.post("/score", response_model=Prediction, status_code=status.HTTP_200_OK)
async def score(application: LoanApplication, request: Request) -> Prediction:
    """Valide la demande, l'envoie au modèle et renvoie le résultat."""
    request_id = getattr(request.state, "request_id", request.headers.get("X-Request-ID", "n/a"))

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            with MODEL_CALL_DURATION_SECONDS.time():
                response = await client.post(
                    f"{MODEL_URL.rstrip('/')}/predict",
                    json=application.model_dump(),
                    headers={"X-Request-ID": request_id},
                )
    except httpx.RequestError as exc:
        MODEL_UPSTREAM_ERRORS_TOTAL.labels(kind="unreachable").inc()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Model service unavailable",
        ) from exc

    if response.status_code >= 400:
        MODEL_UPSTREAM_ERRORS_TOTAL.labels(kind="bad_status").inc()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Model error {response.status_code}: {response.text[:200]}",
        )

    try:
        payload = response.json()
    except ValueError as exc:  # pragma: no cover - protection défensive
        MODEL_UPSTREAM_ERRORS_TOTAL.labels(kind="invalid_json").inc()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Invalid JSON returned by model",
        ) from exc

    payload["request_id"] = request_id

    try:
        prediction = Prediction(**payload)
    except Exception as exc:  # noqa: BLE001
        MODEL_UPSTREAM_ERRORS_TOTAL.labels(kind="schema_mismatch").inc()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Model response schema mismatch",
        ) from exc

    BACKEND_PREDICTIONS_TOTAL.labels(
        predicted_class=str(prediction.prediction),
        model_version=prediction.model_version,
    ).inc()
    BACKEND_PREDICTION_PROBA.observe(prediction.probability)

    persist_scored_application(request_id=request_id,
                               application=application,
                               prediction=prediction)

    return prediction
