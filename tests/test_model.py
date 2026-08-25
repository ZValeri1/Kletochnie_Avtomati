import unittest
import random

from hypothesis import given, settings, strategies as st

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

        self.assertNotEqual(event["event_type"], "frenkel_create")
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

        self.assertNotEqual(event["event_type"], "frenkel_create")
        self.assertEqual(model.snapshot()["config"]["frenkel_threshold_ev"], 70)

    def test_2d_topology_has_bridge_sites_and_axial_interstitial_graph(self):
        model = GammaIrradiationModel(dimensions=(4, 3), seed_init=1)

        bridges = [site for site in model.sites.values() if site.kind == "bridge"]
        center = model.sites["interstitial:1.5,1.5"]
        neighbours = model.neighbors(center.key)

        self.assertEqual(len(bridges), 2 * (4 - 1) + 2 * (3 - 1))
        self.assertEqual(
            {model.sites[key].kind for key in neighbours}, {"lattice", "interstitial"}
        )
        self.assertEqual(
            sum(model.sites[key].kind == "interstitial" for key in neighbours), 3
        )

    def test_3d_topology_has_hollow_sites_with_four_lattice_supports(self):
        model = GammaIrradiationModel(dimensions=(3, 4, 5), seed_init=1)

        hollows = [site for site in model.sites.values() if site.kind == "hollow"]
        expected = 2 * ((3 - 1) * (4 - 1) + (3 - 1) * (5 - 1) + (4 - 1) * (5 - 1))

        self.assertEqual(len(hollows), expected)
        self.assertTrue(all(len(model.supports(site.key)) == 4 for site in hollows))
        self.assertTrue(
            all(model.sites[key].kind == "lattice" for site in hollows for key in model.supports(site.key))
        )

    def test_exact_initialization_can_create_surface_defects(self):
        model = GammaIrradiationModel(dimensions=(5, 5), moved_surface_atoms=2, seed_init=12)

        metrics = model.snapshot()["metrics"]

        self.assertEqual(metrics["vacancies"], 2)
        self.assertEqual(metrics["surface_defects"], 2)
        self.assertEqual(metrics["interstitials"], 0)

    def test_random_initialization_is_seed_reproducible(self):
        left = GammaIrradiationModel(dimensions=(7, 7), defect_concentration=0.15, seed_init=5)
        right = GammaIrradiationModel(dimensions=(7, 7), defect_concentration=0.15, seed_init=5)

        self.assertEqual(left.snapshot()["atoms"], right.snapshot()["atoms"])

    def test_probability_engine_returns_normalized_leaf_outcomes(self):
        model = GammaIrradiationModel(dimensions=(5, 5), moved_atoms=1, seed_init=4)
        atom_id = next(atom["id"] for atom in model.snapshot()["atoms"] if atom["state"] == "interstitial")

        outcomes = model.probability_outcomes(atom_id, energy=20)

        self.assertNotEqual(outcomes[0]["event_type"], "no_change")
        self.assertAlmostEqual(sum(item["probability"] for item in outcomes), 1.0, places=12)
        self.assertTrue(any(item["event_type"] == "recombine_d1" for item in outcomes))

    def test_direction_multiplier_matches_normative_endpoints(self):
        self.assertAlmostEqual(GammaIrradiationModel.direction_multiplier(-1), 0.3)
        self.assertAlmostEqual(GammaIrradiationModel.direction_multiplier(0), 0.5)
        self.assertAlmostEqual(GammaIrradiationModel.direction_multiplier(1), 1.0)

    def test_configurable_transition_weights_redefine_event_distribution(self):
        model = GammaIrradiationModel(
            dimensions=(5, 5),
            weights={"shift": 0, "frenkel_create": 1, "knock": 0, "swap": 0},
        )
        atom_id = next(
            atom["id"] for atom in model.snapshot()["atoms"] if atom["state"] == "correct"
        )

        weights = model._event_type_weights(atom_id, energy=55)

        self.assertEqual(weights, {"frenkel_create": 1.0})
        self.assertEqual(model.snapshot()["config"]["weights"]["frenkel_create"], 1)

    def test_internal_atom_shift_targets_only_an_adjacent_lattice_vacancy(self):
        model = GammaIrradiationModel(dimensions=(5, 5))
        moved_id = next(atom.atom_id for atom in model.atoms.values() if atom.site_key == "lattice:2,2")
        model._relocate(moved_id, "interstitial:2.5,2.5")
        target_id = next(atom.atom_id for atom in model.atoms.values() if atom.site_key == "lattice:2,1")

        shifts = model._candidate_groups(target_id)["shift"]

        self.assertEqual([candidate.destination_key for candidate in shifts], ["lattice:2,2"])

    def test_surface_atom_shift_targets_only_a_lattice_vacancy(self):
        model = GammaIrradiationModel(dimensions=(5, 5))
        moved_id = next(atom.atom_id for atom in model.atoms.values() if atom.site_key == "lattice:0,0")
        model._relocate(moved_id, "bridge:0.5,-0.5")
        target_id = next(atom.atom_id for atom in model.atoms.values() if atom.site_key == "lattice:1,0")

        shifts = model._candidate_groups(target_id)["surface_shift"]

        self.assertEqual([candidate.destination_key for candidate in shifts], ["lattice:0,0"])

    def test_surface_atom_diagnostic_includes_surface_exit_before_its_threshold(self):
        model = GammaIrradiationModel(dimensions=(5, 5))
        edge_atom_id = next(atom.atom_id for atom in model.atoms.values() if atom.site_key == "lattice:0,2")

        below_threshold = model.probability_outcomes(edge_atom_id, energy=40)
        at_threshold = model.probability_outcomes(edge_atom_id, energy=60)

        blocked_exits = [item for item in below_threshold if item["event_type"] == "surface_out"]
        active_exits = [item for item in at_threshold if item["event_type"] == "surface_out"]
        self.assertTrue(blocked_exits)
        self.assertTrue(all(item["probability"] == 0 for item in blocked_exits))
        self.assertTrue(all(not item["active"] and item["threshold_ev"] == 60 for item in blocked_exits))
        self.assertTrue(active_exits)
        self.assertTrue(all(item["active"] and item["probability"] > 0 for item in active_exits))

    def test_interstitial_atom_candidates_respect_lattice_and_surface_destinations(self):
        model = GammaIrradiationModel(dimensions=(5, 5))
        moved_id = next(atom.atom_id for atom in model.atoms.values() if atom.site_key == "lattice:0,0")
        model._relocate(moved_id, "interstitial:0.5,0.5")

        groups = model._candidate_groups(moved_id)

        self.assertTrue(all(key.startswith("lattice:") for key in [item.destination_key for item in groups["recombine_d1"]]))
        self.assertTrue(all(key.startswith("interstitial:") for key in [item.destination_key for item in groups["interstitial_hop"]]))
        self.assertTrue(all(key.startswith("bridge:") for key in [item.destination_key for item in groups["to_surface"]]))

    def test_surface_defect_candidates_cover_surface_return_and_interior_transition(self):
        model = GammaIrradiationModel(dimensions=(5, 5))
        moved_id = next(atom.atom_id for atom in model.atoms.values() if atom.site_key == "lattice:0,0")
        model._relocate(moved_id, "bridge:0.5,-0.5")

        groups = model._candidate_groups(moved_id)

        self.assertTrue(groups["surface_hop"])
        self.assertEqual(groups["surface_return_d1"][0].destination_key, "lattice:0,0")
        self.assertTrue(all(key.startswith("interstitial:") for key in [item.destination_key for item in groups["to_interstitial"]]))

    def test_cascade_records_commits_or_dissipation_without_exceeding_budget(self):
        model = GammaIrradiationModel(dimensions=(5, 5), seed_sim=7)
        model._relocate(0, "interstitial:0.5,0.5")

        cascade = model._process_cascade("interstitial:0.5,0.5", 80)

        self.assertTrue(cascade)
        self.assertTrue(all(item["status"] in {"committed", "dissipated", "conflict_cancelled"} for item in cascade))
        self.assertTrue(
            all(item.get("child_energy_ev", 0) <= item["energy_ev"] for item in cascade)
        )

    # ENERGY/PROB/CASC requirements: thresholded knock, directional selection, and energy shares.
    def test_knock_creates_a_frenkel_pair_and_exposes_cascade_metadata(self):
        model = GammaIrradiationModel(dimensions=(5, 5), seed_sim=7)
        atom_id = next(atom.atom_id for atom in model.atoms.values() if atom.site_key == "lattice:2,2")

        candidate = model._candidate_groups(atom_id)["knock"][0]
        model._apply_candidate(atom_id, candidate)
        cascade = model._process_cascade(candidate.destination_key, 80)

        self.assertEqual(model.metrics()["defects"], 2 + len([
            item for item in cascade if item["status"] == "committed"
        ]) * 2)
        self.assertTrue(all("sequence" in item and "source_site" in item for item in cascade))
        self.assertAlmostEqual(sum(model._dirichlet_shares(4)), 1.0, places=12)

    def test_candidate_weights_prefer_the_beam_direction(self):
        model = GammaIrradiationModel(dimensions=(5, 5))
        atom_id = next(atom.atom_id for atom in model.atoms.values() if atom.site_key == "lattice:2,2")

        weights = [candidate.direction_weight for candidate in model._candidate_groups(atom_id)["knock"]]

        self.assertGreater(max(weights), min(weights))

    def test_invalid_energy_profile_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "profile"):
            GammaIrradiationModel(profile="unknown")

    def test_randomized_model_invariants_hold_for_1000_generated_cases(self):
        generator = random.Random(901)
        for _ in range(1000):
            dimensions = (
                (generator.randrange(2, 7), generator.randrange(2, 7))
                if generator.random() < 0.65
                else (generator.randrange(2, 5), generator.randrange(2, 5), generator.randrange(2, 5))
            )
            model = GammaIrradiationModel(
                dimensions=dimensions,
                moved_atoms=generator.randrange(0, 2) if min(dimensions) >= 3 else 0,
                seed_init=generator.randrange(2**31),
                seed_sim=generator.randrange(2**31),
            )
            atom_count = len(model.atoms)
            for _ in range(3):
                model.step(forced_energy=generator.uniform(0, 100))
                self.assertEqual(len(model.atoms), atom_count)
                self.assertEqual(len(model._occupied), atom_count)
                self.assertEqual(len(set(model._occupied.values())), atom_count)


if __name__ == "__main__":
    unittest.main()


# SIM-FULL-2D-001 / SIM-FULL-3D-001: deterministic model invariants over 1000 inputs.
@settings(max_examples=1000, deadline=None)
@given(
    dimensions=st.one_of(
        st.tuples(st.integers(2, 6), st.integers(2, 6)),
        st.tuples(st.integers(2, 4), st.integers(2, 4), st.integers(2, 4)),
    ),
    seed=st.integers(0, 2**31 - 1),
    energy=st.floats(min_value=0, max_value=100, allow_nan=False, allow_infinity=False),
)
def test_generated_model_invariants(dimensions, seed, energy):
    model = GammaIrradiationModel(dimensions=dimensions, seed_init=seed, seed_sim=seed + 1)
    atom_count = len(model.atoms)

    model.step(forced_energy=energy)

    assert len(model.atoms) == atom_count
    assert len(model._occupied) == atom_count
    assert len(set(model._occupied.values())) == atom_count
