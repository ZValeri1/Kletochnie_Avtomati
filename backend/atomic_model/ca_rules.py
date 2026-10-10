"""Deterministic transition rules for the cellular automata method (nickel).

Physical basis (see docs and the diploma source table for page references):

R0 — thermal dissipation: if the act energy Q_n is below the displacement
     threshold E_d, no displacement occurs (handled by the engine as
     BELOW_THRESHOLD before this module is called).

R1 — single Frenkel pair: if Q_n >= E_d, a lattice atom is displaced into
     an interstitial site, creating a vacancy + interstitial pair.
     E_d(Ni) = 23 +/- 2 eV, experimentally measured
     [Voskoboynikov 2020, p. 11; JNM 1994 (Ni(Al)/Ni3Al), Td(Ni) = 23 +/- 2 eV].

Recombination priority: an interstitial atom next to a vacancy recombines
deterministically — this follows the lowest-energy principle of the FGH98
CA model (2106.04888v1, sec. 2.2): a transition is accepted with
probability P2 = 1 when the local energy decreases (Delta_H < 0), and
recombination always lowers the energy.

Direction choice is deterministic: candidates are ordered by operation
priority, then by shell (r=1 before r=2), then by the destination site key
(lexicographic). No random source is consumed — identical inputs always
produce identical outputs.

The Monte Carlo method is NOT affected by this module: the engine calls
``deterministic_choose`` only when configuration["method"] ==
"cellular_automata".
"""

from __future__ import annotations

from backend.atomic_model.events import EventCandidate, ProbabilityOutcome
from backend.atomic_model.state import SimulationState
from backend.atomic_model.topology import Topology

# Operation priority for the CA method (lower number = higher priority).
# Justification:
#   interstitial_vacancy (0) — recombination: Delta_H < 0 always, so by the
#       lowest-energy principle [FGH98, sec. 2.2] it is accepted with P = 1.
#   lattice_interstitial (1) — R1 Frenkel pair creation, the primary
#       radiation-damage event at Q >= E_d [Voskoboynikov 2020, p. 11-13].
#   lattice_vacancy (2) — vacancy migration (threshold E_m^v ~ 1.0-1.27 eV,
#       much lower than E_d); a fallback when no free interstitial exists.
#   interstitial_interstitial (3) — interstitial migration (E_m^i ~ 0.1 eV).
#   The remaining operations keep the glossary order.
CA_OPERATION_PRIORITY = {
    "interstitial_vacancy": 0,
    "lattice_interstitial": 1,
    "lattice_vacancy": 2,
    "interstitial_interstitial": 3,
    "boundary_external": 4,
    "external_external": 5,
    "external_interstitial": 6,
    "interstitial_external": 7,
    "external_metal": 8,
}

# Displacement threshold energy for nickel, eV.
# Experimental value: E_d = 23 +/- 2 eV
#   [Voskoboynikov 2020, "Моделирование каскадов смещений на поверхности
#    никеля методом молекулярной динамики", ФММ 121(1), p. 11:
#    "экспериментально измеренное значение пороговой энергии смещения
#    в никеле E_d = 23 ± 2 эВ"; potential fitted to 23 < E_d <= 24 eV]
#   [J. Nucl. Mater. 1994, "Displacement threshold energies in Ni(Al)
#    solid solutions and in Ni3Al": Td(Ni) = 23 +/- 2 eV]
NI_DISPLACEMENT_THRESHOLD_EV = 23.0


# ---------------------------------------------------------------------------
# R4-R7: Photonuclear reaction thresholds for nickel (eV)
# ---------------------------------------------------------------------------
# Sources:
#   [Zaman 2018] Zaman M., Kim G., Naik H. et al. "Flux weighted average
#       cross-sections of natNi(γ,x) reactions with the bremsstrahlung
#       end-point energies of 55, 59, 61 and 65 MeV" // Nucl. Phys. A. 2018.
#       V. 978. P. 173-186. Table 2, p. 5 — experimental thresholds.
#   [AME2020] Wang M. et al. "The AME 2020 atomic mass evaluation" //
#       Chinese Phys. C. 2021. V. 45. Art. 030003 — calculated Q-values
#       for (γ,α) reactions (not measured in Zaman 2018).
#
# Thresholds in eV (1 MeV = 1e6 eV):
PHOTONUCLEAR_THRESHOLDS_EV = {
    # (γ,α) reactions — [AME2020 calculation], not in Zaman 2018 Table 2
    # (Fe products were not measured in that experiment)
    "58ni_gamma_alpha_54fe": 6.40e6,   # 58Ni(γ,α)54Fe
    "60ni_gamma_alpha_56fe": 6.29e6,   # 60Ni(γ,α)56Fe
    # (γ,p) reactions
    "58ni_gamma_p_57co": 8.17e6,       # Zaman 2018 Table 2 (experimental)
    "60ni_gamma_p_59co": 9.53e6,       # [AME2020]; 59Co stable, not measured
    # (γ,n) reactions
    "60ni_gamma_n_59ni": 11.39e6,      # [AME2020]
    "58ni_gamma_n_57ni": 12.22e6,      # Zaman 2018 Table 2 (experimental)
    # Higher channels — Zaman 2018 Table 2
    "58ni_gamma_pn_56co": 19.55e6,
    "60ni_gamma_pn_58co": 19.99e6,
    "58ni_gamma_2n_56ni": 22.47e6,
    "61ni_gamma_p2n_58co": 27.81e6,
    "60ni_gamma_p2n_57co": 28.56e6,
    "58ni_gamma_p2n_55co": 29.64e6,
    "60ni_gamma_3n_57ni": 32.61e6,
    "62ni_gamma_p3n_58co": 38.42e6,
    "60ni_gamma_p3n_56co": 39.95e6,
    "60ni_gamma_4n_56ni": 42.87e6,
    "60ni_gamma_p4n_55co": 50.04e6,
}

# Minimum photonuclear threshold (for R4 activation check)
MIN_PHOTONUCLEAR_THRESHOLD_EV = 6.29e6  # 60Ni(γ,α)56Fe

# Deterministic channel selection order (R4-R7):
# sorted by threshold ascending; first channel with Q >= threshold wins.
# Justification: lowest-energy channel is the most probable at given Q
# (cross-section rises from threshold, peaks at GDR ~15-19 MeV).
PHOTONUCLEAR_CHANNELS = [
    # (channel_name, threshold_eV, product_element, emitted_particle, rule)
    ("gamma_alpha", 6.29e6, "fe", "alpha", "R4"),
    ("gamma_p", 8.17e6, "co", "proton", "R5"),
    ("gamma_n", 11.39e6, "ni_isotope", "neutron", "R6"),
    ("gamma_pn", 19.55e6, "co", "proton+neutron", "R7"),
    ("gamma_2n", 22.47e6, "ni_isotope", "2neutron", "R7"),
]


def photonuclear_channel(q_n: float) -> tuple[str, str, str, str] | None:
    """Determine photonuclear reaction channel deterministically.

    Selection rule: the channel with the LOWEST threshold that is
    exceeded by q_n wins (most probable channel at given energy).

    Args:
        q_n: act energy in eV

    Returns:
        (channel_name, product_element, emitted_particle, rule_id) or None
        if q_n < MIN_PHOTONUCLEAR_THRESHOLD_EV.

    Source: Zaman 2018 Table 2 thresholds; AME2020 for (γ,α).
    """
    if q_n < MIN_PHOTONUCLEAR_THRESHOLD_EV:
        return None

    selected = None
    for name, threshold, product, emitted, rule in PHOTONUCLEAR_CHANNELS:
        if q_n >= threshold:
            selected = (name, product, emitted, rule)
            break  # first (lowest threshold) wins
    return selected


def deterministic_choose(
    outcomes: list[ProbabilityOutcome],
    atom_id: int,
) -> EventCandidate | None:
    """Pick one outcome deterministically (no random source).

    Selection order:
      1. Only selectable outcomes participate (engine already filtered
         Q_n < E_d via BELOW_THRESHOLD).
      2. Minimum operation priority (see CA_OPERATION_PRIORITY).
      3. Tie-break: shell r=1 before r=2, then lexicographic destination
         site key — fully reproducible and iteration-order independent.
    """
    selectable = [item for item in outcomes if item.selectable]
    if not selectable:
        return None

    def sort_key(item: ProbabilityOutcome) -> tuple[int, int, str]:
        priority = CA_OPERATION_PRIORITY.get(item.operation or "", 99)
        return (priority, item.shell, item.destination_site)

    best = min(selectable, key=sort_key)
    if best.total_weight <= 0:
        return None

    return EventCandidate(
        operation=best.operation,
        atom_id=atom_id,
        source_key=best.source_site,
        destination_key=best.destination_site,
        shell=best.shell,
        operation_weight=best.operation_weight,
        shell_weight=best.shell_weight,
        position_weight=best.position_weight,
        total_weight=best.total_weight,
        probability=1.0,
    )


# ---------------------------------------------------------------------------
# R2-R3: Deterministic cascade chain (Kinchin-Pease hard-sphere model)
# ---------------------------------------------------------------------------
# Physical basis:
#   Kinchin & Pease 1955, Rep. Prog. Phys. 18, p.9, §2.2.2:
#     "At its first collision the energy is shared by two atoms and at the
#      second group of collisions the energy is shared by four atoms."
#     Binary collisions with energy halving: E -> E/2 + E/2.
#     Atom with E_d <= E < 2*E_d is displaced but cannot continue the cascade.
#     N_d = E/(2*E_d) for E > 2*E_d (eq. 2.8a).
#   Norgett, Robinson, Torrens 1975, Nucl. Eng. Des. 33, p.53, eq.(4):
#     N_d = g*xi/(2*E_d), g = 0.8 (displacement efficiency).
#   Voskoboynikov 2020, FMM 121(1), p.13: confirms N_FP = 0.8*E/(2*E_d) for Ni.
#
# At Q_max = 82 eV (current profile): N_d = max(1, floor(0.8*82/46)) = 1,
# i.e. the cascade is indistinguishable from R1 (single Frenkel pair).
# For real cascades (N_d >= 8) Q_max >= 500 eV is required.

def cascade_chain(
    q_n: float,
    topology: Topology,
    state: SimulationState,
    pka_atom_id: int,
    first_candidate: EventCandidate,
) -> list[EventCandidate]:
    """Build a deterministic cascade chain per Kinchin-Pease model.

    Args:
        q_n: act energy (eV), must be >= 2*E_d for a cascade to develop
        topology: lattice topology
        state: current simulation state (used as read-only reference)
        pka_atom_id: primary knock-on atom id
        first_candidate: the first displacement (R1 Frenkel pair) already chosen

    Returns:
        List of EventCandidate: [first_candidate, ...additional displacements].
        At Q_max = 82 eV this returns just [first_candidate] (N_d = 1).
    """
    e_d = NI_DISPLACEMENT_THRESHOLD_EV

    # Maximum number of Frenkel pairs per NRT formula:
    # N_d = max(1, floor(0.8 * Q / (2 * E_d)))
    n_d_max = max(1, int(0.8 * q_n / (2 * e_d)))

    candidates = [first_candidate]

    # If Q < 2*E_d or N_d == 1, no cascade develops — just R1
    if q_n < 2 * e_d or n_d_max <= 1:
        return candidates

    # Cascade BFS with energy halving (Kinchin/Pease §2.2.2).
    # Residual energy after first displacement: Q/2 (hard-sphere sharing).
    e_res = q_n / 2

    # Virtual state: track occupancy as we add candidates
    occupied = dict(state.occupied)
    atoms = dict(state.atoms)

    # Queue: (site_key, energy) of displaced atoms that may continue
    queue = [(first_candidate.destination_key, e_res)]
    visited = {first_candidate.source_key, first_candidate.destination_key}

    while queue and len(candidates) < n_d_max:
        site, energy = queue.pop(0)

        if energy < e_d:
            continue  # cannot displace further (Kinchin/Pease: E < E_d stops)

        # Find a lattice atom in shell r=1 from site, not yet displaced
        target_atom, target_site = _find_lattice_neighbor(
            topology, occupied, site, visited
        )
        if target_atom is None:
            continue

        # Find free interstitial in shell r=1 from target_site
        dest = _find_free_interstitial(topology, occupied, target_site, visited)
        if dest is None:
            continue

        # Create candidate for this displacement (Frenkel pair)
        candidate = _make_cascade_candidate(target_atom, target_site, dest)
        candidates.append(candidate)

        # Update virtual occupancy
        del occupied[target_site]
        occupied[dest] = target_atom
        atoms[target_atom] = dest
        visited.add(target_site)
        visited.add(dest)

        # Energy halving: if energy >= 2*E_d, the displaced atom continues
        # with energy/2 (Kinchin/Pease: atom with E >= 2*E_d can produce
        # further displacements; after collision both have E/2).
        if energy >= 2 * e_d:
            queue.append((dest, energy / 2))

    return candidates


def _find_lattice_neighbor(
    topology: Topology,
    occupied: dict[str, int],
    site: str,
    visited: set[str],
) -> tuple[int | None, str | None]:
    """Find a lattice atom in shell r=1 from site, not yet displaced.

    Deterministic: sorted order of shell site keys.
    """
    try:
        shell_sites = topology.shell(site, 1)
    except Exception:
        return None, None
    for key in sorted(shell_sites):
        if key in visited or key not in occupied:
            continue
        site_obj = topology.sites[key]
        if site_obj.kind == "lattice" and site_obj.metal_relation != "outside":
            return occupied[key], key
    return None, None


def _find_free_interstitial(
    topology: Topology,
    occupied: dict[str, int],
    site: str,
    visited: set[str],
) -> str | None:
    """Find a free interstitial site in shell r=1 from site.

    Deterministic: sorted order of shell site keys.
    """
    try:
        shell_sites = topology.shell(site, 1)
    except Exception:
        return None
    for key in sorted(shell_sites):
        if key in visited or key in occupied:
            continue
        site_obj = topology.sites[key]
        if site_obj.kind == "interstitial" and site_obj.metal_relation != "outside":
            return key
    return None


def _make_cascade_candidate(
    atom_id: int, source: str, dest: str
) -> EventCandidate:
    """Create EventCandidate for a cascade displacement (Frenkel pair)."""
    return EventCandidate(
        operation="lattice_interstitial",
        atom_id=atom_id,
        source_key=source,
        destination_key=dest,
        shell=1,
        operation_weight=0.20,   # lattice_interstitial default weight
        shell_weight=0.75,       # r=1 shell weight
        position_weight=0.20,    # interstitial position weight
        total_weight=0.20 * 0.75 * 0.20,
        probability=1.0,         # deterministic
    )
