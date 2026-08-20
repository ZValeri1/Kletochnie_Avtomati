"""Portable JSON project storage with atomic replacement."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from backend.app.core.model import GammaIrradiationModel

PROJECTS_ROOT = Path(__file__).resolve().parents[3] / "projects"
NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _project_path(name: str) -> Path:
    if not NAME_PATTERN.fullmatch(name):
        raise ValueError("Project name must contain only letters, digits, hyphens, or underscores")
    return PROJECTS_ROOT / name


def save_project(name: str, model: GammaIrradiationModel) -> dict:
    path = _project_path(name)
    path.mkdir(parents=True, exist_ok=True)
    export = model.export_state()
    documents = {
        "manifest.json": {"format_version": 1, "name": name},
        "config.json": export["config"],
        "state.json": export,
    }
    for filename, value in documents.items():
        target = path / filename
        temporary = target.with_suffix(f"{target.suffix}.tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, target)
    return {"name": name, "path": str(path), "format_version": 1}


def load_project(name: str) -> GammaIrradiationModel:
    path = _project_path(name)
    state_file = path / "state.json"
    if not state_file.exists():
        raise ValueError("Project does not exist")
    return GammaIrradiationModel.from_export(json.loads(state_file.read_text(encoding="utf-8")))
