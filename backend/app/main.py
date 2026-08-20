from __future__ import annotations

from pathlib import Path
import random

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.app.core.model import GammaIrradiationModel
from backend.app.services.projects import load_project, save_project

app = FastAPI(title="Gamma Irradiation Web Model", version="0.1.0")
_model: GammaIrradiationModel | None = None
FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "dist"
app.mount("/assets", StaticFiles(directory=FRONTEND / "assets"), name="assets")


class ModelStream:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.clients.add(websocket)

    async def publish(self, message: dict) -> None:
        for client in tuple(self.clients):
            try:
                await client.send_json(message)
            except RuntimeError:
                self.clients.discard(client)


stream = ModelStream()


class ModelRequest(BaseModel):
    dimensions: list[int] = Field(default=[30, 30], min_length=2, max_length=3)
    moved_atoms: int = Field(default=0, ge=0)
    seed_init: int | None = None
    seed_sim: int | None = None
    profile: str = "fe_co60_physical"
    q_max_ev: float | None = Field(default=None, ge=0)
    frenkel_threshold_ev: float = Field(default=40, ge=0)
    recombine_threshold_ev: float = Field(default=4, ge=0)
    moved_surface_atoms: int = Field(default=0, ge=0)
    defect_concentration: float | None = Field(default=None, ge=0, le=1)
    thresholds: dict[str, float] | None = None
    weights: dict[str, float] | None = None


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
    overwrite: bool = False


class ExperimentRequest(BaseModel):
    runs: int = Field(default=30, ge=1, le=100)
    steps: int = Field(default=100, ge=1, le=1000)
    master_seed: int = 42
    bootstrap_samples: int = Field(default=2000, ge=100, le=5000)


def current_model() -> GammaIrradiationModel:
    if _model is None:
        raise HTTPException(status_code=409, detail="Create a model before requesting its state")
    return _model


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/model", status_code=201)
async def create_model(request: ModelRequest) -> dict:
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
            moved_surface_atoms=request.moved_surface_atoms,
            defect_concentration=request.defect_concentration,
            thresholds=request.thresholds,
            weights=request.weights,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    snapshot = _model.snapshot()
    await stream.publish({"type": "snapshot", "snapshot": snapshot})
    return snapshot


@app.get("/api/model/snapshot")
def model_snapshot() -> dict:
    return current_model().snapshot()


@app.post("/api/model/step")
async def model_step(request: StepRequest) -> dict:
    event = current_model().step(forced_energy=request.forced_energy)
    await stream.publish({"type": "event", "event": event, "snapshot": current_model().snapshot()})
    return event


@app.post("/api/model/undo")
async def undo_model() -> dict:
    try:
        snapshot = current_model().undo()
        await stream.publish({"type": "snapshot", "snapshot": snapshot})
        return snapshot
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/model/redo")
async def redo_model() -> dict:
    try:
        snapshot = current_model().redo()
        await stream.publish({"type": "snapshot", "snapshot": snapshot})
        return snapshot
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/model/move")
async def move_atom(request: MoveRequest) -> dict:
    try:
        event = current_model().move(request.atom_id, request.destination_key)
        await stream.publish({"type": "event", "event": event, "snapshot": current_model().snapshot()})
        return event
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/api/model/atoms/{atom_id}/destinations")
def move_destinations(atom_id: int) -> dict:
    try:
        return {"atom_id": atom_id, "destinations": current_model().available_destinations(atom_id)}
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post("/api/model/run")
async def run_model(steps: int = 1) -> dict:
    if not 1 <= steps <= 1000:
        raise HTTPException(status_code=422, detail="steps must be between 1 and 1000")
    events = []
    for _ in range(steps):
        event = current_model().step()
        events.append(event)
        await stream.publish({"type": "event", "event": event, "snapshot": current_model().snapshot()})
    return {"events": events, "snapshot": current_model().snapshot()}


@app.post("/api/model/pause")
async def pause_model() -> dict:
    result = {"paused": True, "snapshot": current_model().snapshot()}
    await stream.publish({"type": "status", **result})
    return result


@app.post("/api/model/probabilities")
def probabilities(request: ProbabilityRequest) -> dict:
    model = current_model()
    if request.atom_id not in model.atoms:
        raise HTTPException(status_code=404, detail="Atom does not exist")
    # A diagnostic call is pure: it never advances the simulation RNG or revision.
    outcomes = model.probability_outcomes(request.atom_id, request.energy_ev)
    return {
        "atom_id": request.atom_id,
        "energy_ev": request.energy_ev,
        "outcomes": outcomes,
        "total_probability": sum(item["probability"] for item in outcomes),
    }


@app.post("/api/experiment")
def experiment(request: ExperimentRequest) -> dict:
    source = current_model()
    seed_rng = random.Random(request.master_seed)
    trajectories: list[list[dict]] = []
    for _ in range(request.runs):
        model = GammaIrradiationModel(
            dimensions=source.dimensions,
            moved_atoms=source.moved_atoms,
            moved_surface_atoms=source.moved_surface_atoms,
            defect_concentration=source.defect_concentration,
            seed_init=seed_rng.randrange(2**31),
            seed_sim=seed_rng.randrange(2**31),
            profile=source.profile,
            q_max_ev=source.q_max_ev,
            frenkel_threshold_ev=source.frenkel_threshold_ev,
            recombine_threshold_ev=source.recombine_threshold_ev,
            thresholds=source.thresholds,
            weights=source.weights,
        )
        trajectory = [model.metrics()]
        for _ in range(request.steps):
            model.step()
            trajectory.append(model.metrics())
        trajectories.append(trajectory)
    bootstrap_rng = random.Random(request.master_seed ^ 0x5EED)

    def interval(values: list[float]) -> list[float]:
        means = sorted(
            sum(values[bootstrap_rng.randrange(request.runs)] for _ in range(request.runs)) / request.runs
            for _ in range(request.bootstrap_samples)
        )
        lower = means[int((len(means) - 1) * 0.025)]
        upper = means[int((len(means) - 1) * 0.975)]
        return [lower, upper]

    return {
        "runs": request.runs,
        "steps": request.steps,
        "bootstrap_samples": request.bootstrap_samples,
        "trajectory": [
            {
                "act": index,
                "entropy_mean": sum(run[index]["entropy"] for run in trajectories) / request.runs,
                "defects_mean": sum(run[index]["defects"] for run in trajectories) / request.runs,
                "vacancies_mean": sum(run[index]["vacancies"] for run in trajectories) / request.runs,
                "interstitials_mean": sum(run[index]["interstitials"] for run in trajectories) / request.runs,
                "surface_defects_mean": sum(run[index]["surface_defects"] for run in trajectories) / request.runs,
                "entropy_ci95": interval([run[index]["entropy"] for run in trajectories]),
                "defects_ci95": interval([run[index]["defects"] for run in trajectories]),
            }
            for index in range(request.steps + 1)
        ],
    }


@app.post("/api/project/save")
def save_model(request: ProjectRequest) -> dict:
    try:
        return save_project(request.name, current_model(), request.overwrite)
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
    await stream.connect(websocket)
    await websocket.send_json({"type": "snapshot", "snapshot": current_model().snapshot()})
    try:
        while True:
            message = await websocket.receive_json()
            if message.get("type") == "snapshot":
                await websocket.send_json({"type": "snapshot", "snapshot": current_model().snapshot()})
    except WebSocketDisconnect:
        pass
    finally:
        stream.clients.discard(websocket)


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")
