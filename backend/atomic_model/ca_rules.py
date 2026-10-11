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

Rules added on 2026-10-11 (cellular automata only):

R1 vacancy preference (AUTHOR HYPOTHESIS, not yet verified in literature):
if a free vacancy is selectable, the knocked-on atom flies into the NEAREST
one (operation lattice_vacancy, probability 1).  Motivation: bonds near a
vacancy are weaker, so a displaced atom is deterministically attracted to
it; filling a vacancy creates no new interstitial and therefore reduces
the defect count.  If no vacancy is selectable, the Frenkel pair
(lattice_interstitial) is created as before.

Irradiation direction cycle: act k irradiates face d(k) = k mod 2n of the
sample (n = number of axes), so over one cycle the energy enters the
material uniformly from all sides.  The primary knock-on is directed along
d(k) (into the material from the irradiated face) unless the vacancy
preference above applies.

R2-R3 cascade direction: the propagation vector changes at every collision
(molecular dynamics of nickel cascades shows exactly this, Voskoboynikov
2020, FMM 121(1), p.13-14) and is bent towards free vacancies (the same
author hypothesis); without vacancies nearby the neighbour ordering is
cyclically rotated by (act_number + generation), which guarantees a
different direction at each collision and no preferred direction overall.

The Monte Carlo method is NOT affected by this module: the engine calls
these helpers only when configuration["method"] == "cellular_automata".
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

    return _candidate_from_outcome(best, atom_id)


def _candidate_from_outcome(
    item: ProbabilityOutcome, atom_id: int
) -> EventCandidate:
    """Build a deterministic (probability 1) candidate from an outcome."""
    return EventCandidate(
        operation=item.operation,
        atom_id=atom_id,
        source_key=item.source_site,
        destination_key=item.destination_site,
        shell=item.shell,
        operation_weight=item.operation_weight,
        shell_weight=item.shell_weight,
        position_weight=item.position_weight,
        total_weight=item.total_weight,
        probability=1.0,
    )


# ---------------------------------------------------------------------------
# Irradiation direction cycle (uniform energy input from all sides)
# ---------------------------------------------------------------------------
# Act k irradiates face d(k) = k mod 2n (n = number of axes): over one full
# cycle every face of the sample receives exactly one act, i.e. the energy
# enters the material uniformly from all sides and no direction is
# preferred.  The face (axis, 0) is the face at coordinate 0 along `axis`
# (the quantum travels towards +axis); (axis, 1) is the face at coordinate
# dim-1 (the quantum travels towards -axis).

def irradiation_faces(dimensions) -> tuple[tuple[int, int], ...]:
    """All irradiation faces of the sample: (axis, side), side in (0, 1)."""
    return tuple(
        (axis, side)
        for axis in range(len(tuple(dimensions)))
        for side in (0, 1)
    )


def irradiation_direction(act_number: int, dimensions) -> tuple[int, int]:
    """Face irradiated during act `act_number` (deterministic cycle)."""
    faces = irradiation_faces(dimensions)
    return faces[int(act_number) % len(faces)]


def travel_vector(face: tuple[int, int], ndim: int) -> tuple[int, ...]:
    """Unit travel direction of the quantum entering through `face`."""
    axis, side = face
    vector = [0] * ndim
    vector[axis] = 1 if side == 0 else -1
    return tuple(vector)


def choose_primary_displacement(
    outcomes: list[ProbabilityOutcome],
    atom_id: int,
    topology: Topology | None = None,
    act_number: int = 0,
) -> EventCandidate | None:
    """Primary CA event choice (R9 / R1) with the 2026-10-11 rules.

    Selection order:
      1. R9 recombination (interstitial_vacancy) — lowest-energy principle
         [FGH98, sec. 2.2], unchanged.
      2. R1 vacancy preference (AUTHOR HYPOTHESIS): the nearest selectable
         free vacancy (shell r=1 before r=2, then sorted site key) — the
         knocked-on atom is guaranteed to fly into it.
      3. Frenkel pair (lattice_interstitial) along the irradiation
         direction d(act_number): destinations whose coordinate grows along
         the quantum travel vector; if the atom sits on the opposite
         boundary and no such destination is selectable, any direction.
      4. Any other operation — deterministic_choose fallback.
    """
    selectable = [item for item in outcomes if item.selectable]
    if not selectable:
        return None

    recombination = [
        item for item in selectable if item.operation == "interstitial_vacancy"
    ]
    if recombination:
        best = min(recombination, key=lambda i: (i.shell, i.destination_site))
        return _candidate_from_outcome(best, atom_id)

    displacements = [
        item for item in selectable
        if item.operation in ("lattice_vacancy", "lattice_interstitial")
    ]
    if not displacements:
        return deterministic_choose(outcomes, atom_id)

    vacancies = [
        item for item in displacements if item.operation == "lattice_vacancy"
    ]
    if vacancies:
        best = min(vacancies, key=lambda i: (i.shell, i.destination_site))
        return _candidate_from_outcome(best, atom_id)

    pool = displacements
    if topology is not None:
        axis, side = irradiation_direction(act_number, topology.dimensions)
        sign = 1 if side == 0 else -1
        source_coordinate = topology.sites[displacements[0].source_site].coordinate
        cone = [
            item for item in displacements
            if (
                topology.sites[item.destination_site].coordinate[axis]
                - source_coordinate[axis]
            ) * sign > 0
        ]
        if cone:
            pool = cone
    best = min(pool, key=lambda i: (i.shell, i.destination_site))
    return _candidate_from_outcome(best, atom_id)


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
# Direction rule (2026-10-11, author's model):
#   Molecular dynamics of cascades on nickel shows that the propagation
#   direction changes at every collision and the cascade develops with a
#   shock wave perpendicular to the close-packed planes [Voskoboynikov
#   2020, FMM 121(1), p.13-14].  The deterministic counterpart used here:
#     1) vacancy bias (AUTHOR HYPOTHESIS, unverified): the cascade vector
#        is bent towards free vacancies — bonds near a vacancy are weaker,
#        so a knocked-on atom deterministically flies into it; such a
#        displacement fills the vacancy and creates no new interstitial,
#        i.e. the defect count grows slower than in the pure Kinchin-Pease
#        picture;
#     2) rotation: the neighbour ordering is cyclically rotated by
#        (act_number + generation), so even without vacancies nearby the
#        propagation vector changes at every collision and no single
#        direction is preferred over many acts.
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
    act_number: int = 0,
) -> list[EventCandidate]:
    """Build a deterministic cascade chain per Kinchin-Pease model.

    Args:
        q_n: act energy (eV), must be >= 2*E_d for a cascade to develop
        topology: lattice topology
        state: current simulation state (used as read-only reference)
        pka_atom_id: primary knock-on atom id
        first_candidate: the first displacement (R1) already chosen
        act_number: index of the current act (seeds the direction rotation)

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

    # Queue: (site_key, energy) of displaced atoms that may continue
    queue = [(first_candidate.destination_key, e_res)]
    visited = {first_candidate.source_key, first_candidate.destination_key}
    generation = 0

    while queue and len(candidates) < n_d_max:
        site, energy = queue.pop(0)

        if energy < e_d:
            continue  # cannot displace further (Kinchin/Pease: E < E_d stops)

        generation += 1
        step = _cascade_step(
            topology, occupied, site, visited, int(act_number) + generation
        )
        if step is None:
            continue
        target_atom, target_site, dest, dest_kind, dest_shell = step

        candidates.append(
            _make_cascade_candidate(
                target_atom, target_site, dest, dest_kind, dest_shell
            )
        )

        # Update virtual occupancy
        del occupied[target_site]
        occupied[dest] = target_atom
        visited.add(target_site)
        visited.add(dest)

        # Energy halving: if energy >= 2*E_d, the displaced atom continues
        # with energy/2 (Kinchin/Pease: atom with E >= 2*E_d can produce
        # further displacements; after collision both have E/2).
        if energy >= 2 * e_d:
            queue.append((dest, energy / 2))

    return candidates


def _rotated(items: list[str], offset: int) -> list[str]:
    """Cyclically rotate a sorted site-key list (direction change)."""
    if not items:
        return []
    shift = offset % len(items)
    return items[shift:] + items[:shift]


def _free_vacancy_near(
    topology: Topology,
    occupied: dict[str, int],
    site: str,
    visited: set[str],
) -> bool:
    """True if a free (empty, inside-metal) lattice site sits in shell r=1/r=2."""
    for radius in (1, 2):
        try:
            shell_sites = topology.shell(site, radius)
        except Exception:
            return False
        for key in sorted(shell_sites):
            if key in visited or key in occupied:
                continue
            site_obj = topology.sites[key]
            if site_obj.kind == "lattice" and site_obj.metal_relation != "outside":
                return True
    return False


def _find_destination(
    topology: Topology,
    occupied: dict[str, int],
    site: str,
    visited: set[str],
    offset: int,
) -> tuple[str | None, str | None, int]:
    """Destination for a knocked-on atom from `site`.

    Vacancy bias (author hypothesis): a free vacancy in shell r=1 (then
    r=2) wins over any interstitial site; only then free interstitials are
    considered (the pre-2026-10-11 behaviour).  Ordering inside each group
    is rotated by `offset`, so the direction changes at every collision.
    """
    for kind in ("lattice", "interstitial"):
        for radius in (1, 2):
            try:
                shell_sites = topology.shell(site, radius)
            except Exception:
                continue
            for key in _rotated(sorted(shell_sites), offset):
                if key in visited or key in occupied:
                    continue
                site_obj = topology.sites[key]
                if site_obj.kind == kind and site_obj.metal_relation != "outside":
                    return key, kind, radius
    return None, None, 0


def _cascade_step(
    topology: Topology,
    occupied: dict[str, int],
    site: str,
    visited: set[str],
    offset: int,
) -> tuple[int, str, str, str, int] | None:
    """One cascade collision: target lattice atom + destination for it.

    Targets (lattice atoms in shell r=1, then r=2, of the carrier site) are
    taken in rotated order — the propagation direction therefore changes
    at every collision [Voskoboynikov 2020, p.13-14].  Targets with a free
    vacancy in their own neighbourhood come first: the cascade vector is
    bent towards vacancies (author hypothesis — weaker bonds near a
    vacancy attract the knocked-on atom).
    """
    for radius in (1, 2):
        try:
            shell_sites = topology.shell(site, radius)
        except Exception:
            continue
        ordered = _rotated(sorted(shell_sites), offset)
        targets: list[tuple[bool, str]] = []
        for key in ordered:
            if key in visited or key not in occupied:
                continue
            site_obj = topology.sites[key]
            if site_obj.kind != "lattice" or site_obj.metal_relation == "outside":
                continue
            targets.append(
                (not _free_vacancy_near(topology, occupied, key, visited), key)
            )
        # Stable sort: vacancy-attracted targets first, rotation order kept
        targets.sort(key=lambda pair: pair[0])
        for _, target_site in targets:
            dest, dest_kind, dest_shell = _find_destination(
                topology, occupied, target_site, visited, offset
            )
            if dest is None:
                continue
            return occupied[target_site], target_site, dest, dest_kind, dest_shell
    return None


def _make_cascade_candidate(
    atom_id: int,
    source: str,
    dest: str,
    dest_kind: str,
    shell: int,
) -> EventCandidate:
    """Create EventCandidate for a cascade displacement.

    dest_kind == "lattice" means the knocked-on atom fills a free vacancy
    (operation lattice_vacancy — no new interstitial, author hypothesis);
    dest_kind == "interstitial" is the classical Frenkel pair.  Recorded
    weights follow the model specification factors (from_lattice_*).
    """
    if dest_kind == "lattice":
        operation = "lattice_vacancy"
        operation_weight = 0.80   # from_lattice_vacancy
        position_weight = 0.95    # from_lattice_inside
    else:
        operation = "lattice_interstitial"
        operation_weight = 0.20   # from_lattice_interstitial
        position_weight = 0.20    # interstitial position weight
    shell_weight = 0.75 if shell == 1 else 0.25
    return EventCandidate(
        operation=operation,
        atom_id=atom_id,
        source_key=source,
        destination_key=dest,
        shell=shell,
        operation_weight=operation_weight,
        shell_weight=shell_weight,
        position_weight=position_weight,
        total_weight=operation_weight * shell_weight * position_weight,
        probability=1.0,         # deterministic
    )
