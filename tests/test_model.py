import unittest

from backend.app.core.model import GammaIrradiationModel


class ModelContractTests(unittest.TestCase):
    def test_ideal_2d_lattice_has_zero_defects_and_entropy(self):
        model = GammaIrradiationModel(dimensions=(4, 3), seed_init=7, seed_sim=11)

        snapshot = model.snapshot()

        self.assertEqual(snapshot["metrics"]["vacancies"], 0)
        self.assertEqual(snapshot["metrics"]["interstitials"], 0)
        self.assertEqual(snapshot["metrics"]["surface_defects"], 0)
        self.assertEqual(snapshot["metrics"]["defects"], 0)
        self.assertEqual(snapshot["metrics"]["entropy"], 0.0)
        self.assertEqual(len(snapshot["atoms"]), 12)

    def test_exact_initialization_is_reproducible_and_preserves_atoms(self):
        left = GammaIrradiationModel(dimensions=(5, 5), moved_atoms=3, seed_init=42)
        right = GammaIrradiationModel(dimensions=(5, 5), moved_atoms=3, seed_init=42)

        self.assertEqual(left.snapshot()["atoms"], right.snapshot()["atoms"])
        self.assertEqual(left.snapshot()["metrics"]["vacancies"], 3)
        self.assertEqual(left.snapshot()["metrics"]["interstitials"], 3)
        self.assertEqual(len(left.snapshot()["atoms"]), 25)

    def test_step_returns_a_complete_act_and_increments_revision(self):
        model = GammaIrradiationModel(dimensions=(4, 4), seed_sim=1)

        event = model.step(forced_energy=0.0)

        self.assertEqual(event["event_type"], "no_change")
        self.assertEqual(event["energy_ev"], 0.0)
        self.assertEqual(event["revision"], 1)
        self.assertEqual(model.snapshot()["revision"], 1)

    def test_history_restores_a_step_and_replays_it(self):
        model = GammaIrradiationModel(dimensions=(5, 5), seed_sim=4)
        initial = model.snapshot()

        model.step(forced_energy=55.0)
        after_step = model.snapshot()
        model.undo()

        self.assertEqual(model.snapshot()["atoms"], initial["atoms"])
        self.assertTrue(model.snapshot()["can_redo"])
        model.redo()
        self.assertEqual(model.snapshot()["atoms"], after_step["atoms"])
        self.assertEqual(model.snapshot()["metrics"], after_step["metrics"])

    def test_manual_move_is_atomic_and_reversible(self):
        model = GammaIrradiationModel(dimensions=(4, 4), seed_init=3)
        atom_id = next(atom["id"] for atom in model.snapshot()["atoms"] if atom["state"] == "correct")
        destination = next(site["key"] for site in model.available_destinations(atom_id))
        atom_count = len(model.snapshot()["atoms"])

        model.move(atom_id, destination)

        self.assertEqual(len(model.snapshot()["atoms"]), atom_count)
        self.assertEqual(model.snapshot()["metrics"]["defects"], 2)
        model.undo()
        self.assertEqual(model.snapshot()["metrics"]["defects"], 0)

    def test_configurable_energy_threshold_controls_frenkel_creation(self):
        model = GammaIrradiationModel(
            dimensions=(5, 5), seed_sim=2, q_max_ev=100, frenkel_threshold_ev=70
        )

        event = model.step(forced_energy=60)

        self.assertEqual(event["event_type"], "no_change")
        self.assertEqual(model.snapshot()["config"]["frenkel_threshold_ev"], 70)


if __name__ == "__main__":
    unittest.main()
