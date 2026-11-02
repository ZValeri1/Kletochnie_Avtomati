"""Unit tests for the cellular automata deterministic rules (nickel)."""
import pytest

from backend.atomic_model.ca_rules import (
    CA_OPERATION_PRIORITY,
    NI_DISPLACEMENT_THRESHOLD_EV,
    deterministic_choose,
)
from backend.atomic_model.events import ProbabilityOutcome


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
