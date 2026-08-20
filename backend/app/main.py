from __future__ import annotations

from pathlib import Path
import random

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.app.core.model import GammaIrradiationModel
from backend.app.services.projects import load_project, save_project

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
    q_max_ev: float | None = Field(default=None, ge=0)
    frenkel_threshold_ev: float = Field(default=40, ge=0)
    recombine_threshold_ev: float = Field(default=4, ge=0)


class StepRequest(BaseModel):
    forced_energy: float | None = Field(default=None, ge=0)


class ProbabilityRequest(BaseModel):
    atom_id: int = Field(ge=0)
    energy_ev: float = Field(ge=0)


class MoveRequest(BaseModel):
    atom_id: int = Field(ge=0)
    destination_key: str


class ProjectRequest(BaseModel):
    name: str


class ExperimentRequest(BaseModel):
    runs: int = Field(default=30, ge=1, le=100)
    steps: int = Field(default=100, ge=1, le=1000)
    master_seed: int = 42


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
            q_max_ev=request.q_max_ev,
            frenkel_threshold_ev=request.frenkel_threshold_ev,
            recombine_threshold_ev=request.recombine_threshold_ev,
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


@app.post("/api/model/undo")
def undo_model() -> dict:
    try:
        return current_model().undo()
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/model/redo")
def redo_model() -> dict:
    try:
        return current_model().redo()
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/model/move")
def move_atom(request: MoveRequest) -> dict:
    try:
        return current_model().move(request.atom_id, request.destination_key)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/model/run")
def run_model(steps: int = 1) -> dict:
    if not 1 <= steps <= 1000:
        raise HTTPException(status_code=422, detail="steps must be between 1 and 1000")
    events = [current_model().step() for _ in range(steps)]
    return {"events": events, "snapshot": current_model().snapshot()}


@app.post("/api/model/pause")
def pause_model() -> dict:
    return {"paused": True, "snapshot": current_model().snapshot()}


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


@app.post("/api/experiment")
def experiment(request: ExperimentRequest) -> dict:
    source = current_model()
    seed_rng = random.Random(request.master_seed)
    trajectories: list[list[dict]] = []
    for _ in range(request.runs):
        model = GammaIrradiationModel(
            dimensions=source.dimensions,
            seed_init=seed_rng.randrange(2**31),
            seed_sim=seed_rng.randrange(2**31),
            profile=source.profile,
        )
        trajectory = [model.metrics()]
        for _ in range(request.steps):
            model.step()
            trajectory.append(model.metrics())
        trajectories.append(trajectory)
    return {
        "runs": request.runs,
        "steps": request.steps,
        "trajectory": [
            {
                "act": index,
                "entropy_mean": sum(run[index]["entropy"] for run in trajectories) / request.runs,
                "defects_mean": sum(run[index]["defects"] for run in trajectories) / request.runs,
            }
            for index in range(request.steps + 1)
        ],
    }


@app.post("/api/project/save")
def save_model(request: ProjectRequest) -> dict:
    try:
        return save_project(request.name, current_model())
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/project/load")
def load_model(request: ProjectRequest) -> dict:
    global _model
    try:
        _model = load_project(request.name)
        return _model.snapshot()
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.websocket("/ws/model")
async def model_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.send_json({"type": "snapshot", "snapshot": current_model().snapshot()})
    while True:
        message = await websocket.receive_json()
        if message.get("type") == "snapshot":
            await websocket.send_json({"type": "snapshot", "snapshot": current_model().snapshot()})


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")
