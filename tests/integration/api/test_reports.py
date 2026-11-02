import csv
import io
import json
import time
import pytest
from xml.etree import ElementTree
from zipfile import ZipFile

from fastapi.testclient import TestClient

from backend.api.application import create_app
from backend.data_research.report import METRICS, build_report


def archive_response(response):
    assert response.status_code == 200, response.text if response.status_code != 200 else ""
    assert response.headers["content-type"] == "application/zip"
    assert "attachment" in response.headers["content-disposition"]
    return ZipFile(io.BytesIO(response.content))


def test_trial_report_has_full_history_parameters_and_six_valid_charts(tmp_path):
    with TestClient(create_app(projects_root=tmp_path / "projects")) as client:
        created = client.post("/api/simulations", json={
            "dimensions": [3, 3], "seed_init": 9007199254740993,
            "seed_sim": 23, "q_max_ev": 0,
        }).json()
        path = f'/api/simulations/{created["simulation_id"]}'
        configured = client.patch(path + "/configuration", json={
            "expected_revision": 0,
            "external_direction_probabilities": {"toward_metal": 0.6, "along_surface": 0.25, "away_from_metal": 0.15},
        }).json()
        client.post(path + "/step", json={"expected_revision": configured["revision"]})
        journal = client.get(path + "/journal.json").json()
        before = client.get(path + "/snapshot").json()
        archive = archive_response(client.get(path + "/report.zip"))
        assert client.get(path + "/snapshot").json() == before
        assert client.get("/api/simulations/missing/report.zip").status_code == 404
    data = json.loads(archive.read("data.json"))
    run = data["runs"][0]
    assert run["metrics"] == journal["metrics"]
    assert run["configuration"] == journal["configuration"]
    assert run["configuration"]["seed_init"] == 9007199254740993
    assert run["configuration"]["external_direction_probabilities"]["toward_metal"] == 0.6
    rows = list(csv.DictReader(io.StringIO(archive.read("runs/001/metrics.csv").decode("utf-8-sig"))))
    assert len(rows) == len(journal["metrics"])
    assert float(rows[-1]["d"]) == before["metrics"]["d"]
    html = archive.read("report.html").decode()
    assert html.count("<svg ") == 6
    assert "Начальные параметры" in html
    assert "9007199254740993" in html
    for key in METRICS:
        svg = ElementTree.fromstring(archive.read(f"runs/001/{key}.svg"))
        assert svg.tag.endswith("svg")
    assert not list(tmp_path.rglob("*.zip"))


def test_series_report_keeps_run_seeds_settings_and_aggregates(tmp_path):
    with TestClient(create_app(projects_root=tmp_path / "projects")) as client:
        created = client.post("/api/experiments", json={
            "configurations": [{"dimensions": [2, 2], "q_max_ev": 0}],
            "repetitions": 2, "steps": 1, "master_seed": 123,
        }).json()
        path = f'/api/experiments/{created["experiment_id"]}'
        for _ in range(200):
            if client.get(path).json()["status"] not in {"PENDING", "RUNNING"}:
                break
            time.sleep(0.01)
        archive = archive_response(client.get(path + "/report.zip"))
        result = client.get(path + "/results").json()
        # The report uses captured results, even if a live simulation is removed.
        first = result["successful_runs"][0]
        client.delete(f'/api/simulations/{first["simulation_id"]}?expected_revision={first["snapshot"]["revision"]}')
        assert client.get(path + "/report.zip").status_code == 200
    data = json.loads(archive.read("data.json"))
    assert data["metadata"]["repetitions"] == 2
    assert data["metadata"]["steps"] == 1
    assert data["metadata"]["master_seed"] == 123
    assert data["configurations"][0]["dimensions"] == [2, 2]
    assert data["aggregate"] == result["aggregate"]
    assert len(data["runs"]) == 2
    for run in data["runs"]:
        assert run["configuration"]["seed_init"] == run["derived_seeds"]["seed_init"]
        assert run["configuration"]["seed_sim"] == run["derived_seeds"]["seed_sim"]
    assert len([name for name in archive.namelist() if name.endswith(".svg")]) == 18


def test_running_series_cannot_export_and_cancelled_series_can(tmp_path):
    with TestClient(create_app(projects_root=tmp_path / "projects")) as client:
        created = client.post("/api/experiments", json={
            "configurations": [{"dimensions": [3, 3], "q_max_ev": 0}],
            "steps": 10000, "master_seed": 7,
        }).json()
        path = f'/api/experiments/{created["experiment_id"]}'
        assert client.get(path + "/report.zip").status_code == 400
        client.post(path + "/cancel")
        archive = archive_response(client.get(path + "/report.zip"))
        assert json.loads(archive.read("data.json"))["metadata"]["status"] == "CANCELLED"
        assert "Серия отменена" in archive.read("report.html").decode()
        assert client.get("/api/experiments/missing/report.zip").status_code == 400


def test_report_escapes_failure_text_and_supports_empty_and_single_point_data():
    point = {"act_number": 0, "revision": 0, "origin": "initial", **dict.fromkeys(METRICS, 0)}
    report = build_report(title="<script>alert(1)</script>", metadata={"status": "COMPLETED_WITH_ERRORS"},
        runs=[{"configuration": {}, "metrics": [point]}, {"configuration": {}, "metrics": []}],
        failures=[{"message": "<img src=x onerror=alert(1)>"}])
    with ZipFile(io.BytesIO(report)) as archive:
        html = archive.read("report.html").decode()
        assert "<script>" not in html
        assert "<img src=x" not in html
        assert "&lt;img" in html
        assert "Нет данных" in html
        assert "<circle" in archive.read("runs/001/d.svg").decode()


def test_session_export_contains_exact_queue_and_names_without_changing_calculations(tmp_path):
    with TestClient(create_app(projects_root=tmp_path / "projects")) as client:
        ids = [client.post("/api/simulations", json={"dimensions": [2, 2], "q_max_ev": 0}).json()["simulation_id"] for _ in range(3)]
        name = 'Образец №1 <test> / одинаковое имя'
        for simulation_id in ids[:2]:
            path = f"/api/simulations/{simulation_id}"
            before = client.get(path + "/snapshot").json()
            renamed = client.patch(path + "/name", json={"name": "  " + name + "  "})
            assert renamed.status_code == 200
            assert renamed.json()["name"] == name
            assert client.get(path + "/snapshot").json() == before
            assert client.get(path + "/journal.json").json()["name"] == name
        archive = archive_response(client.post("/api/simulations/report.zip", json={"simulation_ids": ids[:2][::-1]}))
        data = json.loads(archive.read("data.json"))
        assert [run["simulation_id"] for run in data["runs"]] == ids[:2][::-1]
        assert [run["name"] for run in data["runs"]] == [name, name]
        assert ids[2] not in archive.read("data.json").decode()
        assert archive.read("report.html").decode().count("<svg ") == 12
        assert "Образец №1 &lt;test&gt;" in archive.read("report.html").decode()
        for folder in ("001", "002"):
            assert json.loads(archive.read(f"runs/{folder}/metadata.json"))["name"] == name
            svg = ElementTree.fromstring(archive.read(f"runs/{folder}/d.svg"))
            assert name in svg.find("{http://www.w3.org/2000/svg}title").text
        single = archive_response(client.get(f"/api/simulations/{ids[0]}/report.zip"))
        assert json.loads(single.read("data.json"))["runs"][0]["name"] == name
        # Saving/loading, stepping and resetting preserve metadata independently of physical history.
        assert client.post("/api/projects/named/save", json={"simulation_ids": ids[:2]}).status_code == 200
        loaded = client.post("/api/projects/named/load").json()["simulations"]
        assert [item["name"] for item in loaded] == [name, name]
        path = f'/api/simulations/{loaded[0]["simulation_id"]}'
        step = client.post(path + "/step", json={"expected_revision": loaded[0]["revision"]}).json()
        client.post(path + "/reset", json={"expected_revision": step["revision"]})
        assert client.get(path + "/journal.json").json()["name"] == name


@pytest.mark.parametrize("name", ["", "   ", "a" * 121, "line\nbreak", 123, None])
def test_invalid_names_are_rejected_without_mutating_session(tmp_path, name):
    with TestClient(create_app(projects_root=tmp_path / "projects")) as client:
        created = client.post("/api/simulations", json={"dimensions": [2, 2]}).json()
        path = f'/api/simulations/{created["simulation_id"]}'
        response = client.patch(path + "/name", json={"name": name})
        assert response.status_code == 422
        assert response.json()["code"] == "VALIDATION_ERROR"
        assert client.get(path + "/journal.json").json()["name"] == created["name"]


def test_session_export_rejects_empty_duplicate_or_missing_members(tmp_path):
    with TestClient(create_app(projects_root=tmp_path / "projects")) as client:
        created = client.post("/api/simulations", json={"dimensions": [2, 2]}).json()
        simulation_id = created["simulation_id"]
        for ids in ([], [simulation_id, simulation_id]):
            assert client.post("/api/simulations/report.zip", json={"simulation_ids": ids}).status_code == 422
        assert client.post("/api/simulations/report.zip", json={"simulation_ids": [simulation_id, "missing"]}).status_code == 404
        assert client.patch("/api/simulations/missing/name", json={"name": "Example"}).status_code == 404


def test_rename_running_simulation_broadcasts_name_and_keeps_running(tmp_path):
    with TestClient(create_app(projects_root=tmp_path / "projects")) as client:
        created = client.post("/api/simulations", json={"dimensions": [2, 2], "q_max_ev": 0}).json()
        simulation_id = created["simulation_id"]
        path = f"/api/simulations/{simulation_id}"
        client.post(path + "/run", json={"expected_revision": 0, "mode": "visual", "interval_ms": 5000})
        with client.websocket_connect(f"/ws/simulations/{simulation_id}") as socket:
            socket.receive_json()
            renamed = client.patch(path + "/name", json={"name": "Во время расчёта"}).json()
            assert renamed["status"] == "RUNNING"
            for _ in range(10):
                message = socket.receive_json()
                if message["type"] == "status" and message["summary"].get("name") == "Во время расчёта":
                    break
            else:
                pytest.fail("Rename was not broadcast")
