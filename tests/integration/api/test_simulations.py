from fastapi.testclient import TestClient
import json
import time


def client(tmp_path):
    from backend.api.application import create_app

    return TestClient(
        create_app(projects_root=tmp_path / "projects", max_parallel_simulations=2)
    )


def create_simulation(test_client, **overrides):
    payload = {"dimensions": [4, 4], "seed_init": 2, "seed_sim": 3, "q_max_ev": 0}
    payload.update(overrides)
    response = test_client.post("/api/simulations", json=payload)
    assert response.status_code == 201
    return response.json()


def test_api_keeps_two_simulations_isolated(tmp_path):
    with client(tmp_path) as test_client:
        left = create_simulation(test_client, seed_sim=10)
        right = create_simulation(test_client, seed_sim=20)

        stepped = test_client.post(
            f"/api/simulations/{left['simulation_id']}/step",
            json={"expected_revision": 0},
        )
        untouched = test_client.get(
            f"/api/simulations/{right['simulation_id']}/snapshot"
        )

    assert stepped.status_code == 200
    assert stepped.json()["snapshot"]["revision"] == 1
    assert untouched.json()["revision"] == 0


def test_api_revision_conflict_is_structured_and_non_mutating(tmp_path):
    with client(tmp_path) as test_client:
        created = create_simulation(test_client)
        simulation_id = created["simulation_id"]
        conflict = test_client.post(
            f"/api/simulations/{simulation_id}/step",
            json={"expected_revision": 9},
        )
        snapshot = test_client.get(
            f"/api/simulations/{simulation_id}/snapshot"
        ).json()

    assert conflict.status_code == 409
    assert conflict.json()["code"] == "REVISION_CONFLICT"
    assert conflict.json()["schema_version"] == 1
    assert snapshot["revision"] == 0
    assert conflict.json()["revision"] == snapshot["revision"]


def test_api_invalid_configuration_returns_a_versioned_error(tmp_path):
    with client(tmp_path) as test_client:
        response = test_client.post(
            "/api/simulations", json={"dimensions": [1, 1], "q_max_ev": -1}
        )

    assert response.status_code == 422
    assert response.json()["schema_version"] == 1
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_api_lifecycle_run_pause_resume_stop(tmp_path):
    with client(tmp_path) as test_client:
        created = create_simulation(test_client)
        simulation_id = created["simulation_id"]
        statuses = []
        for command in ("run", "pause", "run", "stop"):
            for _ in range(20):
                revision = test_client.get(
                    f"/api/simulations/{simulation_id}/snapshot"
                ).json()["revision"]
                response = test_client.post(
                    f"/api/simulations/{simulation_id}/{command}",
                    json={"expected_revision": revision},
                )
                if response.status_code != 409:
                    break
            assert response.status_code == 200
            statuses.append(response.json()["status"])

    assert statuses == ["RUNNING", "PAUSED", "RUNNING", "STOPPED"]


def test_websocket_routes_only_events_of_the_subscribed_simulation(tmp_path):
    from backend.contracts.simulation import EventStreamMessage, SnapshotStreamMessage

    with client(tmp_path) as test_client:
        left = create_simulation(test_client)
        right = create_simulation(test_client)
        left_id = left["simulation_id"]
        right_id = right["simulation_id"]

        with test_client.websocket_connect(f"/ws/simulations/{left_id}") as websocket:
            initial = websocket.receive_json()
            test_client.post(
                f"/api/simulations/{right_id}/step",
                json={"expected_revision": 0},
            )
            test_client.post(
                f"/api/simulations/{left_id}/step",
                json={"expected_revision": 0},
            )
            event = websocket.receive_json()
            snapshot_message = websocket.receive_json()

        with test_client.websocket_connect(
            f"/ws/simulations/{left_id}"
        ) as reconnected:
            resynchronized = reconnected.receive_json()

    assert initial["snapshot"]["simulation_id"] == left_id
    assert initial["schema_version"] == 1
    assert initial["type"] == "snapshot"
    assert initial["simulation_id"] == left_id
    assert initial["revision"] == initial["snapshot"]["revision"]
    assert isinstance(initial["message_id"], int)
    assert SnapshotStreamMessage.model_validate(initial).snapshot.simulation_id == left_id
    assert event["simulation_id"] == left_id
    assert event["revision"] == 1
    assert event["type"] == "event"
    decoded_event = EventStreamMessage.model_validate(event)
    assert decoded_event.event.simulation_id == left_id
    assert snapshot_message["type"] == "snapshot"
    assert snapshot_message["revision"] == event["revision"]
    assert initial["message_id"] < event["message_id"] < snapshot_message["message_id"]
    assert resynchronized["type"] == "snapshot"
    assert resynchronized["snapshot"]["revision"] == 1
    assert resynchronized["revision"] == 1


def test_api_project_round_trip_restores_all_simulations(tmp_path):
    with client(tmp_path) as test_client:
        left = create_simulation(test_client, seed_sim=41)
        right = create_simulation(test_client, seed_sim=42)
        saved = test_client.post(
            "/api/projects/project-a/save",
            json={"simulation_ids": [left["simulation_id"], right["simulation_id"]]},
        )
        loaded = test_client.post("/api/projects/project-a/load")

    assert saved.status_code == 200
    assert loaded.status_code == 200
    assert len(loaded.json()["simulations"]) == 2
    assert {item["seed_sim"] for item in loaded.json()["simulations"]} == {41, 42}


def test_api_preparation_counts_errors_and_lock(tmp_path):
    with client(tmp_path) as test_client:
        created = create_simulation(test_client)
        simulation_id = created["simulation_id"]
        assert created["status"] == "PREPARATION"
        assert created["snapshot"]["counts"] == {
            "n0": 16, "n_atoms": 16, "n_v": 0, "n_i": 0, "n_as": 0
        }
        rejected = test_client.post(
            f"/api/simulations/{simulation_id}/edit",
            json={
                "expected_revision": 0,
                "action": "add",
                "destination_key": "lattice:0,0",
            },
        )
        assert rejected.status_code == 422
        assert rejected.json()["code"] == "DISCONNECTED_ATOM"
        configured = test_client.patch(
            f"/api/simulations/{simulation_id}/configuration",
            json={
                "expected_revision": 0,
                "initialization_mode": "explicit_defective",
                "n_v": 2,
                "n_i": 1,
                "n_as": 0,
            },
        )
        assert configured.status_code == 200
        assert configured.json()["snapshot"]["counts"]["n_atoms"] == 15
        started = test_client.post(
            f"/api/simulations/{simulation_id}/start",
            json={"expected_revision": 1},
        )
        assert started.json()["status"] == "PAUSED"
        locked = test_client.post(
            f"/api/simulations/{simulation_id}/edit",
            json={
                "expected_revision": started.json()["revision"],
                "action": "remove",
                "atom_id": 0,
            },
        )
        assert locked.status_code == 400
        assert locked.json()["code"] == "EDIT_NOT_ALLOWED"


def test_openapi_requires_revision_for_every_concurrent_mutation(tmp_path):
    with client(tmp_path) as test_client:
        schema = test_client.get("/openapi.json").json()
        created = create_simulation(test_client)
        missing_revision = test_client.post(
            f"/api/simulations/{created['simulation_id']}/start"
        )

    commands = {
        "start": "start",
        "run": "run",
        "pause": "pause",
        "stop": "stop",
        "undo": "undo",
        "redo": "redo",
        "retry": "error/retry",
        "acknowledge": "error/acknowledge",
        "reset": "reset",
    }
    for command, path_suffix in commands.items():
        operation = schema["paths"][f"/api/simulations/{{simulation_id}}/{path_suffix}"]["post"]
        assert operation["requestBody"]["required"] is True
        body = operation["requestBody"]["content"]["application/json"]["schema"]
        assert body["$ref"].endswith("/RevisionRequest")
    serialized = json.dumps(schema)
    for removed in ("forced_energy", "total_dose", "defect_concentration", "moved_atoms"):
        assert removed not in serialized
    delete_operation = schema["paths"]["/api/simulations/{simulation_id}"]["delete"]
    expected_revision = next(
        item for item in delete_operation["parameters"] if item["name"] == "expected_revision"
    )
    assert expected_revision["required"] is True
    assert missing_revision.status_code == 422
    assert missing_revision.json()["code"] == "VALIDATION_ERROR"


def test_openapi_references_the_shared_response_dtos(tmp_path):
    with client(tmp_path) as test_client:
        schema = test_client.get("/openapi.json").json()

    expected = {
        ("/api/simulations/{simulation_id}/snapshot", "get"): "SimulationSnapshot",
        ("/api/simulations/{simulation_id}/step", "post"): "StepResponse",
        ("/api/simulations/{simulation_id}/events", "get"): "EventPage",
        ("/api/simulations/{simulation_id}/metrics", "get"): "MetricsSeries",
        ("/api/simulations/{simulation_id}/diagnostics/probabilities", "post"): "ProbabilityOverlay",
        ("/api/simulations/{simulation_id}/slices", "get"): "SliceAtlas",
        ("/api/simulations/{simulation_id}/configuration", "patch"): "StepResponse",
        ("/api/simulations/{simulation_id}/edit", "post"): "StepResponse",
        ("/api/simulations/{simulation_id}/edit/preview", "post"): "PreparationEditPreview",
        ("/api/simulations/{simulation_id}/start", "post"): "SimulationSummary",
        ("/api/simulations/{simulation_id}/run", "post"): "SimulationSummary",
        ("/api/simulations/{simulation_id}/pause", "post"): "SimulationSummary",
        ("/api/simulations/{simulation_id}/stop", "post"): "SimulationSummary",
        ("/api/simulations/{simulation_id}/error/acknowledge", "post"): "SimulationSummary",
        ("/api/simulations/{simulation_id}/undo", "post"): "SimulationSnapshot",
        ("/api/simulations/{simulation_id}/redo", "post"): "SimulationSnapshot",
        ("/api/simulations/{simulation_id}/reset", "post"): "SimulationSnapshot",
        ("/api/simulations/{simulation_id}/error/retry", "post"): "StepResponse",
    }
    for (path, method), model in expected.items():
        response = schema["paths"][path][method]["responses"]["200"]
        response_schema = response["content"]["application/json"]["schema"]
        assert response_schema["$ref"].endswith(f"/{model}")


def test_openapi_types_the_complete_p5_http_surface(tmp_path):
    with client(tmp_path) as test_client:
        schema = test_client.get("/openapi.json").json()

    expected = {
        ("/api/simulations", "post", "201"): "SimulationCreatedResponse",
        ("/api/simulations/{simulation_id}/journal.json", "get", "200"): "JournalExport",
        ("/api/simulations/{simulation_id}/atoms/{atom_id}/destinations", "get", "200"): "DestinationsResponse",
        ("/api/projects/{project_id}/save", "post", "200"): "ProjectStatus",
        ("/api/projects/{project_id}/load", "post", "200"): "ProjectLoadResponse",
        ("/api/projects/{project_id}", "delete", "200"): "ProjectStatus",
        ("/api/experiments", "post", "202"): "ExperimentStatus",
        ("/api/experiments/{experiment_id}", "get", "200"): "ExperimentStatus",
        ("/api/experiments/{experiment_id}/cancel", "post", "200"): "ExperimentStatus",
        ("/api/experiments/{experiment_id}/results", "get", "200"): "ExperimentResults",
    }
    for (path, method, status_code), model in expected.items():
        response_schema = schema["paths"][path][method]["responses"][status_code][
            "content"
        ]["application/json"]["schema"]
        assert response_schema["$ref"].endswith(f"/{model}")

    project_list = schema["paths"]["/api/projects"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    simulation_list = schema["paths"]["/api/simulations"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    assert project_list["items"]["$ref"].endswith("/ProjectStatus")
    assert simulation_list["items"]["$ref"].endswith("/SimulationSummary")
    assert "/api/simulations/batch" not in schema["paths"]
    assert "/api/projects/{project_id}/export" not in schema["paths"]


def test_openapi_versions_every_public_json_request(tmp_path):
    with client(tmp_path) as test_client:
        schema = test_client.get("/openapi.json").json()

    request_models = set()
    for path in schema["paths"].values():
        for operation in path.values():
            request_body = operation.get("requestBody")
            if request_body is None:
                continue
            body_schema = request_body["content"]["application/json"]["schema"]
            request_models.add(body_schema["$ref"].rsplit("/", 1)[-1])

    assert request_models
    for model_name in request_models:
        model_schema = schema["components"]["schemas"][model_name]
        assert model_schema["properties"]["schema_version"]["const"] == 1


def test_api_uses_typed_config_patch_and_one_preparation_edit_route(tmp_path):
    with client(tmp_path) as test_client:
        created = create_simulation(test_client)
        simulation_id = created["simulation_id"]
        configured = test_client.patch(
            f"/api/simulations/{simulation_id}/configuration",
            json={
                "expected_revision": 0,
                "initialization_mode": "explicit_defective",
                "n_v": 2,
                "n_i": 1,
                "n_as": 0,
            },
        )
        edited = test_client.post(
            f"/api/simulations/{simulation_id}/edit",
            json={"expected_revision": 1, "action": "remove", "atom_id": 0},
        )
        paths = test_client.get("/openapi.json").json()["paths"]

    assert configured.status_code == 200
    assert configured.json()["snapshot"]["counts"]["n_atoms"] == 15
    assert edited.status_code == 200
    assert edited.json()["snapshot"]["revision"] == 2
    for old_path in ("move", "add-atom", "remove-atom", "configure-initialization", "edit-boundary"):
        assert f"/api/simulations/{{simulation_id}}/{old_path}" not in paths


def test_manual_edit_preview_returns_server_metrics_without_mutating_the_simulation(tmp_path):
    with client(tmp_path) as test_client:
        created = create_simulation(test_client)
        simulation_id = created["simulation_id"]
        before = test_client.get(
            f"/api/simulations/{simulation_id}/snapshot"
        ).json()
        destinations = test_client.get(
            f"/api/simulations/{simulation_id}/atoms/0/destinations"
        ).json()["destinations"]
        destination = next(item for item in destinations if item["selectable"])

        preview = test_client.post(
            f"/api/simulations/{simulation_id}/edit/preview",
            json={
                "expected_revision": before["revision"],
                "action": "move",
                "atom_id": 0,
                "destination_key": destination["key"],
            },
        )
        after = test_client.get(
            f"/api/simulations/{simulation_id}/snapshot"
        ).json()

    assert preview.status_code == 200
    assert preview.json()["simulation_id"] == simulation_id
    assert preview.json()["revision"] == before["revision"]
    assert preview.json()["action"] == "move"
    assert preview.json()["metrics_before"] == before["metrics"]
    assert preview.json()["counts_before"] == before["counts"]
    assert preview.json()["counts_after"]["n_atoms"] == before["counts"]["n_atoms"]
    assert after == before


def test_api_exposes_event_metrics_diagnosis_slices_and_journal_views(tmp_path):
    with client(tmp_path) as test_client:
        created = create_simulation(test_client)
        simulation_id = created["simulation_id"]
        stepped = test_client.post(
            f"/api/simulations/{simulation_id}/step",
            json={"expected_revision": 0},
        )
        events = test_client.get(
            f"/api/simulations/{simulation_id}/events", params={"offset": 0, "limit": 1}
        )
        metrics = test_client.get(f"/api/simulations/{simulation_id}/metrics")
        diagnosis = test_client.post(
            f"/api/simulations/{simulation_id}/diagnostics/probabilities",
            json={"atom_id": 0, "q_test": 30.0},
        )
        journal = test_client.get(
            f"/api/simulations/{simulation_id}/journal.json"
        )
        three_d = create_simulation(test_client, dimensions=[2, 2, 2])
        slices = test_client.get(
            f"/api/simulations/{three_d['simulation_id']}/slices"
        )
        unsupported_slices = test_client.get(
            f"/api/simulations/{three_d['simulation_id']}/slices",
            params={"axis": "x"},
        )

    assert stepped.status_code == 200
    assert events.status_code == 200
    assert events.json()["total"] == 1
    assert len(events.json()["events"]) == 1
    assert metrics.json()["points"][-1]["revision"] == 1
    assert diagnosis.status_code == 200
    assert diagnosis.json()["revision"] == 1
    assert any(not item["selectable"] for item in diagnosis.json()["outcomes"])
    assert journal.headers["content-disposition"].endswith('"journal.json"')
    assert journal.json()["events"] == events.json()["events"]
    journal_payload = journal.json()
    assert journal_payload["configuration"]["seed_sim"] == 3
    assert journal_payload["metrics"] == metrics.json()["points"]
    assert journal_payload["final_snapshot"]["revision"] == 1
    assert journal_payload["formulas"]["d"] == "D = N_V + N_I + N_As"
    serialized_journal = json.dumps(journal_payload)
    assert "random_state" not in serialized_journal
    assert "checkpoints" not in serialized_journal
    assert '"path"' not in serialized_journal
    assert slices.status_code == 200
    assert slices.json()["axis"] == "z"
    assert slices.json()["slices"]
    assert unsupported_slices.status_code == 422


def test_slice_atlas_returns_only_nonempty_layers_at_their_real_z_coordinates(
    tmp_path,
):
    with client(tmp_path) as test_client:
        created = create_simulation(test_client, dimensions=[2, 2, 2])
        response = test_client.get(
            f"/api/simulations/{created['simulation_id']}/slices"
        )

    assert response.status_code == 200
    assert [layer["coordinate"] for layer in response.json()["slices"]] == [
        2.0,
        2.5,
        3.0,
    ]


def test_slice_atlas_keeps_an_atom_only_external_layer(tmp_path):
    with client(tmp_path) as test_client:
        created = create_simulation(test_client, dimensions=[2, 2, 2])
        added = test_client.post(
            f"/api/simulations/{created['simulation_id']}/edit",
            json={
                "expected_revision": 0,
                "action": "add",
                "destination_key": "lattice:2,2,1",
            },
        )
        response = test_client.get(
            f"/api/simulations/{created['simulation_id']}/slices"
        )

    assert added.status_code == 200
    assert [layer["coordinate"] for layer in response.json()["slices"]] == [
        1.0,
        2.0,
        2.5,
        3.0,
    ]


def test_event_and_metrics_views_apply_public_filters(tmp_path):
    with client(tmp_path) as test_client:
        created = create_simulation(test_client)
        simulation_id = created["simulation_id"]
        stepped = test_client.post(
            f"/api/simulations/{simulation_id}/step",
            json={"expected_revision": 0},
        ).json()
        destinations = test_client.get(
            f"/api/simulations/{simulation_id}/atoms/0/destinations"
        ).json()["destinations"]
        destination = next(item for item in destinations if item["selectable"])
        edited = test_client.post(
            f"/api/simulations/{simulation_id}/edit",
            json={
                "expected_revision": stepped["revision"],
                "action": "move",
                "atom_id": 0,
                "destination_key": destination["key"],
            },
        )
        manual_events = test_client.get(
            f"/api/simulations/{simulation_id}/events",
            params={"origin": "manual_edit", "offset": 0, "limit": 100},
        )
        no_change_events = test_client.get(
            f"/api/simulations/{simulation_id}/events",
            params={"operation": "no_change", "act_from": 1, "act_to": 1},
        )
        metrics = test_client.get(
            f"/api/simulations/{simulation_id}/metrics",
            params={"act_from": 1, "act_to": 1},
        )

    assert edited.status_code == 200
    assert manual_events.json()["total"] == 1
    assert {item["origin"] for item in manual_events.json()["events"]} == {"manual_edit"}
    assert no_change_events.json()["total"] == 1
    assert {item["operation"] for item in no_change_events.json()["events"]} == {"no_change"}
    assert metrics.json()["points"]
    assert {item["act_number"] for item in metrics.json()["points"]} == {1}


def test_http_error_mapping_distinguishes_missing_command_and_internal(tmp_path):
    from backend.api.application import create_app

    with client(tmp_path) as test_client:
        missing = test_client.get("/api/simulations/missing/snapshot")
        created = create_simulation(test_client)
        simulation_id = created["simulation_id"]
        started = test_client.post(
            f"/api/simulations/{simulation_id}/start",
            json={"expected_revision": 0},
        )
        invalid = test_client.post(
            f"/api/simulations/{simulation_id}/start",
            json={"expected_revision": started.json()["revision"]},
        )

    app = create_app(projects_root=tmp_path / "internal-error")

    async def explode(_simulation_id):
        raise RuntimeError("private implementation detail")

    app.state.manager.get_snapshot = explode
    with TestClient(app, raise_server_exceptions=False) as unsafe_client:
        internal = unsafe_client.get("/api/simulations/anything/snapshot")

    assert missing.status_code == 404
    assert missing.json()["code"] == "SIMULATION_NOT_FOUND"
    assert invalid.status_code == 400
    assert invalid.json()["code"] == "INVALID_SIMULATION_COMMAND"
    assert internal.status_code == 500
    assert internal.json()["code"] == "INTERNAL_ERROR"
    assert "private implementation detail" not in json.dumps(internal.json())


def test_project_api_lists_and_requires_explicit_delete_confirmation(tmp_path):
    with client(tmp_path) as test_client:
        created = create_simulation(test_client)
        saved = test_client.post(
            "/api/projects/project-a/save",
            json={"simulation_ids": [created["simulation_id"]], "overwrite": False},
        )
        listed = test_client.get("/api/projects")
        refused = test_client.delete("/api/projects/project-a")
        deleted = test_client.delete(
            "/api/projects/project-a", params={"confirm": True}
        )
        missing = test_client.post("/api/projects/project-a/load")

    assert saved.status_code == 200
    saved_payload = saved.json()
    listed_payload = listed.json()[0]
    assert saved_payload["project_id"] == "project-a"
    assert saved_payload["status"] == "SAVED"
    assert saved_payload["simulation_count"] == 1
    assert saved_payload["created_at"]
    assert saved_payload["updated_at"]
    assert saved_payload["history_truncated"] is False
    assert listed_payload == {**saved_payload, "status": "AVAILABLE"}
    assert refused.status_code == 400
    assert refused.json()["code"] == "CONFIRMATION_REQUIRED"
    assert deleted.json()["status"] == "DELETED"
    assert missing.status_code == 404


def test_experiment_api_exposes_create_status_cancel_and_results(tmp_path):
    with client(tmp_path) as test_client:
        created = test_client.post(
            "/api/experiments",
            json={
                "configurations": [{"dimensions": [2, 2], "q_max_ev": 0}],
                "steps": 0,
                "master_seed": 7,
            },
        )
        experiment_id = created.json()["experiment_id"]
        status_response = None
        for _ in range(20):
            status_response = test_client.get(f"/api/experiments/{experiment_id}")
            if status_response.json()["status"] not in {"PENDING", "RUNNING"}:
                break
            time.sleep(0.01)
        results = test_client.get(f"/api/experiments/{experiment_id}/results")

        cancellable = test_client.post(
            "/api/experiments",
            json={
                "configurations": [{"dimensions": [3, 3], "q_max_ev": 0}],
                "steps": 10_000,
                "master_seed": 8,
            },
        )
        cancelled = test_client.post(
            f"/api/experiments/{cancellable.json()['experiment_id']}/cancel"
        )

    assert created.status_code == 202
    assert status_response.json()["status"] == "COMPLETED"
    assert results.status_code == 200
    assert results.json()["experiment_id"] == experiment_id
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
