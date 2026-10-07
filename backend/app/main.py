from pathlib import Path

from backend.api.application import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[2]

app = create_app(
    projects_root=PROJECT_ROOT / "runtime" / "projects",
    max_parallel_simulations=4,
    frontend_root=PROJECT_ROOT / "dist",
)
