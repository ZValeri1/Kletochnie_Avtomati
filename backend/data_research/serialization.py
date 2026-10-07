from __future__ import annotations

from copy import deepcopy
from math import isfinite

from backend.data_research.errors import ProjectDataError, UnsupportedProjectSchemaError


class ProjectSerializer:
    schema_version = 1

    @classmethod
    def validate(cls, payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise ProjectDataError("Project payload must be an object")
        if payload.get("schema_version") != cls.schema_version:
            raise UnsupportedProjectSchemaError("Unsupported project schema version")
        if not payload.get("project_id"):
            raise ProjectDataError("project_id is required")
        if not isinstance(payload.get("application_version"), str):
            raise ProjectDataError("application_version is required")
        if not isinstance(payload.get("simulations"), list):
            raise ProjectDataError("simulations must be a list")
        seen_ids: set[str] = set()
        for simulation in payload["simulations"]:
            if not isinstance(simulation, dict):
                raise ProjectDataError("Each simulation must be an object")
            if not simulation.get("simulation_id") or "revision" not in simulation:
                raise ProjectDataError("Simulation id and revision are required")
            simulation_id = simulation["simulation_id"]
            if simulation_id in seen_ids:
                raise ProjectDataError("Simulation ids must be unique within a project")
            seen_ids.add(simulation_id)
            cls._validate_simulation(simulation)
        return deepcopy(payload)

    @classmethod
    def _validate_simulation(cls, simulation: dict) -> None:
        required = {
            "configuration",
            "state",
            "random_state",
            "history",
            "events",
            "metrics",
            "last_valid_snapshot",
        }
        missing = required.difference(simulation)
        if missing:
            raise ProjectDataError(
                f"Simulation is missing required fields: {', '.join(sorted(missing))}"
            )
        if not isinstance(simulation["revision"], int) or simulation["revision"] < 0:
            raise ProjectDataError("Simulation revision must be a non-negative integer")
        if not isinstance(simulation["configuration"], dict):
            raise ProjectDataError("Simulation configuration must be an object")
        dimensions = simulation["configuration"].get("dimensions")
        if (
            not isinstance(dimensions, (list, tuple))
            or len(dimensions) not in (2, 3)
            or any(not isinstance(item, int) or item < 2 for item in dimensions)
        ):
            raise ProjectDataError("Simulation dimensions are invalid")
        cls._validate_state(simulation["state"])
        history = simulation["history"]
        if not isinstance(history, dict):
            raise ProjectDataError("Simulation history must be an object")
        checkpoints = history.get("checkpoints")
        limit = history.get("limit")
        cursor = history.get("cursor")
        if (
            not isinstance(checkpoints, list)
            or not checkpoints
            or not isinstance(limit, int)
            or limit < 1
            or len(checkpoints) > limit + 1
            or not isinstance(cursor, int)
            or not 0 <= cursor < len(checkpoints)
        ):
            raise ProjectDataError("Simulation history is invalid")
        for checkpoint in checkpoints:
            if not isinstance(checkpoint, dict) or "random_state" not in checkpoint:
                raise ProjectDataError("History checkpoint is invalid")
            cls._validate_state(checkpoint.get("state"))
        if not isinstance(simulation["events"], list):
            raise ProjectDataError("Simulation events must be a list")
        if not isinstance(simulation["metrics"], list):
            raise ProjectDataError("Simulation metrics must be a list")
        if not isinstance(simulation["last_valid_snapshot"], dict):
            raise ProjectDataError("last_valid_snapshot must be an object")
        for point in simulation["metrics"]:
            if not isinstance(point, dict):
                raise ProjectDataError("Metric point must be an object")
            for name in ("d", "s"):
                value = point.get(name)
                if not isinstance(value, (int, float)) or not isfinite(float(value)):
                    raise ProjectDataError("Metric values must be finite numbers")
        if simulation["events"] != simulation["state"].get("events", []):
            raise ProjectDataError("Journal does not match the current state")
        if simulation["metrics"] != simulation["state"].get("metrics_points", []):
            raise ProjectDataError("Metrics do not match the current state")

    @staticmethod
    def _validate_state(state) -> None:
        if not isinstance(state, dict):
            raise ProjectDataError("Simulation state must be an object")
        atoms = state.get("atoms")
        occupied = state.get("occupied")
        if not isinstance(atoms, dict) or not isinstance(occupied, dict):
            raise ProjectDataError("State atoms and occupancy must be objects")
        if len(set(atoms.values())) != len(atoms):
            raise ProjectDataError("State contains duplicate occupied sites")
        expected = {str(site): int(atom_id) for atom_id, site in atoms.items()}
        try:
            decoded_occupied = {
                str(site): int(atom_id) for site, atom_id in occupied.items()
            }
        except (TypeError, ValueError) as error:
            raise ProjectDataError("State occupancy is invalid") from error
        if decoded_occupied != expected:
            raise ProjectDataError("State occupancy does not match atoms")
