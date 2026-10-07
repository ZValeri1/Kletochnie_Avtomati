# Test suites

Tests are grouped by purpose first and by architecture block second:

- `unit/atomic_model` — domain topology, state, events, executor, and metrics.
- `unit/simulation_management` — sessions, history, scheduler, snapshots, and event delivery.
- `unit/frontend` — TypeScript DTO, mapper, store, and renderer-isolation checks.
- `property` — generated domain invariant sequences.
- `integration/api` — HTTP and WebSocket application flows.
- `integration/data_research` — project storage, experiments, statistics, and export.
- `contract` — shared versioned JSON DTO fixtures and Python contract checks.
- `e2e` — short browser smoke scenarios.
- `long` — stability and large experiment runs; never part of the default suite.

## Setup

Run these commands from the project root in an activated Python virtual environment:

```powershell
python -m pip install -r requirements.txt
pnpm install --frozen-lockfile
pnpm exec playwright install chromium
```

The Python test dependencies are pinned in `requirements.txt`. The root
`package.json` owns the frontend and Playwright commands.

## Fast checks

```powershell
python -m pytest --collect-only
python -m pytest
pnpm test:discovery
pnpm test:unit
pnpm build
```

`test:discovery` must list both the frontend unit and E2E suites. The backend
import smoke test also checks that the application imports from the project
root without a legacy `PYTHONPATH`.

## Browser and extended checks

After `pnpm build`, start the API with `python -m uvicorn backend.app.main:app
--host 127.0.0.1 --port 8000` in another terminal. Then run:

```powershell
pnpm test:e2e
python -m pytest tests/long
```

The long suite is deliberately excluded from default pytest discovery.
