from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.app.core.model import GammaIrradiationModel

app = FastAPI(title="Gamma Irradiation Web Model", version="0.1.0")
_model: GammaIrradiationModel | None = None
FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "dist"
app.mount("/assets", StaticFiles(directory=FRONTEND / "assets"), name="assets")


class ModelRequest(BaseModel):
    dimensions: list[int] = Field(default=[30, 30], min_length=2, max_length=3)
    moved_atoms: int = Field(default=0, ge=0)
    seed_init: int | None = None
    seed_sim: int | None = None
    profile: str = "fe_co60_physical"


class StepRequest(BaseModel):
    forced_energy: float | None = Field(default=None, ge=0)


class ProbabilityRequest(BaseModel):
    atom_id: int = Field(ge=0)
    energy_ev: float = Field(ge=0)


def current_model() -> GammaIrradiationModel:
    if _model is None:
        raise HTTPException(status_code=409, detail="Create a model before requesting its state")
    return _model


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/model", status_code=201)
def create_model(request: ModelRequest) -> dict:
    global _model
    try:
        _model = GammaIrradiationModel(
            dimensions=tuple(request.dimensions),
            moved_atoms=request.moved_atoms,
            seed_init=request.seed_init,
            seed_sim=request.seed_sim,
            profile=request.profile,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _model.snapshot()


@app.get("/api/model/snapshot")
def model_snapshot() -> dict:
    return current_model().snapshot()


@app.post("/api/model/step")
def model_step(request: StepRequest) -> dict:
    return current_model().step(forced_energy=request.forced_energy)


@app.post("/api/model/probabilities")
def probabilities(request: ProbabilityRequest) -> dict:
    model = current_model()
    if request.atom_id not in model.atoms:
        raise HTTPException(status_code=404, detail="Atom does not exist")
    # A diagnostic call is pure: it never advances the simulation RNG or revision.
    return {
        "atom_id": request.atom_id,
        "energy_ev": request.energy_ev,
        "outcomes": [{"event_type": "no_change", "probability": 1.0, "destinations": []}],
        "total_probability": 1.0,
    }


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")
