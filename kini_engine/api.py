from __future__ import annotations

from typing import Any

from .core import KiniEngine, Match


try:
    from fastapi import FastAPI
except Exception:
    FastAPI = None  # type: ignore[assignment]


def create_app(engine: KiniEngine | None = None):
    if FastAPI is None:
        raise RuntimeError("Install kini-engine[api] to use the HTTP API")
    app = FastAPI(title="Kini API", version="0.2.0")
    model = engine or KiniEngine()

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "fitted": model.fitted}

    @app.post("/predict")
    def predict(
        home: str,
        away: str,
        kickoff_at: str,
        information_at: str,
    ) -> dict[str, Any]:
        p = model.predict(
            Match(kickoff_at, home, away),
            information_at=information_at,
        )
        return p.__dict__

    return app
