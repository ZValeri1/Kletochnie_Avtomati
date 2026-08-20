"""Portable JSON project storage with atomic replacement."""

from __future__ import annotations

import json
import os
import re
import csv
from io import StringIO
from pathlib import Path

from backend.app.core.model import GammaIrradiationModel

PROJECTS_ROOT = Path(__file__).resolve().parents[3] / "projects"
NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _project_path(name: str) -> Path:
    if not NAME_PATTERN.fullmatch(name):
        raise ValueError("Project name must contain only letters, digits, hyphens, or underscores")
    return PROJECTS_ROOT / name


def _write_json(target: Path, value: dict) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f"{target.suffix}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, target)


def _write_text(target: Path, value: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f"{target.suffix}.tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, target)


def save_project(name: str, model: GammaIrradiationModel, overwrite: bool = False) -> dict:
    path = _project_path(name)
    if path.exists() and any(path.iterdir()) and not overwrite:
        raise ValueError("Project folder is not empty; set overwrite to confirm replacement")
    path.mkdir(parents=True, exist_ok=True)
    export = model.export_state()
    documents = {
        "manifest.json": {"format_version": 1, "name": name, "status": "completed"},
        "config.json": export["config"],
        "seeds.json": {"seed_init": model.seed_init, "seed_sim": model.seed_sim},
        "state.json": export,
        "states/initial_state.json": model._history[0],
        "states/final_state.json": model._history_state(),
    }
    for filename, value in documents.items():
        _write_json(path / filename, value)
    _write_text(path / "runs" / "run_000" / "events.jsonl", "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in model.events))
    metrics = model.metrics()
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=["act", *metrics.keys()])
    writer.writeheader()
    writer.writerow({"act": model.act_number, **metrics})
    _write_text(path / "runs" / "run_000" / "metrics.csv", buffer.getvalue())
    return {"name": name, "path": str(path), "format_version": 1, "overwrite": overwrite}


def load_project(name: str) -> GammaIrradiationModel:
    path = _project_path(name)
    manifest = path / "manifest.json"
    state_file = path / "state.json"
    if not manifest.exists() or not state_file.exists():
        raise ValueError("Project does not exist")
    metadata = json.loads(manifest.read_text(encoding="utf-8"))
    if metadata.get("format_version") != 1:
        raise ValueError("Unsupported project format")
    return GammaIrradiationModel.from_export(json.loads(state_file.read_text(encoding="utf-8")))
