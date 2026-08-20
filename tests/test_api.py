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

    def test_probability_diagnostic_does_not_consume_model_revision(self):
        self.client.post("/api/model", json={"dimensions": [4, 4], "seed_init": 3})

        response = self.client.post("/api/model/probabilities", json={"atom_id": 0, "energy_ev": 0})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total_probability"], 1.0)
        self.assertEqual(response.json()["outcomes"][0]["event_type"], "no_change")
        self.assertEqual(self.client.get("/api/model/snapshot").json()["revision"], 0)
