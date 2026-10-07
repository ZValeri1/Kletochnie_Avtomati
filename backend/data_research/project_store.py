from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from backend.contracts.projects import ProjectMetadata
from backend.data_research.errors import (
    ProjectConflictError,
    ProjectDataError,
    ProjectNotFoundError,
    StorageUnavailableError,
    UnsupportedProjectSchemaError,
)
from backend.data_research.serialization import ProjectSerializer


PROJECT_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class ProjectStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, project_export: dict, overwrite: bool = False) -> ProjectMetadata:
        project_export = ProjectSerializer.validate(project_export)
        project_id = project_export.get("project_id")
        target = self._path(project_id)
        if target.exists() and not overwrite:
            raise ProjectConflictError(f"Project {project_id} already exists")
        now = datetime.now(timezone.utc).isoformat()
        created_at = now
        if target.exists():
            try:
                existing_manifest = json.loads(
                    (target / "manifest.json").read_text(encoding="utf-8")
                )
                created_at = existing_manifest.get("created_at", now)
            except (OSError, json.JSONDecodeError):
                created_at = now

        temporary = self.root / f".{project_id}.{uuid.uuid4().hex}.tmp"
        backup = self.root / f".{project_id}.{uuid.uuid4().hex}.backup"
        try:
            temporary.mkdir(parents=True)
        except OSError as error:
            raise StorageUnavailableError("Project storage is unavailable") from error
        try:
            self._write_project(
                temporary,
                project_export,
                created_at=created_at,
                updated_at=now,
            )
            if target.exists():
                os.replace(target, backup)
            try:
                os.replace(temporary, target)
            except Exception:
                if backup.exists() and not target.exists():
                    os.replace(backup, target)
                raise
            if backup.exists():
                shutil.rmtree(backup)
        except OSError as error:
            raise StorageUnavailableError("Project storage is unavailable") from error
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
        return self._metadata(project_export, created_at=created_at, updated_at=now)

    def load(self, project_id: str) -> dict:
        path = self._path(project_id)
        manifest_file = path / "manifest.json"
        project_file = path / "project.json"
        if not manifest_file.is_file() or not project_file.is_file():
            raise ProjectNotFoundError(f"Project {project_id} does not exist")
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            if manifest.get("schema_version") != 1:
                raise UnsupportedProjectSchemaError("Unsupported project schema version")
            if (
                not isinstance(manifest.get("created_at"), str)
                or not isinstance(manifest.get("updated_at"), str)
                or not isinstance(manifest.get("history_truncated"), bool)
            ):
                raise ProjectDataError("Project manifest metadata is invalid")
            payload = json.loads(project_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ProjectDataError("Project data is corrupted") from error
        except OSError as error:
            raise StorageUnavailableError("Project storage is unavailable") from error
        if (
            manifest.get("project_id") != project_id
            or payload.get("project_id") != project_id
            or manifest.get("simulation_count") != len(payload.get("simulations", []))
        ):
            raise ProjectDataError("Project manifest does not match project data")
        return ProjectSerializer.validate(payload)

    def list(self) -> list[ProjectMetadata]:
        result = []
        for path in sorted(self.root.iterdir()):
            if path.is_dir() and not path.name.startswith("."):
                try:
                    payload = self.load(path.name)
                except ProjectDataError:
                    continue
                try:
                    manifest = json.loads(
                        (path / "manifest.json").read_text(encoding="utf-8")
                    )
                    created_at = manifest["created_at"]
                    updated_at = manifest["updated_at"]
                except (OSError, json.JSONDecodeError, KeyError):
                    continue
                result.append(
                    self._metadata(
                        payload,
                        created_at=created_at,
                        updated_at=updated_at,
                    )
                )
        return result

    def delete(self, project_id: str) -> None:
        target = self._path(project_id)
        if not target.is_dir():
            raise ProjectNotFoundError(f"Project {project_id} does not exist")
        try:
            shutil.rmtree(target)
        except OSError as error:
            raise StorageUnavailableError("Project storage is unavailable") from error

    def _path(self, project_id: str) -> Path:
        if not isinstance(project_id, str) or not PROJECT_PATTERN.fullmatch(project_id):
            raise ProjectDataError("Invalid project id")
        return self.root / project_id

    @staticmethod
    def _metadata(payload: dict, *, created_at: str, updated_at: str) -> ProjectMetadata:
        return ProjectMetadata(
            project_id=payload["project_id"],
            created_at=created_at,
            updated_at=updated_at,
            simulation_count=len(payload.get("simulations", [])),
            history_truncated=any(
                item.get("history", {}).get("history_truncated", False)
                for item in payload.get("simulations", [])
            ),
        )

    @staticmethod
    def _write_project(
        path: Path, payload: dict, *, created_at: str, updated_at: str
    ) -> None:
        manifest = {
            "schema_version": 1,
            "project_id": payload["project_id"],
            "simulation_count": len(payload.get("simulations", [])),
            "created_at": created_at,
            "updated_at": updated_at,
            "history_truncated": any(
                item.get("history", {}).get("history_truncated", False)
                for item in payload.get("simulations", [])
            ),
        }
        (path / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (path / "project.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
