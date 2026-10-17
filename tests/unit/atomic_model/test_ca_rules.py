"""Unit tests for the cellular automata deterministic rules (nickel)."""
import pytest

from backend.atomic_model.ca_rules import (
    CA_OPERATION_PRIORITY,
    NI_DISPLACEMENT_THRESHOLD_EV,
    cascade_chain,
    choose_primary_displacement,
    choose_target_atom,
    deterministic_choose,
    irradiation_direction,
    travel_vector,
    _chebyshev,
    _rotated,
)
import backend.atomic_model.ca_rules as ca_rules_module
from backend.atomic_model.events import EventCandidate, EventEngine, ProbabilityOutcome, RandomSource
from backend.atomic_model.state import SimulationState
from backend.atomic_model.topology import Topology


def make_outcome(operation, shell=1, dest="lattice:1,1", selectable=True, total_weight=0.5):
    return ProbabilityOutcome(
        source_site="lattice:0,0",
        source_coordinate=(0.0, 0.0),
        source_kind="lattice",
        destination_site=dest,
        destination_coordinate=(1.0, 1.0),
        destination_kind="lattice",
        destination_relation="interior",
        operation=operation,
        shell=shell,
        operation_weight=total_weight,
        shell_weight=1.0,
        position_weight=1.0,
        total_weight=total_weight,
        probability=0.5,
        selectable=selectable,
        block_code=None,
        q_test=30.0,
        q_thr=NI_DISPLACEMENT_THRESHOLD_EV,
    )


class TestNickelThreshold:
    def test_displacement_threshold_is_23_ev(self):
        """E_d(Ni) = 23 +/- 2 eV — experimental value.

        Sources:
          - Voskoboynikov 2020, FMM 121(1), p. 11: "экспериментально
            измеренное значение пороговой энергии смещения в никеле
            E_d = 23 ± 2 эВ"; potential fitted to 23 < E_d <= 24 eV.
          - J. Nucl. Mater. 1994 (Ni(Al)/Ni3Al): Td(Ni) = 23 +/- 2 eV.
        """
        assert NI_DISPLACEMENT_THRESHOLD_EV == 23.0


class TestDeterministicChoose:
    def test_returns_none_for_empty(self):
        assert deterministic_choose([], 0) is None

    def test_returns_none_when_nothing_selectable(self):
        outcomes = [make_outcome("lattice_interstitial", selectable=False)]
        assert deterministic_choose(outcomes, 0) is None

    def test_frenkel_pair_priority_over_vacancy_migration(self):
        """R1: at Q >= E_d the Frenkel pair (lattice_interstitial) wins
        over vacancy migration (lattice_vacancy), regardless of weights."""
        outcomes = [
            make_outcome("lattice_vacancy", dest="lattice:1,0", total_weight=0.70),
            make_outcome("lattice_interstitial", dest="interstitial:0.5,0.5", total_weight=0.20),
        ]
        candidate = deterministic_choose(outcomes, 0)
        assert candidate.operation == "lattice_interstitial"
        assert candidate.probability == 1.0

    def test_recombination_highest_priority(self):
        """Recombination (interstitial_vacancy) has priority 0 — the
        lowest-energy principle from FGH98 (2106.04888v1, sec. 2.2):
        Delta_H < 0 => accepted with P = 1."""
        outcomes = [
            make_outcome("lattice_interstitial", dest="interstitial:0.5,0.5"),
            make_outcome("interstitial_vacancy", dest="lattice:1,0"),
        ]
        candidate = deterministic_choose(outcomes, 0)
        assert candidate.operation == "interstitial_vacancy"

    def test_shell_tiebreak_r1_before_r2(self):
        outcomes = [
            make_outcome("lattice_interstitial", shell=2, dest="interstitial:1.5,0.5"),
            make_outcome("lattice_interstitial", shell=1, dest="interstitial:0.5,0.5"),
        ]
        candidate = deterministic_choose(outcomes, 0)
        assert candidate.shell == 1
        assert candidate.destination_key == "interstitial:0.5,0.5"

    def test_lexicographic_tiebreak_same_shell(self):
        outcomes = [
            make_outcome("lattice_interstitial", shell=1, dest="interstitial:1.5,0.5"),
            make_outcome("lattice_interstitial", shell=1, dest="interstitial:0.5,0.5"),
            make_outcome("lattice_interstitial", shell=1, dest="interstitial:0.5,1.5"),
        ]
        candidate = deterministic_choose(outcomes, 0)
        assert candidate.destination_key == "interstitial:0.5,0.5"

    def test_deterministic_same_result_every_time(self):
        outcomes = [
            make_outcome("lattice_vacancy", dest="lattice:2,0"),
            make_outcome("lattice_interstitial", dest="interstitial:0.5,0.5"),
            make_outcome("lattice_interstitial", shell=2, dest="interstitial:1.5,1.5"),
        ]
        results = [deterministic_choose(outcomes, 0) for _ in range(50)]
        assert all(
            r.operation == results[0].operation and r.destination_key == results[0].destination_key
            for r in results
        )

    def test_zero_weight_rejected(self):
        outcomes = [make_outcome("external_metal", total_weight=0.0)]
        assert deterministic_choose(outcomes, 0) is None

    def test_priority_table_covers_all_operations(self):
        from backend.atomic_model.events import EventEngine
        for op in EventEngine.DEFAULT_OPERATION_WEIGHTS:
            base = op[:-3] if op.endswith("_r1") or op.endswith("_r2") else op
            assert base in CA_OPERATION_PRIORITY or op in CA_OPERATION_PRIORITY, (
                f"operation {op} missing from CA_OPERATION_PRIORITY"
            )


class TestCascadeFormula:
    """Tests for the Kinchin-Pease / NRT cascade formula.

    N_d = max(1, floor(0.8 * Q / (2 * E_d)))
    Sources:
      - Kinchin & Pease 1955, Rep. Prog. Phys. 18, p.9, eq. 2.8a
      - NRT 1975, Nucl. Eng. Des. 33, p.53, eq.(4): g = 0.8
      - Voskoboynikov 2020, FMM 121(1), p.13: N_FP = 0.8*E/(2*E_d) for Ni
    """

    def test_n_d_formula_at_q_max_82(self):
        """At Q_max = 82 eV, E_d = 23 eV: N_d = max(1, floor(0.8*82/46)) = 1."""
        q = 82.0
        e_d = NI_DISPLACEMENT_THRESHOLD_EV
        n_d = max(1, int(0.8 * q / (2 * e_d)))
        assert n_d == 1, "At Q_max=82 eV cascade gives 1 pair (indistinguishable from R1)"

    def test_n_d_formula_at_500_ev(self):
        """At Q = 500 eV: N_d = floor(0.8*500/46) = floor(8.7) = 8 pairs."""
        q = 500.0
        e_d = NI_DISPLACEMENT_THRESHOLD_EV
        n_d = max(1, int(0.8 * q / (2 * e_d)))
        assert n_d == 8, "At Q=500 eV cascade should give 8 Frenkel pairs"

    def test_n_d_formula_at_1000_ev(self):
        """At Q = 1000 eV: N_d = floor(0.8*1000/46) = floor(17.4) = 17 pairs."""
        q = 1000.0
        e_d = NI_DISPLACEMENT_THRESHOLD_EV
        n_d = max(1, int(0.8 * q / (2 * e_d)))
        assert n_d == 17, "At Q=1000 eV cascade should give 17 Frenkel pairs"

    def test_n_d_minimum_is_one(self):
        """N_d >= 1 for any Q >= E_d (R1 guarantees at least one pair)."""
        e_d = NI_DISPLACEMENT_THRESHOLD_EV
        for q in [23, 30, 40, 46, 50]:
            n_d = max(1, int(0.8 * q / (2 * e_d)))
            assert n_d >= 1

    def test_cascade_threshold_is_2_ed(self):
        """Cascade develops only at Q >= 2*E_d = 46 eV (Kinchin/Pease)."""
        e_d = NI_DISPLACEMENT_THRESHOLD_EV
        # Below 2*E_d: no cascade, just R1
        assert 45 < 2 * e_d  # 45 < 46
        # At 2*E_d: cascade may develop
        assert 46 >= 2 * e_d  # 46 >= 46


class TestPhotonuclearChannels:
    """Tests for R4-R7 photonuclear reaction channel selection.

    Thresholds from:
      - Zaman 2018, Nucl. Phys. A 978, p.173-186, Table 2, p.5 (experimental)
      - AME2020 (Wang et al., Chinese Phys. C 45, 030003, 2021) for (γ,α)
    """

    def test_no_channel_below_min_threshold(self):
        """Below 6.29 MeV no photonuclear reaction occurs."""
        from backend.atomic_model.ca_rules import photonuclear_channel
        assert photonuclear_channel(6.28e6) is None
        assert photonuclear_channel(1e6) is None
        assert photonuclear_channel(82.0) is None  # current Q_max in eV

    def test_r4_gamma_alpha_at_6_29_mev(self):
        """R4: (γ,α) channel opens at 6.29 MeV (60Ni → 56Fe + α)."""
        from backend.atomic_model.ca_rules import photonuclear_channel
        result = photonuclear_channel(6.29e6)
        assert result is not None
        name, product, emitted, rule = result
        assert name == "gamma_alpha"
        assert product == "fe"
        assert emitted == "alpha"
        assert rule == "R4"

    def test_r5_gamma_p_at_8_17_mev(self):
        """R5: (γ,p) channel opens at 8.17 MeV (58Ni → 57Co + p).

        Source: Zaman 2018 Table 2 — experimental threshold.
        """
        from backend.atomic_model.ca_rules import photonuclear_channel
        # At 8.17 MeV: gamma_p threshold reached, but gamma_alpha (6.29) is lower
        # First channel with threshold <= q_n wins → gamma_alpha still selected
        result = photonuclear_channel(8.17e6)
        assert result is not None
        name, product, emitted, rule = result
        # Lowest threshold channel wins: gamma_alpha (6.29) < gamma_p (8.17)
        assert name == "gamma_alpha"

    def test_channel_selection_lowest_threshold_wins(self):
        """Deterministic rule: channel with LOWEST threshold <= q_n wins."""
        from backend.atomic_model.ca_rules import photonuclear_channel
        # At 7 MeV: only gamma_alpha (6.29) is open
        result = photonuclear_channel(7e6)
        assert result[0] == "gamma_alpha"
        # At 20 MeV: gamma_alpha (6.29) still lowest open channel
        result = photonuclear_channel(20e6)
        assert result[0] == "gamma_alpha"
        # At 55 MeV: same
        result = photonuclear_channel(55e6)
        assert result[0] == "gamma_alpha"

    def test_zaman2018_thresholds_match(self):
        """Verify thresholds match Zaman 2018 Table 2 exactly."""
        from backend.atomic_model.ca_rules import PHOTONUCLEAR_THRESHOLDS_EV
        # Zaman 2018 Table 2 experimental values (MeV → eV)
        assert PHOTONUCLEAR_THRESHOLDS_EV["58ni_gamma_p_57co"] == 8.17e6
        assert PHOTONUCLEAR_THRESHOLDS_EV["58ni_gamma_n_57ni"] == 12.22e6
        assert PHOTONUCLEAR_THRESHOLDS_EV["58ni_gamma_pn_56co"] == 19.55e6
        assert PHOTONUCLEAR_THRESHOLDS_EV["58ni_gamma_2n_56ni"] == 22.47e6
        assert PHOTONUCLEAR_THRESHOLDS_EV["60ni_gamma_pn_58co"] == 19.99e6
        assert PHOTONUCLEAR_THRESHOLDS_EV["58ni_gamma_p2n_55co"] == 29.64e6

    def test_min_photonuclear_threshold(self):
        """Minimum threshold is 6.29 MeV — 60Ni(γ,α)56Fe [AME2020]."""
        from backend.atomic_model.ca_rules import MIN_PHOTONUCLEAR_THRESHOLD_EV
        assert MIN_PHOTONUCLEAR_THRESHOLD_EV == 6.29e6


class TestPhotonuclearProfile:
    """Tests for the ni_photonuclear profile (R4-R7, CA-only).

    Q_max = 55 MeV is the bremsstrahlung end-point energy of the PAL
    experiment [Zaman 2018, Nucl. Phys. A 978, p. 173-186], chosen so that
    all photonuclear channels with thresholds 6.29-50.04 MeV (Zaman 2018
    Table 2 + AME2020) are reachable.
    """

    def test_ni_photonuclear_requires_cellular_automata(self):
        """The photonuclear profile is CA-only; MC stays frozen."""
        from backend.atomic_model.engine import SimulationEngine
        with pytest.raises(ValueError, match="cellular_automata"):
            SimulationEngine._validated_configuration({
                "dimensions": [4, 4],
                "profile": "ni_photonuclear",
                "method": "monte_carlo",
            })

    def test_ni_photonuclear_default_q_max_is_55_mev(self):
        from backend.atomic_model.engine import SimulationEngine
        config = SimulationEngine._validated_configuration({
            "dimensions": [4, 4],
            "profile": "ni_photonuclear",
            "method": "cellular_automata",
        })
        assert config["q_max_ev"] == 55.0e6
        assert config["q_thr_ev"] == 23.0  # E_d(Ni) stays the lattice threshold

    def test_fe_co60_physical_defaults_unchanged(self):
        """MC and CA lattice-damage defaults must not change."""
        from backend.atomic_model.engine import SimulationEngine
        mc = SimulationEngine._validated_configuration({"dimensions": [4, 4]})
        assert mc["profile"] == "fe_co60_physical"
        assert mc["method"] == "monte_carlo"
        assert mc["q_max_ev"] == 82.0
        assert mc["q_thr_ev"] == 20.0

        ca = SimulationEngine._validated_configuration({
            "dimensions": [4, 4],
            "method": "cellular_automata",
        })
        assert ca["profile"] == "fe_co60_physical"
        assert ca["q_max_ev"] == 82.0
        assert ca["q_thr_ev"] == 23.0

    def test_unknown_profile_rejected(self):
        from backend.atomic_model.engine import SimulationEngine
        with pytest.raises(ValueError, match="Unsupported profile"):
            SimulationEngine._validated_configuration({
                "dimensions": [4, 4],
                "profile": "bogus_profile",
            })


# ---------------------------------------------------------------------------
# Rules of 2026-10-11: irradiation cycle, R1 vacancy preference,
# cascade direction change / vacancy bias
# ---------------------------------------------------------------------------

CA_CONFIG = {
    "dimensions": [5, 5],
    "profile": "fe_co60_physical",
    "method": "cellular_automata",
    "q_max_ev": 82.0,
    "q_thr_ev": 23.0,
    "weights": {},
}


def ideal_state(dimensions=(5, 5)):
    config = dict(CA_CONFIG, dimensions=list(dimensions))
    topology = Topology.create(tuple(dimensions))
    state = SimulationState.create_ideal(topology, config)
    return topology, state, config


def make_vacancy(state, site_key):
    """Remove the atom occupying site_key, leaving a free vacancy."""
    atom_id = state.occupied.pop(site_key)
    del state.atoms[atom_id]
    return atom_id


class TestIrradiationCycle:
    """Energy enters the material uniformly from all sides:
    d(k) = k mod 2n (n = number of axes)."""

    def test_2d_cycle_covers_four_faces(self):
        seq = [irradiation_direction(k, (5, 5)) for k in range(8)]
        assert seq[:4] == [(0, 0), (0, 1), (1, 0), (1, 1)]
        assert seq[4:] == seq[:4]

    def test_3d_cycle_covers_six_faces(self):
        seq = [irradiation_direction(k, (4, 4, 4)) for k in range(6)]
        assert len(set(seq)) == 6

    def test_every_face_once_per_cycle(self):
        from backend.atomic_model.ca_rules import irradiation_faces
        dims = (6, 6)
        faces = irradiation_faces(dims)
        seq = [irradiation_direction(k, dims) for k in range(len(faces))]
        assert sorted(seq) == sorted(faces)

    def test_travel_vector_points_into_material(self):
        assert travel_vector((0, 0), 2) == (1, 0)
        assert travel_vector((0, 1), 2) == (-1, 0)
        assert travel_vector((1, 0), 2) == (0, 1)
        assert travel_vector((2, 1), 3) == (0, 0, -1)


class TestPrimaryDisplacementRules:
    """R9 > R1 nearest vacancy (author hypothesis) > Frenkel pair along
    the irradiation direction."""

    def test_vacancy_preference_over_interstitial(self):
        topology, state, config = ideal_state()
        src = "lattice:7,7"
        vac = "lattice:8,7"
        atom_id = state.occupied[src]
        make_vacancy(state, vac)
        outcomes = EventEngine(config).probabilities(topology, state, atom_id, 30.0)
        candidate = choose_primary_displacement(outcomes, atom_id, topology, 0)
        assert candidate.operation == "lattice_vacancy"
        assert candidate.destination_key == vac
        assert candidate.probability == 1.0

    def test_nearest_shell_wins_for_vacancy(self):
        topology, state, config = ideal_state()
        src = "lattice:7,7"
        atom_id = state.occupied[src]
        make_vacancy(state, "lattice:8,7")      # shell r=1
        make_vacancy(state, "lattice:9,7")      # shell r=2
        outcomes = EventEngine(config).probabilities(topology, state, atom_id, 30.0)
        candidate = choose_primary_displacement(outcomes, atom_id, topology, 0)
        assert candidate.shell == 1
        assert candidate.destination_key == "lattice:8,7"

    def test_frenkel_pair_follows_irradiation_direction(self):
        topology, state, config = ideal_state()
        src = "lattice:7,7"
        atom_id = state.occupied[src]
        source_coordinate = topology.sites[src].coordinate
        outcomes = EventEngine(config).probabilities(topology, state, atom_id, 30.0)
        expected_signs = [(0, 1), (0, -1), (1, 1), (1, -1)]
        for act, (axis, sign) in enumerate(expected_signs):
            candidate = choose_primary_displacement(
                outcomes, atom_id, topology, act
            )
            assert candidate.operation == "lattice_interstitial"
            delta = (
                topology.sites[candidate.destination_key].coordinate[axis]
                - source_coordinate[axis]
            )
            assert delta * sign > 0

    def test_recombination_still_highest_priority(self):
        topology, state, config = ideal_state()
        vac = "lattice:8,7"
        src = "lattice:7,7"
        atom_id = state.occupied[src]
        make_vacancy(state, vac)
        state.relocate(atom_id, "interstitial:7.5,7.5")
        outcomes = EventEngine(config).probabilities(topology, state, atom_id, 30.0)
        candidate = choose_primary_displacement(outcomes, atom_id, topology, 0)
        assert candidate.operation == "interstitial_vacancy"
        # The atom's own vacated site (lattice:7,7) is the nearest free
        # vacancy: recombination into it annihilates the Frenkel pair.
        assert candidate.destination_key == src


class TestCascadeDirectionRules:
    """R2-R3: direction changes at every collision; the vector is bent
    towards free vacancies (author hypothesis)."""

    def first_candidate(self, atom_id, source, dest):
        return EventCandidate(
            operation="lattice_interstitial",
            atom_id=atom_id,
            source_key=source,
            destination_key=dest,
            shell=1,
            operation_weight=0.20,
            shell_weight=0.75,
            position_weight=0.20,
            total_weight=0.20 * 0.75 * 0.20,
            probability=1.0,
        )

    def test_cascade_bends_towards_vacancy(self):
        topology, state, config = ideal_state()
        vac = "lattice:8,6"
        source = "lattice:6,6"
        atom_id = state.occupied[source]
        make_vacancy(state, vac)
        first = self.first_candidate(atom_id, source, "interstitial:6.5,6.5")
        candidates = cascade_chain(200.0, topology, state, atom_id, first, 0)
        assert len(candidates) >= 2
        second = candidates[1]
        # The knocked-on atom fills a free vacancy: no new interstitial.
        # With the reverse rule (2026-10-16) this may be the prepared
        # vacancy ahead or the vacancy left behind by the PKA.
        assert second.operation == "lattice_vacancy"
        assert second.destination_key in (vac, source)
        assert second.probability == 1.0

    def test_direction_changes_every_collision(self):
        topology, state, config = ideal_state(dimensions=(6, 6))
        source = "lattice:8,8"
        atom_id = state.occupied[source]
        first = self.first_candidate(atom_id, source, "interstitial:8.5,8.5")
        candidates = cascade_chain(500.0, topology, state, atom_id, first, 0)
        assert len(candidates) >= 3

        def relative_vector(candidate):
            src = topology.sites[candidate.source_key].coordinate
            dst = topology.sites[candidate.destination_key].coordinate
            return tuple(round(d - s, 1) for s, d in zip(src, dst))

        vectors = [relative_vector(c) for c in candidates[1:]]
        # Pre-2026-10-11 lexicographic ordering froze the direction; the
        # rotation rule must produce more than one propagation vector.
        assert len(set(vectors)) > 1

    def test_rotation_helper_changes_order(self):
        items = ["a", "b", "c", "d"]
        assert _rotated(items, 0) != _rotated(items, 1)
        assert _rotated(items, len(items)) == items
        assert sorted(_rotated(items, 3)) == items

    def test_cascade_without_vacancies_still_interstitial(self):
        topology, state, config = ideal_state()
        source = "lattice:7,7"
        atom_id = state.occupied[source]
        first = self.first_candidate(atom_id, source, "interstitial:7.5,7.5")
        candidates = cascade_chain(200.0, topology, state, atom_id, first, 0)
        assert len(candidates) >= 2
        # reverse rule: the only free vacancy is the one left by the PKA,
        # the cascade turns back and the next atom fills it
        assert candidates[1].operation == "lattice_vacancy"
        assert candidates[1].destination_key == source

    def test_cascade_without_vacancies_forward_only_option(self, monkeypatch):
        monkeypatch.setattr(ca_rules_module, "CASCADE_ALLOW_REVERSE", False)
        topology, state, config = ideal_state()
        source = "lattice:7,7"
        atom_id = state.occupied[source]
        first = self.first_candidate(atom_id, source, "interstitial:7.5,7.5")
        candidates = cascade_chain(200.0, topology, state, atom_id, first, 0)
        assert len(candidates) >= 2
        assert candidates[1].operation == "lattice_interstitial"


class TestTargetAtomRules:
    """Energy first affects interstitial atoms (revision 2026-10-11 #2)."""

    def test_interstitial_nearest_to_irradiated_face(self):
        topology, state, config = ideal_state()
        atom_a = state.occupied["lattice:6,6"]
        state.relocate(atom_a, "interstitial:6.5,6.5")
        atom_b = state.occupied["lattice:8,8"]
        state.relocate(atom_b, "interstitial:8.5,8.5")
        rng = RandomSource(1)
        # act 0: face x = 0 -> the interstitial nearer to that face
        assert choose_target_atom(topology, state, 0, rng) == atom_a
        # act 1: face x = max -> the other one
        assert choose_target_atom(topology, state, 1, rng) == atom_b

    def test_defect_free_lattice_falls_back_to_uniform(self):
        topology, state, config = ideal_state()
        rng = RandomSource(3)
        assert choose_target_atom(topology, state, 0, rng) in state.atoms


class TestInterstitialPursuit:
    """Interstitial atom pursues the nearest vacancy act by act."""

    def test_annihilation_when_vacancy_reachable(self):
        topology, state, config = ideal_state()
        src = "lattice:5,5"
        atom_id = state.occupied[src]
        state.relocate(atom_id, "interstitial:7.5,7.5")  # own vac unreachable
        make_vacancy(state, "lattice:8,8")   # r=1 from the interstitial
        outcomes = EventEngine(config).probabilities(topology, state, atom_id, 30.0)
        candidate = choose_primary_displacement(
            outcomes, atom_id, topology, 0, state=state
        )
        assert candidate.operation == "interstitial_vacancy"
        assert candidate.destination_key == "lattice:8,8"

    def test_pursuit_step_strictly_closer(self):
        topology, state, config = ideal_state(dimensions=(8, 8))
        src = "lattice:9,9"
        atom_id = state.occupied[src]
        state.relocate(atom_id, "interstitial:12.5,12.5")  # own vac far behind
        make_vacancy(state, "lattice:15,15")               # nearest, unreachable
        outcomes = EventEngine(config).probabilities(topology, state, atom_id, 30.0)
        candidate = choose_primary_displacement(
            outcomes, atom_id, topology, 0, state=state
        )
        assert candidate.operation == "interstitial_interstitial"
        # the diagonal r=2 step is the strictly closest one
        assert candidate.destination_key == "interstitial:14.5,14.5"
        target = "lattice:15,15"
        assert _chebyshev(topology, candidate.destination_key, target) < \
            _chebyshev(topology, "interstitial:12.5,12.5", target)


class TestCascadeForwardWave:
    """The cascade develops outwards: no strictly backward steps."""

    def first_candidate(self, atom_id, source, dest):
        return EventCandidate(
            operation="lattice_interstitial",
            atom_id=atom_id,
            source_key=source,
            destination_key=dest,
            shell=1,
            operation_weight=0.20,
            shell_weight=0.75,
            position_weight=0.20,
            total_weight=0.20 * 0.75 * 0.20,
            probability=1.0,
        )

    def test_cascade_can_turn_back(self):
        """Reverse rule (2026-10-16): a step towards the cascade centre
        (a turn by up to 180 degrees) is admissible."""
        topology, state, config = ideal_state(dimensions=(10, 10))
        source = "lattice:14,14"
        atom_id = state.occupied[source]
        first = self.first_candidate(atom_id, source, "interstitial:14.5,14.5")
        candidates = cascade_chain(500.0, topology, state, atom_id, first, 0)
        assert len(candidates) >= 3
        assert any(
            _chebyshev(topology, c.destination_key, source)
            < _chebyshev(topology, c.source_key, source)
            for c in candidates[1:]
        )

    def test_cascade_never_steps_backward(self, monkeypatch):
        monkeypatch.setattr(ca_rules_module, "CASCADE_ALLOW_REVERSE", False)
        # 10x10 keeps the short cascade away from the metal boundary,
        # where the forward pass has no destinations by construction
        topology, state, config = ideal_state(dimensions=(10, 10))
        source = "lattice:14,14"
        atom_id = state.occupied[source]
        first = self.first_candidate(atom_id, source, "interstitial:14.5,14.5")
        candidates = cascade_chain(200.0, topology, state, atom_id, first, 0)
        assert len(candidates) >= 3
        for candidate in candidates[1:]:
            assert _chebyshev(topology, candidate.destination_key, source) >= \
                _chebyshev(topology, candidate.source_key, source)
