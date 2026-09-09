"""Service `feedback` — collecte des annotations métier (SQUELETTE À COMPLÉTER).

POST /feedback : un conseiller renvoie la **vraie** classe d'un dossier déjà
scoré (`request_id`). On valide que le `request_id` existe (jointure avec
`prod_scored.csv`), puis on stocke dans SQLite. Quand assez de **nouveaux**
feedbacks se sont accumulés, le job `retrain.py` (cron) réentraîne.

Briques A (endpoint) et B (stockage).
Mini-cours : 01 (endpoint feedback), 02 (stockage versionné).

⚠️ Un feedback devient une **donnée d'entraînement**. Une annotation fausse, mal
rattachée ou écrasée en silence dégrade le prochain modèle. D'où les 4 cas à
traiter explicitement :

    request_id inconnu                  → 404
    label hors {0,1}                    → 422 (Pydantic s'en charge)
    même request_id, même label         → 201, sans doublon (rejeu réseau)
    même request_id, label différent    → 409 (arbitrage humain requis)
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

DATA = Path(__file__).parent.parent.parent.parent / "data"
DB_PATH = Path(os.environ.get("FEEDBACK_DB", DATA / "feedbacks.db"))


class Feedback(BaseModel):
    """Annotation métier sur un dossier déjà scoré."""

    request_id: str = Field(..., examples=["REQ-00042"])
    true_label: int = Field(..., ge=0, le=1, description="0 = remboursé, 1 = défaut")
    comments: str | None = None


def _init_db() -> None:
    """Crée la table de feedbacks si elle n'existe pas."""
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS feedbacks (
                request_id TEXT PRIMARY KEY,
                true_label INTEGER NOT NULL,
                comments   TEXT,
                created_at TEXT NOT NULL,
                used_for_training INTEGER NOT NULL DEFAULT 0
                -- TODO 1 (brique B) — ajoutez `used_for_training`
                -- (INTEGER NOT NULL DEFAULT 0).
                -- Sans cette colonne, le trigger ne peut compter que le TOTAL,
                -- et le cron redéclenche un réentraînement toutes les 6 h sur
                -- les mêmes données une fois le seuil franchi.
            )"""
        )
        columns = {row[1] for row in con.execute("PRAGMA table_info(feedbacks)")}
        if "used_for_training" not in columns:
            con.execute(
                "ALTER TABLE feedbacks ADD COLUMN used_for_training "
                "INTEGER NOT NULL DEFAULT 0"
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Charge les request_id valides + initialise la base au démarrage."""
    DB_PATH.parent.mkdir(exist_ok=True)
    _init_db()
    app.state.valid_ids = set(pd.read_csv(DATA / "prod_scored.csv")["request_id"])
    yield


app = FastAPI(title="Pyrenex Feedback Service", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/feedback/count")
async def count() -> dict[str, int]:
    """Volume de feedbacks : total et non encore consommés."""
    with sqlite3.connect(DB_PATH) as con:
        total = con.execute("SELECT COUNT(*) FROM feedbacks").fetchone()[0]
        new = con.execute("SELECT COUNT(*) FROM feedbacks WHERE used_for_training = 0").fetchone()[0]

    return {"count": int(total), "new": int(new)}


@app.post("/feedback", status_code=status.HTTP_201_CREATED)
async def post_feedback(fb: Feedback) -> dict[str, str]:
    """Enregistre une annotation métier."""
    if fb.request_id not in app.state.valid_ids:
        raise HTTPException(
            status_code=404, detail=f"request_id inconnu : {fb.request_id}"
        )

    with sqlite3.connect(DB_PATH) as con:
        existing = con.execute(
            "SELECT true_label FROM feedbacks WHERE request_id = ?",
            (fb.request_id,),
        ).fetchone()

        # Gestion du conflit :
        #   - s'il est identique     → réponse idempotente, pas de doublon ;
        #   - s'il est différent     → HTTP 409, avec un message explicite.
        if existing is not None:
            existing_label = int(existing[0])

            if existing_label == fb.true_label:
                return {"status": "stored", "request_id": fb.request_id}

            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"feedback contradictoire pour {fb.request_id} : "
                    f"label existant={existing_label}, nouveau label={fb.true_label}"
                ),
            )
            
        con.execute(
            "INSERT INTO feedbacks (request_id, true_label, comments, created_at, used_for_training) "
            "VALUES (?, ?, ?, ?, 0)",
            (
                fb.request_id,
                fb.true_label,
                fb.comments,
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    return {"status": "stored", "request_id": fb.request_id}
