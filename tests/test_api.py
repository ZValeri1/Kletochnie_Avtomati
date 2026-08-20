import unittest

from fastapi.testclient import TestClient

from backend.app.main import app


class ApiContractTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_model_lifecycle_exposes_snapshot_and_step(self):
        created = self.client.post(
            "/api/model", json={"dimensions": [4, 4], "seed_init": 3, "seed_sim": 4}
        )

        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["metrics"]["defects"], 0)

        stepped = self.client.post("/api/model/step", json={"forced_energy": 0.0})

        self.assertEqual(stepped.status_code, 200)
        self.assertEqual(stepped.json()["event_type"], "no_change")
        self.assertEqual(stepped.json()["revision"], 1)

        snapshot = self.client.get("/api/model/snapshot")
        self.assertEqual(snapshot.status_code, 200)
        self.assertEqual(snapshot.json()["revision"], 1)

    def test_model_accepts_energy_configuration(self):
        created = self.client.post(
            "/api/model", json={"dimensions": [4, 4], "q_max_ev": 120, "frenkel_threshold_ev": 75}
        )

        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["config"]["q_max_ev"], 120)

    def test_probability_diagnostic_does_not_consume_model_revision(self):
        self.client.post("/api/model", json={"dimensions": [4, 4], "seed_init": 3})

        response = self.client.post("/api/model/probabilities", json={"atom_id": 0, "energy_ev": 0})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total_probability"], 1.0)
        self.assertEqual(response.json()["outcomes"][0]["event_type"], "no_change")
        self.assertEqual(self.client.get("/api/model/snapshot").json()["revision"], 0)

    def test_api_exposes_probability_outcomes_and_manual_destinations(self):
        created = self.client.post(
            "/api/model", json={"dimensions": [5, 5], "moved_atoms": 1, "seed_init": 2}
        ).json()
        atom_id = next(atom["id"] for atom in created["atoms"] if atom["state"] == "interstitial")

        probabilities = self.client.post(
            "/api/model/probabilities", json={"atom_id": atom_id, "energy_ev": 20}
        )
        destinations = self.client.get(f"/api/model/atoms/{atom_id}/destinations")

        self.assertEqual(probabilities.status_code, 200)
        self.assertAlmostEqual(probabilities.json()["total_probability"], 1.0, places=12)
        self.assertEqual(destinations.status_code, 200)
        self.assertTrue(destinations.json()["destinations"])

    def test_websocket_starts_with_authoritative_snapshot(self):
        self.client.post("/api/model", json={"dimensions": [4, 4]})

        with self.client.websocket_connect("/ws/model") as websocket:
            message = websocket.receive_json()

        self.assertEqual(message["type"], "snapshot")
        self.assertEqual(message["snapshot"]["revision"], 0)

    def test_websocket_streams_event_delta_with_revision(self):
        self.client.post("/api/model", json={"dimensions": [4, 4], "seed_sim": 2})

        with self.client.websocket_connect("/ws/model") as websocket:
            websocket.receive_json()
            stepped = self.client.post("/api/model/step", json={"forced_energy": 0})
            message = websocket.receive_json()

        self.assertEqual(stepped.status_code, 200)
        self.assertEqual(message["type"], "event")
        self.assertEqual(message["event"]["revision"], 1)
        self.assertIn("deltas", message["event"])

    def test_history_endpoints_restore_and_reapply_model_state(self):
        self.client.post("/api/model", json={"dimensions": [5, 5], "seed_sim": 6})
        self.client.post("/api/model/step", json={"forced_energy": 55})

        undone = self.client.post("/api/model/undo")
        redone = self.client.post("/api/model/redo")

        self.assertEqual(undone.status_code, 200)
        self.assertTrue(undone.json()["can_redo"])
        self.assertEqual(redone.status_code, 200)
        self.assertFalse(redone.json()["can_redo"])

    def test_project_round_trip_and_experiment_are_reproducible(self):
        self.client.post("/api/model", json={"dimensions": [5, 4], "moved_atoms": 2, "seed_init": 8, "seed_sim": 9})
        self.client.post("/api/model/step", json={"forced_energy": 55})

        saved = self.client.post("/api/project/save", json={"name": "api_round_trip", "overwrite": True})
        self.client.post("/api/model", json={"dimensions": [3, 3]})
        loaded = self.client.post("/api/project/load", json={"name": "api_round_trip"})
        experiment = self.client.post("/api/experiment", json={"runs": 3, "steps": 4, "master_seed": 12})

        self.assertEqual(saved.status_code, 200)
        self.assertEqual(loaded.status_code, 200)
        self.assertEqual(loaded.json()["dimensions"], [5, 4])
        self.assertEqual(experiment.status_code, 200)
        self.assertEqual(len(experiment.json()["trajectory"]), 5)
        self.assertEqual(len(experiment.json()["trajectory"][0]["entropy_ci95"]), 2)
        self.assertIn("surface_defects_mean", experiment.json()["trajectory"][0])

    def test_project_requires_explicit_overwrite(self):
        self.client.post("/api/model", json={"dimensions": [4, 4]})
        self.client.post("/api/project/save", json={"name": "overwrite_contract", "overwrite": True})

        rejected = self.client.post("/api/project/save", json={"name": "overwrite_contract"})

        self.assertEqual(rejected.status_code, 422)
